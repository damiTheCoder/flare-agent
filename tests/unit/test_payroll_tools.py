"""Payroll tool tests (rows 36-39)."""

from __future__ import annotations

import json

import pytest

from tools_gateway.accounting import store
from tools_gateway.builtin import create_default_registry

COMPANY = "acme"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.delenv("FLARE_ACCOUNTING_TENANTS", raising=False)
    store.reset_for_tests(str(tmp_path / "accounting.db"))
    yield
    store.reset_for_tests(str(tmp_path / "closed.db"))


@pytest.fixture()
def reg():
    return create_default_registry()


async def call(reg, tool_name: str, **args):
    return await reg.execute(tool_name, args)


def body(result) -> dict:
    assert result.ok, result.content
    return json.loads(result.content)


async def make_employee(
    reg, name="Ada", basic="300000.00", housing="100000.00", transport="50000.00"
):
    return body(
        await call(
            reg,
            "create_employee",
            companyId=COMPANY,
            name=name,
            basicSalary=basic,
            housingAllowance=housing,
            transportAllowance=transport,
        )
    )


async def test_requires_tenant(reg):
    result = await call(reg, "get_employees")
    assert not result.ok
    assert result.error_code == "NO_ORGANIZATION"


async def test_employee_name_and_negative_components(reg):
    blank = await call(reg, "create_employee", companyId=COMPANY, name=" ", basicSalary="1")
    assert not blank.ok
    assert blank.error_code == "VALIDATION"

    negative = await call(reg, "create_employee", companyId=COMPANY, name="X", basicSalary="-1")
    assert not negative.ok
    assert negative.error_code == "VALIDATION"
    assert "negative" in negative.content


async def test_employee_gross(reg):
    employee = await make_employee(reg)
    assert employee["grossSalary"] == "450000.00"
    assert employee["isActive"] is True


async def test_run_payroll_math(reg):
    await make_employee(reg)
    result = body(await call(reg, "run_payroll", companyId=COMPANY, month=11, year=2026))

    run = result["run"]
    assert run["totalGross"] == "450000.00"
    assert run["totalPension"] == "36000.00"  # 8% of gross
    assert run["totalNhf"] == "7500.00"  # 2.5% of basic
    assert run["totalPaye"] == "90666.67"
    assert run["totalNet"] == "315833.33"

    journal = result["journal"]
    assert journal["status"] == "PENDING"
    assert journal["totalDebit"] == "450000.00"
    assert journal["totalCredit"] == "450000.00"


async def test_payroll_runs_once_per_month(reg):
    await make_employee(reg)
    first = await call(reg, "run_payroll", companyId=COMPANY, month=11, year=2026)
    assert first.ok
    second = await call(reg, "run_payroll", companyId=COMPANY, month=11, year=2026)
    assert not second.ok
    assert second.error_code == "STATE"
    assert "already been run" in second.content


async def test_payroll_requires_active_employees(reg):
    result = await call(reg, "run_payroll", companyId=COMPANY, month=11, year=2026)
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "No active employees" in result.content


async def test_payroll_month_bounds(reg):
    await make_employee(reg)
    result = await call(reg, "run_payroll", companyId=COMPANY, month=13, year=2026)
    assert not result.ok
    assert result.error_code == "VALIDATION"


async def test_history_and_balances_untouched(reg):
    await make_employee(reg)
    await call(reg, "run_payroll", companyId=COMPANY, month=11, year=2026)
    history = body(await call(reg, "get_payroll_history", companyId=COMPANY))
    assert history["count"] == 1
    assert history["runs"][0]["month"] == "11"

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    salaries = next(row for row in trial["accounts"] if row["code"] == "5100")
    assert salaries["balance"] == "0.00"
