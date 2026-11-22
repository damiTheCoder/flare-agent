"""Equity and loan tools (inventory rows 53-58).

Equity injections, dividends, loans and repayments all raise PENDING
journals. Nothing posts here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, STATE, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _date as parse_required_date
from tools_gateway.accounting.ledger import _optional_date as parse_optional_date
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.ledger import propose_entry
from tools_gateway.accounting.money import ZERO, add, fmt, to_money
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


# ---------------------------------------------------------------------------
# equity
# ---------------------------------------------------------------------------


def _create_equity(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    equity_type = args.get("type")
    if equity_type not in ("SHARE_CAPITAL", "RETAINED_EARNINGS_ADJUSTMENT"):
        raise AccountingError(
            VALIDATION, "type must be SHARE_CAPITAL or RETAINED_EARNINGS_ADJUSTMENT"
        )
    amount = to_money(args.get("amount"), "equity amount")
    if amount <= 0:
        raise AccountingError(VALIDATION, "Equity amount must be greater than zero")
    equity_date = parse_required_date(args.get("date"), "equity date", default_today=True)
    description = args.get("description")
    label = (
        description.strip()
        if isinstance(description, str) and description.strip()
        else equity_type.replace("_", " ").lower()
    )

    cash = _require_account(company, "Cash", "ASSET")
    credit = _require_account(
        company,
        "Share Capital" if equity_type == "SHARE_CAPITAL" else "Retained Earnings",
        "EQUITY",
    )

    journal = propose_entry(
        company,
        date=equity_date,
        memo=f"Equity: {label}",
        lines=[
            {"accountId": cash["id"], "debit": fmt(amount)},
            {"accountId": credit["id"], "credit": fmt(amount)},
        ],
    )
    row = store.insert_row(
        "equity_transactions",
        {
            "company_id": company["id"],
            "type": equity_type,
            "amount": fmt(amount),
            "date": equity_date,
            "description": label,
            "journal_entry_id": journal["id"],
        },
    )
    return {
        "equity": {
            "id": row["id"],
            "type": equity_type,
            "amount": fmt(amount),
            "date": equity_date,
            "description": label,
        },
        "journal": journal,
        "note": "The journal is PENDING; approve it with approve_journal.",
    }


def _record_dividend(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    amount = to_money(args.get("amount"), "dividend amount")
    if amount <= 0:
        raise AccountingError(VALIDATION, "Dividend amount must be greater than zero")
    dividend_date = parse_required_date(args.get("date"), "dividend date", default_today=True)
    description = args.get("description")
    label = (
        description.strip()
        if isinstance(description, str) and description.strip()
        else "Dividend declared"
    )

    cash = _require_account(company, "Cash", "ASSET")
    retained = _require_account(company, "Retained Earnings", "EQUITY")

    journal = propose_entry(
        company,
        date=dividend_date,
        memo=f"Dividend: {label}",
        lines=[
            {"accountId": retained["id"], "debit": fmt(amount)},
            {"accountId": cash["id"], "credit": fmt(amount)},
        ],
    )
    row = store.insert_row(
        "equity_transactions",
        {
            "company_id": company["id"],
            "type": "DIVIDEND",
            "amount": fmt(amount),
            "date": dividend_date,
            "description": label,
            "journal_entry_id": journal["id"],
        },
    )
    return {
        "equity": {
            "id": row["id"],
            "type": "DIVIDEND",
            "amount": fmt(amount),
            "date": dividend_date,
            "description": label,
        },
        "journal": journal,
        "note": "The journal is PENDING; approve it with approve_journal.",
    }


def _equity_summary(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    transactions = store.select_rows(
        "equity_transactions", company["id"], None, "date DESC, created_at DESC"
    )
    rows = [
        {
            "id": row["id"],
            "type": row["type"],
            "amount": row["amount"],
            "date": row["date"],
            "description": row["description"],
        }
        for row in transactions
    ]
    share_capital = ZERO
    retained = ZERO
    for account in store.list_accounts(company["id"]):
        if account["name"] == "Share Capital":
            share_capital = Decimal(account["balance"])
        elif account["name"] == "Retained Earnings":
            retained = Decimal(account["balance"])
    dividends = (
        add(*(Decimal(row["amount"]) for row in rows if row["type"] == "DIVIDEND"))
        if any(row["type"] == "DIVIDEND" for row in rows)
        else ZERO
    )
    return {
        "shareCapital": fmt(share_capital),
        "retainedEarnings": fmt(retained),
        "dividendsDeclared": fmt(dividends),
        "transactions": rows,
    }


# ---------------------------------------------------------------------------
# loans
# ---------------------------------------------------------------------------


def _loan_payload(loan: dict[str, Any]) -> dict[str, Any]:
    repayments = store.select_rows(
        "loan_repayments", loan["company_id"], {"loan_id": loan["id"]}, "date"
    )
    return {
        "id": loan["id"],
        "lenderName": loan["lender_name"],
        "principalAmount": loan["principal_amount"],
        "interestRate": loan["interest_rate"],
        "startDate": loan["start_date"],
        "termMonths": loan["term_months"],
        "balance": loan["balance"],
        "status": loan["status"],
        "repayments": [
            {
                "id": row["id"],
                "date": row["date"],
                "principalPaid": row["principal_paid"],
                "interestPaid": row["interest_paid"],
                "totalPaid": row["total_paid"],
            }
            for row in repayments
        ],
    }


def _create_loan(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    lender = args.get("lenderName")
    if not isinstance(lender, str) or lender.strip() == "":
        raise AccountingError(VALIDATION, "Lender name is required")
    principal = to_money(args.get("principalAmount"), "loan principal")
    if principal <= 0:
        raise AccountingError(VALIDATION, "Loan principal must be greater than zero")
    rate = to_money(args.get("interestRate"), "interest rate")
    if rate < 0 or rate > 100:
        raise AccountingError(VALIDATION, "Interest rate must be between 0 and 100")
    try:
        term = int(args.get("termMonths"))
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, "termMonths must be a positive integer") from None
    if term < 1:
        raise AccountingError(VALIDATION, "termMonths must be a positive integer")
    start_date = parse_required_date(args.get("startDate"), "loan start date", default_today=True)

    cash = _require_account(company, "Cash", "ASSET")
    payable = _require_account(company, "Long-term Loans", "LIABILITY")

    journal = propose_entry(
        company,
        date=start_date,
        memo=f"Loan received from {lender.strip()}",
        lines=[
            {"accountId": cash["id"], "debit": fmt(principal)},
            {"accountId": payable["id"], "credit": fmt(principal)},
        ],
    )
    loan = store.insert_row(
        "loans",
        {
            "company_id": company["id"],
            "lender_name": lender.strip(),
            "principal_amount": fmt(principal),
            "interest_rate": fmt(rate),
            "start_date": start_date,
            "term_months": term,
            "balance": fmt(principal),
            "status": "ACTIVE",
        },
    )
    return {
        "loan": _loan_payload(loan),
        "journal": journal,
        "note": "The journal is PENDING; approve it with approve_journal.",
    }


def _get_loans(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("loans", company["id"], None, "start_date DESC")
    return {"loans": [_loan_payload(row) for row in rows], "count": len(rows)}


def _record_repayment(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    loan_id = args.get("loanId")
    if not isinstance(loan_id, str) or loan_id.strip() == "":
        raise AccountingError(VALIDATION, "loanId is required")
    amount = to_money(args.get("amount"), "repayment amount")
    if amount <= 0:
        raise AccountingError(VALIDATION, "Repayment amount must be greater than zero")

    loan = store.select_one("loans", company["id"], {"id": loan_id.strip()})
    if loan is None:
        raise AccountingError(NOT_FOUND, f"Loan {loan_id} not found")
    if loan["status"] == "PAID":
        raise AccountingError(STATE, "Loan is already fully paid")

    bank_id = args.get("bankAccountId")
    if not isinstance(bank_id, str) or bank_id.strip() == "":
        raise AccountingError(VALIDATION, "bankAccountId is required")
    bank = store.account_by_id(company["id"], bank_id.strip())
    if bank is None:
        raise AccountingError(NOT_FOUND, f"Account {bank_id} not found")
    if bank["type"] != "ASSET":
        raise AccountingError(VALIDATION, "Bank account must be an ASSET account")

    payable = _require_account(company, "Long-term Loans", "LIABILITY")
    interest_account = _require_account(company, "Interest Expense", "EXPENSE")

    balance = Decimal(loan["balance"])
    monthly_interest = (balance * Decimal(loan["interest_rate"]) / 100 / 12).quantize(
        Decimal("0.01")
    )

    interest_paid = amount if amount < monthly_interest else monthly_interest
    principal_paid = amount - interest_paid
    if principal_paid > balance:
        principal_paid = balance
        interest_paid = amount - principal_paid
    total_paid = principal_paid + interest_paid
    repayment_date = parse_optional_date(args.get("date"), "repayment date")

    lines = [{"accountId": payable["id"], "debit": fmt(principal_paid)}]
    if interest_paid > 0:
        lines.append({"accountId": interest_account["id"], "debit": fmt(interest_paid)})
    lines.append({"accountId": bank["id"], "credit": fmt(total_paid)})

    journal = propose_entry(
        company,
        date=repayment_date,
        memo=f"Loan repayment: {loan['lender_name']}",
        lines=lines,
    )

    new_balance = balance - principal_paid
    store.update_row(
        "loans",
        company["id"],
        loan["id"],
        {"balance": fmt(new_balance), "status": "PAID" if new_balance <= 0 else "ACTIVE"},
    )
    repayment = store.insert_row(
        "loan_repayments",
        {
            "company_id": company["id"],
            "loan_id": loan["id"],
            "date": repayment_date or loan["start_date"],
            "principal_paid": fmt(principal_paid),
            "interest_paid": fmt(interest_paid),
            "total_paid": fmt(total_paid),
            "journal_entry_id": journal["id"],
        },
    )
    updated = store.select_one("loans", company["id"], {"id": loan["id"]})
    return {
        "loan": _loan_payload(updated) if updated else None,
        "repayment": {
            "id": repayment["id"],
            "principalPaid": fmt(principal_paid),
            "interestPaid": fmt(interest_paid),
            "totalPaid": fmt(total_paid),
        },
        "journal": journal,
        "note": "The repayment journal is PENDING; approve it with approve_journal.",
    }


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def finance_tools() -> list[Tool]:
    return [
        Tool(
            name="create_equity_transaction",
            description=(
                "Record share capital or a retained-earnings adjustment and raise a PENDING "
                "journal (debit Cash / credit the equity account)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "type": {
                        "type": "string",
                        "enum": ["SHARE_CAPITAL", "RETAINED_EARNINGS_ADJUSTMENT"],
                    },
                    "amount": {"type": "string"},
                    "date": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["type", "amount"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_equity, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="record_dividend",
            description=(
                "Declare a dividend and raise a PENDING journal (debit Retained Earnings / "
                "credit Cash)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "amount": {"type": "string"},
                    "date": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["amount"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_record_dividend, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_equity_summary",
            description=(
                "Share capital, retained earnings, dividends declared and equity "
                "transactions. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_equity_summary, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_loan",
            description=(
                "Record a loan received and raise a PENDING journal (debit Cash / credit "
                "Long-term Loans). Interest rate is 0-100."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "lenderName": {"type": "string", "minLength": 1},
                    "principalAmount": {"type": "string"},
                    "interestRate": {"type": "string"},
                    "startDate": {"type": "string"},
                    "termMonths": {"type": "integer"},
                },
                "required": ["lenderName", "principalAmount", "interestRate", "termMonths"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_loan, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_loans",
            description="List loans with balance, status and repayments. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_loans, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="record_loan_repayment",
            description=(
                "Record a loan repayment, splitting it between interest (balance x rate / 12) "
                "and principal, and raise a PENDING journal. Refuses a settled loan or a "
                "non-asset account."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "loanId": {"type": "string", "minLength": 1},
                    "amount": {"type": "string"},
                    "bankAccountId": {"type": "string", "minLength": 1},
                    "date": {"type": "string"},
                },
                "required": ["loanId", "amount", "bankAccountId"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_record_repayment, args),
            permission=PERMISSION_WRITE,
        ),
    ]


def register_finance_tools(registry: ToolRegistry) -> None:
    for tool in finance_tools():
        registry.register(tool)
