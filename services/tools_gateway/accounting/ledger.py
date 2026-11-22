"""Ledger tools (Batch 1: inventory rows 1-10).

Double-entry rules live here, not in storage: a journal must balance, carry
two-decimal non-negative money, and each line belongs to exactly one side.
Balance changes happen only when a PENDING entry is approved; approval is a
permission=destructive tool and is also blocked while the period is locked.

Every function returns ``ToolResult(ok, content=JSON, error_code, artifacts)``
and never raises: business failures become VALIDATION / NOT_FOUND / STATE,
tenant failures become NO_ORGANIZATION / UNAUTHORIZED.
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import (
    NOT_FOUND,
    STATE,
    VALIDATION,
    AccountingError,
)
from tools_gateway.accounting.money import ZERO, add, assert_non_negative, fmt, to_money
from tools_gateway.registry import (
    PERMISSION_DESTRUCTIVE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    Tool,
    ToolRegistry,
    ToolResult,
)

DEBIT_NORMAL = {"ASSET", "EXPENSE"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _json(payload: Any) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)


async def _run(
    handler: Callable[[dict[str, Any], dict[str, Any]], Any], args: dict[str, Any]
) -> ToolResult:
    try:
        company = store.resolve_tenant(args.get("companyId"))
        return ToolResult(ok=True, content=_json(handler(company, args)))
    except AccountingError as exc:
        return ToolResult(ok=False, content=exc.message, error_code=exc.code)


def _date(value: Any, field: str, *, default_today: bool = False) -> str:
    if value is None or value == "":
        if default_today:
            return datetime.now(UTC).date().isoformat()
        raise AccountingError(VALIDATION, f"{field} is required")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    candidate = raw[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        raise AccountingError(VALIDATION, f"{field} must be an ISO date (YYYY-MM-DD)") from None


def _optional_date(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _date(value, field)


def _month_range(month: Any, year: Any) -> tuple[int, int, str, str]:
    try:
        month_number = int(month)
        year_number = int(year)
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, "month and year must be integers") from None
    if not 1 <= month_number <= 12:
        raise AccountingError(VALIDATION, "month must be between 1 and 12")
    if not 2000 <= year_number <= 2100:
        raise AccountingError(VALIDATION, "year must be between 2000 and 2100")
    last = calendar.monthrange(year_number, month_number)[1]
    start = date(year_number, month_number, 1).isoformat()
    end = date(year_number, month_number, last).isoformat()
    return month_number, year_number, start, end


def _normalize_lines(raw_lines: Any) -> list[tuple[str, Decimal, Decimal]]:
    if not isinstance(raw_lines, list) or not raw_lines:
        raise AccountingError(VALIDATION, "Journal must contain at least one line")

    normalized: list[tuple[str, Decimal, Decimal]] = []
    total_debit = ZERO
    total_credit = ZERO

    for index, raw in enumerate(raw_lines, start=1):
        label = f"Line {index}"
        if not isinstance(raw, dict):
            raise AccountingError(VALIDATION, f"{label}: must be an object")
        account_id = raw.get("accountId")
        if not isinstance(account_id, str) or account_id.strip() == "":
            raise AccountingError(VALIDATION, f"{label}: accountId is required")
        debit = to_money(raw.get("debit"), f"{label} debit")
        credit = to_money(raw.get("credit"), f"{label} credit")
        assert_non_negative(debit, f"{label} debit")
        assert_non_negative(credit, f"{label} credit")
        if debit > 0 and credit > 0:
            raise AccountingError(
                VALIDATION, f"{label}: a line cannot have both a debit and a credit"
            )
        total_debit = add(total_debit, debit)
        total_credit = add(total_credit, credit)
        normalized.append((account_id.strip(), debit, credit))

    if total_debit != total_credit:
        raise AccountingError(
            VALIDATION,
            f"Journal is unbalanced: debits {fmt(total_debit)} != credits {fmt(total_credit)}",
        )
    return normalized


def _entry_payload(entry: dict[str, Any]) -> dict[str, Any]:
    lines = [
        {
            "id": line["id"],
            "accountId": line["account_id"],
            "debit": line["debit"],
            "credit": line["credit"],
        }
        for line in entry["lines"]
    ]
    total_debit = (
        add(*(Decimal(line["debit"]) for line in entry["lines"])) if entry["lines"] else ZERO
    )
    total_credit = (
        add(*(Decimal(line["credit"]) for line in entry["lines"])) if entry["lines"] else ZERO
    )
    return {
        "id": entry["id"],
        "date": entry["date"],
        "memo": entry["memo"],
        "status": entry["status"],
        "isLocked": bool(entry["is_locked"]),
        "lines": lines,
        "totalDebit": fmt(total_debit),
        "totalCredit": fmt(total_credit),
        "requiresApproval": entry["status"] == "PENDING",
    }


# ---------------------------------------------------------------------------
# 1. trial balance
# ---------------------------------------------------------------------------


def _trial_balance(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = []
    total_debit = ZERO
    total_credit = ZERO
    for account in store.list_accounts(company["id"]):
        balance = Decimal(account["balance"])
        debit = ZERO
        credit = ZERO
        if account["type"] in DEBIT_NORMAL:
            if balance >= 0:
                debit = balance
            else:
                credit = -balance
        else:
            if balance >= 0:
                credit = balance
            else:
                debit = -balance
        total_debit = add(total_debit, debit)
        total_credit = add(total_credit, credit)
        rows.append(
            {
                "id": account["id"],
                "code": account["code"],
                "name": account["name"],
                "type": account["type"],
                "category": account["category"],
                "isSystem": bool(account["is_system"]),
                "debit": fmt(debit),
                "credit": fmt(credit),
                "balance": fmt(balance),
            }
        )
    return {"accounts": rows, "totalDebit": fmt(total_debit), "totalCredit": fmt(total_credit)}


# ---------------------------------------------------------------------------
# 2. propose journal
# ---------------------------------------------------------------------------


def propose_entry(
    company: dict[str, Any],
    *,
    date: object,
    memo: object,
    lines: object,
) -> dict[str, Any]:
    """Validate and persist a PENDING journal. Used by every domain that
    raises a journal (sales, purchases, payroll, ...), never posts."""
    normalized = _normalize_lines(lines)
    journal_date = _date(date, "date", default_today=True)
    memo_text = str(memo).strip() if isinstance(memo, str) and memo.strip() else None

    found = store.accounts_by_ids(company["id"], [line[0] for line in normalized])
    missing = [account_id for account_id, _debit, _credit in normalized if account_id not in found]
    if missing:
        raise AccountingError(NOT_FOUND, f"Account(s) not found: {', '.join(missing)}")

    entry = store.insert_entry(
        company["id"],
        date=journal_date,
        memo=memo_text,
        lines=[(account_id, fmt(debit), fmt(credit)) for account_id, debit, credit in normalized],
    )
    store.record_audit(
        company["id"],
        action="PROPOSE_JOURNAL",
        entity_type="JournalEntry",
        entity_id=entry["id"],
        detail={"memo": entry["memo"], "date": entry["date"]},
    )
    return _entry_payload(entry)


def _propose_journal(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    payload = propose_entry(
        company, date=args.get("date"), memo=args.get("memo"), lines=args.get("lines")
    )
    payload["note"] = "PENDING: balances are unchanged until approve_journal is approved"
    return payload


# ---------------------------------------------------------------------------
# 3. approve journal
# ---------------------------------------------------------------------------


def post_entry(company: dict[str, Any], journal_id: str) -> dict[str, Any]:
    """Post a PENDING entry exactly once. Shared by approve_journal and the
    reconciliation flow, which is the one place that posts as part of an
    approval action."""
    entry = store.get_entry(company["id"], journal_id)
    if entry is None:
        raise AccountingError(NOT_FOUND, f"Journal entry {journal_id} not found")
    if entry["is_locked"]:
        raise AccountingError(STATE, "Period is locked.")
    if entry["status"] != "PENDING":
        raise AccountingError(STATE, f"Journal entry {journal_id} is not PENDING")

    # Re-validate the stored lines before any balance moves.
    normalized = _normalize_lines(
        [
            {
                "accountId": line["account_id"],
                "debit": line["debit"],
                "credit": line["credit"],
            }
            for line in entry["lines"]
        ]
    )

    if not store.claim_pending(company["id"], journal_id):
        raise AccountingError(STATE, f"Journal entry {journal_id} is not PENDING")

    accounts = store.accounts_by_ids(company["id"], [line[0] for line in normalized])
    for account_id, debit, credit in normalized:
        if debit == 0 and credit == 0:
            continue
        account = accounts.get(account_id)
        if account is None:
            raise AccountingError(NOT_FOUND, f"Account {account_id} not found")
        delta = debit - credit if account["type"] in DEBIT_NORMAL else credit - debit
        store.adjust_balance(company["id"], account_id, fmt(delta))

    posted = store.get_entry(company["id"], journal_id)
    assert posted is not None
    store.record_audit(
        company["id"],
        action="APPROVE_JOURNAL",
        entity_type="JournalEntry",
        entity_id=journal_id,
    )
    payload = _entry_payload(posted)
    payload["posted"] = True
    return payload


def _approve_journal(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    journal_id = args.get("journalId")
    if not isinstance(journal_id, str) or journal_id.strip() == "":
        raise AccountingError(VALIDATION, "journalId is required")
    return post_entry(company, journal_id.strip())


# ---------------------------------------------------------------------------
# 4. pending journals
# ---------------------------------------------------------------------------


def _pending_journals(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    entries = store.list_entries(company["id"], "PENDING")
    return {"journals": [_entry_payload(entry) for entry in entries], "count": len(entries)}


# ---------------------------------------------------------------------------
# 5. general ledger
# ---------------------------------------------------------------------------


def _general_ledger(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    account_id = args.get("accountId")
    if account_id is not None and (not isinstance(account_id, str) or account_id.strip() == ""):
        raise AccountingError(VALIDATION, "accountId must be a non-empty string")
    status = args.get("status")
    if status is None:
        status = "POSTED"
    if status not in ("PENDING", "POSTED"):
        raise AccountingError(VALIDATION, "status must be PENDING or POSTED")

    rows = store.posted_lines(
        company["id"],
        account_id=account_id.strip() if isinstance(account_id, str) else None,
        start=_optional_date(args.get("from"), "from"),
        end=_optional_date(args.get("to"), "to"),
        status=status,
    )
    lines = [
        {
            "entryId": row["entry_id"],
            "date": row["date"],
            "memo": row["memo"],
            "status": row["status"],
            "accountId": row["account_id"],
            "accountCode": row["code"],
            "accountName": row["name"],
            "debit": row["debit"],
            "credit": row["credit"],
        }
        for row in rows
    ]
    total_debit = add(*(Decimal(line["debit"]) for line in lines)) if lines else ZERO
    total_credit = add(*(Decimal(line["credit"]) for line in lines)) if lines else ZERO
    return {
        "status": status,
        "lines": lines,
        "totalDebit": fmt(total_debit),
        "totalCredit": fmt(total_credit),
    }


# ---------------------------------------------------------------------------
# 6. profit and loss
# ---------------------------------------------------------------------------


def _profit_and_loss(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    rows = store.posted_lines(
        company["id"],
        start=_optional_date(args.get("from"), "from"),
        end=_optional_date(args.get("to"), "to"),
        status="POSTED",
    )

    accounts: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["type"] not in ("REVENUE", "EXPENSE"):
            continue
        bucket = accounts.setdefault(
            row["account_id"],
            {
                "accountId": row["account_id"],
                "code": row["code"],
                "name": row["name"],
                "type": row["type"],
                "amount": ZERO,
            },
        )
        debit = Decimal(row["debit"])
        credit = Decimal(row["credit"])
        movement = credit - debit if row["type"] == "REVENUE" else debit - credit
        bucket["amount"] = add(bucket["amount"], movement)

    ordered = sorted(accounts.values(), key=lambda item: item["code"])
    revenue = [
        dict(item, amount=fmt(item["amount"]))
        for item in ordered
        if item["type"] == "REVENUE"
    ]
    expenses = [
        dict(item, amount=fmt(item["amount"]))
        for item in ordered
        if item["type"] == "EXPENSE"
    ]
    total_revenue = add(*(Decimal(item["amount"]) for item in revenue)) if revenue else ZERO
    total_expenses = add(*(Decimal(item["amount"]) for item in expenses)) if expenses else ZERO
    return {
        "from": args.get("from"),
        "to": args.get("to"),
        "revenue": revenue,
        "expenses": expenses,
        "totalRevenue": fmt(total_revenue),
        "totalExpenses": fmt(total_expenses),
        "netIncome": fmt(total_revenue - total_expenses),
    }


# ---------------------------------------------------------------------------
# 7. balance sheet
# ---------------------------------------------------------------------------


def _balance_sheet(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    as_of = _optional_date(args.get("asOf"), "asOf")
    rows = store.posted_lines(company["id"], end=as_of, status="POSTED")

    balances: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = balances.setdefault(
            row["account_id"],
            {
                "accountId": row["account_id"],
                "code": row["code"],
                "name": row["name"],
                "type": row["type"],
                "amount": ZERO,
            },
        )
        debit = Decimal(row["debit"])
        credit = Decimal(row["credit"])
        if row["type"] in ("ASSET", "EXPENSE"):
            bucket["amount"] = add(bucket["amount"], debit - credit)
        else:
            bucket["amount"] = add(bucket["amount"], credit - debit)

    ordered = sorted(balances.values(), key=lambda item: item["code"])
    assets = [
        dict(item, amount=fmt(item["amount"]))
        for item in ordered
        if item["type"] == "ASSET"
    ]
    liabilities = [
        dict(item, amount=fmt(item["amount"]))
        for item in ordered
        if item["type"] == "LIABILITY"
    ]
    equity = [
        dict(item, amount=fmt(item["amount"]))
        for item in ordered
        if item["type"] == "EQUITY"
    ]

    total_assets = add(*(Decimal(item["amount"]) for item in assets)) if assets else ZERO
    total_liabilities = (
        add(*(Decimal(item["amount"]) for item in liabilities)) if liabilities else ZERO
    )
    total_equity = add(*(Decimal(item["amount"]) for item in equity)) if equity else ZERO

    revenue = ZERO
    expenses = ZERO
    for row in rows:
        debit = Decimal(row["debit"])
        credit = Decimal(row["credit"])
        if row["type"] == "REVENUE":
            revenue = add(revenue, credit - debit)
        elif row["type"] == "EXPENSE":
            expenses = add(expenses, debit - credit)
    net_income = revenue - expenses

    return {
        "asOf": as_of,
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "totalAssets": fmt(total_assets),
        "totalLiabilities": fmt(total_liabilities),
        "totalEquity": fmt(add(total_equity, net_income)),
        "netIncome": fmt(net_income),
    }


# ---------------------------------------------------------------------------
# 8-9. period lock / unlock
# ---------------------------------------------------------------------------


def _lock_period(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    month, year, start, end = _month_range(args.get("month"), args.get("year"))
    locked = store.set_period_lock(company["id"], start, end, True)
    return {"month": month, "year": year, "locked": locked}


def _unlock_period(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    month, year, start, end = _month_range(args.get("month"), args.get("year"))
    unlocked = store.set_period_lock(company["id"], start, end, False)
    return {"month": month, "year": year, "unlocked": unlocked}


# ---------------------------------------------------------------------------
# 10. locked periods
# ---------------------------------------------------------------------------


def _locked_periods(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for row in store.locked_entries(company["id"]):
        parsed = date.fromisoformat(row["date"])
        key = (parsed.year, parsed.month)
        bucket = grouped.get(key)
        if bucket is None:
            grouped[key] = {
                "month": parsed.month,
                "year": parsed.year,
                "count": 1,
                "lockedAt": row["locked_at"],
            }
        else:
            bucket["count"] += 1
    return {"periods": sorted(grouped.values(), key=lambda item: (-item["year"], -item["month"]))}


# ---------------------------------------------------------------------------
# tool definitions
# ---------------------------------------------------------------------------

_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; requests without it fail with NO_ORGANIZATION.",
}

_DATE = {"type": "string", "description": "ISO date (YYYY-MM-DD)."}


def ledger_tools() -> list[Tool]:
    return [
        Tool(
            name="get_trial_balance",
            description=(
                "Return the trial balance: every account with code, name, type, category, "
                "debit, credit and signed balance, plus totals. Read-only. Use it to discover "
                "accountId values — never invent them."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: _run(_trial_balance, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="propose_journal",
            description=(
                "Create a PENDING double-entry journal proposal. Debits must equal credits; "
                "each line is either a debit or a credit, two decimals max, non-negative. "
                "Account balances do NOT change until approve_journal is approved."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "date": _DATE,
                    "memo": {"type": "string", "description": "Short description."},
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "accountId": {"type": "string", "minLength": 1},
                                "debit": {
                                    "type": "string",
                                    "description": 'Decimal string, e.g. "500.00".',
                                },
                                "credit": {
                                    "type": "string",
                                    "description": 'Decimal string, e.g. "500.00".',
                                },
                            },
                            "required": ["accountId"],
                        },
                    },
                },
                "required": ["lines"],
                "additionalProperties": False,
            },
            func=lambda **args: _run(_propose_journal, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="approve_journal",
            description=(
                "APPROVAL REQUIRED. Posts a PENDING journal to the ledger exactly once: it "
                "flips the status and permanently moves account balances. Refused when the "
                "entry is already posted or its period is locked. Only call after the user "
                "explicitly approves the proposed entry."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "journalId": {"type": "string", "minLength": 1},
                },
                "required": ["journalId"],
                "additionalProperties": False,
            },
            func=lambda **args: _run(_approve_journal, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
        Tool(
            name="get_pending_journals",
            description=(
                "List journal entries awaiting approval, with their lines and totals. " "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: _run(_pending_journals, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="get_general_ledger",
            description=(
                "Return journal lines for one account or the whole ledger, optionally bounded "
                "by ISO dates. Defaults to POSTED entries; pass status=PENDING for proposals."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "accountId": {
                        "type": "string",
                        "description": "Account id from get_trial_balance.",
                    },
                    "from": _DATE,
                    "to": _DATE,
                    "status": {"type": "string", "enum": ["PENDING", "POSTED"]},
                },
                "additionalProperties": False,
            },
            func=lambda **args: _run(_general_ledger, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="get_profit_and_loss",
            description="Revenue, expenses and net income for a date range. POSTED entries only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY, "from": _DATE, "to": _DATE},
                "additionalProperties": False,
            },
            func=lambda **args: _run(_profit_and_loss, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="get_balance_sheet",
            description=(
                "Assets, liabilities and equity as of a date, including net income up to that "
                "date. POSTED entries only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY, "asOf": _DATE},
                "additionalProperties": False,
            },
            func=lambda **args: _run(_balance_sheet, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="lock_period",
            description=(
                "APPROVAL REQUIRED. Locks every journal in a month so nothing in that period "
                "can be posted. Destructive: it blocks legitimate postings until unlocked."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "month": {"type": "integer"},
                    "year": {"type": "integer"},
                },
                "required": ["month", "year"],
                "additionalProperties": False,
            },
            func=lambda **args: _run(_lock_period, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
        Tool(
            name="unlock_period",
            description=(
                "APPROVAL REQUIRED. Reverses a period lock so its journals can be posted again. "
                "Destructive: reopens a previously closed accounting period."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "month": {"type": "integer"},
                    "year": {"type": "integer"},
                },
                "required": ["month", "year"],
                "additionalProperties": False,
            },
            func=lambda **args: _run(_unlock_period, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
        Tool(
            name="get_locked_periods",
            description=(
                "List months that currently contain locked journals, newest first. " "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: _run(_locked_periods, args),
            permission=PERMISSION_READ,
        ),
    ]


def register_ledger_tools(registry: ToolRegistry) -> None:
    for tool in ledger_tools():
        registry.register(tool)
