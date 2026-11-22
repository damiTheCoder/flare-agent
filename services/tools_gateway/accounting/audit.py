"""Audit tools (inventory rows 11-12).

Read-only views over the audit trail. Mutating tools append rows through
``store.record_audit``; the export bundles the ledger, sub-ledgers and the
trail into one JSON document.
"""

from __future__ import annotations

import json
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.registry import PERMISSION_READ, Tool, ToolRegistry


def _get_log(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    try:
        page = int(args.get("page") or 1)
        page_size = int(args.get("pageSize") or 50)
    except (TypeError, ValueError):
        raise AccountingError(VALIDATION, "page and pageSize must be integers") from None
    if page < 1 or page > 1000:
        raise AccountingError(VALIDATION, "page must be between 1 and 1000")
    if page_size < 1 or page_size > 200:
        raise AccountingError(VALIDATION, "pageSize must be between 1 and 200")

    where: dict[str, Any] = {}
    action = args.get("action")
    if isinstance(action, str) and action.strip():
        where["action"] = action.strip()
    entity_type = args.get("entityType")
    if isinstance(entity_type, str) and entity_type.strip():
        where["entity_type"] = entity_type.strip()

    rows = store.select_rows("audit_log", company["id"], where, "created_at DESC")
    start = (page - 1) * page_size
    items = [
        {
            "id": row["id"],
            "action": row["action"],
            "entityType": row["entity_type"],
            "entityId": row["entity_id"],
            "userId": row["user_id"],
            "after": json.loads(row["after"]) if row["after"] else None,
            "createdAt": row["created_at"],
        }
        for row in rows[start : start + page_size]
    ]
    return {"items": items, "total": len(rows), "page": page, "pageSize": page_size}


def _export(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    company_row = {
        "id": company.get("id"),
        "name": company.get("name"),
    }
    payload = {
        "company": company_row,
        "accounts": store.list_accounts(company["id"]),
        "journalEntries": store.list_entries(company["id"], None),
        "auditLog": store.select_rows("audit_log", company["id"], None, "created_at ASC"),
        "customers": store.list_customers(company["id"]),
        "vendors": store.list_vendors(company["id"]),
        "invoices": store.list_invoices(company["id"]),
        "bills": store.list_bills(company["id"]),
    }
    return payload


def audit_tools() -> list[Tool]:
    company_id = {
        "type": "string",
        "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
    }
    return [
        Tool(
            name="get_audit_log",
            description=(
                "Read the audit trail, newest first, optionally filtered by action or entity "
                "type. Paginated (page 1-1000, pageSize 1-200). Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": company_id,
                    "page": {"type": "integer"},
                    "pageSize": {"type": "integer"},
                    "action": {"type": "string"},
                    "entityType": {"type": "string"},
                },
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_log, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="export_audit_package",
            description=(
                "Export one JSON bundle for an auditor: company, chart of accounts, every "
                "journal entry with lines, the audit trail, customers, vendors, invoices and "
                "bills. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": company_id},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_export, args),
            permission=PERMISSION_READ,
        ),
    ]


def register_audit_tools(registry: ToolRegistry) -> None:
    for tool in audit_tools():
        registry.register(tool)
