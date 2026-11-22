"""Budget, equity and loan tool tests (rows 49-58)."""

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


async def account_id(reg, code: str) -> str:
    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    return next(row["id"] for row in trial["accounts"] if row["code"] == code)


async def test_budget_validations(reg):
    sales = await account_id(reg, "4000")

    blank = await call(reg, "create_budget", companyId=COMPANY, name=" ", fiscalYear=2026, lines=[])
    assert not blank.ok
    assert blank.error_code == "VALIDATION"

    no_lines = await call(
        reg, "create_budget", companyId=COMPANY, name="B", fiscalYear=2026, lines=[]
    )
    assert not no_lines.ok
    assert "at least one line" in no_lines.content

    negative = await call(
        reg,
        "create_budget",
        companyId=COMPANY,
        name="B",
        fiscalYear=2026,
        lines=[{"accountId": sales, "amount": "-1.00"}],
    )
    assert not negative.ok
    assert negative.error_code == "VALIDATION"

    unknown = await call(
        reg,
        "create_budget",
        companyId=COMPANY,
        name="B",
        fiscalYear=2026,
        lines=[{"accountId": "acc_missing", "amount": "10.00"}],
    )
    assert not unknown.ok
    assert unknown.error_code == "NOT_FOUND"


async def test_budget_vs_actual_and_delete(reg):
    sales = await account_id(reg, "4000")
    cash = await account_id(reg, "1010")
    budget = body(
        await call(
            reg,
            "create_budget",
            companyId=COMPANY,
            name="2026 plan",
            fiscalYear=2026,
            lines=[{"accountId": sales, "amount": "100000.00"}],
        )
    )["budget"]

    empty = body(await call(reg, "get_budget_vs_actual", companyId=COMPANY, budgetId=budget["id"]))
    assert empty["totalActual"] == "0.00"
    assert empty["totalVariance"] == "100000.00"

    proposed = body(
        await call(
            reg,
            "propose_journal",
            companyId=COMPANY,
            date="2026-06-01",
            lines=[
                {"accountId": cash, "debit": "1000.00"},
                {"accountId": sales, "credit": "1000.00"},
            ],
        )
    )
    await call(reg, "approve_journal", companyId=COMPANY, journalId=proposed["id"])

    with_actual = body(
        await call(reg, "get_budget_vs_actual", companyId=COMPANY, budgetId=budget["id"])
    )
    assert with_actual["totalActual"] == "1000.00"
    assert with_actual["totalVariance"] == "99000.00"

    deleted = body(await call(reg, "delete_budget", companyId=COMPANY, budgetId=budget["id"]))
    assert deleted["deleted"] is True
    listed = body(await call(reg, "get_budgets", companyId=COMPANY))
    assert listed["count"] == 0

    missing = await call(reg, "delete_budget", companyId=COMPANY, budgetId=budget["id"])
    assert not missing.ok
    assert missing.error_code == "NOT_FOUND"


async def test_equity_and_dividend(reg):
    zero = await call(
        reg, "create_equity_transaction", companyId=COMPANY, type="SHARE_CAPITAL", amount="0"
    )
    assert not zero.ok
    assert zero.error_code == "VALIDATION"

    equity = body(
        await call(
            reg,
            "create_equity_transaction",
            companyId=COMPANY,
            type="SHARE_CAPITAL",
            amount="50000.00",
        )
    )
    assert equity["journal"]["status"] == "PENDING"
    assert equity["journal"]["totalDebit"] == "50000.00"

    dividend = body(await call(reg, "record_dividend", companyId=COMPANY, amount="5000.00"))
    assert dividend["journal"]["status"] == "PENDING"
    assert dividend["journal"]["totalCredit"] == "5000.00"

    summary = body(await call(reg, "get_equity_summary", companyId=COMPANY))
    types = [row["type"] for row in summary["transactions"]]
    assert types == ["DIVIDEND", "SHARE_CAPITAL"]
    assert summary["dividendsDeclared"] == "5000.00"


async def test_loan_validations(reg):
    cases = [
        {"lenderName": " ", "principalAmount": "100", "interestRate": "10", "termMonths": 12},
        {"lenderName": "B", "principalAmount": "0", "interestRate": "10", "termMonths": 12},
        {"lenderName": "B", "principalAmount": "100", "interestRate": "101", "termMonths": 12},
        {"lenderName": "B", "principalAmount": "100", "interestRate": "10", "termMonths": 0},
    ]
    for case in cases:
        result = await call(reg, "create_loan", companyId=COMPANY, **case)
        assert not result.ok, case
        assert result.error_code == "VALIDATION", case


async def test_loan_repayment_split_and_settlement(reg):
    loan = body(
        await call(
            reg,
            "create_loan",
            companyId=COMPANY,
            lenderName="Bank",
            principalAmount="120000.00",
            interestRate="12",
            termMonths=12,
            startDate="2026-01-01",
        )
    )["loan"]
    assert loan["balance"] == "120000.00"

    bank = await account_id(reg, "1020")
    repayment = body(
        await call(
            reg,
            "record_loan_repayment",
            companyId=COMPANY,
            loanId=loan["id"],
            amount="5000.00",
            bankAccountId=bank,
            date="2026-02-01",
        )
    )
    # Monthly interest = 120000 * 12% / 12 = 1200; principal = 3800.
    assert repayment["repayment"]["interestPaid"] == "1200.00"
    assert repayment["repayment"]["principalPaid"] == "3800.00"
    assert repayment["loan"]["balance"] == "116200.00"
    assert repayment["journal"]["status"] == "PENDING"

    final = body(
        await call(
            reg,
            "record_loan_repayment",
            companyId=COMPANY,
            loanId=loan["id"],
            amount="117362.00",
            bankAccountId=bank,
            date="2026-03-01",
        )
    )
    assert final["loan"]["status"] == "PAID"
    assert final["loan"]["balance"] == "0.00"

    again = await call(
        reg,
        "record_loan_repayment",
        companyId=COMPANY,
        loanId=loan["id"],
        amount="1.00",
        bankAccountId=bank,
    )
    assert not again.ok
    assert again.error_code == "STATE"
    assert "fully paid" in again.content


async def test_loan_repayment_requires_asset_bank(reg):
    loan = body(
        await call(
            reg,
            "create_loan",
            companyId=COMPANY,
            lenderName="Bank",
            principalAmount="1000.00",
            interestRate="0",
            termMonths=6,
        )
    )["loan"]
    sales = await account_id(reg, "4000")
    result = await call(
        reg,
        "record_loan_repayment",
        companyId=COMPANY,
        loanId=loan["id"],
        amount="100.00",
        bankAccountId=sales,
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "ASSET" in result.content
