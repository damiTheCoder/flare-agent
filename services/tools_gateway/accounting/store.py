"""SQLite persistence for the accounting tools.

One database file holds every tenant; every row carries ``company_id`` and
every query filters on it, so a tool can never read or write another
company's books. A tenant is provisioned with a standard chart of accounts
the first time it is used (the old core did the same via its seed).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools_gateway.accounting.errors import (
    NO_ORGANIZATION,
    UNAUTHORIZED,
    AccountingError,
)

# code, name, type, category
CHART_OF_ACCOUNTS: tuple[tuple[str, str, str, str], ...] = (
    ("1010", "Cash", "ASSET", "Current Assets"),
    ("1020", "Bank", "ASSET", "Current Assets"),
    ("1100", "Accounts Receivable", "ASSET", "Current Assets"),
    ("1110", "VAT Input", "ASSET", "Current Assets"),
    ("1200", "Inventory", "ASSET", "Current Assets"),
    ("1500", "Fixed Assets", "ASSET", "Fixed Assets"),
    ("1510", "Accumulated Depreciation", "ASSET", "Fixed Assets"),
    ("2010", "Accounts Payable", "LIABILITY", "Current Liabilities"),
    ("2100", "VAT Payable", "LIABILITY", "Current Liabilities"),
    ("2110", "WHT Payable", "LIABILITY", "Current Liabilities"),
    ("2200", "Long-term Loans", "LIABILITY", "Long-term Liabilities"),
    ("2210", "PAYE Payable", "LIABILITY", "Current Liabilities"),
    ("2220", "Pension Payable", "LIABILITY", "Current Liabilities"),
    ("2230", "NHF Payable", "LIABILITY", "Current Liabilities"),
    ("2240", "Net Salaries Payable", "LIABILITY", "Current Liabilities"),
    ("2250", "Employee Reimbursement Payable", "LIABILITY", "Current Liabilities"),
    ("3000", "Share Capital", "EQUITY", "Equity"),
    ("3100", "Retained Earnings", "EQUITY", "Equity"),
    ("4000", "Sales Revenue", "REVENUE", "Operating Revenue"),
    ("4900", "Inventory Adjustment", "REVENUE", "Other Revenue"),
    ("4910", "Gain on Asset Disposal", "REVENUE", "Other Revenue"),
    ("5000", "Cost of Goods Sold", "EXPENSE", "Cost of Sales"),
    ("5100", "Salaries Expense", "EXPENSE", "Operating Expenses"),
    ("5200", "Rent", "EXPENSE", "Operating Expenses"),
    ("5300", "Depreciation Expense", "EXPENSE", "Operating Expenses"),
    ("5400", "Office Supplies Expense", "EXPENSE", "Operating Expenses"),
    ("5500", "Interest Expense", "EXPENSE", "Operating Expenses"),
    ("5600", "Loss on Asset Disposal", "EXPENSE", "Operating Expenses"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id         TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,
    category   TEXT NOT NULL,
    is_system  INTEGER NOT NULL DEFAULT 0,
    balance    TEXT NOT NULL DEFAULT '0.00',
    UNIQUE (company_id, code),
    UNIQUE (company_id, name)
);
CREATE INDEX IF NOT EXISTS idx_accounts_company ON accounts (company_id);
CREATE TABLE IF NOT EXISTS journal_entries (
    id         TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    date       TEXT NOT NULL,
    memo       TEXT,
    status     TEXT NOT NULL DEFAULT 'PENDING',
    is_locked  INTEGER NOT NULL DEFAULT 0,
    locked_at  TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_company_date ON journal_entries (company_id, date);
CREATE INDEX IF NOT EXISTS idx_entries_company_status ON journal_entries (company_id, status);
CREATE TABLE IF NOT EXISTS journal_lines (
    id         TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    entry_id   TEXT NOT NULL,
    account_id TEXT NOT NULL,
    debit      TEXT NOT NULL DEFAULT '0.00',
    credit     TEXT NOT NULL DEFAULT '0.00'
);
CREATE INDEX IF NOT EXISTS idx_lines_entry ON journal_lines (entry_id);
CREATE INDEX IF NOT EXISTS idx_lines_account ON journal_lines (company_id, account_id);
CREATE TABLE IF NOT EXISTS customers (
    id         TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    email      TEXT,
    phone      TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_company ON customers (company_id, name);
CREATE TABLE IF NOT EXISTS items (
    id             TEXT PRIMARY KEY,
    company_id     TEXT NOT NULL,
    name           TEXT NOT NULL,
    sku            TEXT,
    price          TEXT NOT NULL DEFAULT '0.00',
    cost           TEXT NOT NULL DEFAULT '0.00',
    stock_quantity INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_company ON items (company_id, name);
CREATE TABLE IF NOT EXISTS sales_invoices (
    id             TEXT PRIMARY KEY,
    company_id     TEXT NOT NULL,
    customer_id    TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    date           TEXT NOT NULL,
    due_date       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'DRAFT',
    total_amount   TEXT NOT NULL DEFAULT '0.00',
    amount_paid    TEXT NOT NULL DEFAULT '0.00',
    created_at     TEXT NOT NULL,
    UNIQUE (company_id, invoice_number)
);
CREATE INDEX IF NOT EXISTS idx_invoices_company ON sales_invoices (company_id, date);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id          TEXT PRIMARY KEY,
    company_id  TEXT NOT NULL,
    invoice_id  TEXT NOT NULL,
    item_id     TEXT,
    description TEXT NOT NULL,
    quantity    TEXT NOT NULL,
    unit_price  TEXT NOT NULL,
    total       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines (invoice_id);
CREATE TABLE IF NOT EXISTS vendors (
    id         TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    email      TEXT,
    phone      TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vendors_company ON vendors (company_id, name);
CREATE TABLE IF NOT EXISTS purchase_bills (
    id            TEXT PRIMARY KEY,
    company_id    TEXT NOT NULL,
    vendor_id     TEXT NOT NULL,
    bill_number   TEXT NOT NULL,
    date          TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'RECEIVED',
    total_amount  TEXT NOT NULL DEFAULT '0.00',
    vat_rate      TEXT NOT NULL DEFAULT '7.50',
    vat_amount    TEXT NOT NULL DEFAULT '0.00',
    amount_paid   TEXT NOT NULL DEFAULT '0.00',
    wht_rate      TEXT NOT NULL DEFAULT '0.00',
    wht_amount    TEXT NOT NULL DEFAULT '0.00',
    net_payable   TEXT NOT NULL DEFAULT '0.00',
    created_at    TEXT NOT NULL,
    UNIQUE (company_id, bill_number)
);
CREATE INDEX IF NOT EXISTS idx_bills_company ON purchase_bills (company_id, date);
CREATE TABLE IF NOT EXISTS bill_lines (
    id          TEXT PRIMARY KEY,
    company_id  TEXT NOT NULL,
    bill_id     TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity    TEXT NOT NULL,
    unit_cost   TEXT NOT NULL,
    total       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bill_lines_bill ON bill_lines (bill_id);
CREATE TABLE IF NOT EXISTS bank_transactions (
    id                 TEXT PRIMARY KEY,
    company_id         TEXT NOT NULL,
    date               TEXT NOT NULL,
    description        TEXT NOT NULL,
    amount             TEXT NOT NULL,
    type               TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'UNRECONCILED',
    matched_invoice_id TEXT,
    matched_bill_id    TEXT,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bank_txn_company ON bank_transactions (company_id, status);
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL, email TEXT,
    basic_salary TEXT NOT NULL DEFAULT '0.00', housing_allowance TEXT NOT NULL DEFAULT '0.00',
    transport_allowance TEXT NOT NULL DEFAULT '0.00', is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payroll_runs (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, month TEXT NOT NULL, year INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT', total_gross TEXT NOT NULL DEFAULT '0.00',
    total_net TEXT NOT NULL DEFAULT '0.00', total_paye TEXT NOT NULL DEFAULT '0.00',
    total_pension TEXT NOT NULL DEFAULT '0.00', total_nhf TEXT NOT NULL DEFAULT '0.00',
    created_at TEXT NOT NULL, UNIQUE (company_id, month, year)
);
CREATE TABLE IF NOT EXISTS expense_categories (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE (company_id, name)
);
CREATE TABLE IF NOT EXISTS expenses (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, date TEXT NOT NULL,
    description TEXT NOT NULL, amount TEXT NOT NULL, category_id TEXT NOT NULL,
    employee_id TEXT, payment_method TEXT NOT NULL, status TEXT NOT NULL,
    journal_entry_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fixed_assets (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
    purchase_date TEXT NOT NULL, cost TEXT NOT NULL,
    useful_life_years INTEGER NOT NULL, salvage_value TEXT NOT NULL DEFAULT '0.00',
    accumulated_depreciation TEXT NOT NULL DEFAULT '0.00',
    is_disposed INTEGER NOT NULL DEFAULT 0, disposal_date TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_lines (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, budget_id TEXT NOT NULL,
    account_id TEXT NOT NULL, amount TEXT NOT NULL DEFAULT '0.00',
    period TEXT NOT NULL DEFAULT 'ANNUAL'
);
CREATE TABLE IF NOT EXISTS equity_transactions (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, type TEXT NOT NULL,
    amount TEXT NOT NULL, date TEXT NOT NULL, description TEXT NOT NULL,
    journal_entry_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS loans (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, lender_name TEXT NOT NULL,
    principal_amount TEXT NOT NULL, interest_rate TEXT NOT NULL, start_date TEXT NOT NULL,
    term_months INTEGER NOT NULL, balance TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS loan_repayments (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, loan_id TEXT NOT NULL, date TEXT NOT NULL,
    principal_paid TEXT NOT NULL, interest_paid TEXT NOT NULL, total_paid TEXT NOT NULL,
    journal_entry_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL, client_id TEXT,
    budget TEXT NOT NULL DEFAULT '0.00', start_date TEXT NOT NULL, end_date TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_transactions (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, project_id TEXT NOT NULL, date TEXT NOT NULL,
    description TEXT NOT NULL, amount TEXT NOT NULL, type TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_profiles (
    company_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', logo_url TEXT,
    currency TEXT NOT NULL DEFAULT 'NGN', fiscal_year_start TEXT NOT NULL DEFAULT 'January',
    vat_rate TEXT NOT NULL DEFAULT '7.50', wht_rate_company TEXT NOT NULL DEFAULT '10.00',
    wht_rate_individual TEXT NOT NULL DEFAULT '5.00', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, filename TEXT NOT NULL,
    original_name TEXT NOT NULL, mime_type TEXT NOT NULL, content TEXT NOT NULL,
    uploaded_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
    source TEXT NOT NULL DEFAULT 'UPLOAD', extracted_data TEXT
);
CREATE TABLE IF NOT EXISTS integrations (
    company_id TEXT PRIMARY KEY, drive INTEGER NOT NULL DEFAULT 0,
    gmail INTEGER NOT NULL DEFAULT 0, drive_refresh_token TEXT, drive_email TEXT,
    drive_sync_schedule TEXT NOT NULL DEFAULT 'MANUAL', gmail_refresh_token TEXT,
    gmail_email TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_counters (
    company_id TEXT NOT NULL, month TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0, cached_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (company_id, month)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL, user_id TEXT NOT NULL,
    action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    before TEXT, after TEXT, created_at TEXT NOT NULL
);
"""

_connection: sqlite3.Connection | None = None
_override_path: str | None = None
_lock = threading.Lock()


def _default_path() -> Path:
    configured = os.environ.get("FLARE_ACCOUNTING_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[3] / ".data" / "accounting.db"


def connect() -> sqlite3.Connection:
    """Return the process-wide connection, creating the schema on first use."""
    global _connection
    with _lock:
        if _connection is None:
            path = Path(_override_path) if _override_path else _default_path()
            if str(path) != ":memory:":
                path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.executescript(_SCHEMA)
            connection.commit()
            _connection = connection
        return _connection


def reset_for_tests(path: str) -> None:
    """Point the module at a fresh database (tests only)."""
    global _connection, _override_path
    with _lock:
        if _connection is not None:
            _connection.close()
        _connection = None
        _override_path = path


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _allowed_tenants() -> set[str] | None:
    raw = os.environ.get("FLARE_ACCOUNTING_TENANTS", "").strip()
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def resolve_tenant(company_id: object) -> dict[str, Any]:
    """Validate the tenant id and provision it on first use.

    ``companyId`` empty/absent -> NO_ORGANIZATION. A tenant that exists but is
    outside the configured allow-list -> UNAUTHORIZED.
    """
    if not isinstance(company_id, str) or company_id.strip() == "":
        raise AccountingError(
            NO_ORGANIZATION,
            "companyId is required: sign in or select a business first",
        )
    tenant = company_id.strip()
    allowed = _allowed_tenants()
    if allowed is not None and tenant not in allowed:
        raise AccountingError(UNAUTHORIZED, f"tenant {tenant!r} is not accessible")

    connection = connect()
    row = connection.execute("SELECT * FROM companies WHERE id = ?", (tenant,)).fetchone()
    if row is not None:
        return dict(row)

    with connection:  # transaction: company + chart appear together
        connection.execute(
            "INSERT INTO companies (id, name, created_at) VALUES (?, ?, ?)",
            (tenant, tenant, now_iso()),
        )
        for code, name, account_type, category in CHART_OF_ACCOUNTS:
            connection.execute(
                "INSERT INTO accounts (id, company_id, code, name, type, category, is_system)"
                " VALUES (?, ?, ?, ?, ?, ?, 1)",
                (new_id("acc"), tenant, code, name, account_type, category),
            )
    return {"id": tenant, "name": tenant, "created_at": now_iso()}


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def list_accounts(company_id: str) -> list[dict[str, Any]]:
    rows = (
        connect()
        .execute("SELECT * FROM accounts WHERE company_id = ? ORDER BY code", (company_id,))
        .fetchall()
    )
    return [dict(row) for row in rows]


def account_by_id(company_id: str, account_id: str) -> dict[str, Any] | None:
    row = (
        connect()
        .execute("SELECT * FROM accounts WHERE company_id = ? AND id = ?", (company_id, account_id))
        .fetchone()
    )
    return dict(row) if row is not None else None


def accounts_by_ids(company_id: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = (
        connect()
        .execute(
            f"SELECT * FROM accounts WHERE company_id = ? AND id IN ({placeholders})",
            (company_id, *ids),
        )
        .fetchall()
    )
    return {row["id"]: dict(row) for row in rows}


def get_entry(company_id: str, entry_id: str) -> dict[str, Any] | None:
    connection = connect()
    row = connection.execute(
        "SELECT * FROM journal_entries WHERE company_id = ? AND id = ?",
        (company_id, entry_id),
    ).fetchone()
    if row is None:
        return None
    lines = connection.execute(
        "SELECT * FROM journal_lines WHERE company_id = ? AND entry_id = ? ORDER BY id",
        (company_id, entry_id),
    ).fetchall()
    entry = dict(row)
    entry["lines"] = [dict(line) for line in lines]
    return entry


def list_entries(company_id: str, status: str | None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM journal_entries WHERE company_id = ?"
    params: list[Any] = [company_id]
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY date, created_at"
    entries = [dict(row) for row in connect().execute(sql, params).fetchall()]
    for entry in entries:
        lines = (
            connect()
            .execute(
                "SELECT * FROM journal_lines WHERE company_id = ? AND entry_id = ? ORDER BY id",
                (company_id, entry["id"]),
            )
            .fetchall()
        )
        entry["lines"] = [dict(line) for line in lines]
    return entries


def posted_lines(
    company_id: str,
    *,
    account_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    status: str | None = "POSTED",
) -> list[dict[str, Any]]:
    sql = (
        "SELECT l.id, l.entry_id, l.account_id, l.debit, l.credit,"
        " e.date, e.memo, e.status, a.code, a.name, a.type"
        " FROM journal_lines l"
        " JOIN journal_entries e ON e.id = l.entry_id"
        " JOIN accounts a ON a.id = l.account_id"
        " WHERE l.company_id = ?"
    )
    params: list[Any] = [company_id]
    if status is not None:
        sql += " AND e.status = ?"
        params.append(status)
    if account_id is not None:
        sql += " AND l.account_id = ?"
        params.append(account_id)
    if start is not None:
        sql += " AND e.date >= ?"
        params.append(start)
    if end is not None:
        sql += " AND e.date <= ?"
        params.append(end)
    sql += " ORDER BY e.date, e.id, l.id"
    return [dict(row) for row in connect().execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def insert_entry(
    company_id: str,
    *,
    date: str,
    memo: str | None,
    lines: list[tuple[str, str, str]],
) -> dict[str, Any]:
    """Create a PENDING entry and its lines atomically.

    ``lines`` is a list of (account_id, debit, credit) with money already
    formatted as two-decimal strings.
    """
    entry_id = new_id("je")
    connection = connect()
    with connection:
        connection.execute(
            "INSERT INTO journal_entries (id, company_id, date, memo, status, created_at)"
            " VALUES (?, ?, ?, ?, 'PENDING', ?)",
            (entry_id, company_id, date, memo, now_iso()),
        )
        for account_id, debit, credit in lines:
            connection.execute(
                "INSERT INTO journal_lines (id, company_id, entry_id, account_id, debit, credit)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("jl"), company_id, entry_id, account_id, debit, credit),
            )
    entry = get_entry(company_id, entry_id)
    assert entry is not None
    return entry


def claim_pending(company_id: str, entry_id: str) -> bool:
    """Atomically flip PENDING -> POSTED; False when another caller won."""
    connection = connect()
    with connection:
        cursor = connection.execute(
            "UPDATE journal_entries SET status = 'POSTED'"
            " WHERE company_id = ? AND id = ? AND status = 'PENDING'",
            (company_id, entry_id),
        )
    return cursor.rowcount == 1


def adjust_balance(company_id: str, account_id: str, delta: str) -> None:
    connection = connect()
    row = connection.execute(
        "SELECT balance FROM accounts WHERE company_id = ? AND id = ?",
        (company_id, account_id),
    ).fetchone()
    if row is None:
        return
    updated = (Decimal(row["balance"]) + Decimal(delta)).quantize(Decimal("0.01"))
    with connection:
        connection.execute(
            "UPDATE accounts SET balance = ? WHERE company_id = ? AND id = ?",
            (str(updated), company_id, account_id),
        )


def set_period_lock(company_id: str, start: str, end: str, locked: bool) -> int:
    connection = connect()
    with connection:
        if locked:
            cursor = connection.execute(
                "UPDATE journal_entries SET is_locked = 1, locked_at = ?"
                " WHERE company_id = ? AND date >= ? AND date <= ? AND is_locked = 0",
                (now_iso(), company_id, start, end),
            )
        else:
            cursor = connection.execute(
                "UPDATE journal_entries SET is_locked = 0, locked_at = NULL"
                " WHERE company_id = ? AND date >= ? AND date <= ? AND is_locked = 1",
                (company_id, start, end),
            )
    return cursor.rowcount


def locked_entries(company_id: str) -> list[dict[str, Any]]:
    rows = (
        connect()
        .execute(
            "SELECT date, locked_at FROM journal_entries" " WHERE company_id = ? AND is_locked = 1",
            (company_id,),
        )
        .fetchall()
    )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# accounts by seeded name
# ---------------------------------------------------------------------------


def account_by_name(company_id: str, name: str) -> dict[str, Any] | None:
    row = (
        connect()
        .execute("SELECT * FROM accounts WHERE company_id = ? AND name = ?", (company_id, name))
        .fetchone()
    )
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------


def insert_customer(
    company_id: str, *, name: str, email: str | None, phone: str | None
) -> dict[str, Any]:
    customer_id = new_id("cus")
    connection = connect()
    with connection:
        connection.execute(
            "INSERT INTO customers (id, company_id, name, email, phone, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (customer_id, company_id, name, email, phone, now_iso()),
        )
    row = connection.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return dict(row)


def list_customers(company_id: str) -> list[dict[str, Any]]:
    rows = (
        connect()
        .execute("SELECT * FROM customers WHERE company_id = ? ORDER BY name", (company_id,))
        .fetchall()
    )
    return [dict(row) for row in rows]


def get_customer(company_id: str, customer_id: str) -> dict[str, Any] | None:
    row = (
        connect()
        .execute(
            "SELECT * FROM customers WHERE company_id = ? AND id = ?", (company_id, customer_id)
        )
        .fetchone()
    )
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# items
# ---------------------------------------------------------------------------


def insert_item(
    company_id: str,
    *,
    name: str,
    sku: str | None,
    price: str,
    cost: str,
    stock_quantity: int,
) -> dict[str, Any]:
    item_id = new_id("itm")
    connection = connect()
    with connection:
        connection.execute(
            "INSERT INTO items (id, company_id, name, sku, price, cost, stock_quantity, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, company_id, name, sku, price, cost, stock_quantity, now_iso()),
        )
    row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return dict(row)


def list_items(company_id: str) -> list[dict[str, Any]]:
    rows = (
        connect()
        .execute("SELECT * FROM items WHERE company_id = ? ORDER BY name", (company_id,))
        .fetchall()
    )
    return [dict(row) for row in rows]


def get_item(company_id: str, item_id: str) -> dict[str, Any] | None:
    row = (
        connect()
        .execute("SELECT * FROM items WHERE company_id = ? AND id = ?", (company_id, item_id))
        .fetchone()
    )
    return dict(row) if row is not None else None


def items_by_ids(company_id: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = (
        connect()
        .execute(
            f"SELECT * FROM items WHERE company_id = ? AND id IN ({placeholders})",
            (company_id, *ids),
        )
        .fetchall()
    )
    return {row["id"]: dict(row) for row in rows}


def decrement_stock(company_id: str, item_id: str, units: int) -> None:
    if units <= 0:
        return
    connection = connect()
    with connection:
        connection.execute(
            "UPDATE items SET stock_quantity = stock_quantity - ?"
            " WHERE company_id = ? AND id = ?",
            (units, company_id, item_id),
        )


# ---------------------------------------------------------------------------
# sales invoices
# ---------------------------------------------------------------------------


def next_invoice_number(company_id: str) -> str:
    row = (
        connect()
        .execute("SELECT COUNT(*) AS total FROM sales_invoices WHERE company_id = ?", (company_id,))
        .fetchone()
    )
    return f"INV-{int(row['total']) + 1:04d}"


def insert_invoice(
    company_id: str,
    *,
    number: str,
    customer_id: str,
    date: str,
    due_date: str,
    total: str,
    lines: list[tuple[str | None, str, str, str, str]],
) -> dict[str, Any]:
    """Create a DRAFT invoice and its lines atomically."""
    invoice_id = new_id("inv")
    connection = connect()
    with connection:
        connection.execute(
            "INSERT INTO sales_invoices"
            " (id, company_id, customer_id, invoice_number, date, due_date, status,"
            "  total_amount, amount_paid, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', ?, '0.00', ?)",
            (invoice_id, company_id, customer_id, number, date, due_date, total, now_iso()),
        )
        for item_id, description, quantity, unit_price, line_total in lines:
            connection.execute(
                "INSERT INTO invoice_lines"
                " (id, company_id, invoice_id, item_id, description, quantity, unit_price, total)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("inl"),
                    company_id,
                    invoice_id,
                    item_id,
                    description,
                    quantity,
                    unit_price,
                    line_total,
                ),
            )
    invoice = get_invoice(company_id, invoice_id)
    assert invoice is not None
    return invoice


def get_invoice(company_id: str, invoice_id: str) -> dict[str, Any] | None:
    connection = connect()
    row = connection.execute(
        "SELECT * FROM sales_invoices WHERE company_id = ? AND id = ?",
        (company_id, invoice_id),
    ).fetchone()
    if row is None:
        return None
    invoice = dict(row)
    lines = connection.execute(
        "SELECT * FROM invoice_lines WHERE company_id = ? AND invoice_id = ? ORDER BY id",
        (company_id, invoice_id),
    ).fetchall()
    invoice["lines"] = [dict(line) for line in lines]
    customer = connection.execute(
        "SELECT name FROM customers WHERE company_id = ? AND id = ?",
        (company_id, invoice["customer_id"]),
    ).fetchone()
    invoice["customer"] = customer["name"] if customer is not None else None
    return invoice


def list_invoices(company_id: str) -> list[dict[str, Any]]:
    rows = (
        connect()
        .execute(
            "SELECT id FROM sales_invoices WHERE company_id = ?"
            " ORDER BY date DESC, created_at DESC",
            (company_id,),
        )
        .fetchall()
    )
    invoices = []
    for row in rows:
        invoice = get_invoice(company_id, row["id"])
        if invoice is not None:
            invoices.append(invoice)
    return invoices


def update_invoice_payment(
    company_id: str, invoice_id: str, *, amount_paid: str, status: str
) -> dict[str, Any]:
    connection = connect()
    with connection:
        connection.execute(
            "UPDATE sales_invoices SET amount_paid = ?, status = ?"
            " WHERE company_id = ? AND id = ?",
            (amount_paid, status, company_id, invoice_id),
        )
    invoice = get_invoice(company_id, invoice_id)
    assert invoice is not None
    return invoice


# ---------------------------------------------------------------------------
# vendors
# ---------------------------------------------------------------------------


def insert_vendor(
    company_id: str, *, name: str, email: str | None, phone: str | None
) -> dict[str, Any]:
    vendor_id = new_id("ven")
    connection = connect()
    with connection:
        connection.execute(
            "INSERT INTO vendors (id, company_id, name, email, phone, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (vendor_id, company_id, name, email, phone, now_iso()),
        )
    row = connection.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    return dict(row)


def list_vendors(company_id: str) -> list[dict[str, Any]]:
    rows = (
        connect()
        .execute("SELECT * FROM vendors WHERE company_id = ? ORDER BY name", (company_id,))
        .fetchall()
    )
    return [dict(row) for row in rows]


def get_vendor(company_id: str, vendor_id: str) -> dict[str, Any] | None:
    row = (
        connect()
        .execute("SELECT * FROM vendors WHERE company_id = ? AND id = ?", (company_id, vendor_id))
        .fetchone()
    )
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# purchase bills
# ---------------------------------------------------------------------------


def next_bill_number(company_id: str) -> str:
    row = (
        connect()
        .execute("SELECT COUNT(*) AS total FROM purchase_bills WHERE company_id = ?", (company_id,))
        .fetchone()
    )
    return f"BILL-{int(row['total']) + 1:04d}"


def insert_bill(
    company_id: str,
    *,
    number: str,
    vendor_id: str,
    date: str,
    due_date: str,
    status: str,
    total: str,
    vat_rate: str,
    vat_amount: str,
    wht_rate: str,
    wht_amount: str,
    net_payable: str,
    lines: list[tuple[str, str, str, str]],
) -> dict[str, Any]:
    """Create a bill and its lines atomically."""
    bill_id = new_id("bil")
    connection = connect()
    with connection:
        connection.execute(
            "INSERT INTO purchase_bills"
            " (id, company_id, vendor_id, bill_number, date, due_date, status,"
            "  total_amount, vat_rate, vat_amount, amount_paid, wht_rate, wht_amount,"
            "  net_payable, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '0.00', ?, ?, ?, ?)",
            (
                bill_id,
                company_id,
                vendor_id,
                number,
                date,
                due_date,
                status,
                total,
                vat_rate,
                vat_amount,
                wht_rate,
                wht_amount,
                net_payable,
                now_iso(),
            ),
        )
        for description, quantity, unit_cost, line_total in lines:
            connection.execute(
                "INSERT INTO bill_lines"
                " (id, company_id, bill_id, description, quantity, unit_cost, total)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("bll"),
                    company_id,
                    bill_id,
                    description,
                    quantity,
                    unit_cost,
                    line_total,
                ),
            )
    bill = get_bill(company_id, bill_id)
    assert bill is not None
    return bill


def get_bill(company_id: str, bill_id: str) -> dict[str, Any] | None:
    connection = connect()
    row = connection.execute(
        "SELECT * FROM purchase_bills WHERE company_id = ? AND id = ?",
        (company_id, bill_id),
    ).fetchone()
    if row is None:
        return None
    bill = dict(row)
    lines = connection.execute(
        "SELECT * FROM bill_lines WHERE company_id = ? AND bill_id = ? ORDER BY id",
        (company_id, bill_id),
    ).fetchall()
    bill["lines"] = [dict(line) for line in lines]
    vendor = connection.execute(
        "SELECT name FROM vendors WHERE company_id = ? AND id = ?",
        (company_id, bill["vendor_id"]),
    ).fetchone()
    bill["vendor"] = vendor["name"] if vendor is not None else None
    return bill


def list_bills(company_id: str) -> list[dict[str, Any]]:
    rows = (
        connect()
        .execute(
            "SELECT id FROM purchase_bills WHERE company_id = ?"
            " ORDER BY date DESC, created_at DESC",
            (company_id,),
        )
        .fetchall()
    )
    bills = []
    for row in rows:
        bill = get_bill(company_id, row["id"])
        if bill is not None:
            bills.append(bill)
    return bills


def update_bill_payment(
    company_id: str, bill_id: str, *, amount_paid: str, status: str
) -> dict[str, Any]:
    connection = connect()
    with connection:
        connection.execute(
            "UPDATE purchase_bills SET amount_paid = ?, status = ?"
            " WHERE company_id = ? AND id = ?",
            (amount_paid, status, company_id, bill_id),
        )
    bill = get_bill(company_id, bill_id)
    assert bill is not None
    return bill


def account_movement(company_id: str, account_name: str) -> tuple[Decimal, Decimal]:
    """Debit and credit totals for a named account across ALL journal statuses."""
    rows = (
        connect()
        .execute(
            "SELECT l.debit, l.credit FROM journal_lines l"
            " JOIN accounts a ON a.id = l.account_id"
            " WHERE l.company_id = ? AND a.name = ?",
            (company_id, account_name),
        )
        .fetchall()
    )
    debit = Decimal("0.00")
    credit = Decimal("0.00")
    for row in rows:
        debit += Decimal(row["debit"])
        credit += Decimal(row["credit"])
    return debit.quantize(Decimal("0.01")), credit.quantize(Decimal("0.01"))


def set_stock(company_id: str, item_id: str, quantity: int) -> dict[str, Any]:
    """Set on-hand units (callers validate that quantity stays non-negative)."""
    connection = connect()
    with connection:
        connection.execute(
            "UPDATE items SET stock_quantity = ? WHERE company_id = ? AND id = ?",
            (quantity, company_id, item_id),
        )
    item = get_item(company_id, item_id)
    assert item is not None
    return item


# ---------------------------------------------------------------------------
# bank transactions
# ---------------------------------------------------------------------------


def insert_bank_transaction(
    company_id: str,
    *,
    date: str,
    description: str,
    amount: str,
    txn_type: str,
) -> dict[str, Any]:
    txn_id = new_id("btx")
    connection = connect()
    with connection:
        connection.execute(
            "INSERT INTO bank_transactions"
            " (id, company_id, date, description, amount, type, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'UNRECONCILED', ?)",
            (txn_id, company_id, date, description, amount, txn_type, now_iso()),
        )
    row = connection.execute("SELECT * FROM bank_transactions WHERE id = ?", (txn_id,)).fetchone()
    return dict(row)


def get_bank_transaction(company_id: str, txn_id: str) -> dict[str, Any] | None:
    row = (
        connect()
        .execute(
            "SELECT * FROM bank_transactions WHERE company_id = ? AND id = ?",
            (company_id, txn_id),
        )
        .fetchone()
    )
    return dict(row) if row is not None else None


def list_bank_transactions(company_id: str, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM bank_transactions WHERE company_id = ?"
    params: list[Any] = [company_id]
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY date DESC, created_at DESC"
    rows = connect().execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def find_bank_match(
    company_id: str, *, invoice_id: str | None = None, bill_id: str | None = None
) -> dict[str, Any] | None:
    if invoice_id is not None:
        row = (
            connect()
            .execute(
                "SELECT * FROM bank_transactions"
                " WHERE company_id = ? AND matched_invoice_id = ? ORDER BY created_at LIMIT 1",
                (company_id, invoice_id),
            )
            .fetchone()
        )
    elif bill_id is not None:
        row = (
            connect()
            .execute(
                "SELECT * FROM bank_transactions"
                " WHERE company_id = ? AND matched_bill_id = ? ORDER BY created_at LIMIT 1",
                (company_id, bill_id),
            )
            .fetchone()
        )
    else:
        return None
    return dict(row) if row is not None else None


def mark_bank_reconciled(
    company_id: str,
    txn_id: str,
    *,
    invoice_id: str | None = None,
    bill_id: str | None = None,
) -> dict[str, Any]:
    connection = connect()
    with connection:
        connection.execute(
            "UPDATE bank_transactions"
            " SET status = 'RECONCILED', matched_invoice_id = ?, matched_bill_id = ?"
            " WHERE company_id = ? AND id = ?",
            (invoice_id, bill_id, company_id, txn_id),
        )
    txn = get_bank_transaction(company_id, txn_id)
    assert txn is not None
    return txn


# ---------------------------------------------------------------------------
# generic row helpers (table/column names are validated identifiers)
# ---------------------------------------------------------------------------

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
_COLUMNS: dict[str, set[str]] = {}


def _columns(table: str) -> set[str]:
    if not _IDENT.match(table):
        raise ValueError(f"invalid table name {table!r}")
    if table not in _COLUMNS:
        rows = connect().execute(f"PRAGMA table_info({table})").fetchall()
        _COLUMNS[table] = {row["name"] for row in rows}
    return _COLUMNS[table]


def _check(table: str, names: list[str]) -> None:
    known = _columns(table)
    for name in names:
        if not _IDENT.match(name) or name not in known:
            raise ValueError(f"unknown column {table}.{name}")


def insert_row(table: str, values: dict[str, Any]) -> dict[str, Any]:
    row = dict(values)
    known = _columns(table)
    if "id" in known:
        row.setdefault("id", new_id(table[:3]))
    # Every *_at column in this schema is a timestamp with no DB default.
    for column in known:
        if column.endswith("_at"):
            row.setdefault(column, now_iso())
    _check(table, list(row))
    connection = connect()
    with connection:
        connection.execute(
            f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
    # Return the persisted row so callers see DB defaults too.
    if "id" in known:
        stored = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (row["id"],)).fetchone()
    else:
        stored = connection.execute(
            f"SELECT * FROM {table} WHERE company_id = ?", (row["company_id"],)
        ).fetchone()
    return dict(stored) if stored is not None else row


def select_rows(
    table: str,
    company_id: str,
    where: dict[str, Any] | None = None,
    order_by: str | None = None,
) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM {table} WHERE company_id = ?"
    params: list[Any] = [company_id]
    for key, value in (where or {}).items():
        _check(table, [key])
        sql += f" AND {key} = ?"
        params.append(value)
    if order_by:
        for token in re.split(r"[\s,]+", order_by):
            if token and token.upper() not in ("ASC", "DESC"):
                _check(table, [token])
        sql += f" ORDER BY {order_by}"
    return [dict(row) for row in connect().execute(sql, params).fetchall()]


def select_one(table: str, company_id: str, where: dict[str, Any]) -> dict[str, Any] | None:
    rows = select_rows(table, company_id, where)
    return rows[0] if rows else None


def update_row(table: str, company_id: str, row_id: str, values: dict[str, Any]) -> dict[str, Any]:
    _check(table, list(values))
    if "updated_at" in _columns(table):
        values = {**values, "updated_at": now_iso()}
    assignments = ", ".join(f"{key} = ?" for key in values)
    key = "id" if "id" in _columns(table) else "company_id"
    connection = connect()
    with connection:
        connection.execute(
            f"UPDATE {table} SET {assignments} WHERE company_id = ? AND {key} = ?",
            (*values.values(), company_id, row_id),
        )
    row = (
        connect()
        .execute(
            f"SELECT * FROM {table} WHERE company_id = ? AND {key} = ?",
            (company_id, row_id),
        )
        .fetchone()
    )
    return dict(row) if row is not None else {}


def delete_row(table: str, company_id: str, row_id: str) -> bool:
    connection = connect()
    with connection:
        cursor = connection.execute(
            f"DELETE FROM {table} WHERE company_id = ? AND id = ?", (company_id, row_id)
        )
    return cursor.rowcount > 0


def delete_rows(table: str, company_id: str, where: dict[str, Any]) -> int:
    sql = f"DELETE FROM {table} WHERE company_id = ?"
    params: list[Any] = [company_id]
    for key, value in where.items():
        _check(table, [key])
        sql += f" AND {key} = ?"
        params.append(value)
    connection = connect()
    with connection:
        cursor = connection.execute(sql, params)
    return cursor.rowcount


# ---------------------------------------------------------------------------
# audit + usage
# ---------------------------------------------------------------------------


def record_audit(
    company_id: str,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: str = "agent",
    detail: dict[str, Any] | None = None,
) -> None:
    insert_row(
        "audit_log",
        {
            "company_id": company_id,
            "user_id": user_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "after": json.dumps(detail or {}, default=str),
        },
    )


def usage_for(company_id: str, month: str) -> dict[str, Any]:
    row = (
        connect()
        .execute(
            "SELECT * FROM usage_counters WHERE company_id = ? AND month = ?",
            (company_id, month),
        )
        .fetchone()
    )
    if row is not None:
        return dict(row)
    return {
        "company_id": company_id,
        "month": month,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
    }
