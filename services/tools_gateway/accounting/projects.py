"""Project tools (inventory rows 59-62).

Projects are analytical only: their transactions do not raise journals.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _date as parse_required_date
from tools_gateway.accounting.ledger import _optional_date as parse_optional_date
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.money import ZERO, add, fmt, to_money
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry


def _totals(company: dict[str, Any], project_id: str) -> tuple[Decimal, Decimal]:
    rows = store.select_rows("project_transactions", company["id"], {"project_id": project_id})
    revenue = ZERO
    expenses = ZERO
    for row in rows:
        if row["type"] == "REVENUE":
            revenue = add(revenue, Decimal(row["amount"]))
        else:
            expenses = add(expenses, Decimal(row["amount"]))
    return revenue, expenses


def _project_payload(project: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    revenue, expenses = _totals(company, project["id"])
    budget = Decimal(project["budget"])
    profit = revenue - expenses
    margin = (profit / revenue * 100).quantize(Decimal("0.1")) if revenue > 0 else ZERO
    return {
        "id": project["id"],
        "name": project["name"],
        "clientId": project["client_id"],
        "budget": fmt(budget),
        "spent": fmt(expenses),
        "remaining": fmt(budget - expenses),
        "revenue": fmt(revenue),
        "profit": fmt(profit),
        "margin": str(margin),
        "startDate": project["start_date"],
        "endDate": project["end_date"],
        "status": project["status"],
    }


def _create_project(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Project name is required")
    budget = to_money(args.get("budget"), "budget")
    if budget < 0:
        raise AccountingError(VALIDATION, "Budget must not be negative")
    start_date = parse_required_date(
        args.get("startDate"), "project start date", default_today=True
    )
    end_date = parse_optional_date(args.get("endDate"), "project end date")
    if end_date is not None and end_date < start_date:
        raise AccountingError(VALIDATION, "End date must be on or after the start date")

    client_id = args.get("clientId")
    if client_id is not None and client_id != "":
        if not isinstance(client_id, str):
            raise AccountingError(VALIDATION, "clientId must be a string")
        if store.get_customer(company["id"], client_id.strip()) is None:
            raise AccountingError(NOT_FOUND, f"Customer {client_id} not found")
        client_id = client_id.strip()
    else:
        client_id = None

    status = "COMPLETED" if args.get("status") == "COMPLETED" else "ACTIVE"
    project = store.insert_row(
        "projects",
        {
            "company_id": company["id"],
            "name": name.strip(),
            "client_id": client_id,
            "budget": fmt(budget),
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
        },
    )
    return {"project": _project_payload(project, company)}


def _get_projects(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("projects", company["id"], None, "start_date DESC")
    return {"projects": [_project_payload(row, company) for row in rows], "count": len(rows)}


def _add_transaction(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    project_id = args.get("projectId")
    if not isinstance(project_id, str) or project_id.strip() == "":
        raise AccountingError(VALIDATION, "projectId is required")
    project = store.select_one("projects", company["id"], {"id": project_id.strip()})
    if project is None:
        raise AccountingError(NOT_FOUND, f"Project {project_id} not found")

    txn_type = args.get("type")
    if txn_type not in ("REVENUE", "EXPENSE"):
        raise AccountingError(VALIDATION, "type must be REVENUE or EXPENSE")
    description = args.get("description")
    if not isinstance(description, str) or description.strip() == "":
        raise AccountingError(VALIDATION, "Description is required")
    amount = to_money(args.get("amount"), "amount")
    if amount <= 0:
        raise AccountingError(VALIDATION, "Amount must be greater than zero")
    txn_date = parse_required_date(args.get("date"), "transaction date", default_today=True)

    row = store.insert_row(
        "project_transactions",
        {
            "company_id": company["id"],
            "project_id": project["id"],
            "date": txn_date,
            "description": description.strip(),
            "amount": fmt(amount),
            "type": txn_type,
        },
    )
    return {
        "transaction": {
            "id": row["id"],
            "projectId": project["id"],
            "date": txn_date,
            "description": row["description"],
            "amount": fmt(amount),
            "type": txn_type,
        },
        "project": _project_payload(project, company),
    }


def _profitability(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    project_id = args.get("projectId")
    if not isinstance(project_id, str) or project_id.strip() == "":
        raise AccountingError(VALIDATION, "projectId is required")
    project = store.select_one("projects", company["id"], {"id": project_id.strip()})
    if project is None:
        raise AccountingError(NOT_FOUND, f"Project {project_id} not found")

    rows = store.select_rows(
        "project_transactions", company["id"], {"project_id": project["id"]}, "date"
    )
    revenue, expenses = _totals(company, project["id"])
    profit = revenue - expenses
    return {
        "project": _project_payload(project, company),
        "revenueLines": [
            {
                "id": row["id"],
                "date": row["date"],
                "description": row["description"],
                "amount": row["amount"],
            }
            for row in rows
            if row["type"] == "REVENUE"
        ],
        "expenseLines": [
            {
                "id": row["id"],
                "date": row["date"],
                "description": row["description"],
                "amount": row["amount"],
            }
            for row in rows
            if row["type"] == "EXPENSE"
        ],
        "totalRevenue": fmt(revenue),
        "totalExpenses": fmt(expenses),
        "profit": fmt(profit),
    }


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def project_tools() -> list[Tool]:
    return [
        Tool(
            name="create_project",
            description=(
                "Create a project with a non-negative budget; an optional client must exist and "
                "the end date cannot precede the start. No journal is raised."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string", "minLength": 1},
                    "clientId": {"type": "string"},
                    "budget": {"type": "string"},
                    "startDate": {"type": "string"},
                    "endDate": {"type": "string"},
                    "status": {"type": "string", "enum": ["ACTIVE", "COMPLETED"]},
                },
                "required": ["name", "budget"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_project, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_projects",
            description="List projects with budget, spend, revenue and profit. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_projects, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="add_project_transaction",
            description=(
                "Record project revenue or expense (amount > 0, description required). "
                "Analytical only: no journal is raised."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "projectId": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "enum": ["REVENUE", "EXPENSE"]},
                    "description": {"type": "string", "minLength": 1},
                    "amount": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["projectId", "type", "description", "amount"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_add_transaction, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_project_profitability",
            description="Revenue lines, expense lines and profit for one project. Read-only.",
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "projectId": {"type": "string", "minLength": 1},
                },
                "required": ["projectId"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_profitability, args),
            permission=PERMISSION_READ,
        ),
    ]


def register_project_tools(registry: ToolRegistry) -> None:
    for tool in project_tools():
        registry.register(tool)
