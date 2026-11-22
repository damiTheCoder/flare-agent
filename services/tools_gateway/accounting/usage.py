"""AI usage tools (inventory rows 83-84)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.money import fmt
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry

# Per-million-token rates used for the estimate; documented so callers can rely
# on them rather than guessing.
INPUT_RATE = Decimal("0.14")
OUTPUT_RATE = Decimal("0.28")
CACHED_RATE = Decimal("0.014")
MILLION = Decimal(1000000)


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _tokens(value: Any, field: str) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, f"{field} must be an integer") from None
    if amount < 0:
        raise AccountingError(VALIDATION, f"{field} must not be negative")
    return amount


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    input_tokens = int(row["input_tokens"])
    output_tokens = int(row["output_tokens"])
    cached_tokens = int(row["cached_tokens"])
    cost = (
        Decimal(input_tokens) / MILLION * INPUT_RATE
        + Decimal(output_tokens) / MILLION * OUTPUT_RATE
        + Decimal(cached_tokens) / MILLION * CACHED_RATE
    ).quantize(Decimal("0.01"))
    return {
        "month": row["month"],
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cachedTokens": cached_tokens,
        "totalTokens": input_tokens + output_tokens + cached_tokens,
        "estimatedCost": fmt(cost),
    }


def _get(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    return {"usage": _payload(store.usage_for(company["id"], _month()))}


def _record(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    month = _month()
    input_tokens = _tokens(args.get("inputTokens") or 0, "inputTokens")
    output_tokens = _tokens(args.get("outputTokens") or 0, "outputTokens")
    cached_tokens = _tokens(args.get("cachedTokens") or 0, "cachedTokens")

    connection = store.connect()
    with connection:
        connection.execute(
            "INSERT INTO usage_counters"
            " (company_id, month, input_tokens, output_tokens, cached_tokens)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(company_id, month) DO UPDATE SET"
            "  input_tokens = input_tokens + excluded.input_tokens,"
            "  output_tokens = output_tokens + excluded.output_tokens,"
            "  cached_tokens = cached_tokens + excluded.cached_tokens",
            (company["id"], month, input_tokens, output_tokens, cached_tokens),
        )
    updated = store.usage_for(company["id"], month)
    return {"usage": _payload(updated), "recorded": True}


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def usage_tools() -> list[Tool]:
    return [
        Tool(
            name="get_token_usage",
            description=(
                "Month-to-date AI token usage (input, output, cached) and the estimated cost. "
                "Read-only."
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
            name="record_token_usage",
            description=(
                "Add token counts reported by the chat runtime to this month's usage. Counts "
                "must be non-negative integers."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "inputTokens": {"type": "integer"},
                    "outputTokens": {"type": "integer"},
                    "cachedTokens": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_record, args),
            permission=PERMISSION_WRITE,
        ),
    ]


def register_usage_tools(registry: ToolRegistry) -> None:
    for tool in usage_tools():
        registry.register(tool)
