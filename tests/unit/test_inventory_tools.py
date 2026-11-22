"""Inventory tool tests (Batch 4).

Covers item creation guards, the whole-number/zero-quantity rules, the
non-negative stock floor, and the pending valuation journals for inbound and
outbound adjustments.
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


async def make_item(reg, *, name="Widget", price="100.00", cost="40.00", stock=10) -> dict:
    return body(
        await call(
            reg,
            "create_item",
            companyId=COMPANY,
            name=name,
            price=price,
            cost=cost,
            stockQuantity=stock,
        )
    )


async def test_requires_tenant(reg):
    result = await call(reg, "get_items")
    assert not result.ok
    assert result.error_code == "NO_ORGANIZATION"


async def test_create_item_requires_name(reg):
    result = await call(reg, "create_item", companyId=COMPANY, name="  ", price="10.00")
    assert not result.ok
    assert result.error_code == "VALIDATION"


async def test_create_item_rejects_negative_price_and_cost(reg):
    negative_price = await call(reg, "create_item", companyId=COMPANY, name="X", price="-1.00")
    assert not negative_price.ok
    assert negative_price.error_code == "VALIDATION"

    negative_cost = await call(
        reg, "create_item", companyId=COMPANY, name="X", price="1.00", cost="-1.00"
    )
    assert not negative_cost.ok
    assert negative_cost.error_code == "VALIDATION"


async def test_opening_stock_is_clamped_at_zero(reg):
    item = await make_item(reg, stock=-5)
    assert item["stockQuantity"] == 0


async def test_items_are_listed_alphabetically(reg):
    await make_item(reg, name="Zeta")
    await make_item(reg, name="Alpha")
    listed = body(await call(reg, "get_items", companyId=COMPANY))
    assert [row["name"] for row in listed["items"]] == ["Alpha", "Zeta"]


async def test_zero_quantity_adjustment_is_rejected(reg):
    item = await make_item(reg)
    result = await call(
        reg,
        "adjust_stock",
        companyId=COMPANY,
        itemId=item["id"],
        quantity=0,
        reason="count",
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "non-zero" in result.content


async def test_fraction_below_one_is_rejected_as_fractional(reg):
    item = await make_item(reg)
    result = await call(
        reg,
        "adjust_stock",
        companyId=COMPANY,
        itemId=item["id"],
        quantity=0.4,
        reason="count",
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "whole number" in result.content


async def test_stock_cannot_go_below_zero(reg):
    item = await make_item(reg, stock=2)
    result = await call(
        reg,
        "adjust_stock",
        companyId=COMPANY,
        itemId=item["id"],
        quantity=-3,
        reason="damage",
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "below zero" in result.content

    unchanged = store.get_item(COMPANY, item["id"])
    assert unchanged is not None
    assert unchanged["stock_quantity"] == 2


async def test_unknown_item_is_not_found(reg):
    result = await call(
        reg,
        "adjust_stock",
        companyId=COMPANY,
        itemId="itm_missing",
        quantity=1,
        reason="count",
    )
    assert not result.ok
    assert result.error_code == "NOT_FOUND"


async def test_inbound_adjustment_raises_pending_inventory_journal(reg):
    item = await make_item(reg, cost="40.00", stock=10)
    result = body(
        await call(
            reg,
            "adjust_stock",
            companyId=COMPANY,
            itemId=item["id"],
            quantity=2,
            reason="found during count",
        )
    )

    assert result["item"]["stockQuantity"] == 12
    journal = result["journal"]
    assert journal["status"] == "PENDING"
    assert journal["requiresApproval"] is True
    assert journal["totalDebit"] == "80.00"
    assert journal["totalCredit"] == "80.00"

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    inventory = next(row for row in trial["accounts"] if row["code"] == "1200")
    assert inventory["balance"] == "0.00"


async def test_outbound_adjustment_raises_pending_cogs_journal(reg):
    item = await make_item(reg, cost="40.00", stock=10)
    result = body(
        await call(
            reg,
            "adjust_stock",
            companyId=COMPANY,
            itemId=item["id"],
            quantity=-3,
            reason="damaged stock",
        )
    )

    assert result["item"]["stockQuantity"] == 7
    journal = result["journal"]
    assert journal is not None
    assert journal["status"] == "PENDING"
    assert journal["totalDebit"] == "120.00"

    cogs = next(
        row
        for row in body(await call(reg, "get_trial_balance", companyId=COMPANY))["accounts"]
        if row["code"] == "5000"
    )
    assert cogs["balance"] == "0.00"


async def test_fractional_adjustment_is_rejected(reg):
    item = await make_item(reg, stock=10)
    result = await call(
        reg,
        "adjust_stock",
        companyId=COMPANY,
        itemId=item["id"],
        quantity=2.9,
        reason="count",
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "whole number" in result.content

    unchanged = store.get_item(COMPANY, item["id"])
    assert unchanged is not None
    assert unchanged["stock_quantity"] == 10


async def test_zero_cost_item_moves_stock_without_a_journal(reg):
    item = await make_item(reg, cost="0.00", stock=5)
    result = body(
        await call(
            reg,
            "adjust_stock",
            companyId=COMPANY,
            itemId=item["id"],
            quantity=-2,
            reason="write-off",
        )
    )
    assert result["item"]["stockQuantity"] == 3
    assert result["journal"] is None


async def test_inventory_permissions(reg):
    assert reg.get("get_items").permission == "read"
    assert reg.get("create_item").permission == "write"
    assert reg.get("adjust_stock").permission == "write"
