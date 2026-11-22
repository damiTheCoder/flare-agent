"""Inventory tools (Batch 4: inventory rows 26-28).

Items carry money (price, cost) and integer stock. Adjustments move stock and
raise a PENDING valuation journal: an increase credits Inventory Adjustment,
a decrease debits Cost of Goods Sold. Nothing posts here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.ledger import propose_entry
from tools_gateway.accounting.money import fmt, to_money
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


def _item_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "name": item["name"],
        "sku": item["sku"],
        "price": item["price"],
        "cost": item["cost"],
        "stockQuantity": item["stock_quantity"],
    }


def _whole_quantity(value: object, field: str = "quantity") -> int:
    """Truncate like the core; reject non-numeric input outright."""
    if value is None or value == "":
        raise AccountingError(VALIDATION, f"{field} is required")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise AccountingError(VALIDATION, f"{field} must be a number") from None
    if not parsed.is_finite():
        raise AccountingError(VALIDATION, f"{field} must be a finite number")
    return int(parsed)


# ---------------------------------------------------------------------------
# 26. items
# ---------------------------------------------------------------------------


def _get_items(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    items = [_item_payload(item) for item in store.list_items(company["id"])]
    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# 27. create item
# ---------------------------------------------------------------------------


def _create_item(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Item name is required")

    price = to_money(args.get("price"), "item price")
    cost = to_money(args.get("cost") if args.get("cost") is not None else "0", "item cost")
    if price < 0 or cost < 0:
        raise AccountingError(VALIDATION, "Item price and cost must not be negative")

    # The core clamps opening stock at zero rather than rejecting it.
    opening_stock = max(0, _whole_quantity(args.get("stockQuantity") or 0, "stockQuantity"))

    sku = args.get("sku")
    item = store.insert_item(
        company["id"],
        name=name.strip(),
        sku=sku.strip() if isinstance(sku, str) and sku.strip() else None,
        price=fmt(price),
        cost=fmt(cost),
        stock_quantity=opening_stock,
    )
    return _item_payload(item)


# ---------------------------------------------------------------------------
# 28. adjust stock
# ---------------------------------------------------------------------------


def _adjust_stock(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    item_id = args.get("itemId")
    if not isinstance(item_id, str) or item_id.strip() == "":
        raise AccountingError(VALIDATION, "itemId is required")

    reason = args.get("reason")
    if not isinstance(reason, str) or reason.strip() == "":
        raise AccountingError(VALIDATION, "reason is required")

    delta = _whole_quantity(args.get("quantity"))
    if delta == 0:
        raise AccountingError(VALIDATION, "Stock adjustment must be a non-zero whole number")

    item = store.get_item(company["id"], item_id.strip())
    if item is None:
        raise AccountingError(NOT_FOUND, f"Item {item_id} not found")

    next_stock = int(item["stock_quantity"]) + delta
    if next_stock < 0:
        raise AccountingError(VALIDATION, "Stock cannot go below zero")

    item = store.set_stock(company["id"], item["id"], next_stock)

    value = Decimal(item["cost"]) * abs(delta)
    journal: dict[str, Any] | None = None
    if value > 0:
        inventory = _require_account(company, "Inventory", "ASSET")
        if delta > 0:
            adjustment = _require_account(company, "Inventory Adjustment", "REVENUE")
            journal = propose_entry(
                company,
                date=None,
                memo=f"Stock adjustment: {reason.strip()}",
                lines=[
                    {"accountId": inventory["id"], "debit": fmt(value)},
                    {"accountId": adjustment["id"], "credit": fmt(value)},
                ],
            )
        else:
            cogs = _require_account(company, "Cost of Goods Sold", "EXPENSE")
            journal = propose_entry(
                company,
                date=None,
                memo=f"Stock adjustment: {reason.strip()}",
                lines=[
                    {"accountId": cogs["id"], "debit": fmt(value)},
                    {"accountId": inventory["id"], "credit": fmt(value)},
                ],
            )

    return {
        "item": _item_payload(item),
        "journal": journal,
        "note": (
            "The valuation journal is PENDING; approve it with approve_journal."
            if journal is not None
            else "No journal was raised: the item's cost is zero, so the move has no value."
        ),
    }


# ---------------------------------------------------------------------------
# tool definitions
# ---------------------------------------------------------------------------

_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; requests without it fail with NO_ORGANIZATION.",
}


def inventory_tools() -> list[Tool]:
    return [
        Tool(
            name="get_items",
            description=(
                "List catalog items with price, cost and on-hand stock. Read-only. Use it to "
                "discover itemId values for invoices and stock adjustments."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_items, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_item",
            description=(
                "Create a catalog item. Name is required; price and cost must be non-negative "
                "(cost defaults to 0). Opening stock is clamped at zero."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string", "minLength": 1},
                    "sku": {"type": "string"},
                    "price": {"type": "string", "description": 'Decimal string, e.g. "100.00".'},
                    "cost": {"type": "string", "description": "Decimal string; defaults to 0."},
                    "stockQuantity": {
                        "type": "number",
                        "description": "Opening units; negatives are clamped to 0.",
                    },
                },
                "required": ["name", "price"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_item, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="adjust_stock",
            description=(
                "Adjust on-hand stock by a non-zero whole number of units and raise a PENDING "
                "valuation journal: an increase debits Inventory / credits Inventory Adjustment; "
                "a decrease debits Cost of Goods Sold / credits Inventory (valued at the item's "
                "cost). Stock may never go below zero. Balances change only after "
                "approve_journal."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "itemId": {"type": "string", "minLength": 1},
                    "quantity": {
                        "type": "number",
                        "description": "Units to add (positive) or remove (negative); truncated.",
                    },
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": ["itemId", "quantity", "reason"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_adjust_stock, args),
            permission=PERMISSION_WRITE,
        ),
    ]


def register_inventory_tools(registry: ToolRegistry) -> None:
    for tool in inventory_tools():
        registry.register(tool)
