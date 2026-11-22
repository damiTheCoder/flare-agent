"""Decimal money helpers.

Money never touches float: every value is parsed from its textual form,
rejected when it carries more than two decimal places, and quantized to
cents. Rates use the same parser with a wider tolerance.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext

from tools_gateway.accounting.errors import VALIDATION, AccountingError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def to_money(value: object, field: str = "amount") -> Decimal:
    """Parse a monetary value, rejecting sub-cent precision."""
    if value is None or value == "":
        return ZERO
    # Floats are only accepted through their shortest repr, never binary noise.
    raw = repr(value) if isinstance(value, float) else str(value).strip()
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise AccountingError(VALIDATION, f"{field} must be a decimal number") from None
    if not parsed.is_finite():
        raise AccountingError(VALIDATION, f"{field} must be a finite number")
    if parsed.as_tuple().exponent < -2:
        raise AccountingError(VALIDATION, f"{field} must have at most 2 decimal places")
    return parsed.quantize(CENT)


def assert_non_negative(value: Decimal, field: str) -> None:
    if value < 0:
        raise AccountingError(VALIDATION, f"{field} must not be negative")


def fmt(value: Decimal) -> str:
    """Canonical two-decimal string for storage and JSON output."""
    return str(value.quantize(CENT))


def add(*values: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        total = ZERO
        for value in values:
            total += value
        return total.quantize(CENT)
