"""Document, integration and usage tool tests (rows 65-84)."""

from __future__ import annotations

import json

import pytest

from tools_gateway.accounting import store
from tools_gateway.builtin import create_default_registry

COMPANY = "acme"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    for name in (
        "FLARE_ACCOUNTING_TENANTS",
        "FLARE_GOOGLE_CLIENT_ID",
        "FLARE_GOOGLE_CLIENT_SECRET",
        "FLARE_VISION_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    store.reset_for_tests(str(tmp_path / "accounting.db"))
    yield
    store.reset_for_tests(str(tmp_path / "closed.db"))


@pytest.fixture()
def reg():
    return create_default_registry()


async def call(reg, tool_name: str, **args):
    return await reg.execute(tool_name, args)


def body(result) -> dict:
    assert result.ok, result.content
    return json.loads(result.content)


async def test_document_upload_and_list(reg):
    uploaded = body(
        await call(
            reg,
            "upload_document",
            companyId=COMPANY,
            filename="receipt.txt",
            content="Total 1000 naira",
        )
    )["document"]
    assert uploaded["status"] == "PENDING"

    listed = body(await call(reg, "list_documents", companyId=COMPANY))
    assert listed["count"] == 1
    assert listed["documents"][0]["filename"] == "receipt.txt"

    blank = await call(reg, "upload_document", companyId=COMPANY, filename=" ", content="x")
    assert not blank.ok
    assert blank.error_code == "VALIDATION"


async def test_ocr_reports_missing_provider(reg):
    uploaded = body(
        await call(reg, "upload_document", companyId=COMPANY, filename="r.txt", content="x")
    )["document"]
    result = await call(reg, "ocr_document", companyId=COMPANY, documentId=uploaded["id"])
    assert not result.ok
    assert result.error_code == "PROVIDER_NOT_CONFIGURED"


async def test_extract_creates_pending_bill(reg):
    uploaded = body(
        await call(reg, "upload_document", companyId=COMPANY, filename="invoice.txt", content="x")
    )["document"]
    result = body(
        await call(
            reg,
            "extract_document",
            companyId=COMPANY,
            documentId=uploaded["id"],
            autoCreateBill=True,
            extractedData={
                "vendorName": "New Vendor",
                "date": "2026-11-10",
                "lineItems": [{"description": "Paper", "quantity": 2, "unitCost": "100.00"}],
            },
        )
    )
    assert result["bill"]["total"] == "215.00"
    assert result["journal"]["status"] == "PENDING"
    vendors = body(await call(reg, "get_vendors", companyId=COMPANY))
    assert vendors["vendors"][0]["name"] == "New Vendor"


async def test_integration_state_and_schedule(reg):
    state = body(await call(reg, "get_integration_state", companyId=COMPANY))["integrations"]
    assert state["drive"] is False and state["gmail"] is False

    updated = body(
        await call(reg, "set_integration_state", companyId=COMPANY, drive=True, gmail=True)
    )["integrations"]
    assert updated["drive"] is True and updated["gmail"] is True

    scheduled = body(await call(reg, "schedule_drive_sync", companyId=COMPANY, schedule="WEEKLY"))[
        "integrations"
    ]
    assert scheduled["driveSyncSchedule"] == "WEEKLY"

    bad = await call(reg, "schedule_drive_sync", companyId=COMPANY, schedule="HOURLY")
    assert not bad.ok


async def test_provider_dependent_tools_are_honest(reg):
    connect = await call(reg, "connect_drive", companyId=COMPANY)
    assert not connect.ok
    assert connect.error_code == "PROVIDER_NOT_CONFIGURED"

    # Not connected -> STATE before provider checks.
    send = await call(
        reg,
        "send_email",
        companyId=COMPANY,
        to="a@b.com",
        subject="Hi",
        body="Hello",
    )
    assert not send.ok
    assert send.error_code == "STATE"

    await call(reg, "set_integration_state", companyId=COMPANY, gmail=True)
    send_connected = await call(
        reg,
        "send_email",
        companyId=COMPANY,
        to="a@b.com",
        subject="Hi",
        body="Hello",
    )
    assert not send_connected.ok
    assert send_connected.error_code == "PROVIDER_NOT_CONFIGURED"

    calendar = await call(
        reg,
        "create_calendar_event",
        companyId=COMPANY,
        summary="Review",
        startTime="2026-11-20T10:00:00+01:00",
        endTime="2026-11-20T11:00:00+01:00",
    )
    assert not calendar.ok
    assert calendar.error_code == "PROVIDER_NOT_CONFIGURED"


async def test_disconnect_email_reverses_state(reg):
    await call(reg, "set_integration_state", companyId=COMPANY, gmail=True)
    result = body(await call(reg, "disconnect_email", companyId=COMPANY))
    assert result["connected"] is False
    status = body(await call(reg, "get_email_status", companyId=COMPANY))
    assert status["connected"] is False


async def test_usage_record_and_read(reg):
    empty = body(await call(reg, "get_token_usage", companyId=COMPANY))["usage"]
    assert empty["totalTokens"] == 0

    body(
        await call(
            reg,
            "record_token_usage",
            companyId=COMPANY,
            inputTokens=1000,
            outputTokens=500,
            cachedTokens=100,
        )
    )
    usage = body(await call(reg, "get_token_usage", companyId=COMPANY))["usage"]
    assert usage["inputTokens"] == 1000
    assert usage["outputTokens"] == 500
    assert usage["totalTokens"] == 1600

    negative = await call(reg, "record_token_usage", companyId=COMPANY, inputTokens=-5)
    assert not negative.ok
    assert negative.error_code == "VALIDATION"
