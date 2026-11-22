"""Sales tools (Batch 2: inventory rows 13-18).

Invoices and payments only ever raise PENDING journals through
``ledger.propose_entry``; nothing here posts. Approval stays with
``approve_journal`` (permission=destructive).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from tools_gateway.accounting import store
from tools_gateway.accounting.errors import NOT_FOUND, STATE, VALIDATION, AccountingError
from tools_gateway.accounting.ledger import (
    _date as parse_required_date,
)
from tools_gateway.accounting.ledger import (
    _optional_date as parse_optional_date,
)
from tools_gateway.accounting.ledger import (
    _run as run_tool,
)
from tools_gateway.accounting.ledger import propose_entry
from tools_gateway.accounting.money import ZERO, add, assert_non_negative, fmt, to_money
from tools_gateway.registry import (
    PERMISSION_READ,
    PERMISSION_WRITE,
    Tool,
    ToolRegistry,
)

VAT_RATE = Decimal("0.075")
AGING_BUCKETS = (
    ("current", "Current"),
    ("1-30", "1-30"),
    ("31-60", "31-60"),
    ("61-90", "61-90"),
    ("90+", "90+"),
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_quantity(value: object, field: str) -> Decimal:
    if value is None or value == "":
        raise AccountingError(VALIDATION, f"{field} is required")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise AccountingError(VALIDATION, f"{field} must be a decimal number") from None
    if not parsed.is_finite():
        raise AccountingError(VALIDATION, f"{field} must be a finite number")
    assert_non_negative(parsed, field)
    return parsed


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


def _invoice_payload(invoice: dict[str, Any]) -> dict[str, Any]:
    total = Decimal(invoice["total_amount"])
    paid = Decimal(invoice["amount_paid"])
    subtotal = (
        add(*(Decimal(line["total"]) for line in invoice["lines"])) if invoice["lines"] else ZERO
    )
    return {
        "id": invoice["id"],
        "invoiceNumber": invoice["invoice_number"],
        "customerId": invoice["customer_id"],
        "customer": invoice["customer"],
        "date": invoice["date"],
        "dueDate": invoice["due_date"],
        "status": invoice["status"],
        "lines": [
            {
                "id": line["id"],
                "itemId": line["item_id"],
                "description": line["description"],
                "quantity": line["quantity"],
                "unitPrice": line["unit_price"],
                "total": line["total"],
            }
            for line in invoice["lines"]
        ],
        "subtotal": fmt(subtotal),
        "vat": fmt(total - subtotal),
        "total": fmt(total),
        "amountPaid": fmt(paid),
        "outstanding": fmt(total - paid),
    }


def _bucket_for(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1-30"
    if days_past_due <= 60:
        return "31-60"
    if days_past_due <= 90:
        return "61-90"
    return "90+"


# ---------------------------------------------------------------------------
# 13. customers
# ---------------------------------------------------------------------------


def _get_customers(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    customers = [
        {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
        }
        for row in store.list_customers(company["id"])
    ]
    return {"customers": customers, "count": len(customers)}


# ---------------------------------------------------------------------------
# 14. create customer
# ---------------------------------------------------------------------------


def _create_customer(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Customer name is required")
    email = args.get("email")
    phone = args.get("phone")
    customer = store.insert_customer(
        company["id"],
        name=name.strip(),
        email=email.strip() if isinstance(email, str) and email.strip() else None,
        phone=phone.strip() if isinstance(phone, str) and phone.strip() else None,
    )
    return {
        "id": customer["id"],
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["phone"],
    }


# ---------------------------------------------------------------------------
# 15. invoices
# ---------------------------------------------------------------------------


def _get_invoices(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    invoices = [_invoice_payload(invoice) for invoice in store.list_invoices(company["id"])]
    return {"invoices": invoices, "count": len(invoices)}


# ---------------------------------------------------------------------------
# 16. create invoice
# ---------------------------------------------------------------------------


def _create_invoice(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    raw_items = args.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AccountingError(VALIDATION, "Invoice must contain at least one line item")

    customer_id = args.get("customerId")
    if not isinstance(customer_id, str) or customer_id.strip() == "":
        raise AccountingError(VALIDATION, "customerId is required")
    customer = store.get_customer(company["id"], customer_id.strip())
    if customer is None:
        raise AccountingError(NOT_FOUND, f"Customer {customer_id} not found")

    invoice_date = parse_required_date(args.get("date"), "invoice date")
    due_date = parse_optional_date(args.get("dueDate"), "invoice due date")
    if due_date is None:
        due_date = (date.fromisoformat(invoice_date) + timedelta(days=30)).isoformat()

    resolved: list[dict[str, Any]] = []
    subtotal = ZERO
    cogs_total = ZERO
    stock_moves: list[tuple[str, int]] = []

    for index, raw in enumerate(raw_items, start=1):
        label = f"Line {index}"
        if not isinstance(raw, dict):
            raise AccountingError(VALIDATION, f"{label}: must be an object")
        quantity = _to_quantity(raw.get("quantity"), f"{label} quantity")

        item_id = raw.get("itemId")
        item = None
        if item_id is not None:
            if not isinstance(item_id, str) or item_id.strip() == "":
                raise AccountingError(VALIDATION, f"{label}: itemId must be a non-empty string")
            item = store.get_item(company["id"], item_id.strip())
            if item is None:
                raise AccountingError(NOT_FOUND, f"Item {item_id} not found")
            item_id = item["id"]

        unit_price_raw = raw.get("unitPrice")
        if unit_price_raw is not None and unit_price_raw != "":
            unit_price = to_money(unit_price_raw, f"{label} unitPrice")
        elif item is not None:
            unit_price = to_money(item["price"], f"{label} unitPrice")
        else:
            unit_price = ZERO

        description = raw.get("description")
        if isinstance(description, str) and description.strip():
            line_description = description.strip()
        elif item is not None:
            line_description = item["name"]
        else:
            line_description = f"Line {index}"

        line_total = (unit_price * quantity).quantize(Decimal("0.01"))
        subtotal = add(subtotal, line_total)
        resolved.append(
            {
                "itemId": item_id,
                "description": line_description,
                "quantity": quantity,
                "unitPrice": unit_price,
                "total": line_total,
            }
        )

        if item is not None:
            units = max(0, int(round(quantity)))
            if units > 0:
                stock_moves.append((item["id"], units))
            cogs_total = add(cogs_total, Decimal(item["cost"]) * quantity)

    if subtotal <= 0:
        raise AccountingError(VALIDATION, "Invoice total must be greater than zero")

    vat = (subtotal * VAT_RATE).quantize(Decimal("0.01"))
    total = subtotal + vat

    receivable = _require_account(company, "Accounts Receivable", "ASSET")
    revenue = _require_account(company, "Sales Revenue", "REVENUE")
    vat_payable = _require_account(company, "VAT Payable", "LIABILITY") if vat > 0 else None

    invoice = store.insert_invoice(
        company["id"],
        number=store.next_invoice_number(company["id"]),
        customer_id=customer["id"],
        date=invoice_date,
        due_date=due_date,
        total=fmt(total),
        lines=[
            (
                line["itemId"],
                line["description"],
                str(line["quantity"]),
                fmt(line["unitPrice"]),
                fmt(line["total"]),
            )
            for line in resolved
        ],
    )

    journal = propose_entry(
        company,
        date=invoice_date,
        memo=f"Invoice {invoice['invoice_number']} - {customer['name']}",
        lines=[
            {"accountId": receivable["id"], "debit": fmt(total)},
            {"accountId": revenue["id"], "credit": fmt(subtotal)},
            *(
                [{"accountId": vat_payable["id"], "credit": fmt(vat)}]
                if vat_payable is not None
                else []
            ),
        ],
    )

    cogs_journal: dict[str, Any] | None = None
    if cogs_total > 0:
        cogs_account = _require_account(company, "Cost of Goods Sold", "EXPENSE")
        inventory = _require_account(company, "Inventory", "ASSET")
        cogs_journal = propose_entry(
            company,
            date=invoice_date,
            memo=f"COGS for invoice {invoice['invoice_number']}",
            lines=[
                {"accountId": cogs_account["id"], "debit": fmt(cogs_total)},
                {"accountId": inventory["id"], "credit": fmt(cogs_total)},
            ],
        )
        for item_id, units in stock_moves:
            store.decrement_stock(company["id"], item_id, units)

    return {
        "invoice": _invoice_payload(invoice),
        "journal": journal,
        "cogsJournal": cogs_journal,
        "note": "Both journals are PENDING; approve them with approve_journal.",
    }


# ---------------------------------------------------------------------------
# 17. record invoice payment
# ---------------------------------------------------------------------------


def _record_invoice_payment(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    invoice_id = args.get("invoiceId")
    if not isinstance(invoice_id, str) or invoice_id.strip() == "":
        raise AccountingError(VALIDATION, "invoiceId is required")

    payment = to_money(args.get("amount"), "amount")
    if payment <= 0:
        raise AccountingError(VALIDATION, "Payment amount must be greater than zero")

    invoice = store.get_invoice(company["id"], invoice_id.strip())
    if invoice is None:
        raise AccountingError(NOT_FOUND, f"Invoice {invoice_id} not found")
    if invoice["status"] == "PAID":
        raise AccountingError(STATE, f"Invoice {invoice['invoice_number']} is already paid")

    total = Decimal(invoice["total_amount"])
    paid = Decimal(invoice["amount_paid"])
    outstanding = total - paid
    if outstanding <= 0:
        raise AccountingError(
            STATE, f"Invoice {invoice['invoice_number']} has no outstanding balance"
        )
    if payment > outstanding:
        raise AccountingError(
            VALIDATION,
            f"Payment {fmt(payment)} exceeds outstanding balance {fmt(outstanding)}",
        )

    bank_account_id = args.get("bankAccountId")
    if not isinstance(bank_account_id, str) or bank_account_id.strip() == "":
        raise AccountingError(VALIDATION, "bankAccountId is required")
    bank = store.account_by_id(company["id"], bank_account_id.strip())
    if bank is None:
        raise AccountingError(NOT_FOUND, f"Account {bank_account_id} not found")
    if bank["type"] != "ASSET":
        raise AccountingError(VALIDATION, "Bank account must be an ASSET account")

    receivable = _require_account(company, "Accounts Receivable", "ASSET")
    new_paid = add(paid, payment)
    fully_paid = new_paid == total
    status = "PAID" if fully_paid else "SENT"
    payment_date = parse_required_date(args.get("date"), "payment date", default_today=True)

    updated = store.update_invoice_payment(
        company["id"], invoice["id"], amount_paid=fmt(new_paid), status=status
    )

    journal = propose_entry(
        company,
        date=payment_date,
        memo=f"Payment for invoice {invoice['invoice_number']}",
        lines=[
            {"accountId": bank["id"], "debit": fmt(payment)},
            {"accountId": receivable["id"], "credit": fmt(payment)},
        ],
    )

    return {
        "invoice": _invoice_payload(updated),
        "journal": journal,
        "note": "The receipt journal is PENDING; approve it with approve_journal.",
    }


# ---------------------------------------------------------------------------
# 18. AR aging
# ---------------------------------------------------------------------------


def _ar_aging(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    as_of_raw = args.get("asOf")
    if as_of_raw is None or as_of_raw == "":
        as_of = datetime.now(UTC).date()
    else:
        as_of = date.fromisoformat(parse_required_date(as_of_raw, "asOf"))

    buckets = {key: {"count": 0, "total": ZERO} for key, _label in AGING_BUCKETS}
    total_outstanding = ZERO
    rows: list[dict[str, Any]] = []

    for invoice in store.list_invoices(company["id"]):
        if invoice["status"] == "PAID":
            continue
        total = Decimal(invoice["total_amount"])
        paid = Decimal(invoice["amount_paid"])
        outstanding = total - paid
        if outstanding <= 0:
            continue

        due = date.fromisoformat(invoice["due_date"])
        days_past_due = (as_of - due).days
        bucket = _bucket_for(days_past_due)
        buckets[bucket]["count"] += 1
        buckets[bucket]["total"] = add(buckets[bucket]["total"], outstanding)
        total_outstanding = add(total_outstanding, outstanding)

        subtotal = (
            add(*(Decimal(line["total"]) for line in invoice["lines"]))
            if invoice["lines"]
            else ZERO
        )
        rows.append(
            {
                "invoiceId": invoice["id"],
                "invoiceNumber": invoice["invoice_number"],
                "customer": invoice["customer"],
                "date": invoice["date"],
                "dueDate": invoice["due_date"],
                "total": fmt(total),
                "amountPaid": fmt(paid),
                "outstanding": fmt(outstanding),
                "subtotal": fmt(subtotal),
                "vat": fmt(total - subtotal),
                "daysPastDue": days_past_due,
                "bucket": bucket,
            }
        )

    return {
        "asOf": as_of.isoformat(),
        "buckets": [
            {
                "key": key,
                "label": label,
                "count": buckets[key]["count"],
                "total": fmt(buckets[key]["total"]),
            }
            for key, label in AGING_BUCKETS
        ],
        "totalOutstanding": fmt(total_outstanding),
        "invoices": rows,
    }


# ---------------------------------------------------------------------------
# tool definitions
# ---------------------------------------------------------------------------

_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; requests without it fail with NO_ORGANIZATION.",
}
_DATE = {"type": "string", "description": "ISO date (YYYY-MM-DD)."}


def sales_tools() -> list[Tool]:
    return [
        Tool(
            name="get_customers",
            description="List all customers alphabetically. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_customers, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_customer",
            description="Create a customer. Name is required; email and phone are optional.",
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "name": {"type": "string", "minLength": 1},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_customer, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_invoices",
            description=(
                "List sales invoices with customer, status, total, amount paid and outstanding "
                "balance. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_invoices, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_invoice",
            description=(
                "Create a sales invoice for a customer. Adds 7.5% VAT and raises a PENDING "
                "accounts-receivable / sales-revenue / VAT-payable journal (plus a PENDING "
                "COGS / inventory journal for item-linked lines that carry a cost). Balances "
                "change only after approve_journal. Omit unitPrice to use the catalog price."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "customerId": {"type": "string", "minLength": 1},
                    "date": _DATE,
                    "dueDate": _DATE,
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "itemId": {"type": "string"},
                                "description": {"type": "string"},
                                "quantity": {"type": "number", "exclusiveMinimum": 0},
                                "unitPrice": {
                                    "type": "string",
                                    "description": "Decimal string; defaults to the catalog price.",
                                },
                            },
                            "required": ["quantity"],
                        },
                    },
                },
                "required": ["customerId", "date", "items"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_invoice, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="record_invoice_payment",
            description=(
                "Record a receipt against an invoice and raise a PENDING cash / "
                "accounts-receivable journal. Rejects overpayment and non-asset accounts. "
                "Balances change only after approve_journal."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "invoiceId": {"type": "string", "minLength": 1},
                    "amount": {"type": "string", "description": 'Decimal string, e.g. "500.00".'},
                    "bankAccountId": {
                        "type": "string",
                        "description": "ASSET account id to debit (Cash or Bank).",
                    },
                    "date": _DATE,
                },
                "required": ["invoiceId", "amount", "bankAccountId"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_record_invoice_payment, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_ar_aging",
            description=(
                "Accounts-receivable aging as of a date: current / 1-30 / 31-60 / 61-90 / 90+ "
                "buckets plus each outstanding invoice. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY, "asOf": _DATE},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_ar_aging, args),
            permission=PERMISSION_READ,
        ),
    ]


def register_sales_tools(registry: ToolRegistry) -> None:
    for tool in sales_tools():
        registry.register(tool)
