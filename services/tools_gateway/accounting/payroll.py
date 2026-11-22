"""Payroll tools (inventory rows 36-39).

Gross = basic + housing + transport. Pension is 8% of gross, NHF 2.5% of
basic, PAYE follows the simplified Nigerian bands on annual gross (divided by
twelve). The consolidated journal is PENDING; nothing posts here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, STATE, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.ledger import propose_entry
from tools_gateway.accounting.money import ZERO, add, fmt, to_money
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry

PENSION_RATE = Decimal("0.08")
NHF_RATE = Decimal("0.025")
BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal(300000), Decimal("0.07")),
    (Decimal(300000), Decimal("0.11")),
    (Decimal(500000), Decimal("0.15")),
    (Decimal(500000), Decimal("0.19")),
    (Decimal(1600000), Decimal("0.21")),
)


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


def compute_paye(annual_gross: Decimal) -> Decimal:
    remaining = annual_gross
    tax = Decimal("0.00")
    for limit, rate in BANDS:
        if remaining <= 0:
            break
        slice_amount = remaining if remaining < limit else limit
        tax += slice_amount * rate
        remaining -= slice_amount
    if remaining > 0:
        tax += remaining * Decimal("0.24")
    return tax.quantize(Decimal("0.01"))


def _employee_payload(employee: dict[str, Any]) -> dict[str, Any]:
    gross = (
        Decimal(employee["basic_salary"])
        + Decimal(employee["housing_allowance"])
        + Decimal(employee["transport_allowance"])
    )
    return {
        "id": employee["id"],
        "name": employee["name"],
        "email": employee["email"],
        "basicSalary": employee["basic_salary"],
        "housingAllowance": employee["housing_allowance"],
        "transportAllowance": employee["transport_allowance"],
        "grossSalary": fmt(gross),
        "isActive": bool(employee["is_active"]),
    }


def _get_employees(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("employees", company["id"], None, "name")
    return {"employees": [_employee_payload(row) for row in rows], "count": len(rows)}


def _create_employee(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Employee name is required")

    basic = to_money(args.get("basicSalary"), "basic salary")
    housing = to_money(
        args.get("housingAllowance") if args.get("housingAllowance") is not None else "0",
        "housing allowance",
    )
    transport = to_money(
        args.get("transportAllowance") if args.get("transportAllowance") is not None else "0",
        "transport allowance",
    )
    if basic < 0 or housing < 0 or transport < 0:
        raise AccountingError(VALIDATION, "Salary components must not be negative")

    email = args.get("email")
    row = store.insert_row(
        "employees",
        {
            "company_id": company["id"],
            "name": name.strip(),
            "email": email.strip() if isinstance(email, str) and email.strip() else None,
            "basic_salary": fmt(basic),
            "housing_allowance": fmt(housing),
            "transport_allowance": fmt(transport),
            "is_active": 1 if args.get("isActive", True) else 0,
        },
    )
    return _employee_payload(row)


def _run_payroll(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    try:
        month = int(args.get("month"))
        year = int(args.get("year"))
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, "month and year must be integers") from None
    if not 1 <= month <= 12:
        raise AccountingError(VALIDATION, "month must be between 1 and 12")
    if not 2000 <= year <= 2100:
        raise AccountingError(VALIDATION, "year must be between 2000 and 2100")
    label = f"{month:02d}"

    existing = store.select_one("payroll_runs", company["id"], {"month": label, "year": year})
    if existing is not None:
        raise AccountingError(STATE, f"Payroll for {label}/{year} has already been run")

    employees = [
        row
        for row in store.select_rows("employees", company["id"], None, "name")
        if row["is_active"] == 1
    ]
    if not employees:
        raise AccountingError(VALIDATION, "No active employees to pay")

    total_gross = ZERO
    total_paye = ZERO
    total_pension = ZERO
    total_nhf = ZERO
    total_net = ZERO

    for employee in employees:
        basic = Decimal(employee["basic_salary"])
        gross = (
            basic
            + Decimal(employee["housing_allowance"])
            + Decimal(employee["transport_allowance"])
        )
        pension = (gross * PENSION_RATE).quantize(Decimal("0.01"))
        nhf = (basic * NHF_RATE).quantize(Decimal("0.01"))
        paye = (compute_paye(gross * 12) / 12).quantize(Decimal("0.01"))
        net = gross - pension - nhf - paye

        total_gross = add(total_gross, gross)
        total_paye = add(total_paye, paye)
        total_pension = add(total_pension, pension)
        total_nhf = add(total_nhf, nhf)
        total_net = add(total_net, net)

    salaries = _require_account(company, "Salaries Expense", "EXPENSE")
    paye_payable = _require_account(company, "PAYE Payable", "LIABILITY")
    pension_payable = _require_account(company, "Pension Payable", "LIABILITY")
    nhf_payable = _require_account(company, "NHF Payable", "LIABILITY")
    net_payable = _require_account(company, "Net Salaries Payable", "LIABILITY")

    journal = propose_entry(
        company,
        date=date(year, month, 1).isoformat(),
        memo=f"Payroll {label}/{year}",
        lines=[
            {"accountId": salaries["id"], "debit": fmt(total_gross)},
            {"accountId": paye_payable["id"], "credit": fmt(total_paye)},
            {"accountId": pension_payable["id"], "credit": fmt(total_pension)},
            {"accountId": nhf_payable["id"], "credit": fmt(total_nhf)},
            {"accountId": net_payable["id"], "credit": fmt(total_net)},
        ],
    )

    run = store.insert_row(
        "payroll_runs",
        {
            "company_id": company["id"],
            "month": label,
            "year": year,
            "status": "DRAFT",
            "total_gross": fmt(total_gross),
            "total_net": fmt(total_net),
            "total_paye": fmt(total_paye),
            "total_pension": fmt(total_pension),
            "total_nhf": fmt(total_nhf),
        },
    )
    return {
        "run": {
            "id": run["id"],
            "month": run["month"],
            "year": run["year"],
            "status": run["status"],
            "totalGross": run["total_gross"],
            "totalNet": run["total_net"],
            "totalPaye": run["total_paye"],
            "totalPension": run["total_pension"],
            "totalNhf": run["total_nhf"],
        },
        "journal": journal,
        "note": "The payroll journal is PENDING; approve it with approve_journal.",
    }


def _history(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("payroll_runs", company["id"], None, "year DESC, month DESC")
    return {
        "runs": [
            {
                "id": row["id"],
                "month": row["month"],
                "year": row["year"],
                "status": row["status"],
                "totalGross": row["total_gross"],
                "totalNet": row["total_net"],
                "totalPaye": row["total_paye"],
                "totalPension": row["total_pension"],
                "totalNhf": row["total_nhf"],
            }
            for row in rows
        ],
        "count": len(rows),
    }


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def payroll_tools() -> list[Tool]:
    return [
        Tool(
            name="get_employees",
            description="List employees with salary components and monthly gross. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_employees, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_employee",
            description=(
                "Create an employee. Name and basic salary are required; allowances default to "
                "zero and must not be negative."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string", "minLength": 1},
                    "email": {"type": "string"},
                    "basicSalary": {"type": "string"},
                    "housingAllowance": {"type": "string"},
                    "transportAllowance": {"type": "string"},
                    "isActive": {"type": "boolean"},
                },
                "required": ["name", "basicSalary"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_employee, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="run_payroll",
            description=(
                "Calculate one month's payroll (pension 8%, NHF 2.5%, simplified PAYE bands) "
                "and raise a PENDING consolidated journal. A month can only be run once. "
                "Balances change only after approve_journal."
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
            func=lambda **args: run_tool(_run_payroll, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_payroll_history",
            description="List payroll runs, newest first. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_history, args),
            permission=PERMISSION_READ,
        ),
    ]


def register_payroll_tools(registry: ToolRegistry) -> None:
    for tool in payroll_tools():
        registry.register(tool)
