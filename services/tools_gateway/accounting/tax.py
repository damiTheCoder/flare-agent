"""Tax tools (inventory rows 32-35).

Summary balances plus downloadable schedules. Schedules are returned as CSV
in ``content`` with a filename in ``artifacts`` so a caller can hand the text
straight to a file.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.ledger import _month_range as month_range
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.money import ZERO, add, fmt
from tools_gateway.registry import PERMISSION_READ, Tool, ToolRegistry, ToolResult


def _csv(rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue()


def _summary(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    vat = store.account_by_name(company["id"], "VAT Payable")
    wht_debit, wht_credit = store.account_movement(company["id"], "WHT Payable")
    return {
        "vatPayable": fmt(Decimal(vat["balance"])) if vat is not None else "0.00",
        "whtPayable": fmt(wht_credit - wht_debit),
    }


def _vat_schedule(company: dict[str, Any], args: dict[str, Any]) -> Any:
    month, year, start, end = month_range(args.get("month"), args.get("year"))
    rows: list[list[str]] = [["document", "number", "counterparty", "date", "net", "vat", "gross"]]
    output_vat = ZERO
    input_vat = ZERO

    for invoice in store.list_invoices(company["id"]):
        if not (start <= invoice["date"] <= end):
            continue
        subtotal = (
            add(*(Decimal(line["total"]) for line in invoice["lines"]))
            if invoice["lines"]
            else ZERO
        )
        vat = Decimal(invoice["total_amount"]) - subtotal
        output_vat = add(output_vat, vat)
        rows.append(
            [
                "SALES_INVOICE",
                invoice["invoice_number"],
                invoice["customer"] or "",
                invoice["date"],
                fmt(subtotal),
                fmt(vat),
                fmt(Decimal(invoice["total_amount"])),
            ]
        )

    for bill in store.list_bills(company["id"]):
        if not (start <= bill["date"] <= end):
            continue
        subtotal = (
            add(*(Decimal(line["total"]) for line in bill["lines"])) if bill["lines"] else ZERO
        )
        vat = Decimal(bill["vat_amount"])
        input_vat = add(input_vat, vat)
        rows.append(
            [
                "PURCHASE_BILL",
                bill["bill_number"],
                bill["vendor"] or "",
                bill["date"],
                fmt(subtotal),
                fmt(vat),
                fmt(Decimal(bill["total_amount"])),
            ]
        )

    rows.append(["TOTAL", "output", "", "", "", fmt(output_vat), ""])
    rows.append(["TOTAL", "input", "", "", "", fmt(input_vat), ""])
    rows.append(["TOTAL", "net", "", "", "", fmt(output_vat - input_vat), ""])

    filename = f"vat-schedule-{year}-{month:02d}.csv"
    return {"csv": _csv(rows), "filename": filename}


def _paye_schedule(company: dict[str, Any], args: dict[str, Any]) -> Any:
    month, year, _start, _end = month_range(args.get("month"), args.get("year"))
    label = f"{month:02d}"
    runs = store.select_rows("payroll_runs", company["id"], {"month": label, "year": year})
    rows: list[list[str]] = [["period", "status", "gross", "paye", "pension", "nhf", "net"]]
    for run in runs:
        rows.append(
            [
                f"{label}/{year}",
                run["status"],
                run["total_gross"],
                run["total_paye"],
                run["total_pension"],
                run["total_nhf"],
                run["total_net"],
            ]
        )
    return {"csv": _csv(rows), "filename": f"paye-schedule-{year}-{label}.csv"}


def _wht_schedule(company: dict[str, Any], args: dict[str, Any]) -> Any:
    month, year, start, end = month_range(args.get("month"), args.get("year"))
    rows: list[list[str]] = [["bill", "vendor", "date", "subtotal", "whtRate", "whtAmount"]]
    total = ZERO
    for bill in store.list_bills(company["id"]):
        if not (start <= bill["date"] <= end):
            continue
        subtotal = (
            add(*(Decimal(line["total"]) for line in bill["lines"])) if bill["lines"] else ZERO
        )
        wht = Decimal(bill["wht_amount"])
        total = add(total, wht)
        rows.append(
            [
                bill["bill_number"],
                bill["vendor"] or "",
                bill["date"],
                fmt(subtotal),
                bill["wht_rate"],
                fmt(wht),
            ]
        )
    rows.append(["TOTAL", "", "", "", "", fmt(total)])
    return {"csv": _csv(rows), "filename": f"wht-schedule-{year}-{month:02d}.csv"}


def tax_tools() -> list[Tool]:
    company_id = {
        "type": "string",
        "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
    }
    period = {
        "month": {"type": "integer"},
        "year": {"type": "integer"},
    }

    def csv_tool(name: str, handler, description: str) -> Tool:
        async def _invoke(**args):
            try:
                company = store.resolve_tenant(args.get("companyId"))
                payload = handler(company, args)
            except Exception as exc:  # noqa: BLE001 - mapped below
                from tools_gateway.accounting.errors import AccountingError

                if isinstance(exc, AccountingError):
                    return ToolResult(ok=False, content=exc.message, error_code=exc.code)
                raise
            return ToolResult(
                ok=True,
                content=payload["csv"],
                artifacts={"format": "csv", "filename": payload["filename"]},
            )

        return Tool(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "companyId": company_id,
                    "month": period["month"],
                    "year": period["year"],
                },
                "required": ["month", "year"],
                "additionalProperties": False,
            },
            func=_invoke,
            permission=PERMISSION_READ,
        )

    return [
        Tool(
            name="get_tax_summary",
            description="VAT and WHT payable balances. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": company_id},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_summary, args),
            permission=PERMISSION_READ,
        ),
        csv_tool(
            "get_vat_schedule",
            _vat_schedule,
            "VAT schedule for a month as CSV: output VAT on invoices, input VAT on bills and "
            "the net. Read-only.",
        ),
        csv_tool(
            "get_paye_schedule",
            _paye_schedule,
            "PAYE schedule for a month as CSV, one row per payroll run. Read-only.",
        ),
        csv_tool(
            "get_wht_schedule",
            _wht_schedule,
            "WHT withheld schedule for a month as CSV, one row per bill. Read-only.",
        ),
    ]


def register_tax_tools(registry: ToolRegistry) -> None:
    for tool in tax_tools():
        registry.register(tool)
