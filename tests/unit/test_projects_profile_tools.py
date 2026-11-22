"""Project and business-profile tool tests (rows 59-64)."""

from __future__ import annotations

import json

import pytest

from tools_gateway.accounting import store
from tools_gateway.builtin import create_default_registry

COMPANY = "acme"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.delenv("FLARE_ACCOUNTING_TENANTS", raising=False)
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


async def test_project_validations(reg):
    blank = await call(reg, "create_project", companyId=COMPANY, name=" ", budget="0")
    assert not blank.ok
    assert blank.error_code == "VALIDATION"

    negative = await call(reg, "create_project", companyId=COMPANY, name="P", budget="-1")
    assert not negative.ok
    assert negative.error_code == "VALIDATION"

    bad_dates = await call(
        reg,
        "create_project",
        companyId=COMPANY,
        name="P",
        budget="10",
        startDate="2026-05-01",
        endDate="2026-04-01",
    )
    assert not bad_dates.ok
    assert "End date" in bad_dates.content

    unknown_client = await call(
        reg,
        "create_project",
        companyId=COMPANY,
        name="P",
        budget="10",
        clientId="cus_missing",
    )
    assert not unknown_client.ok
    assert unknown_client.error_code == "NOT_FOUND"


async def test_project_transactions_and_profitability(reg):
    project = body(
        await call(reg, "create_project", companyId=COMPANY, name="Website", budget="5000.00")
    )["project"]

    await call(
        reg,
        "add_project_transaction",
        companyId=COMPANY,
        projectId=project["id"],
        type="REVENUE",
        description="Deposit",
        amount="1000.00",
    )
    await call(
        reg,
        "add_project_transaction",
        companyId=COMPANY,
        projectId=project["id"],
        type="EXPENSE",
        description="Hosting",
        amount="400.00",
    )

    report = body(
        await call(reg, "get_project_profitability", companyId=COMPANY, projectId=project["id"])
    )
    assert report["totalRevenue"] == "1000.00"
    assert report["totalExpenses"] == "400.00"
    assert report["profit"] == "600.00"

    listed = body(await call(reg, "get_projects", companyId=COMPANY))
    assert listed["projects"][0]["margin"] == "60.0"


async def test_project_transaction_guards(reg):
    project = body(await call(reg, "create_project", companyId=COMPANY, name="P", budget="0"))[
        "project"
    ]
    zero = await call(
        reg,
        "add_project_transaction",
        companyId=COMPANY,
        projectId=project["id"],
        type="REVENUE",
        description="x",
        amount="0.00",
    )
    assert not zero.ok
    assert zero.error_code == "VALIDATION"

    blank = await call(
        reg,
        "add_project_transaction",
        companyId=COMPANY,
        projectId=project["id"],
        type="EXPENSE",
        description=" ",
        amount="1.00",
    )
    assert not blank.ok
    assert "Description" in blank.content

    missing = await call(
        reg,
        "get_project_profitability",
        companyId=COMPANY,
        projectId="prj_missing",
    )
    assert not missing.ok
    assert missing.error_code == "NOT_FOUND"


async def test_profile_defaults_and_update(reg):
    profile = body(await call(reg, "get_business_profile", companyId=COMPANY))["profile"]
    assert profile["currency"] == "NGN"
    assert profile["vatRate"] == "7.50"

    updated = body(
        await call(
            reg,
            "update_business_profile",
            companyId=COMPANY,
            name="Acme Ltd",
            currency="USD",
            vatRate="10",
        )
    )["profile"]
    assert updated["name"] == "Acme Ltd"
    assert updated["currency"] == "USD"
    assert updated["vatRate"] == "10.00"

    bad_rate = await call(reg, "update_business_profile", companyId=COMPANY, vatRate="101")
    assert not bad_rate.ok
    assert bad_rate.error_code == "VALIDATION"
