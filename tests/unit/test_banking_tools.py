"""Banking tool tests (Batch 5).

Reconciliation is the only tool that posts as part of an approval, so these
tests assert the ledger actually moved. They also cover direction mismatches,
over-matching, double matches and an already-reconciled transaction.
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


async def call(reg, tool_name: str, **args):
    return await reg.execute(tool_name, args)


def body(result) -> dict:
    assert result.ok, result.content
    return json.loads(result.content)


async def account_id(reg, code: str) -> str:
    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    return next(row["id"] for row in trial["accounts"] if row["code"] == code)


async def make_invoice(reg, *, quantity=1, unit_price="100.00") -> dict:
    customer = body(await call(reg, "create_customer", companyId=COMPANY, name="Ada Ltd"))["id"]
    item = body(
        await call(
            reg,
            "create_item",
            companyId=COMPANY,
            name="Widget",
            price=unit_price,
        )
    )["id"]
    return body(
        await call(
            reg,
            "create_invoice",
            companyId=COMPANY,
            customerId=customer,
            date="2026-11-15",
            items=[{"itemId": item, "quantity": quantity}],
        )
    )["invoice"]


async def make_bill(reg, *, quantity=1, unit_cost="1000.00") -> dict:
    vendor = body(await call(reg, "create_vendor", companyId=COMPANY, name="Supply Co"))["id"]
    return body(
        await call(
            reg,
            "create_bill",
            companyId=COMPANY,
            vendorId=vendor,
            date="2026-11-15",
            items=[{"description": "Paper", "quantity": quantity, "unitCost": unit_cost}],
        )
    )["bill"]


def make_txn(amount: str, txn_type: str, *, description="Bank entry") -> dict:
    store.resolve_tenant(COMPANY)
    return store.insert_bank_transaction(
        COMPANY,
        date="2026-11-18",
        description=description,
        amount=amount,
        txn_type=txn_type,
    )


async def test_requires_tenant(reg):
    result = await call(reg, "get_bank_accounts")
    assert not result.ok
    assert result.error_code == "NO_ORGANIZATION"


async def test_bank_accounts_are_asset_cash_and_bank(reg):
    listed = body(await call(reg, "get_bank_accounts", companyId=COMPANY))
    names = [row["name"] for row in listed["accounts"]]
    assert names == ["Cash", "Bank"]
    assert all(row["type"] == "ASSET" for row in listed["accounts"])


async def test_unreconciled_lists_only_open_transactions(reg):
    make_txn("10.00", "INFLOW", description="one")
    make_txn("20.00", "OUTFLOW", description="two")
    listed = body(await call(reg, "get_unreconciled_bank_transactions", companyId=COMPANY))
    assert listed["count"] == 2
    assert all(txn["status"] == "UNRECONCILED" for txn in listed["transactions"])


async def test_unknown_transaction_is_not_found(reg):
    invoice = await make_invoice(reg)
    result = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId="btx_missing",
        matchedId=invoice["id"],
        matchedType="INVOICE",
    )
    assert not result.ok
    assert result.error_code == "NOT_FOUND"


async def test_inflow_cannot_match_a_bill(reg):
    bill = await make_bill(reg)
    txn = make_txn("100.00", "INFLOW")
    result = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=txn["id"],
        matchedId=bill["id"],
        matchedType="BILL",
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "INFLOW" in result.content


async def test_outflow_cannot_match_an_invoice(reg):
    invoice = await make_invoice(reg)
    txn = make_txn("100.00", "OUTFLOW")
    result = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=txn["id"],
        matchedId=invoice["id"],
        matchedType="INVOICE",
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "OUTFLOW" in result.content


async def test_overpayment_is_rejected(reg):
    invoice = await make_invoice(reg)  # total 107.50
    txn = make_txn("999.00", "INFLOW")
    result = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=txn["id"],
        matchedId=invoice["id"],
        matchedType="INVOICE",
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "exceeds invoice outstanding" in result.content


async def test_already_reconciled_transaction_is_a_state_error(reg):
    invoice = await make_invoice(reg)
    txn = make_txn("107.50", "INFLOW")
    first = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=txn["id"],
        matchedId=invoice["id"],
        matchedType="INVOICE",
    )
    assert first.ok, first.content

    second = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=txn["id"],
        matchedId=invoice["id"],
        matchedType="INVOICE",
    )
    assert not second.ok
    assert second.error_code == "STATE"
    assert "already reconciled" in second.content


async def test_a_document_cannot_be_matched_twice(reg):
    invoice = await make_invoice(reg)
    first_txn = make_txn("50.00", "INFLOW")
    second_txn = make_txn("50.00", "INFLOW")

    first = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=first_txn["id"],
        matchedId=invoice["id"],
        matchedType="INVOICE",
    )
    assert first.ok, first.content

    second = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=second_txn["id"],
        matchedId=invoice["id"],
        matchedType="INVOICE",
    )
    assert not second.ok
    assert second.error_code == "STATE"
    assert "already matched" in second.content


async def test_successful_inflow_posts_the_journal(reg):
    invoice = await make_invoice(reg)  # total 107.50
    txn = make_txn("107.50", "INFLOW")

    result = body(
        await call(
            reg,
            "reconcile_bank_transaction",
            companyId=COMPANY,
            transactionId=txn["id"],
            matchedId=invoice["id"],
            matchedType="INVOICE",
        )
    )

    assert result["transaction"]["status"] == "RECONCILED"
    assert result["transaction"]["matchedInvoiceId"] == invoice["id"]
    assert result["journal"]["status"] == "POSTED"
    assert result["invoice"]["status"] == "PAID"
    assert result["invoice"]["outstanding"] == "0.00"

    trial = body(await call(reg, "get_trial_balance", companyId=COMPANY))
    cash = next(row for row in trial["accounts"] if row["code"] == "1010")
    receivable = next(row for row in trial["accounts"] if row["code"] == "1100")
    assert cash["balance"] == "107.50"
    assert receivable["balance"] == "-107.50"

    # The receipt journal posted; the invoice's own AR/revenue journal is a
    # separate proposal and is still waiting for approval.
    pending = body(await call(reg, "get_pending_journals", companyId=COMPANY))
    assert pending["count"] == 1
    assert pending["journals"][0]["id"] != result["journal"]["id"]


async def test_outflow_match_records_without_posting(reg):
    bill = await make_bill(reg)  # 1075.00
    txn = make_txn("1075.00", "OUTFLOW")

    result = body(
        await call(
            reg,
            "reconcile_bank_transaction",
            companyId=COMPANY,
            transactionId=txn["id"],
            matchedId=bill["id"],
            matchedType="BILL",
        )
    )
    assert result["transaction"]["status"] == "RECONCILED"
    assert result["transaction"]["matchedBillId"] == bill["id"]
    assert result["journal"] is None

    pending = body(await call(reg, "get_pending_journals", companyId=COMPANY))
    assert pending["count"] == 1  # only the original bill journal


async def test_receipt_account_must_be_an_asset(reg):
    invoice = await make_invoice(reg)
    txn = make_txn("10.00", "INFLOW")
    revenue = await account_id(reg, "4000")

    result = await call(
        reg,
        "reconcile_bank_transaction",
        companyId=COMPANY,
        transactionId=txn["id"],
        matchedId=invoice["id"],
        matchedType="INVOICE",
        bankAccountId=revenue,
    )
    assert not result.ok
    assert result.error_code == "VALIDATION"
    assert "ASSET" in result.content


async def test_banking_permissions(reg):
    assert reg.get("get_bank_accounts").permission == "read"
    assert reg.get("get_unreconciled_bank_transactions").permission == "read"
    assert reg.get("reconcile_bank_transaction").permission == "destructive"
