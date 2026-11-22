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
from pydantic import BaseModel, Field

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


class JournalLineIn(BaseModel):
    accountId: str = Field(min_length=1)  # noqa: N815 - API contract
    debit: str | None = None
    credit: str | None = None


class JournalIn(BaseModel):
    date: str | None = None
    memo: str | None = None
    lines: list[JournalLineIn] | None = None
    debitAccountId: str | None = None  # noqa: N815 - API contract
    creditAccountId: str | None = None  # noqa: N815 - API contract
    amount: str | None = None


@router.get("/accounts")
async def accounts(tenant: str = Depends(company_id)) -> dict[str, Any]:
    trial = await _call("get_trial_balance", tenant)
    return {"accounts": trial["accounts"], "count": len(trial["accounts"])}


@router.get("/pending-journals")
async def pending_journals(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_pending_journals", tenant)


@router.post("/journals", status_code=201)
async def propose_journal(body: JournalIn, tenant: str = Depends(company_id)) -> dict[str, Any]:
    if body.lines:
        lines = [line.model_dump(exclude_none=True) for line in body.lines]
    else:
        if not (body.debitAccountId and body.creditAccountId and body.amount):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "VALIDATION",
                    "message": "Provide lines, or debitAccountId + creditAccountId + amount",
                },
            )
        lines = [
            {"accountId": body.debitAccountId, "debit": body.amount},
            {"accountId": body.creditAccountId, "credit": body.amount},
        ]
    args: dict[str, Any] = {"lines": lines}
    if body.date:
        args["date"] = body.date
    if body.memo:
        args["memo"] = body.memo
    return await _call("propose_journal", tenant, **args)


@router.post("/journals/{journal_id}/approve")
async def approve_journal(journal_id: str, tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("approve_journal", tenant, journalId=journal_id)


@router.get("/balance-sheet")
async def balance_sheet(
    asOf: str | None = None,  # noqa: N803 - query alias
    tenant: str = Depends(company_id),
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if asOf is not None:
        args["asOf"] = asOf
    return await _call("get_balance_sheet", tenant, **args)


@router.get("/bank-accounts")
async def bank_accounts(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_bank_accounts", tenant)


@router.get("/unreconciled")
async def unreconciled(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_unreconciled_bank_transactions", tenant)


@router.get("/tax-summary")
async def tax_summary(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_tax_summary", tenant)


@router.get("/employees")
async def employees(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_employees", tenant)


@router.get("/journals/pending")
async def journals_pending(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_pending_journals", tenant)


@router.get("/aging/ar")
async def aging_ar(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_ar_aging", tenant)


@router.get("/aging/ap")
async def aging_ap(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_ap_aging", tenant)


@router.get("/payroll/history")
async def payroll_history(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_payroll_history", tenant)


@router.get("/tax/summary")
async def tax_summary_slash(tenant: str = Depends(company_id)) -> dict[str, Any]:
    return await _call("get_tax_summary", tenant)


@router.get("/reports/pl")
async def reports_pl(
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


@router.get("/reports/bs")
async def reports_bs(
    asOf: str | None = None,  # noqa: N803 - query alias
    tenant: str = Depends(company_id),
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if asOf is not None:
        args["asOf"] = asOf
    return await _call("get_balance_sheet", tenant, **args)


@router.get("/reconciliation")
async def reconciliation(tenant: str = Depends(company_id)) -> dict[str, Any]:
    transactions = await _call("get_unreconciled_bank_transactions", tenant)
    accounts = await _call("get_bank_accounts", tenant)
    return {
        "transactions": transactions["transactions"],
        "count": transactions["count"],
        "accounts": accounts["accounts"],
    }
