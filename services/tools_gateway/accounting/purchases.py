"""Purchases tools (Batch 3: inventory rows 19-25).

Bills and bill payments only ever raise PENDING journals through
``ledger.propose_entry``; nothing here posts. VAT is 7.5% on the line
subtotal; WHT is withheld at a 0-100% rate on the same subtotal and reduces
what is actually payable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
from tools_gateway.accounting.ledger import (
    propose_entry,
)
from tools_gateway.accounting.money import ZERO, add, fmt, to_money, to_quantity
from tools_gateway.registry import PERMISSION_READ, PERMISSION_WRITE, Tool, ToolRegistry

VAT_RATE = Decimal("7.5")
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


def _require_account(company: dict[str, Any], name: str, account_type: str) -> dict[str, Any]:
    account = store.account_by_name(company["id"], name)
    if account is None or account["type"] != account_type:
        raise AccountingError(NOT_FOUND, f"Required account {name!r} ({account_type}) is missing")
    return account


def _bill_expense_account(company: dict[str, Any]) -> dict[str, Any]:
    preferred = store.account_by_name(company["id"], "Office Supplies Expense")
    if preferred is not None and preferred["type"] == "EXPENSE":
        return preferred
    for account in store.list_accounts(company["id"]):
        if account["type"] == "EXPENSE":
            return account
    raise AccountingError(NOT_FOUND, "No expense account is configured for bills")


def _bill_payload(bill: dict[str, Any]) -> dict[str, Any]:
    total = Decimal(bill["total_amount"])
    paid = Decimal(bill["amount_paid"])
    net_payable = Decimal(bill["net_payable"])
    subtotal = add(*(Decimal(line["total"]) for line in bill["lines"])) if bill["lines"] else ZERO
    return {
        "id": bill["id"],
        "billNumber": bill["bill_number"],
        "vendorId": bill["vendor_id"],
        "vendor": bill["vendor"],
        "date": bill["date"],
        "dueDate": bill["due_date"],
        "status": bill["status"],
        "lines": [
            {
                "id": line["id"],
                "description": line["description"],
                "quantity": line["quantity"],
                "unitCost": line["unit_cost"],
                "total": line["total"],
            }
            for line in bill["lines"]
        ],
        "subtotal": fmt(subtotal),
        "vatRate": bill["vat_rate"],
        "vatAmount": bill["vat_amount"],
        "total": fmt(total),
        "whtRate": bill["wht_rate"],
        "whtAmount": bill["wht_amount"],
        "netPayable": fmt(net_payable),
        "amountPaid": fmt(paid),
        "outstanding": fmt(net_payable - paid),
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
# 19. vendors
# ---------------------------------------------------------------------------


def _get_vendors(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    vendors = [
        {"id": row["id"], "name": row["name"], "email": row["email"], "phone": row["phone"]}
        for row in store.list_vendors(company["id"])
    ]
    return {"vendors": vendors, "count": len(vendors)}


# ---------------------------------------------------------------------------
# 20. create vendor
# ---------------------------------------------------------------------------


def _create_vendor(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise AccountingError(VALIDATION, "Vendor name is required")
    email = args.get("email")
    phone = args.get("phone")
    vendor = store.insert_vendor(
        company["id"],
        name=name.strip(),
        email=email.strip() if isinstance(email, str) and email.strip() else None,
        phone=phone.strip() if isinstance(phone, str) and phone.strip() else None,
    )
    return {
        "id": vendor["id"],
        "name": vendor["name"],
        "email": vendor["email"],
        "phone": vendor["phone"],
    }


# ---------------------------------------------------------------------------
# 21. bills
# ---------------------------------------------------------------------------


def _get_bills(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    bills = [_bill_payload(bill) for bill in store.list_bills(company["id"])]
    return {"bills": bills, "count": len(bills)}


# ---------------------------------------------------------------------------
# 22. create bill
# ---------------------------------------------------------------------------


def _create_bill(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    raw_items = args.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AccountingError(VALIDATION, "Bill must contain at least one line item")

    vendor_id = args.get("vendorId")
    if not isinstance(vendor_id, str) or vendor_id.strip() == "":
        raise AccountingError(VALIDATION, "vendorId is required")
    vendor = store.get_vendor(company["id"], vendor_id.strip())
    if vendor is None:
        raise AccountingError(NOT_FOUND, f"Vendor {vendor_id} not found")

    bill_date = parse_required_date(args.get("date"), "bill date")
    due_date = parse_optional_date(args.get("dueDate"), "bill due date")
    if due_date is None:
        due_date = (date.fromisoformat(bill_date) + timedelta(days=30)).isoformat()

    resolved: list[dict[str, Any]] = []
    subtotal = ZERO
    for index, raw in enumerate(raw_items, start=1):
        label = f"Line {index}"
        if not isinstance(raw, dict):
            raise AccountingError(VALIDATION, f"{label}: must be an object")
        description = raw.get("description")
        if not isinstance(description, str) or description.strip() == "":
            raise AccountingError(VALIDATION, f"{label}: description is required")
        quantity = to_quantity(raw.get("quantity"), f"{label} quantity")
        unit_cost = to_money(raw.get("unitCost"), f"{label} unitCost")
        line_total = (unit_cost * quantity).quantize(Decimal("0.01"))
        subtotal = add(subtotal, line_total)
        resolved.append(
            {
                "description": description.strip(),
                "quantity": quantity,
                "unitCost": unit_cost,
                "total": line_total,
            }
        )

    if subtotal <= 0:
        raise AccountingError(VALIDATION, "Bill total must be greater than zero")

    vat_rate = VAT_RATE
    vat_amount = (subtotal * vat_rate / Decimal(100)).quantize(Decimal("0.01"))
    total = subtotal + vat_amount

    wht_rate = to_money(args.get("whtRate") if args.get("whtRate") is not None else "0", "WHT rate")
    if wht_rate < 0 or wht_rate > 100:
        raise AccountingError(VALIDATION, "WHT rate must be between 0 and 100")
    wht_amount = (subtotal * wht_rate / Decimal(100)).quantize(Decimal("0.01"))
    net_payable = total - wht_amount

    expense = _bill_expense_account(company)
    payable = _require_account(company, "Accounts Payable", "LIABILITY")
    vat_input = _require_account(company, "VAT Input", "ASSET") if vat_amount > 0 else None
    wht_payable = _require_account(company, "WHT Payable", "LIABILITY") if wht_amount > 0 else None

    bill = store.insert_bill(
        company["id"],
        number=store.next_bill_number(company["id"]),
        vendor_id=vendor["id"],
        date=bill_date,
        due_date=due_date,
        status="RECEIVED",
        total=fmt(total),
        vat_rate=fmt(vat_rate),
        vat_amount=fmt(vat_amount),
        wht_rate=fmt(wht_rate),
        wht_amount=fmt(wht_amount),
        net_payable=fmt(net_payable),
        lines=[
            (
                line["description"],
                str(line["quantity"]),
                fmt(line["unitCost"]),
                fmt(line["total"]),
            )
            for line in resolved
        ],
    )

    journal = propose_entry(
        company,
        date=bill_date,
        memo=f"Bill {bill['bill_number']} - {vendor['name']}",
        lines=[
            {"accountId": expense["id"], "debit": fmt(subtotal)},
            *(
                [{"accountId": vat_input["id"], "debit": fmt(vat_amount)}]
                if vat_input is not None
                else []
            ),
            {"accountId": payable["id"], "credit": fmt(net_payable)},
            *(
                [{"accountId": wht_payable["id"], "credit": fmt(wht_amount)}]
                if wht_payable is not None
                else []
            ),
        ],
    )

    return {
        "bill": _bill_payload(bill),
        "journal": journal,
        "note": "The bill journal is PENDING; approve it with approve_journal.",
    }


# ---------------------------------------------------------------------------
# 23. record bill payment
# ---------------------------------------------------------------------------


def _record_bill_payment(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    bill_id = args.get("billId")
    if not isinstance(bill_id, str) or bill_id.strip() == "":
        raise AccountingError(VALIDATION, "billId is required")

    payment = to_money(args.get("amount"), "amount")
    if payment <= 0:
        raise AccountingError(VALIDATION, "Payment amount must be greater than zero")

    bill = store.get_bill(company["id"], bill_id.strip())
    if bill is None:
        raise AccountingError(NOT_FOUND, f"Bill {bill_id} not found")
    if bill["status"] == "PAID":
        raise AccountingError(STATE, f"Bill {bill['bill_number']} is already paid")

    net_payable = Decimal(bill["net_payable"])
    paid = Decimal(bill["amount_paid"])
    outstanding = net_payable - paid
    if outstanding <= 0:
        raise AccountingError(STATE, f"Bill {bill['bill_number']} has no outstanding balance")
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

    payable = _require_account(company, "Accounts Payable", "LIABILITY")
    new_paid = add(paid, payment)
    fully_paid = new_paid == net_payable
    status = "PAID" if fully_paid else "RECEIVED"
    payment_date = parse_required_date(args.get("date"), "payment date", default_today=True)

    updated = store.update_bill_payment(
        company["id"], bill["id"], amount_paid=fmt(new_paid), status=status
    )

    journal = propose_entry(
        company,
        date=payment_date,
        memo=f"Payment for bill {bill['bill_number']}",
        lines=[
            {"accountId": payable["id"], "debit": fmt(payment)},
            {"accountId": bank["id"], "credit": fmt(payment)},
        ],
    )

    return {
        "bill": _bill_payload(updated),
        "journal": journal,
        "note": "The payment journal is PENDING; approve it with approve_journal.",
    }


# ---------------------------------------------------------------------------
# 24. AP aging
# ---------------------------------------------------------------------------


def _ap_aging(company: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    as_of_raw = args.get("asOf")
    if as_of_raw is None or as_of_raw == "":
        as_of = datetime.now(UTC).date()
    else:
        as_of = date.fromisoformat(parse_required_date(as_of_raw, "asOf"))

    buckets = {key: {"count": 0, "total": ZERO} for key, _label in AGING_BUCKETS}
    total_outstanding = ZERO
    rows: list[dict[str, Any]] = []
    vendor_totals: dict[str, dict[str, Decimal]] = {}

    for bill in store.list_bills(company["id"]):
        if bill["status"] == "PAID":
            continue
        # Matches the core: aging is measured on the billed total, WHT aside.
        total = Decimal(bill["total_amount"])
        paid = Decimal(bill["amount_paid"])
        outstanding = total - paid
        if outstanding <= 0:
            continue

        due = date.fromisoformat(bill["due_date"])
        days_past_due = (as_of - due).days
        bucket = _bucket_for(days_past_due)
        buckets[bucket]["count"] += 1
        buckets[bucket]["total"] = add(buckets[bucket]["total"], outstanding)
        total_outstanding = add(total_outstanding, outstanding)

        vendor = bill["vendor"] or ""
        row = vendor_totals.setdefault(
            vendor,
            {
                "total": ZERO,
                "current": ZERO,
                "1-30": ZERO,
                "31-60": ZERO,
                "60+": ZERO,
            },
        )
        row["total"] = add(row["total"], outstanding)
        if bucket == "current":
            row["current"] = add(row["current"], outstanding)
        elif bucket == "1-30":
            row["1-30"] = add(row["1-30"], outstanding)
        elif bucket == "31-60":
            row["31-60"] = add(row["31-60"], outstanding)
        else:
            row["60+"] = add(row["60+"], outstanding)

        rows.append(
            {
                "billId": bill["id"],
                "billNumber": bill["bill_number"],
                "vendor": vendor,
                "date": bill["date"],
                "dueDate": bill["due_date"],
                "total": fmt(total),
                "amountPaid": fmt(paid),
                "outstanding": fmt(outstanding),
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
        "bills": rows,
        "vendors": [
            {
                "vendor": vendor,
                "totalOutstanding": fmt(values["total"]),
                "current": fmt(values["current"]),
                "1-30": fmt(values["1-30"]),
                "31-60": fmt(values["31-60"]),
                "60+": fmt(values["60+"]),
            }
            for vendor, values in vendor_totals.items()
        ],
    }


# ---------------------------------------------------------------------------
# 25. WHT summary
# ---------------------------------------------------------------------------


def _wht_summary(company: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    debit, credit = store.account_movement(company["id"], "WHT Payable")
    return {"whtPayable": fmt(credit - debit), "debit": fmt(debit), "credit": fmt(credit)}


# ---------------------------------------------------------------------------
# tool definitions
# ---------------------------------------------------------------------------

_COMPANY = {
    "type": "string",
    "description": "Tenant (business) id. Required; requests without it fail with NO_ORGANIZATION.",
}
_DATE = {"type": "string", "description": "ISO date (YYYY-MM-DD)."}


def purchases_tools() -> list[Tool]:
    return [
        Tool(
            name="get_vendors",
            description="List all vendors alphabetically. Read-only.",
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_vendors, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_vendor",
            description="Create a vendor. Name is required; email and phone are optional.",
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
            func=lambda **args: run_tool(_create_vendor, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_bills",
            description=(
                "List purchase bills with vendor, VAT, WHT withheld, net payable, amount paid "
                "and outstanding balance. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_get_bills, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="create_bill",
            description=(
                "Create a purchase bill. VAT is 7.5% of the line subtotal; WHT is withheld at "
                "whtRate percent (0-100) of the same subtotal and reduces netPayable. Raises a "
                "PENDING journal (debit expense + VAT input, credit accounts payable + WHT "
                "payable). Balances change only after approve_journal."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "vendorId": {"type": "string", "minLength": 1},
                    "date": _DATE,
                    "dueDate": _DATE,
                    "whtRate": {
                        "type": "number",
                        "description": "Withholding-tax rate as a percentage (0-100).",
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "description": {"type": "string", "minLength": 1},
                                "quantity": {"type": "number", "exclusiveMinimum": 0},
                                "unitCost": {"type": "string"},
                            },
                            "required": ["description", "quantity", "unitCost"],
                        },
                    },
                },
                "required": ["vendorId", "date", "items"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_create_bill, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="record_bill_payment",
            description=(
                "Record a payment against a bill and raise a PENDING accounts-payable / bank "
                "journal. The payable is netPayable (after WHT). Rejects overpayment and "
                "non-asset accounts. Balances change only after approve_journal."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "companyId": _COMPANY,
                    "billId": {"type": "string", "minLength": 1},
                    "amount": {"type": "string"},
                    "bankAccountId": {"type": "string", "minLength": 1},
                    "date": _DATE,
                },
                "required": ["billId", "amount", "bankAccountId"],
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_record_bill_payment, args),
            permission=PERMISSION_WRITE,
        ),
        Tool(
            name="get_ap_aging",
            description=(
                "Accounts-payable aging as of a date: current / 1-30 / 31-60 / 61-90 / 90+ "
                "buckets, each outstanding bill and per-vendor totals. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY, "asOf": _DATE},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_ap_aging, args),
            permission=PERMISSION_READ,
        ),
        Tool(
            name="get_wht_summary",
            description=(
                "Withholding tax held on vendor bills: credit minus debit on the WHT Payable "
                "account, across pending and posted journals. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {"companyId": _COMPANY},
                "additionalProperties": False,
            },
            func=lambda **args: run_tool(_wht_summary, args),
            permission=PERMISSION_READ,
        ),
    ]


def register_purchases_tools(registry: ToolRegistry) -> None:
    for tool in purchases_tools():
        registry.register(tool)
