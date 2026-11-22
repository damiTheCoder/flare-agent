"""Expense tools (inventory rows 40-44).

CASH and BANK expenses post immediately (the inventory says so explicitly);
REIMBURSEMENT claims stay PENDING until approve_expense. That approval tool is
permission=destructive.
"""

from __future__ import annotations

from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, STATE, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _date as parse_required_date
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.ledger import post_entry, propose_entry
from tools_gateway.accounting.money import fmt, to_money
from tools_gateway.registry import (
    PERMISSION_DESTRUCTIVE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    Tool,
    ToolRegistry,
)

METHODS = ("CASH", "BANK", "REIMBURSEMENT")


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


def _expense_payload(expense: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    category = store.select_one("expense_categories", company["id"], {"id": expense["category_id"]})
    employee = (
        store.select_one("employees", company["id"], {"id": expense["employee_id"]})
        if expense["employee_id"]
        else None
    )
    return {
        "id": expense["id"],
        "date": expense["date"],
        "description": expense["description"],
        "amount": expense["amount"],
        "categoryId": expense["category_id"],
        "category": category["name"] if category else None,
        "employeeId": expense["employee_id"],
        "employee": employee["name"] if employee else None,
        "paymentMethod": expense["payment_method"],
        "status": expense["status"],
        "journalEntryId": expense["journal_entry_id"],
    }


def _get_categories(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("expense_categories", company["id"], None, "name")
    return {"categories": [{"id": r["id"], "name": r["name"]} for r in rows], "count": len(rows)}


def _create_category(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Category name is required")
    existing = store.select_one("expense_categories", company["id"], {"name": name.strip()})
    if existing is not None:
        return {"id": existing["id"], "name": existing["name"]}
    row = store.insert_row(
        "expense_categories", {"company_id": company["id"], "name": name.strip()}
    )
    return {"id": row["id"], "name": row["name"]}


def _get_expenses(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("expenses", company["id"], None, "date DESC, created_at DESC")
    return {
        "expenses": [_expense_payload(row, company) for row in rows],
        "count": len(rows),
    }


def _create_expense(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    expense_date = parse_required_date(args.get("date"), "expense date")
    description = args.get("description")
    if not isinstance(description, str) or description.strip() == "":
        raise AccountingError(VALIDATION, "Description is required")
    amount = to_money(args.get("amount"), "expense amount")
    if amount <= 0:
        raise AccountingError(VALIDATION, "Expense amount must be greater than zero")
    method = args.get("paymentMethod")
    if method not in METHODS:
        raise AccountingError(VALIDATION, "paymentMethod must be CASH, BANK or REIMBURSEMENT")

    category_id = args.get("categoryId")
    if not isinstance(category_id, str) or category_id.strip() == "":
        raise AccountingError(VALIDATION, "categoryId is required")
    category = store.select_one("expense_categories", company["id"], {"id": category_id.strip()})
    if category is None:
        raise AccountingError(NOT_FOUND, f"Category {category_id} not found")

    employee_id = None
    if method == "REIMBURSEMENT":
        raw_employee = args.get("employeeId")
        if not isinstance(raw_employee, str) or raw_employee.strip() == "":
            raise AccountingError(VALIDATION, "employeeId is required for a reimbursement")
        employee = store.select_one("employees", company["id"], {"id": raw_employee.strip()})
        if employee is None:
            raise AccountingError(NOT_FOUND, f"Employee {raw_employee} not found")
        employee_id = employee["id"]

    by_name = store.account_by_name(company["id"], f"{category['name']} Expense")
    if by_name is not None and by_name["type"] == "EXPENSE":
        expense_account = by_name
    else:
        expense_account = store.account_by_name(company["id"], "Office Supplies Expense")
        if expense_account is None:
            expense_account = next(
                (a for a in store.list_accounts(company["id"]) if a["type"] == "EXPENSE"),
                None,
            )
    if expense_account is None:
        raise AccountingError(NOT_FOUND, "No expense account is configured")

    if method == "CASH":
        credit_account = _require_account(company, "Cash", "ASSET")
    elif method == "BANK":
        credit_account = _require_account(company, "Bank", "ASSET")
    else:
        credit_account = _require_account(company, "Employee Reimbursement Payable", "LIABILITY")

    proposed = propose_entry(
        company,
        date=expense_date,
        memo=f"Expense: {description.strip()}",
        lines=[
            {"accountId": expense_account["id"], "debit": fmt(amount)},
            {"accountId": credit_account["id"], "credit": fmt(amount)},
        ],
    )

    status = "PENDING" if method == "REIMBURSEMENT" else "APPROVED"
    row = store.insert_row(
        "expenses",
        {
            "company_id": company["id"],
            "date": expense_date,
            "description": description.strip(),
            "amount": fmt(amount),
            "category_id": category["id"],
            "employee_id": employee_id,
            "payment_method": method,
            "status": status,
            "journal_entry_id": proposed["id"],
        },
    )

    journal = proposed
    if method != "REIMBURSEMENT":
        journal = post_entry(company, proposed["id"])

    return {
        "expense": _expense_payload(row, company),
        "journal": journal,
        "note": (
            "The claim is PENDING; approve it with approve_expense."
            if method == "REIMBURSEMENT"
            else "The journal posted immediately because the expense was paid at source."
        ),
    }


def _approve_expense(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    expense_id = args.get("expenseId")
    if not isinstance(expense_id, str) or expense_id.strip() == "":
        raise AccountingError(VALIDATION, "expenseId is required")
    expense = store.select_one("expenses", company["id"], {"id": expense_id.strip()})
    if expense is None:
        raise AccountingError(NOT_FOUND, f"Expense {expense_id} not found")
    if expense["payment_method"] != "REIMBURSEMENT":
        raise AccountingError(STATE, "Only reimbursement claims need approval")
    if expense["status"] != "PENDING":
        raise AccountingError(STATE, f"Expense {expense_id} is not pending")

    journal = None
    if expense["journal_entry_id"]:
        journal = post_entry(company, expense["journal_entry_id"])

    updated = store.update_row("expenses", company["id"], expense["id"], {"status": "APPROVED"})
    store.record_audit(
        company["id"],
        action="APPROVE_EXPENSE",
        entity_type="Expense",
        entity_id=expense["id"],
    )
    return {
        "expense": _expense_payload(updated, company),
        "journal": journal,
        "note": "The reimbursement journal was posted by this approval.",
    }


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def expense_tools() -> list[Tool]:
    return [
        Tool(
            name="get_expense_categories",
            description="List expense categories. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_categories, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_expense_category",
            description=(
                "Create an expense category; returns the existing one if the name is " "taken."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string", "minLength": 1},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_category, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_expenses",
            description="List expenses with category, employee, method and status. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_expenses, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_expense",
            description=(
                "Record an expense. CASH and BANK expenses post their journal immediately; "
                "REIMBURSEMENT claims stay PENDING until approve_expense. Reimbursements "
                "require employeeId."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "date": {"type": "string"},
                    "description": {"type": "string", "minLength": 1},
                    "amount": {"type": "string"},
                    "categoryId": {"type": "string", "minLength": 1},
                    "employeeId": {"type": "string"},
                    "paymentMethod": {
                        "type": "string",
                        "enum": ["CASH", "BANK", "REIMBURSEMENT"],
                    },
                },
                "required": ["date", "description", "amount", "categoryId", "paymentMethod"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_expense, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="approve_expense",
            description=(
                "APPROVAL REQUIRED. Approve a pending reimbursement claim and post its journal. "
                "Only REIMBURSEMENT claims need approval; anything else is a STATE error."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "expenseId": {"type": "string", "minLength": 1},
                },
                "required": ["expenseId"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_approve_expense, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
    ]


def register_expense_tools(registry: ToolRegistry) -> None:
    for tool in expense_tools():
        registry.register(tool)
