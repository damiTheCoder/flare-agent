"""Banking tools (Batch 5: inventory rows 29-31).

Bank reconciliation is the one place where a tool posts as part of an
approval action: it proposes a journal and posts it in the same call, because
the matched receipt must appear on the ledger immediately. It is therefore
registered as permission=destructive.

Direction rules: INFLOW matches invoices, OUTFLOW matches bills. A
transaction and the document it matches can each be used once.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, STATE, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import _run as run_tool
from tools_gateway.accounting.ledger import post_entry, propose_entry
from tools_gateway.accounting.money import add, fmt
from tools_gateway.registry import (
    PERMISSION_DESTRUCTIVE,
    PERMISSION_READ,
    Tool,
    ToolRegistry,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


def _resolve_cash_account(company: dict[str, Any], requested: object) -> dict[str, Any]:
    """Pick the receipt account, refusing anything that is not an ASSET."""
    if requested is not None and requested != "":
        if not isinstance(requested, str) or requested.strip() == "":
            raise AccountingError(VALIDATION, "bankAccountId must be a non-empty string")
        account = store.account_by_id(company["id"], requested.strip())
        if account is None:
            raise AccountingError(NOT_FOUND, f"Account {requested} not found")
        if account["type"] != "ASSET":
            raise AccountingError(VALIDATION, "Bank account must be an ASSET account")
        return account

    for account in store.list_accounts(company["id"]):
        if account["type"] == "ASSET" and account["name"] in ("Cash", "Bank"):
            return account
    raise AccountingError(NOT_FOUND, "Cash or Bank account is not configured")


def _txn_payload(txn: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": txn["id"],
        "date": txn["date"],
        "description": txn["description"],
        "amount": txn["amount"],
        "type": txn["type"],
        "status": txn["status"],
        "matchedInvoiceId": txn["matched_invoice_id"],
        "matchedBillId": txn["matched_bill_id"],
    }


# ---------------------------------------------------------------------------
# 29. bank accounts
# ---------------------------------------------------------------------------


def _bank_accounts(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    accounts = [
        {
            "id": account["id"],
            "code": account["code"],
            "name": account["name"],
            "type": account["type"],
            "balance": account["balance"],
        }
        for account in store.list_accounts(company["id"])
        if account["type"] == "ASSET" and account["name"] in ("Cash", "Bank")
    ]
    return {"accounts": accounts, "count": len(accounts)}


# ---------------------------------------------------------------------------
# 30. unreconciled transactions
# ---------------------------------------------------------------------------


def _unreconciled(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    transactions = [
        _txn_payload(txn) for txn in store.list_bank_transactions(company["id"], "UNRECONCILED")
    ]
    return {"count": len(transactions), "transactions": transactions}


# ---------------------------------------------------------------------------
# 31. reconcile
# ---------------------------------------------------------------------------


def _reconcile(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    transaction_id = args.get("transactionId")
    if not isinstance(transaction_id, str) or transaction_id.strip() == "":
        raise AccountingError(VALIDATION, "transactionId is required")
    matched_id = args.get("matchedId")
    if not isinstance(matched_id, str) or matched_id.strip() == "":
        raise AccountingError(VALIDATION, "matchedId is required")
    matched_type = args.get("matchedType")
    if matched_type not in ("INVOICE", "BILL"):
        raise AccountingError(VALIDATION, "matchedType must be INVOICE or BILL")

    transaction = store.get_bank_transaction(company["id"], transaction_id.strip())
    if transaction is None:
        raise AccountingError(NOT_FOUND, f"Bank transaction {transaction_id} not found")
    if transaction["status"] == "RECONCILED":
        raise AccountingError(STATE, f"Bank transaction {transaction_id} is already reconciled")

    amount = abs(Decimal(transaction["amount"]))
    if amount <= 0:
        raise AccountingError(VALIDATION, "Bank transaction amount must be non-zero")

    if transaction["type"] == "INFLOW":
        if matched_type != "INVOICE":
            raise AccountingError(VALIDATION, "INFLOW transactions must be matched to an invoice")
        invoice = store.get_invoice(company["id"], matched_id.strip())
        if invoice is None:
            raise AccountingError(NOT_FOUND, f"Invoice {matched_id} not found")

        existing = store.find_bank_match(company["id"], invoice_id=invoice["id"])
        if existing is not None:
            raise AccountingError(
                STATE,
                f"Invoice {invoice['invoice_number']} is already matched to "
                f"transaction {existing['id']}",
            )

        total = Decimal(invoice["total_amount"])
        paid = Decimal(invoice["amount_paid"])
        outstanding = total - paid
        if outstanding <= 0:
            raise AccountingError(
                STATE, f"Invoice {invoice['invoice_number']} has no outstanding balance"
            )
        if amount > outstanding:
            raise AccountingError(
                VALIDATION,
                f"Transaction amount {fmt(amount)} exceeds invoice outstanding "
                f"balance {fmt(outstanding)}",
            )

        cash = _resolve_cash_account(company, args.get("bankAccountId"))
        receivable = _require_account(company, "Accounts Receivable", "ASSET")

        new_paid = add(paid, amount)
        fully_paid = new_paid == total
        store.update_invoice_payment(
            company["id"],
            invoice["id"],
            amount_paid=fmt(new_paid),
            status="PAID" if fully_paid else "SENT",
        )

        proposed = propose_entry(
            company,
            date=transaction["date"],
            memo=f"Bank match for invoice {invoice['invoice_number']}",
            lines=[
                {"accountId": cash["id"], "debit": fmt(amount)},
                {"accountId": receivable["id"], "credit": fmt(amount)},
            ],
        )
        # The single exception: reconciliation posts immediately.
        journal = post_entry(company, proposed["id"])
        reconciled = store.mark_bank_reconciled(
            company["id"], transaction["id"], invoice_id=invoice["id"]
        )

        updated_invoice = store.get_invoice(company["id"], invoice["id"])
        assert updated_invoice is not None
        return {
            "transaction": _txn_payload(reconciled),
            "journal": journal,
            "matchedType": "INVOICE",
            "invoice": {
                "id": updated_invoice["id"],
                "invoiceNumber": updated_invoice["invoice_number"],
                "status": updated_invoice["status"],
                "amountPaid": updated_invoice["amount_paid"],
                "outstanding": fmt(
                    Decimal(updated_invoice["total_amount"])
                    - Decimal(updated_invoice["amount_paid"])
                ),
            },
            "note": "The receipt journal was posted as part of this approval.",
        }

    if matched_type != "BILL":
        raise AccountingError(VALIDATION, "OUTFLOW transactions must be matched to a bill")

    bill = store.get_bill(company["id"], matched_id.strip())
    if bill is None:
        raise AccountingError(NOT_FOUND, f"Bill {matched_id} not found")

    existing = store.find_bank_match(company["id"], bill_id=bill["id"])
    if existing is not None:
        raise AccountingError(
            STATE,
            f"Bill {bill['bill_number']} is already matched to transaction {existing['id']}",
        )

    # WHT was withheld at source, so the payable — and the ceiling for a
    # match — is netPayable, exactly as in record_bill_payment.
    net_payable = Decimal(bill["net_payable"])
    paid = Decimal(bill["amount_paid"])
    outstanding = net_payable - paid
    if outstanding <= 0:
        raise AccountingError(STATE, f"Bill {bill['bill_number']} has no outstanding balance")
    if amount > outstanding:
        raise AccountingError(
            VALIDATION,
            f"Transaction amount {fmt(amount)} exceeds bill outstanding "
            f"balance {fmt(outstanding)}",
        )

    # Outflows only record the match; the payable itself is settled by
    # record_bill_payment, matching the core.
    reconciled = store.mark_bank_reconciled(company["id"], transaction["id"], bill_id=bill["id"])
    return {
        "transaction": _txn_payload(reconciled),
        "journal": None,
        "matchedType": "BILL",
        "note": (
            "Match recorded. No journal is raised for outflows; settle the bill with "
            "record_bill_payment."
        ),
    }


# ---------------------------------------------------------------------------
# tool definitions
# ---------------------------------------------------------------------------

_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; requests without it fail with NO_ORGANIZATION.",
}


def banking_tools() -> list[Tool]:
    return [
        Tool(
            name="get_bank_accounts",
            description="List the Cash and Bank asset accounts available for receipts. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_bank_accounts, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="get_unreconciled_bank_transactions",
            description="List bank transactions that have not been matched yet. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_unreconciled, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="reconcile_bank_transaction",
            description=(
                "APPROVAL REQUIRED. Match a bank transaction to an invoice (INFLOW) or a bill "
                "(OUTFLOW). Direction must agree with the transaction type; neither the "
                "transaction nor the document may already be matched; the amount may not "
                "exceed the outstanding balance. For INFLOW this posts the Cash/AR journal "
                "immediately as part of the approval; OUTFLOW only records the match and the "
                "bill is settled with record_bill_payment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "transactionId": {"type": "string", "minLength": 1},
                    "matchedId": {"type": "string", "minLength": 1},
                    "matchedType": {"type": "string", "enum": ["INVOICE", "BILL"]},
                    "bankAccountId": {
                        "type": "string",
                        "description": (
                            "Optional ASSET account to debit for an INFLOW; defaults to the "
                            "first Cash or Bank account."
                        ),
                    },
                },
                "required": ["transactionId", "matchedId", "matchedType"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_reconcile, args),
            permission=PERMISSION_DESTRUCTIVE,
        ),
    ]


def register_banking_tools(registry: ToolRegistry) -> None:
    for tool in banking_tools():
        registry.register(tool)
