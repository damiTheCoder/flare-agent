"""Budget tools (inventory rows 49-52).

Budgets are planning records: creating or deleting one raises no journal.
Delete is permission=destructive because it is an irreversible reversal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.money import ZERO, add, fmt, to_money
from tools_gateway.registry import (
    PERMISSION_DESTRUCTIVE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    Tool,
    ToolRegistry,
)


def _budget_payload(budget: dict[str, Any]) -> dict[str, Any]:
    lines = store.select_rows("budget_lines", budget["company_id"], {"budget_id": budget["id"]})
    total = add(*(Decimal(line["amount"]) for line in lines)) if lines else ZERO
    return {
        "id": budget["id"],
        "name": budget["name"],
        "fiscalYear": budget["fiscal_year"],
        "status": budget["status"],
        "startDate": budget["start_date"],
        "endDate": budget["end_date"],
        "totalBudgeted": fmt(total),
        "lines": [
            {
                "accountId": line["account_id"],
                "amount": line["amount"],
                "period": line["period"],
            }
            for line in lines
        ],
    }


def _create_budget(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Budget name is required")
    try:
        fiscal_year = int(args.get("fiscalYear"))
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, "fiscalYear must be an integer") from None
    if not 2000 <= fiscal_year <= 2100:
        raise AccountingError(VALIDATION, "fiscalYear must be between 2000 and 2100")

    raw_lines = args.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise AccountingError(VALIDATION, "Budget must contain at least one line")

    resolved: list[tuple[str, Decimal, str]] = []
    account_ids = []
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise AccountingError(VALIDATION, f"Line {index}: must be an object")
        account_id = raw.get("accountId")
        if not isinstance(account_id, str) or account_id.strip() == "":
            raise AccountingError(VALIDATION, f"Line {index}: accountId is required")
        amount = to_money(raw.get("amount"), f"Line {index} amount")
        if amount < 0:
            raise AccountingError(VALIDATION, "Budget amount must not be negative")
        period = "MONTHLY" if raw.get("period") == "MONTHLY" else "ANNUAL"
        resolved.append((account_id.strip(), amount, period))
        account_ids.append(account_id.strip())

    missing = [
        account_id
        for account_id in set(account_ids)
        if store.account_by_id(company["id"], account_id) is None
    ]
    if missing:
        raise AccountingError(NOT_FOUND, f"Account(s) not found: {', '.join(sorted(missing))}")

    budget = store.insert_row(
        "budgets",
        {
            "company_id": company["id"],
            "name": name.strip(),
            "fiscal_year": fiscal_year,
            "start_date": f"{fiscal_year}-01-01",
            "end_date": f"{fiscal_year}-12-31",
            "status": "ACTIVE",
        },
    )
    for account_id, amount, period in resolved:
        store.insert_row(
            "budget_lines",
            {
                "company_id": company["id"],
                "budget_id": budget["id"],
                "account_id": account_id,
                "amount": fmt(amount),
                "period": period,
            },
        )
    return {"budget": _budget_payload(budget)}


def _get_budgets(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("budgets", company["id"], None, "fiscal_year DESC, name")
    return {"budgets": [_budget_payload(row) for row in rows], "count": len(rows)}


def _vs_actual(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    budget_id = args.get("budgetId")
    if not isinstance(budget_id, str) or budget_id.strip() == "":
        raise AccountingError(VALIDATION, "budgetId is required")
    budget = store.select_one("budgets", company["id"], {"id": budget_id.strip()})
    if budget is None:
        raise AccountingError(NOT_FOUND, f"Budget {budget_id} not found")

    lines = store.select_rows("budget_lines", company["id"], {"budget_id": budget["id"]})
    results = []
    total_budgeted = ZERO
    total_actual = ZERO

    for line in lines:
        account = store.account_by_id(company["id"], line["account_id"])
        if account is None:
            continue
        debit_normal = account["type"] in ("ASSET", "EXPENSE")
        actual = ZERO
        for movement in store.posted_lines(
            company["id"],
            account_id=account["id"],
            start=budget["start_date"],
            end=budget["end_date"],
        ):
            debit = Decimal(movement["debit"])
            credit = Decimal(movement["credit"])
            actual = add(actual, debit - credit if debit_normal else credit - debit)
        budgeted = Decimal(line["amount"])
        variance = budgeted - actual
        percentage = (
            ZERO if budgeted == 0 else (variance / budgeted * 100).quantize(Decimal("0.01"))
        )
        total_budgeted = add(total_budgeted, budgeted)
        total_actual = add(total_actual, actual)
        results.append(
            {
                "accountId": account["id"],
                "code": account["code"],
                "account": account["name"],
                "type": account["type"],
                "period": line["period"],
                "budgeted": fmt(budgeted),
                "actual": fmt(actual),
                "variance": fmt(variance),
                "variancePercent": str(percentage),
            }
        )

    return {
        "budgetId": budget["id"],
        "name": budget["name"],
        "fiscalYear": budget["fiscal_year"],
        "lines": results,
        "totalBudgeted": fmt(total_budgeted),
        "totalActual": fmt(total_actual),
        "totalVariance": fmt(total_budgeted - total_actual),
    }


def _delete_budget(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    budget_id = args.get("budgetId")
    if not isinstance(budget_id, str) or budget_id.strip() == "":
        raise AccountingError(VALIDATION, "budgetId is required")
    budget = store.select_one("budgets", company["id"], {"id": budget_id.strip()})
    if budget is None:
        raise AccountingError(NOT_FOUND, f"Budget {budget_id} not found")
    store.delete_rows("budget_lines", company["id"], {"budget_id": budget["id"]})
    store.delete_row("budgets", company["id"], budget["id"])
    store.record_audit(
        company["id"], action="DELETE_BUDGET", entity_type="Budget", entity_id=budget["id"]
    )
    return {"deleted": True, "budgetId": budget["id"], "name": budget["name"]}


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def budget_tools() -> list[Tool]:
    return [
        Tool(
            name="create_budget",
            description=(
                "Create an active budget for a fiscal year with one or more account lines. "
                "Amounts must be non-negative. No journal is raised."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string", "minLength": 1},
                    "fiscalYear": {"type": "integer"},
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "accountId": {"type": "string", "minLength": 1},
                                "amount": {"type": "string"},
                                "period": {"type": "string", "enum": ["MONTHLY", "ANNUAL"]},
                            },
                            "required": ["accountId"],
                        },
                    },
                },
                "required": ["name", "fiscalYear", "lines"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_budget, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_budgets",
            description="List budgets with totals, newest fiscal year first. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_budgets, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="get_budget_vs_actual",
            description=(
                "Compare a budget against POSTED actuals for its fiscal year, per line, with "
                "variance and variance percent. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "budgetId": {"type": "string", "minLength": 1},
                },
                "required": ["budgetId"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_vs_actual, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="delete_budget",
            description=(
                "APPROVAL REQUIRED. Delete a budget and its lines. Irreversible; no journal is "
                "raised."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "budgetId": {"type": "string", "minLength": 1},
                },
                "required": ["budgetId"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_delete_budget, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
    ]


def register_budget_tools(registry: ToolRegistry) -> None:
    for tool in budget_tools():
        registry.register(tool)
