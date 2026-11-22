"""SQLite persistence for the accounting tools.

One database file holds every tenant; every row carries ``company_id`` and
every query filters on it, so a tool can never read or write another
company's books. A tenant is provisioned with a standard chart of accounts
the first time it is used (the old core did the same via its seed).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
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
    ("1200", "Inventory", "ASSET", "Current Assets"),
    ("1500", "Equipment", "ASSET", "Fixed Assets"),
    ("1510", "Accumulated Depreciation", "ASSET", "Fixed Assets"),
    ("2010", "Accounts Payable", "LIABILITY", "Current Liabilities"),
    ("2100", "VAT Payable", "LIABILITY", "Current Liabilities"),
    ("2110", "WHT Payable", "LIABILITY", "Current Liabilities"),
    ("2200", "Loans Payable", "LIABILITY", "Long-term Liabilities"),
    ("3000", "Share Capital", "EQUITY", "Equity"),
    ("3100", "Retained Earnings", "EQUITY", "Equity"),
    ("4000", "Sales Revenue", "REVENUE", "Operating Revenue"),
    ("5000", "Cost of Goods Sold", "EXPENSE", "Cost of Sales"),
    ("5100", "Salaries", "EXPENSE", "Operating Expenses"),
    ("5200", "Rent", "EXPENSE", "Operating Expenses"),
    ("5300", "Depreciation", "EXPENSE", "Operating Expenses"),
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
    from decimal import Decimal

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
