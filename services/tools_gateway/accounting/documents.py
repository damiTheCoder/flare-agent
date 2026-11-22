"""Document tools (inventory rows 65-68).

Uploads are stored with their text/base64 payload. OCR needs a vision
provider: without FLARE_VISION_URL the tool reports PROVIDER_NOT_CONFIGURED
rather than pretending. Extraction accepts structured data and can auto-create
the matching purchase bill.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.purchases import _create_bill
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry

NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"


def _doc_payload(row: dict[str, Any], *, include_content: bool = False) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "filename": row["filename"],
        "originalName": row["original_name"],
        "mimeType": row["mime_type"],
        "uploadedAt": row["uploaded_at"],
        "status": row["status"],
        "source": row["source"],
        "extractedData": json.loads(row["extracted_data"]) if row["extracted_data"] else None,
    }
    if include_content:
        payload["content"] = row["content"]
    return payload


def _upload(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    filename = args.get("filename")
    if not isinstance(filename, str) or filename.strip() == "":
        raise AccountingError(VALIDATION, "filename is required")
    content = args.get("content")
    if not isinstance(content, str) or content == "":
        raise AccountingError(VALIDATION, "content is required (text or base64)")

    encoding = args.get("encoding") or "text"
    if encoding not in ("text", "base64"):
        raise AccountingError(VALIDATION, "encoding must be text or base64")
    if encoding == "base64":
        try:
            content = base64.b64decode(content).decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            raise AccountingError(VALIDATION, "content is not valid base64") from None

    mime_type = args.get("mimeType") or "text/plain"
    row = store.insert_row(
        "documents",
        {
            "company_id": company["id"],
            "filename": filename.strip(),
            "original_name": filename.strip(),
            "mime_type": str(mime_type),
            "content": content,
            "status": "PENDING",
            "source": "UPLOAD",
        },
    )
    store.record_audit(
        company["id"], action="UPLOAD_DOCUMENT", entity_type="Document", entity_id=row["id"]
    )
    return {"document": _doc_payload(row)}


def _list(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = store.select_rows("documents", company["id"], None, "uploaded_at DESC")
    return {"documents": [_doc_payload(row) for row in rows], "count": len(rows)}


def _ocr(company: dict[str, Any], args: dict[str, Any]):
    document_id = args.get("documentId")
    if not isinstance(document_id, str) or document_id.strip() == "":
        raise AccountingError(VALIDATION, "documentId is required")
    document = store.select_one("documents", company["id"], {"id": document_id.strip()})
    if document is None:
        raise AccountingError(NOT_FOUND, f"Document {document_id} not found")
    if not os.environ.get("FLARE_VISION_URL"):
        # Honest failure: no OCR provider is configured in this deployment.
        return None
    return document


def _extract(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    document_id = args.get("documentId")
    if not isinstance(document_id, str) or document_id.strip() == "":
        raise AccountingError(VALIDATION, "documentId is required")
    document = store.select_one("documents", company["id"], {"id": document_id.strip()})
    if document is None:
        raise AccountingError(NOT_FOUND, f"Document {document_id} not found")

    extracted = args.get("extractedData")
    if not isinstance(extracted, dict):
        raise AccountingError(VALIDATION, "extractedData must be an object")
    vendor_name = extracted.get("vendorName")
    if not isinstance(vendor_name, str) or vendor_name.strip() == "":
        raise AccountingError(VALIDATION, "extractedData.vendorName is required")

    store.update_row(
        "documents",
        company["id"],
        document["id"],
        {"status": "PROCESSED", "extracted_data": json.dumps(extracted)},
    )

    bill_payload = None
    if args.get("autoCreateBill"):
        vendor = store.select_one("vendors", company["id"], {"name": vendor_name.strip()})
        if vendor is None:
            vendor = store.insert_vendor(
                company["id"], name=vendor_name.strip(), email=None, phone=None
            )
        items = extracted.get("lineItems") or []
        bill_args = {
            "vendorId": vendor["id"],
            "date": extracted.get("date") or document["uploaded_at"][:10],
            "items": items,
        }
        if extracted.get("whtRate") is not None:
            bill_args["whtRate"] = extracted["whtRate"]
        bill_payload = _create_bill(company, bill_args)

    refreshed = store.select_one("documents", company["id"], {"id": document["id"]})
    return {
        "document": _doc_payload(refreshed) if refreshed else None,
        "bill": bill_payload["bill"] if bill_payload else None,
        "journal": bill_payload["journal"] if bill_payload else None,
    }


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def document_tools() -> list[Tool]:
    return [
        Tool(
            name="upload_document",
            description=(
                "Store a document for later extraction. Content is text or base64; size is the "
                "caller's responsibility. Status starts PENDING."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "filename": {"type": "string", "minLength": 1},
                    "content": {"type": "string", "minLength": 1},
                    "encoding": {"type": "string", "enum": ["text", "base64"]},
                    "mimeType": {"type": "string"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_upload, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="list_documents",
            description="List stored documents (metadata only). Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_list, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="ocr_document",
            description=(
                "Run OCR on a stored document. Requires a configured vision provider; without "
                "one the tool returns PROVIDER_NOT_CONFIGURED."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "documentId": {"type": "string", "minLength": 1},
                },
                "required": ["documentId"],
                "additionalProperties": False,
            },
            func=lambda **args: _ocr_result(args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="extract_document",
            description=(
                "Attach structured data to a document (vendorName, lineItems, optional whtRate "
                "and date) and optionally create the matching purchase bill, whose journal is "
                "PENDING."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "documentId": {"type": "string", "minLength": 1},
                    "extractedData": {"type": "object"},
                    "autoCreateBill": {"type": "boolean"},
                },
                "required": ["documentId", "extractedData"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_extract, args),
            permission=PERMISSION_WRITE,
        ),
    ]


async def _ocr_result(args: dict[str, Any]):
    from tools_gateway.registry import ToolResult

    try:
        company = store.resolve_tenant(args.get("companyId"))
        document = _ocr(company, args)
    except AccountingError as exc:
        return ToolResult(ok=False, content=exc.message, error_code=exc.code)
    if document is None:
        return ToolResult(
            ok=False,
            content="No OCR provider is configured; set FLARE_VISION_URL to enable it.",
            error_code=NOT_CONFIGURED,
        )
    return ToolResult(
        ok=True,
        content=json.dumps(
            {"documentId": document["id"], "text": document["content"]}, ensure_ascii=False
        ),
    )


def register_document_tools(registry: ToolRegistry) -> None:
    for tool in document_tools():
        registry.register(tool)
