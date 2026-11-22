"""Purchases tool tests (Batch 3).

Covers the edge cases that matter for bills: unknown vendor, empty lines,
positive total, VAT 7.5%, WHT bounds and math, netPayable, pending-only
journals, payment guards and AP aging.

Note: "double-match" is a bank-reconciliation rule (inventory row 31, the
banking batch); the equivalent guard here is paying a bill twice, which is
covered below.
"""

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


async def make_vendor(reg, name: str = "Supply Co") -> str:
    return body(await call(reg, "create_vendor", companyId=COMPANY, name=name))["id"]


async def make_bill(reg, vendor: str, *, wht_rate=None, quantity=1, unit_cost="1000.00"):
    args = {
        "companyId": COMPANY,
        "vendorId": vendor,
        "date": "2026-11-15",
        "items": [
            {"description": "Paper", "quantity": quantity, "unitCost": unit_cost},
        ],
    }
    if wht_rate is not None:
        args["whtRate"] = wht_rate
    return await call(reg, "create_bill", **args)


async def test_requires_tenant(reg):
    result = await call(reg, "get_vendors")
    assert not result.ok
    assert result.error_code == "NO_ORGANIZATION"


async def test_create_vendor_requires_name(reg):
    result = await call(reg, "create_vendor", companyId=COMPANY, name="  ")
    assert not result.ok
    assert result.error_code == "VALIDATION"


async def test_vendors_are_listed_alphabetically(reg):
    await make_vendor(reg, "Zenith")
    await make_vendor(reg, "Alpha")
    listed = body(await call(reg, "get_vendors", companyId=COMPANY))
    assert [row["name"] for row in listed["vendors"]] == ["Alpha", "Zenith"]


async def test_bill_requires_at_least_one_item(reg):
    vendor = await make_vendor(reg)
    result = await call(
        reg, "create_bill", companyId=COMPANY, vendorId=vendor, date="2026-11-15", items=[]
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "at least one" in result.content


async def test_unknown_vendor_is_not_found(reg):
    result = await make_bill(reg, "ven_missing")
    assert not result.ok
    assert result.error_code == "NOT_FOUND"


async def test_bill_total_must_be_positive(reg):
    vendor = await make_vendor(reg)
    result = await make_bill(reg, vendor, unit_cost="0.00")
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "greater than zero" in result.content


async def test_vat_wht_and_net_payable_math(reg):
    vendor = await make_vendor(reg)
    result = body(await make_bill(reg, vendor, wht_rate=5))
    bill = result["bill"]

    assert bill["subtotal"] == "1000.00"
    assert bill["vatAmount"] == "75.00"
    assert bill["total"] == "1075.00"
    assert bill["whtRate"] == "5.00"
    assert bill["whtAmount"] == "50.00"
    assert bill["netPayable"] == "1025.00"
    assert bill["status"] == "RECEIVED"

    journal = result["journal"]
    assert journal["status"] == "PENDING"
    assert journal["totalDebit"] == "1075.00"
    assert journal["totalCredit"] == "1075.00"


async def test_bill_journal_is_pending_and_balances_untouched(reg):
    vendor = await make_vendor(reg)
    await make_bill(reg, vendor)
    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    payable = next(row for row in trial["accounts"] if row["code"] == "2010")
    assert payable["balance"] == "0.00"
    pending = body(await call(reg, "get_pending_journals", companyId=COMPANY))
    assert pending["count"] == 1


async def test_wht_rate_bounds(reg):
    vendor = await make_vendor(reg)
    negative = await make_bill(reg, vendor, wht_rate=-1)
    assert not negative.ok
    assert negative.error_code == "VALIDATION"
    assert "between 0 and 100" in negative.content

    too_high = await make_bill(reg, vendor, wht_rate=101)
    assert not too_high.ok
    assert too_high.error_code == "VALIDATION"
    assert "between 0 and 100" in too_high.content


async def test_wht_defaults_to_zero(reg):
    vendor = await make_vendor(reg)
    bill = body(await make_bill(reg, vendor))["bill"]
    assert bill["whtAmount"] == "0.00"
    assert bill["netPayable"] == "1075.00"


async def test_payment_rejects_overpayment(reg):
    vendor = await make_vendor(reg)
    bill = body(await make_bill(reg, vendor, wht_rate=5))["bill"]
    bank = await account_id(reg, "1020")

    result = await call(
        reg,
        "record_bill_payment",
        companyId=COMPANY,
        billId=bill["id"],
        amount="1025.01",
        bankAccountId=bank,
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "exceeds outstanding" in result.content


async def test_payment_requires_asset_bank(reg):
    vendor = await make_vendor(reg)
    bill = body(await make_bill(reg, vendor))["bill"]
    sales = await account_id(reg, "4000")

    result = await call(
        reg,
        "record_bill_payment",
        companyId=COMPANY,
        billId=bill["id"],
        amount="10.00",
        bankAccountId=sales,
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "ASSET" in result.content


async def test_partial_then_full_payment_and_double_payment_guard(reg):
    vendor = await make_vendor(reg)
    bill = body(await make_bill(reg, vendor, wht_rate=5))["bill"]
    bank = await account_id(reg, "1020")

    partial = body(
        await call(
            reg,
            "record_bill_payment",
            companyId=COMPANY,
            billId=bill["id"],
            amount="500.00",
            bankAccountId=bank,
            date="2026-11-20",
        )
    )
    assert partial["bill"]["status"] == "RECEIVED"
    assert partial["bill"]["outstanding"] == "525.00"
    assert partial["journal"]["status"] == "PENDING"

    final = body(
        await call(
            reg,
            "record_bill_payment",
            companyId=COMPANY,
            billId=bill["id"],
            amount="525.00",
            bankAccountId=bank,
            date="2026-11-22",
        )
    )
    assert final["bill"]["status"] == "PAID"
    assert final["bill"]["outstanding"] == "0.00"

    again = await call(
        reg,
        "record_bill_payment",
        companyId=COMPANY,
        billId=bill["id"],
        amount="1.00",
        bankAccountId=bank,
    )
    assert not again.ok
    assert again.error_code == "STATE"
    assert "already paid" in again.content


async def test_ap_aging_buckets_and_vendor_totals(reg):
    vendor = await make_vendor(reg)
    await make_bill(reg, vendor)  # due 2026-12-15

    current = body(await call(reg, "get_ap_aging", companyId=COMPANY, asOf="2026-12-01"))
    assert current["buckets"][0]["key"] == "current"
    assert current["buckets"][0]["count"] == 1
    assert current["totalOutstanding"] == "1075.00"

    overdue = body(await call(reg, "get_ap_aging", companyId=COMPANY, asOf="2026-12-20"))
    by_key = {bucket["key"]: bucket for bucket in overdue["buckets"]}
    assert by_key["1-30"]["count"] == 1
    assert by_key["1-30"]["total"] == "1075.00"
    assert overdue["vendors"][0]["vendor"] == "Supply Co"
    assert overdue["vendors"][0]["1-30"] == "1075.00"


async def test_wht_summary_includes_pending_bills(reg):
    vendor = await make_vendor(reg)
    await make_bill(reg, vendor, wht_rate=5)
    summary = body(await call(reg, "get_wht_summary", companyId=COMPANY))
    assert summary["whtPayable"] == "50.00"
    assert summary["credit"] == "50.00"


async def test_purchase_permissions(reg):
    assert reg.get("get_vendors").permission == "read"
    assert reg.get("get_bills").permission == "read"
    assert reg.get("get_ap_aging").permission == "read"
    assert reg.get("get_wht_summary").permission == "read"
    assert reg.get("create_vendor").permission == "write"
    assert reg.get("create_bill").permission == "write"
    assert reg.get("record_bill_payment").permission == "write"
