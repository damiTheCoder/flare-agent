"""Tax and audit tool tests (rows 11-12, 32-35)."""

from __future__ import annotations

import csv
import io
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


def rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


async def account_id(reg, code: str) -> str:
    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    return next(row["id"] for row in trial["accounts"] if row["code"] == code)


async def seed_sales_and_bill(reg) -> None:
    customer = body(await call(reg, "create_customer", companyId=COMPANY, name="Ada"))["id"]
    item = body(await call(reg, "create_item", companyId=COMPANY, name="W", price="100.00"))["id"]
    await call(
        reg,
        "create_invoice",
        companyId=COMPANY,
        customerId=customer,
        date="2026-11-10",
        items=[{"itemId": item, "quantity": 2}],
    )
    vendor = body(await call(reg, "create_vendor", companyId=COMPANY, name="Sup"))["id"]
    await call(
        reg,
        "create_bill",
        companyId=COMPANY,
        vendorId=vendor,
        date="2026-11-12",
        whtRate=5,
        items=[{"description": "Paper", "quantity": 1, "unitCost": "1000.00"}],
    )


async def test_tax_summary_reflects_posted_balances(reg):
    await seed_sales_and_bill(reg)
    summary = body(await call(reg, "get_tax_summary", companyId=COMPANY))
    # Nothing has been approved yet, so the VAT payable balance is zero while
    # WHT counts pending bills (matching get_wht_summary).
    assert summary["vatPayable"] == "0.00"
    assert summary["whtPayable"] == "50.00"


async def test_vat_schedule_lists_output_and_input(reg):
    await seed_sales_and_bill(reg)
    result = await call(reg, "get_vat_schedule", companyId=COMPANY, month=11, year=2026)
    assert result.ok
    assert result.artifacts["format"] == "csv"
    grid = rows(result.content)
    data = {row[1]: row for row in grid[1:-3]}
    # Invoice: 200.00 net, 15.00 VAT.
    assert data["INV-0001"][4] == "200.00"
    assert data["INV-0001"][5] == "15.00"
    # Bill: 1000.00 net, 75.00 VAT.
    assert data["BILL-0001"][4] == "1000.00"
    assert data["BILL-0001"][5] == "75.00"
    assert grid[-1][5] == "-60.00"  # net VAT: 15 output - 75 input


async def test_wht_schedule_lists_bills(reg):
    await seed_sales_and_bill(reg)
    result = await call(reg, "get_wht_schedule", companyId=COMPANY, month=11, year=2026)
    grid = rows(result.content)
    assert grid[1][0] == "BILL-0001"
    assert grid[1][5] == "50.00"
    assert grid[-1][5] == "50.00"


async def test_schedule_rejects_bad_month(reg):
    result = await call(reg, "get_vat_schedule", companyId=COMPANY, month=13, year=2026)
    assert not result.ok
    assert result.error_code == "VALIDATION"


async def test_audit_log_records_journal_actions(reg):
    cash = await account_id(reg, "1010")
    sales = await account_id(reg, "4000")
    proposed = body(
        await call(
            reg,
            "propose_journal",
            companyId=COMPANY,
            lines=[
                {"accountId": cash, "debit": "10.00"},
                {"accountId": sales, "credit": "10.00"},
            ],
        )
    )
    await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"])
    log = body(await call(reg, "get_audit_log", companyId=COMPANY))
    actions = [row["action"] for row in log["items"]]
    assert "APPROVE_JOURNAL" in actions
    assert "PROPOSE_JOURNAL" in actions

    filtered = body(await call(reg, "get_audit_log", companyId=COMPANY, action="APPROVE_JOURNAL"))
    assert filtered["total"] == 1


async def test_audit_log_pagination_bounds(reg):
    bad = await call(reg, "get_audit_log", companyId=COMPANY, pageSize=500)
    assert not bad.ok
    assert bad.error_code == "VALIDATION"


async def test_audit_export_bundles_ledger(reg):
    await seed_sales_and_bill(reg)
    bundle = body(await call(reg, "export_audit_package", companyId=COMPANY))
    assert bundle["company"]["id"] == COMPANY
    assert len(bundle["accounts"]) >= 20
    assert len(bundle["invoices"]) == 1
    assert len(bundle["bills"]) == 1
