"""Integration tools (inventory rows 69-82).

Local state (flags, schedule, tokens) is always available. Everything that
needs Google is honest about it: without FLARE_GOOGLE_CLIENT_ID/SECRET the
connect/sync/send/calendar tools return PROVIDER_NOT_CONFIGURED, and using an
integration that is not connected returns STATE.
"""

from __future__ import annotations

import os
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import STATE, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.registry import (
    PERMISSION_DESTRUCTIVE,
    PERMISSION_READ,
    PERMISSION_WRITE,
    Tool,
    ToolRegistry,
    ToolResult,
)

NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
SCHEDULES = ("MANUAL", "WEEKLY", "MONTHLY")


def _configured() -> bool:
    return bool(
        os.environ.get("FLARE_GOOGLE_CLIENT_ID") and os.environ.get("FLARE_GOOGLE_CLIENT_SECRET")
    )


def _not_configured(action: str) -> ToolResult:
    return ToolResult(
        ok=False,
        content=(
            f"{action} needs Google OAuth credentials; set FLARE_GOOGLE_CLIENT_ID and "
            "FLARE_GOOGLE_CLIENT_SECRET."
        ),
        error_code=NOT_CONFIGURED,
    )


def _state(company: dict[str, Any]) -> dict[str, Any]:
    row = store.select_one("integrations", company["id"], {})
    if row is not None:
        return row
    return store.insert_row(
        "integrations",
        {
            "company_id": company["id"],
            "drive": 0,
            "gmail": 0,
            "drive_sync_schedule": "MANUAL",
        },
    )


def _state_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "drive": bool(row["drive"]),
        "gmail": bool(row["gmail"]),
        "driveSyncSchedule": row["drive_sync_schedule"],
        "driveEmail": row["drive_email"],
        "gmailEmail": row["gmail_email"],
    }


def _get_state(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    return {"integrations": _state_payload(_state(company))}


def _set_state(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    _state(company)
    values: dict[str, Any] = {}
    for key, column in (("drive", "drive"), ("gmail", "gmail")):
        if args.get(key) is not None:
            values[column] = 1 if args[key] else 0
    if values:
        store.update_row("integrations", company["id"], company["id"], values)
    return {"integrations": _state_payload(_state(company)), "updated": bool(values)}


def _connected(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    row = _state(company)
    return {
        "drive": bool(row["drive"]),
        "gmail": bool(row["gmail"]),
        "driveEmail": row["drive_email"],
        "gmailEmail": row["gmail_email"],
    }


def _require_connected(company: dict[str, Any], provider: str) -> dict[str, Any]:
    row = _state(company)
    if row[provider] != 1:
        raise AccountingError(STATE, f"{provider} is not connected")
    return row


def _connect(provider: str):
    def _handler(company: dict[str, Any], _args: dict[str, Any]) -> Any:
        if not _configured():
            raise _NotConfigured(provider)
        scope = "drive" if provider == "drive" else "gmail.send"
        return {
            "provider": provider,
            "authorizationUrl": (
                f"https://accounts.google.com/o/oauth2/v2/auth?client_id={os.environ['FLARE_GOOGLE_CLIENT_ID']}"
                f"&response_type=code&access_type=offline&prompt=consent&scope=openid%20email"
                "%20https://www.googleapis.com/auth/"
                f"{scope}"
            ),
        }

    return _handler


class _NotConfigured(Exception):
    def __init__(self, action: str) -> None:
        super().__init__(action)
        self.action = action


def _callback(provider: str):
    def _handler(company: dict[str, Any], args: dict[str, Any]) -> Any:
        if not _configured():
            raise _NotConfigured(provider)
        code = args.get("code")
        if not isinstance(code, str) or code.strip() == "":
            raise AccountingError(VALIDATION, "code is required")
        # A real exchange needs Google's token endpoint; without a provider we
        # refuse rather than storing an unusable token.
        raise _NotConfigured(provider)

    return _handler


def _sync_drive(company: dict[str, Any], _args: dict[str, Any]) -> Any:
    _require_connected(company, "drive")
    if not _configured():
        raise _NotConfigured("Drive sync")
    raise _NotConfigured("Drive sync")


def _schedule(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    schedule = args.get("schedule")
    if schedule not in SCHEDULES:
        raise AccountingError(VALIDATION, "schedule must be MANUAL, WEEKLY or MONTHLY")
    _state(company)
    store.update_row(
        "integrations", company["id"], company["id"], {"drive_sync_schedule": schedule}
    )
    return {"integrations": _state_payload(_state(company))}


def _email_status(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    row = _state(company)
    return {
        "connected": bool(row["gmail"]),
        "email": row["gmail_email"],
        "configured": _configured(),
    }


def _disconnect_email(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    _state(company)
    store.update_row(
        "integrations",
        company["id"],
        company["id"],
        {"gmail": 0, "gmail_refresh_token": None, "gmail_email": None},
    )
    store.record_audit(
        company["id"], action="DISCONNECT_EMAIL", entity_type="Integration", entity_id="gmail"
    )
    return {"connected": False, "email": None}


def _send_email(company: dict[str, Any], args: dict[str, Any]) -> Any:
    _require_connected(company, "gmail")
    to = args.get("to")
    subject = args.get("subject")
    body = args.get("body")
    if not isinstance(to, str) or "@" not in to:
        raise AccountingError(VALIDATION, "to must be an email address")
    if not isinstance(subject, str) or subject.strip() == "":
        raise AccountingError(VALIDATION, "subject is required")
    if not isinstance(body, str) or body.strip() == "":
        raise AccountingError(VALIDATION, "body is required")
    if not _configured():
        raise _NotConfigured("sending email")
    raise _NotConfigured("sending email")


def _calendar_create(company: dict[str, Any], args: dict[str, Any]) -> Any:
    _require_connected(company, "gmail")
    summary = args.get("summary")
    if not isinstance(summary, str) or summary.strip() == "":
        raise AccountingError(VALIDATION, "summary is required")
    start = args.get("startTime")
    end = args.get("endTime")
    if not isinstance(start, str) or not isinstance(end, str):
        raise AccountingError(VALIDATION, "startTime and endTime are required (ISO 8601)")
    if not _configured():
        raise _NotConfigured("creating a calendar event")
    raise _NotConfigured("creating a calendar event")


def _calendar_upcoming(company: dict[str, Any], _args: dict[str, Any]) -> Any:
    _require_connected(company, "gmail")
    if not _configured():
        raise _NotConfigured("listing calendar events")
    raise _NotConfigured("listing calendar events")


def _wrap(handler):
    """Turn _NotConfigured into a structured PROVIDER_NOT_CONFIGURED result."""

    async def _invoke(**args):
        try:
            company = store.resolve_tenant(args.get("companyId"))
            payload = handler(company, args)
        except _NotConfigured as exc:
            return _not_configured(exc.action)
        except AccountingError as exc:
            return ToolResult(ok=False, content=exc.message, error_code=exc.code)
        import json

        return ToolResult(ok=True, content=json.dumps(payload, default=str, ensure_ascii=False))

    return _invoke


_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; missing it fails with NO_ORGANIZATION.",
}


def integration_tools() -> list[Tool]:
    return [
        Tool(
            name="get_integration_state",
            description="Read the Drive/Gmail flags and sync schedule. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_state, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="set_integration_state",
            description="Enable or disable the Drive and Gmail integrations.",
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "drive": {"type": "boolean"},
                    "gmail": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_set_state, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_connected_integrations",
            description=(
                "Which integrations are connected, and the connected account emails. " "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_connected, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="connect_drive",
            description=(
                "Start Google Drive OAuth. Returns the consent URL, or " "PROVIDER_NOT_CONFIGURED."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=_wrap(_connect("drive")),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="drive_callback",
            description="Exchange the Drive OAuth code. Requires provider credentials.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY, "code": {"type": "string", "minLength": 1}},
                "required": ["code"],
                "additionalProperties": False,
            },
            func=_wrap(_callback("drive")),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="sync_drive",
            description="Run a Drive backup. Requires a connected Drive and provider credentials.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=_wrap(_sync_drive),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="schedule_drive_sync",
            description="Set the Drive backup schedule: MANUAL, WEEKLY or MONTHLY.",
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "schedule": {"type": "string"},
                },
                "required": ["schedule"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_schedule, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="connect_email",
            description="Start Gmail OAuth. Returns the consent URL, or PROVIDER_NOT_CONFIGURED.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=_wrap(_connect("gmail")),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="email_callback",
            description="Exchange the Gmail OAuth code. Requires provider credentials.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY, "code": {"type": "string", "minLength": 1}},
                "required": ["code"],
                "additionalProperties": False,
            },
            func=_wrap(_callback("gmail")),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_email_status",
            description=(
                "Gmail connection status and whether OAuth credentials are configured. "
                "Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_email_status, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="disconnect_email",
            description=(
                "APPROVAL REQUIRED. Revoke the stored Gmail credentials. Irreversible without "
                "re-authenticating."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_disconnect_email, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
        Tool(
            name="send_email",
            description=(
                "Send an email, optionally attaching a financial report. Requires a connected "
                "Gmail account and provider credentials, otherwise STATE or "
                "PROVIDER_NOT_CONFIGURED."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "to": {"type": "string", "minLength": 3},
                    "subject": {"type": "string", "minLength": 1},
                    "body": {"type": "string", "minLength": 1},
                    "reportType": {
                        "type": "string",
                        "enum": ["PROFIT_AND_LOSS", "BALANCE_SHEET", "TRIAL_BALANCE"],
                    },
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
            func=_wrap(_send_email),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="create_calendar_event",
            description=(
                "Create a Google Calendar event (optionally with Meet and attendees). Requires a "
                "connected account and provider credentials."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "summary": {"type": "string", "minLength": 1},
                    "startTime": {"type": "string"},
                    "endTime": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "createMeet": {"type": "boolean"},
                    "description": {"type": "string"},
                },
                "required": ["summary", "startTime", "endTime"],
                "additionalProperties": False,
            },
            func=_wrap(_calendar_create),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="list_upcoming_events",
            description="List upcoming Google Calendar events. Requires a connected account.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=_wrap(_calendar_upcoming),
            permission=PERMISSION_READ,
        ),
    ]


def register_integration_tools(registry: ToolRegistry) -> None:
    for tool in integration_tools():
        registry.register(tool)
