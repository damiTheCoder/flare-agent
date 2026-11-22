"""Sales tool tests (Batch 2).

Covers the edge cases that matter for invoicing: at least one line, a
positive total, catalog-price fallback, VAT split, pending-only journals,
payment guards and AR aging buckets.
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


async def make_customer(reg, name: str = "Ada Ltd") -> str:
    return body(await call(reg, "create_customer", companyId=COMPANY, name=name))["id"]


def make_item(
    name: str = "Widget",
    price: str = "100.00",
    cost: str = "0.00",
    stock: int = 10,
) -> str:
    """Seed a catalog item (create_item arrives with the inventory batch)."""
    store.resolve_tenant(COMPANY)
    item = store.insert_item(
        COMPANY, name=name, sku=None, price=price, cost=cost, stock_quantity=stock
    )
    return item["id"]


async def test_requires_tenant(reg):
    result = await call(reg, "get_customers")
    assert not result.ok
    assert result.error_code == "NO_ORGANIZATION"


async def test_create_customer_requires_name(reg):
    result = await call(reg, "create_customer", companyId=COMPANY, name="   ")
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "name" in result.content.lower()


async def test_customers_are_listed_alphabetically(reg):
    await make_customer(reg, "Zed")
    await make_customer(reg, "Ada")
    listed = body(await call(reg, "get_customers", companyId=COMPANY))
    assert [row["name"] for row in listed["customers"]] == ["Ada", "Zed"]


async def test_invoice_requires_at_least_one_item(reg):
    customer = await make_customer(reg)
    result = await call(
        reg,
        "create_invoice",
        companyId=COMPANY,
        customerId=customer,
        date="2026-11-15",
        items=[],
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "at least one" in result.content


async def test_invoice_requires_known_customer(reg):
    item = make_item()
    result = await call(
        reg,
        "create_invoice",
        companyId=COMPANY,
        customerId="cus_missing",
        date="2026-11-15",
        items=[{"itemId": item, "quantity": 1}],
    )
    assert not result.ok
    assert result.error_code == "NOT_FOUND"


async def test_invoice_total_must_be_positive(reg):
    customer = await make_customer(reg)
    result = await call(
        reg,
        "create_invoice",
        companyId=COMPANY,
        customerId=customer,
        date="2026-11-15",
        items=[{"description": "Freebie", "quantity": 2, "unitPrice": "0.00"}],
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "greater than zero" in result.content


async def test_unit_price_falls_back_to_catalog_price(reg):
    customer = await make_customer(reg)
    item = make_item(price="100.00")
    invoice = body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": 2}],
        )
    )["invoice"]

    assert invoice["lines"][0]["unitPrice"] == "100.00"
    assert invoice["subtotal"] == "200.00"
    assert invoice["vat"] == "15.00"
    assert invoice["total"] == "215.00"
    assert invoice["status"] == "DRAFT"


async def test_invoice_journal_is_pending_and_balances_untouched(reg):
    customer = await make_customer(reg)
    item = make_item(price="100.00")
    result = body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": 2}],
        )
    )

    journal = result["journal"]
    assert journal["status"] == "PENDING"
    assert journal["requiresApproval"] is True
    assert journal["totalDebit"] == "215.00"
    assert journal["totalCredit"] == "215.00"

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    receivable = next(row for row in trial["accounts"] if row["code"] == "1100")
    assert receivable["balance"] == "0.00"

    pending = body(await call(reg, "get_pending_journals", companyId=COMPANY))
    assert pending["count"] == 1


async def test_item_cost_raises_pending_cogs_and_moves_stock(reg):
    customer = await make_customer(reg)
    item = make_item(price="100.00", cost="40.00", stock=10)
    result = body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": 3}],
        )
    )

    cogs = result["cogsJournal"]
    assert cogs is not None
    assert cogs["status"] == "PENDING"
    assert cogs["totalDebit"] == "120.00"

    stock = store.get_item(COMPANY, item)
    assert stock is not None
    assert stock["stock_quantity"] == 7


async def test_payment_rejects_non_positive_amount(reg):
    customer = await make_customer(reg)
    item = make_item()
    invoice = body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": 1}],
        )
    )["invoice"]
    bank = await account_id(reg, "1020")

    result = await call(
        reg,
        "record_invoice_payment",
        companyId=COMPANY,
        invoiceId=invoice["id"],
        amount="0.00",
        bankAccountId=bank,
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "greater than zero" in result.content


async def test_payment_rejects_overpayment(reg):
    customer = await make_customer(reg)
    item = make_item(price="100.00")
    invoice = body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": 1}],
        )
    )["invoice"]
    bank = await account_id(reg, "1020")

    result = await call(
        reg,
        "record_invoice_payment",
        companyId=COMPANY,
        invoiceId=invoice["id"],
        amount="999.00",
        bankAccountId=bank,
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "exceeds outstanding" in result.content


async def test_payment_requires_asset_bank_account(reg):
    customer = await make_customer(reg)
    item = make_item(price="100.00")
    invoice = body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": 1}],
        )
    )["invoice"]
    revenue = await account_id(reg, "4000")

    result = await call(
        reg,
        "record_invoice_payment",
        companyId=COMPANY,
        invoiceId=invoice["id"],
        amount="10.00",
        bankAccountId=revenue,
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "ASSET" in result.content


async def test_partial_then_full_payment(reg):
    customer = await make_customer(reg)
    item = make_item(price="100.00")
    invoice = body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": 1}],
        )
    )["invoice"]
    bank = await account_id(reg, "1020")

    partial = body(
        await call(
            reg,
            "record_invoice_payment",
            companyId=COMPANY,
            invoiceId=invoice["id"],
            amount="50.00",
            bankAccountId=bank,
            date="2026-11-20",
        )
    )
    assert partial["invoice"]["status"] == "SENT"
    assert partial["invoice"]["outstanding"] == "57.50"
    assert partial["journal"]["status"] == "PENDING"

    final = body(
        await call(
            reg,
            "record_invoice_payment",
            companyId=COMPANY,
            invoiceId=invoice["id"],
            amount="57.50",
            bankAccountId=bank,
            date="2026-11-25",
        )
    )
    assert final["invoice"]["status"] == "PAID"
    assert final["invoice"]["outstanding"] == "0.00"

    again = await call(
        reg,
        "record_invoice_payment",
        companyId=COMPANY,
        invoiceId=invoice["id"],
        amount="1.00",
        bankAccountId=bank,
    )
    assert not again.ok
    assert again.error_code == "STATE"
    assert "already paid" in again.content


async def test_ar_aging_buckets(reg):
    customer = await make_customer(reg)
    item = make_item(price="100.00")

    async def invoice_on(day: str) -> None:
        result = await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date=day,
            items=[{"itemId": item, "quantity": 1}],
        )
        assert result.ok, result.content

    await invoice_on("2026-11-15")  # due 2026-12-15
    await invoice_on("2026-12-01")  # due 2026-12-31

    current = body(await call(reg, "get_ar_aging", companyId=COMPANY, asOf="2026-12-01"))
    assert current["totalOutstanding"] == "215.00"
    assert current["buckets"][0]["key"] == "current"
    assert current["buckets"][0]["count"] == 2

    overdue = body(await call(reg, "get_ar_aging", companyId=COMPANY, asOf="2026-12-20"))
    by_key = {bucket["key"]: bucket for bucket in overdue["buckets"]}
    assert by_key["1-30"]["count"] == 1
    assert by_key["current"]["count"] == 1
    assert overdue["totalOutstanding"] == "215.00"
    assert (
        next(row for row in overdue["invoices"] if row["invoiceNumber"] == "INV-0001")[
            "daysPastDue"
        ]
        == 5
    )


async def test_invoice_permissions(reg):
    assert reg.get("get_customers").permission == "read"
    assert reg.get("get_invoices").permission == "read"
    assert reg.get("get_ar_aging").permission == "read"
    assert reg.get("create_customer").permission == "write"
    assert reg.get("create_invoice").permission == "write"
    assert reg.get("record_invoice_payment").permission == "write"
