"""REST surface for the ERP pages.

The agent calls tools through the chat stream; the UI pages call the same
tools through these thin REST wrappers, so both paths share one accounting
implementation and one tenant.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from tools_gateway.builtin import create_default_registry
from tools_gateway.registry import ToolRegistry, ToolResult

router = APIRouter(prefix="/api", tags=["accounting"])


@lru_cache(maxsize=1)
def _registry() -> ToolRegistry:
    return create_default_registry()


def company_id(companyId: str | None = Query(default=None)) -> str:  # noqa: N803 - query alias
    return companyId or os.environ.get("FLARE_COMPANY_ID", "acme")


def _data(result: ToolResult) -> Any:
    if not result.ok:
        status = 404 if result.error_code == "NOT_FOUND" else 400
        raise HTTPException(
            status_code=status,
            detail={"code": result.error_code or "ERROR", "message": result.content},
        )
    try:
        return json.loads(result.content)
    except json.JSONDecodeError:
        return result.content


async def _call(tool: str, tenant: str, **args: Any) -> Any:
    return _data(await _registry().execute(tool, {"companyId": tenant, **args}))


@router.get("/summary")
async def summary(tenant: str = Depends(company_id)) -> dict[str, Any]:
    trial = await _call("get_trial_balance", tenant)
    pnl = await _call("get_profit_and_loss", tenant)
    receivable = await _call("get_ar_aging", tenant)
    payable = await _call("get_ap_aging", tenant)
    invoices = await _call("get_invoices", tenant)

    accounts = {row["code"]: row for row in trial["accounts"]}

    def balance(code: str) -> str:
        row = accounts.get(code)
        return row["balance"] if row is not None else "0.00"

    return {
        "totalRevenue": pnl["totalRevenue"],
        "totalExpenses": pnl["totalExpenses"],
        "netIncome": pnl["netIncome"],
        "cash": balance("1010"),
        "bank": balance("1020"),
        "receivables": balance("1100"),
        "payables": balance("2010"),
        "arOutstanding": receivable["totalOutstanding"],
        "apOutstanding": payable["totalOutstanding"],
        "invoiceCount": len(invoices["invoices"]),
    }


@router.get("/trial-balance")
async def trial_balance(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_trial_balance", tenant)


@router.get("/general-ledger")
async def general_ledger(
    accountId: str | None = None,  # noqa: N803 - query alias
    status: str | None = None,
    tenant: str = Depends(company_id),
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if accountId is not None:
        args["accountId"] = accountId
    if status is not None:
        args["status"] = status
    return await _call("get_general_ledger", tenant, **args)


@router.get("/profit-loss")
async def profit_loss(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    tenant: str = Depends(company_id),
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if from_ is not None:
        args["from"] = from_
    if to is not None:
        args["to"] = to
    return await _call("get_profit_and_loss", tenant, **args)


@router.get("/customers")
async def customers(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_customers", tenant)


@router.get("/invoices")
async def invoices(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_invoices", tenant)


@router.get("/vendors")
async def vendors(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_vendors", tenant)


@router.get("/bills")
async def bills(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_bills", tenant)


@router.get("/ar-aging")
async def ar_aging(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_ar_aging", tenant)


@router.get("/ap-aging")
async def ap_aging(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_ap_aging", tenant)
