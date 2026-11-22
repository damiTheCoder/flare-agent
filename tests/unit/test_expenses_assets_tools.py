"""Expense and fixed-asset tool tests (rows 40-48)."""

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


async def account_id(reg, code: str) -> str:
    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    return next(row["id"] for row in trial["accounts"] if row["code"] == code)


async def make_category(reg, name="Rent") -> str:
    return body(await call(reg, "create_expense_category", companyId=COMPANY, name=name))["id"]


async def make_employee(reg) -> str:
    return body(
        await call(reg, "create_employee", companyId=COMPANY, name="Ada", basicSalary="100000")
    )["id"]


async def make_asset(reg, *, cost="120000.00", salvage="0.00", life=5) -> dict:
    return body(
        await call(
            reg,
            "create_asset",
            companyId=COMPANY,
            name="Laptop",
            category="IT",
            purchaseDate="2026-01-10",
            cost=cost,
            usefulLifeYears=life,
            salvageValue=salvage,
        )
    )["asset"]


async def test_category_is_idempotent(reg):
    first = await make_category(reg, "Rent")
    second = await make_category(reg, "Rent")
    assert first == second


async def test_expense_validations(reg):
    category = await make_category(reg)
    zero = await call(
        reg,
        "create_expense",
        companyId=COMPANY,
        date="2026-11-01",
        description="Rent",
        amount="0.00",
        categoryId=category,
        paymentMethod="CASH",
    )
    assert not zero.ok
    assert zero.error_code == "VALIDATION"
    assert "greater than zero" in zero.content

    missing_employee = await call(
        reg,
        "create_expense",
        companyId=COMPANY,
        date="2026-11-01",
        description="Taxi",
        amount="10.00",
        categoryId=category,
        paymentMethod="REIMBURSEMENT",
    )
    assert not missing_employee.ok
    assert missing_employee.error_code == "VALIDATION"
    assert "employeeId" in missing_employee.content


async def test_cash_expense_posts_immediately(reg):
    category = await make_category(reg)
    result = body(
        await call(
            reg,
            "create_expense",
            companyId=COMPANY,
            date="2026-11-01",
            description="Rent",
            amount="500.00",
            categoryId=category,
            paymentMethod="CASH",
        )
    )
    assert result["expense"]["status"] == "APPROVED"
    assert result["journal"]["status"] == "POSTED"

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    cash = next(row for row in trial["accounts"] if row["code"] == "1010")
    assert cash["balance"] == "-500.00"
    pending = body(await call(reg, "get_pending_journals", companyId=COMPANY))
    assert pending["count"] == 0


async def test_reimbursement_stays_pending_until_approved(reg):
    category = await make_category(reg)
    employee = await make_employee(reg)
    result = body(
        await call(
            reg,
            "create_expense",
            companyId=COMPANY,
            date="2026-11-02",
            description="Taxi",
            amount="80.00",
            categoryId=category,
            paymentMethod="REIMBURSEMENT",
            employeeId=employee,
        )
    )
    assert result["expense"]["status"] == "PENDING"
    assert result["journal"]["status"] == "PENDING"

    approved = body(
        await call(reg, "approve_expense", companyId=COMPANY, expenseId=result["expense"]["id"])
    )
    assert approved["expense"]["status"] == "APPROVED"
    assert approved["journal"]["status"] == "POSTED"

    again = await call(reg, "approve_expense", companyId=COMPANY, expenseId=result["expense"]["id"])
    assert not again.ok
    assert again.error_code == "STATE"


async def test_only_reimbursements_need_approval(reg):
    category = await make_category(reg)
    result = body(
        await call(
            reg,
            "create_expense",
            companyId=COMPANY,
            date="2026-11-03",
            description="Rent",
            amount="10.00",
            categoryId=category,
            paymentMethod="BANK",
        )
    )
    rejected = await call(
        reg, "approve_expense", companyId=COMPANY, expenseId=result["expense"]["id"]
    )
    assert not rejected.ok
    assert rejected.error_code == "STATE"
    assert "reimbursement" in rejected.content.lower()


async def test_asset_validations(reg):
    bad_salvage = await call(
        reg,
        "create_asset",
        companyId=COMPANY,
        name="Laptop",
        category="IT",
        purchaseDate="2026-01-10",
        cost="100.00",
        usefulLifeYears=5,
        salvageValue="100.00",
    )
    assert not bad_salvage.ok
    assert bad_salvage.error_code == "VALIDATION"

    bad_life = await call(
        reg,
        "create_asset",
        companyId=COMPANY,
        name="Laptop",
        category="IT",
        purchaseDate="2026-01-10",
        cost="100.00",
        usefulLifeYears=0,
    )
    assert not bad_life.ok
    assert bad_life.error_code == "VALIDATION"


async def test_asset_acquisition_is_pending(reg):
    result = body(
        await call(
            reg,
            "create_asset",
            companyId=COMPANY,
            name="Laptop",
            category="IT",
            purchaseDate="2026-01-10",
            cost="120000.00",
            usefulLifeYears=5,
        )
    )
    assert result["journal"]["status"] == "PENDING"
    assert result["asset"]["monthlyDepreciation"] == "2000.00"

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    fixed = next(row for row in trial["accounts"] if row["code"] == "1500")
    assert fixed["balance"] == "0.00"


async def test_depreciation_raises_pending_journal(reg):
    await make_asset(reg)
    result = body(await call(reg, "run_depreciation", companyId=COMPANY, month=2, year=2026))
    assert result["totalDepreciation"] == "2000.00"
    assert result["journal"]["status"] == "PENDING"

    assets = body(await call(reg, "get_assets", companyId=COMPANY))
    assert assets["assets"][0]["accumulatedDepreciation"] == "2000.00"
    assert assets["assets"][0]["bookValue"] == "118000.00"


async def test_depreciation_errors(reg):
    none = await call(reg, "run_depreciation", companyId=COMPANY, month=2, year=2026)
    assert not none.ok
    assert none.error_code == "VALIDATION"
    assert "No active assets" in none.content

    asset = await make_asset(reg)
    store.update_row(
        "fixed_assets",
        COMPANY,
        asset["id"],
        {"accumulated_depreciation": "120000.00"},
    )
    depleted = await call(reg, "run_depreciation", companyId=COMPANY, month=3, year=2026)
    assert not depleted.ok
    assert depleted.error_code == "VALIDATION"
    assert "fully depreciated" in depleted.content


async def test_disposal_loss_and_single_use(reg):
    asset = await make_asset(reg)
    await call(reg, "run_depreciation", companyId=COMPANY, month=2, year=2026)

    result = body(
        await call(
            reg,
            "dispose_asset",
            companyId=COMPANY,
            assetId=asset["id"],
            disposalDate="2026-11-30",
            proceeds="100000.00",
        )
    )
    assert result["gainOrLoss"] == "-18000.00"  # 100000 proceeds vs 118000 book
    assert result["journal"]["status"] == "PENDING"
    assert result["asset"]["isDisposed"] is True

    again = await call(
        reg,
        "dispose_asset",
        companyId=COMPANY,
        assetId=asset["id"],
        disposalDate="2026-12-01",
    )
    assert not again.ok
    assert again.error_code == "STATE"
    assert "already disposed" in again.content
