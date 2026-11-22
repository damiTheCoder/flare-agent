"""Ledger tool tests (Batch 1).

Covers the rules an agent can trip over: tenant scoping, double-entry
validation, the pending -> posted boundary, and the period lock that must
block posting.
"""

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


async def call(reg, name: str, **args):
    return await reg.execute(name, args)


def body(result) -> dict:
    assert result.ok, result.content
    return json.loads(result.content)


async def account(reg, code: str) -> str:
    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    return next(row["id"] for row in trial["accounts"] if row["code"] == code)


async def propose(reg, lines, date="2026-11-15", memo="test"):
    return await call(reg, "propose_journal", companyId=COMPANY, date=date, memo=memo, lines=lines)


async def test_requires_tenant(reg):
    result = await call(reg, "get_trial_balance")
    assert not result.ok
    assert result.error_code == "NO_ORGANIZATION"


async def test_rejects_tenant_outside_allow_list(reg, monkeypatch):
    monkeypatch.setenv("FLARE_ACCOUNTING_TENANTS", "acme")
    result = await call(reg, "get_trial_balance", companyId="intruder")
    assert not result.ok
    assert result.error_code == "UNAUTHORIZED"


async def test_rejects_unbalanced_journal(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    result = await propose(
        reg,
        [
            {"accountId": cash, "debit": "100.00"},
            {"accountId": sales, "credit": "90.00"},
        ],
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "unbalanced" in result.content


async def test_rejects_line_with_both_sides(reg):
    cash = await account(reg, "1010")
    result = await propose(reg, [{"accountId": cash, "debit": "10.00", "credit": "10.00"}])
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "both" in result.content


async def test_rejects_sub_cent_precision(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    result = await propose(
        reg,
        [
            {"accountId": cash, "debit": "10.005"},
            {"accountId": sales, "credit": "10.005"},
        ],
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "2 decimal" in result.content


async def test_rejects_unknown_account(reg):
    result = await propose(
        reg,
        [
            {"accountId": "acc_missing", "debit": "10.00"},
            {"accountId": "acc_missing2", "credit": "10.00"},
        ],
    )
    assert not result.ok
    assert result.error_code == "NOT_FOUND"


async def test_proposal_is_pending_and_moves_nothing(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    proposed = body(
        await propose(
            reg,
            [
                {"accountId": cash, "debit": "250.00"},
                {"accountId": sales, "credit": "250.00"},
            ],
        )
    )
    assert proposed["status"] == "PENDING"
    assert proposed["requiresApproval"] is True

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    row = next(item for item in trial["accounts"] if item["id"] == cash)
    assert row["balance"] == "0.00"

    pending = body(await call(reg, "get_pending_journals", companyId=COMPANY))
    assert pending["count"] == 1


async def test_approval_posts_and_moves_balances(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    proposed = body(
        await propose(
            reg,
            [
                {"accountId": cash, "debit": "250.00"},
                {"accountId": sales, "credit": "250.00"},
            ],
        )
    )

    posted = body(await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"]))
    assert posted["status"] == "POSTED"
    assert posted["requiresApproval"] is False

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    by_id = {item["id"]: item for item in trial["accounts"]}
    assert by_id[cash]["debit"] == "250.00"
    assert by_id[sales]["credit"] == "250.00"
    assert trial["totalDebit"] == "250.00"
    assert trial["totalCredit"] == "250.00"

    pnl = body(await call(reg, "get_profit_and_loss", companyId=COMPANY))
    assert pnl["totalRevenue"] == "250.00"
    assert pnl["netIncome"] == "250.00"


async def test_double_approval_is_a_state_error(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    proposed = body(
        await propose(
            reg,
            [
                {"accountId": cash, "debit": "10.00"},
                {"accountId": sales, "credit": "10.00"},
            ],
        )
    )
    await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"])
    second = await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"])
    assert not second.ok
    assert second.error_code == "STATE"
    assert "not PENDING" in second.content


async def test_locked_period_blocks_posting(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    proposed = body(
        await propose(
            reg,
            [
                {"accountId": cash, "debit": "40.00"},
                {"accountId": sales, "credit": "40.00"},
            ],
            date="2026-11-15",
        )
    )

    locked = body(await call(reg, "lock_period", companyId=COMPANY, month=11, year=2026))
    assert locked["locked"] == 1

    result = await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"])
    assert not result.ok
    assert result.error_code == "STATE"
    assert "locked" in result.content.lower()

    periods = body(await call(reg, "get_locked_periods", companyId=COMPANY))
    assert periods["periods"][0]["month"] == 11
    assert periods["periods"][0]["year"] == 2026


async def test_unlock_period_reopens_posting(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    proposed = body(
        await propose(
            reg,
            [
                {"accountId": cash, "debit": "5.00"},
                {"accountId": sales, "credit": "5.00"},
            ],
            date="2026-11-20",
        )
    )
    await call(reg, "lock_period", companyId=COMPANY, month=11, year=2026)
    unlocked = body(await call(reg, "unlock_period", companyId=COMPANY, month=11, year=2026))
    assert unlocked["unlocked"] == 1

    posted = body(await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"]))
    assert posted["status"] == "POSTED"


async def test_general_ledger_defaults_to_posted(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    pending = body(
        await propose(
            reg,
            [
                {"accountId": cash, "debit": "7.00"},
                {"accountId": sales, "credit": "7.00"},
            ],
        )
    )

    posted_view = body(await call(reg, "get_general_ledger", companyId=COMPANY, accountId=cash))
    assert posted_view["lines"] == []

    pending_view = body(
        await call(
            reg,
            "get_general_ledger",
            companyId=COMPANY,
            accountId=cash,
            status="PENDING",
        )
    )
    assert [line["entryId"] for line in pending_view["lines"]] == [pending["id"]]

    await call(reg, "approve_journal", companyId=COMPANY, journalId=pending["id"])
    posted_after = body(await call(reg, "get_general_ledger", companyId=COMPANY, accountId=cash))
    assert len(posted_after["lines"]) == 1
    assert posted_after["totalDebit"] == "7.00"


async def test_balance_sheet_includes_net_income(reg):
    cash = await account(reg, "1010")
    sales = await account(reg, "4000")
    proposed = body(
        await propose(
            reg,
            [
                {"accountId": cash, "debit": "120.00"},
                {"accountId": sales, "credit": "120.00"},
            ],
        )
    )
    await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"])

    sheet = body(await call(reg, "get_balance_sheet", companyId=COMPANY))
    assert sheet["totalAssets"] == "120.00"
    assert sheet["netIncome"] == "120.00"
    assert sheet["totalEquity"] == "120.00"


def test_permissions_are_mapped(reg):
    assert reg.get("get_trial_balance").permission == "read"
    assert reg.get("propose_journal").permission == "write"
    assert reg.get("approve_journal").permission == "destructive"
    assert reg.get("lock_period").permission == "destructive"
    assert reg.get("unlock_period").permission == "destructive"
