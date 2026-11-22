"""Business profile tools (inventory rows 63-64)."""

from __future__ import annotations

from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.money import fmt, to_money
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry

CURRENCIES = ("NGN", "USD", "GBP")
DEFAULTS = {
    "name": "",
    "address": "",
    "phone": "",
    "email": "",
    "logo_url": None,
    "currency": "NGN",
    "fiscal_year_start": "January",
    "vat_rate": "7.50",
    "wht_rate_company": "10.00",
    "wht_rate_individual": "5.00",
}


def _profile_row(company: dict[str, Any]) -> dict[str, Any]:
    row = store.select_one("business_profiles", company["id"], {})
    if row is not None:
        return row
    return store.insert_row("business_profiles", {"company_id": company["id"], **DEFAULTS})


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "address": row["address"],
        "phone": row["phone"],
        "email": row["email"],
        "logoUrl": row["logo_url"],
        "currency": row["currency"],
        "fiscalYearStart": row["fiscal_year_start"],
        "vatRate": row["vat_rate"],
        "whtRateCompany": row["wht_rate_company"],
        "whtRateIndividual": row["wht_rate_individual"],
    }


def _get(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    return {"profile": _payload(_profile_row(company))}


def _update(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    _profile_row(company)
    values: dict[str, Any] = {}
    for field, column in (
        ("name", "name"),
        ("address", "address"),
        ("phone", "phone"),
        ("email", "email"),
        ("logoUrl", "logo_url"),
        ("fiscalYearStart", "fiscal_year_start"),
    ):
        raw = args.get(field)
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise AccountingError(VALIDATION, f"{field} must be a string")
        values[column] = raw

    currency = args.get("currency")
    if currency is not None:
        if currency not in CURRENCIES:
            raise AccountingError(VALIDATION, "currency must be NGN, USD or GBP")
        values["currency"] = currency

    for field, column in (
        ("vatRate", "vat_rate"),
        ("whtRateCompany", "wht_rate_company"),
        ("whtRateIndividual", "wht_rate_individual"),
    ):
        raw = args.get(field)
        if raw is None:
            continue
        rate = to_money(raw, field)
        if rate < 0 or rate > 100:
            raise AccountingError(VALIDATION, f"{field} must be between 0 and 100")
        values[column] = fmt(rate)

    if not values:
        return {"profile": _payload(_profile_row(company)), "updated": False}

    store.update_row("business_profiles", company["id"], company["id"], values)
    return {"profile": _payload(_profile_row(company)), "updated": True}


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def profile_tools() -> list[Tool]:
    return [
        Tool(
            name="get_business_profile",
            description=(
                "Read the business profile: name, contact details, currency and tax "
                "rates. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="update_business_profile",
            description=(
                "Update the business profile. Currency is NGN, USD or GBP; tax rates are "
                "percentages between 0 and 100. Omitted fields are left untouched."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "logoUrl": {"type": "string"},
                    "currency": {"type": "string", "enum": ["NGN", "USD", "GBP"]},
                    "fiscalYearStart": {"type": "string"},
                    "vatRate": {"type": "string"},
                    "whtRateCompany": {"type": "string"},
                    "whtRateIndividual": {"type": "string"},
                },
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_update, args),
            permission=PERMISSION_WRITE,
        ),
    ]


def register_profile_tools(registry: ToolRegistry) -> None:
    for tool in profile_tools():
        registry.register(tool)
