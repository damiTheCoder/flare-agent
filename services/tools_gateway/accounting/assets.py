"""Fixed-asset tools (inventory rows 45-48).

Acquisition, depreciation and disposal all raise PENDING journals. Disposal is
permission=destructive because it removes an asset permanently.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, STATE, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _date as parse_required_date
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.ledger import propose_entry
from tools_gateway.accounting.money import ZERO, add, fmt, to_money
from tools_gateway.registry import (
    PERMISSION_DESTRUCTIVE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    Tool,
    ToolRegistry,
)


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


def _monthly_depreciation(asset: dict[str, Any]) -> Decimal:
    cost = Decimal(asset["cost"])
    salvage = Decimal(asset["salvage_value"])
    months = int(asset["useful_life_years"]) * 12
    if months <= 0:
        return ZERO
    return ((cost - salvage) / months).quantize(Decimal("0.01"))


def _asset_payload(asset: dict[str, Any]) -> dict[str, Any]:
    cost = Decimal(asset["cost"])
    accumulated = Decimal(asset["accumulated_depreciation"])
    return {
        "id": asset["id"],
        "name": asset["name"],
        "category": asset["category"],
        "purchaseDate": asset["purchase_date"],
        "cost": fmt(cost),
        "usefulLifeYears": asset["useful_life_years"],
        "salvageValue": fmt(Decimal(asset["salvage_value"])),
        "accumulatedDepreciation": fmt(accumulated),
        "bookValue": fmt(cost - accumulated),
        "monthlyDepreciation": fmt(_monthly_depreciation(asset)),
        "isDisposed": bool(asset["is_disposed"]),
        "disposalDate": asset["disposal_date"],
    }


def _get_assets(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("fixed_assets", company["id"], None, "purchase_date DESC")
    return {"assets": [_asset_payload(row) for row in rows], "count": len(rows)}


def _create_asset(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Asset name is required")
    category = args.get("category")
    if not isinstance(category, str) or category.strip() == "":
        raise AccountingError(VALIDATION, "Asset category is required")

    purchase_date = parse_required_date(args.get("purchaseDate"), "purchase date")
    cost = to_money(args.get("cost"), "asset cost")
    if cost <= 0:
        raise AccountingError(VALIDATION, "Asset cost must be greater than zero")

    salvage = to_money(
        args.get("salvageValue") if args.get("salvageValue") is not None else "0",
        "salvage value",
    )
    if salvage < 0 or salvage >= cost:
        raise AccountingError(VALIDATION, "Salvage value must be between zero and cost")

    try:
        life = int(args.get("usefulLifeYears"))
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, "useful life must be a whole number of years") from None
    if life < 1:
        raise AccountingError(VALIDATION, "Useful life must be at least one year")

    fixed_assets = _require_account(company, "Fixed Assets", "ASSET")
    cash = _require_account(company, "Cash", "ASSET")

    journal = propose_entry(
        company,
        date=purchase_date,
        memo=f"Asset acquisition: {name.strip()}",
        lines=[
            {"accountId": fixed_assets["id"], "debit": fmt(cost)},
            {"accountId": cash["id"], "credit": fmt(cost)},
        ],
    )

    asset = store.insert_row(
        "fixed_assets",
        {
            "company_id": company["id"],
            "name": name.strip(),
            "category": category.strip(),
            "purchase_date": purchase_date,
            "cost": fmt(cost),
            "useful_life_years": life,
            "salvage_value": fmt(salvage),
            "accumulated_depreciation": "0.00",
            "is_disposed": 0,
        },
    )
    store.record_audit(
        company["id"], action="CREATE_ASSET", entity_type="FixedAsset", entity_id=asset["id"]
    )
    return {
        "asset": _asset_payload(asset),
        "journal": journal,
        "note": "The acquisition journal is PENDING; approve it with approve_journal.",
    }


def _run_depreciation(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    try:
        month = int(args.get("month"))
        year = int(args.get("year"))
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, "month and year must be integers") from None
    if not 1 <= month <= 12:
        raise AccountingError(VALIDATION, "month must be between 1 and 12")
    if not 2000 <= year <= 2100:
        raise AccountingError(VALIDATION, "year must be between 2000 and 2100")

    assets = [row for row in store.select_rows("fixed_assets", company["id"], {"is_disposed": 0})]
    if not assets:
        raise AccountingError(VALIDATION, "No active assets to depreciate")

    total = ZERO
    updates: list[tuple[dict[str, Any], Decimal]] = []
    for asset in assets:
        cost = Decimal(asset["cost"])
        salvage = Decimal(asset["salvage_value"])
        accumulated = Decimal(asset["accumulated_depreciation"])
        remaining = cost - salvage - accumulated
        if remaining <= 0:
            continue
        monthly = _min_decimal(_monthly_depreciation(asset), remaining)
        if monthly <= 0:
            continue
        updates.append((asset, monthly))
        total = add(total, monthly)

    if not updates:
        raise AccountingError(VALIDATION, "Assets are already fully depreciated")

    depreciation = _require_account(company, "Depreciation Expense", "EXPENSE")
    accumulated_account = _require_account(company, "Accumulated Depreciation", "ASSET")

    journal = propose_entry(
        company,
        date=f"{year:04d}-{month:02d}-01",
        memo=f"Depreciation {month:02d}/{year}",
        lines=[
            {"accountId": depreciation["id"], "debit": fmt(total)},
            {"accountId": accumulated_account["id"], "credit": fmt(total)},
        ],
    )

    for asset, amount in updates:
        store.update_row(
            "fixed_assets",
            company["id"],
            asset["id"],
            {"accumulated_depreciation": fmt(Decimal(asset["accumulated_depreciation"]) + amount)},
        )

    return {
        "totalDepreciation": fmt(total),
        "count": len(updates),
        "journal": journal,
        "note": "The depreciation journal is PENDING; approve it with approve_journal.",
    }


def _min_decimal(left: Decimal, right: Decimal) -> Decimal:
    return left if left < right else right


def _dispose_asset(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    asset_id = args.get("assetId")
    if not isinstance(asset_id, str) or asset_id.strip() == "":
        raise AccountingError(VALIDATION, "assetId is required")
    disposal_date = parse_required_date(args.get("disposalDate"), "disposal date")
    proceeds = to_money(
        args.get("proceeds") if args.get("proceeds") is not None else "0", "proceeds"
    )
    if proceeds < 0:
        raise AccountingError(VALIDATION, "Disposal proceeds must not be negative")

    asset = store.select_one("fixed_assets", company["id"], {"id": asset_id.strip()})
    if asset is None:
        raise AccountingError(NOT_FOUND, f"Asset {asset_id} not found")
    if asset["is_disposed"] == 1:
        raise AccountingError(STATE, "Asset is already disposed")

    cost = Decimal(asset["cost"])
    accumulated = Decimal(asset["accumulated_depreciation"])
    book_value = cost - accumulated
    difference = proceeds - book_value

    cash = _require_account(company, "Cash", "ASSET")
    fixed_assets = _require_account(company, "Fixed Assets", "ASSET")
    accumulated_account = _require_account(company, "Accumulated Depreciation", "ASSET")

    lines: list[dict[str, str]] = []
    if proceeds > 0:
        lines.append({"accountId": cash["id"], "debit": fmt(proceeds)})
    if accumulated > 0:
        lines.append({"accountId": accumulated_account["id"], "debit": fmt(accumulated)})
    if difference < 0:
        loss = _require_account(company, "Loss on Asset Disposal", "EXPENSE")
        lines.append({"accountId": loss["id"], "debit": fmt(-difference)})
    lines.append({"accountId": fixed_assets["id"], "credit": fmt(cost)})
    if difference > 0:
        gain = _require_account(company, "Gain on Asset Disposal", "REVENUE")
        lines.append({"accountId": gain["id"], "credit": fmt(difference)})

    journal = propose_entry(
        company,
        date=disposal_date,
        memo=f"Asset disposal: {asset['name']}",
        lines=lines,
    )
    disposed = store.update_row(
        "fixed_assets",
        company["id"],
        asset["id"],
        {"is_disposed": 1, "disposal_date": disposal_date},
    )
    store.record_audit(
        company["id"],
        action="DISPOSE_ASSET",
        entity_type="FixedAsset",
        entity_id=asset["id"],
    )
    return {
        "asset": _asset_payload(disposed),
        "journal": journal,
        "gainOrLoss": fmt(difference),
        "note": "The disposal journal is PENDING; approve it with approve_journal.",
    }


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def asset_tools() -> list[Tool]:
    return [
        Tool(
            name="get_assets",
            description=(
                "List fixed assets with cost, accumulated depreciation and book value. "
                "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_assets, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_asset",
            description=(
                "Register a fixed asset and raise a PENDING acquisition journal "
                "(debit Fixed Assets / credit Cash). Cost > 0, salvage in [0, cost), life >= 1."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string", "minLength": 1},
                    "category": {"type": "string", "minLength": 1},
                    "purchaseDate": {"type": "string"},
                    "cost": {"type": "string"},
                    "usefulLifeYears": {"type": "integer"},
                    "salvageValue": {"type": "string"},
                },
                "required": ["name", "category", "purchaseDate", "cost", "usefulLifeYears"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_asset, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="run_depreciation",
            description=(
                "Post one month of straight-line depreciation as a PENDING journal "
                "(period amount = (cost - salvage) / (life * 12))."
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
            func=lambda **args: run_tool(_run_depreciation, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="dispose_asset",
            description=(
                "APPROVAL REQUIRED. Dispose of an asset: removes its cost and accumulated "
                "depreciation, books proceeds, and records the gain or loss as a PENDING "
                "journal. An asset can only be disposed once."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "assetId": {"type": "string", "minLength": 1},
                    "disposalDate": {"type": "string"},
                    "proceeds": {"type": "string"},
                },
                "required": ["assetId", "disposalDate"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_dispose_asset, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
    ]


def register_asset_tools(registry: ToolRegistry) -> None:
    for tool in asset_tools():
        registry.register(tool)
