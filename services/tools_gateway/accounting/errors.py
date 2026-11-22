"""Domain errors for the accounting tools.

Codes mirror the MicroBalance core contract so an agent sees the same
vocabulary it saw through the old gateway: VALIDATION / NOT_FOUND / STATE,
plus the tenant codes NO_ORGANIZATION / UNAUTHORIZED.
"""

from __future__ import annotations

VALIDATION = "VALIDATION"
NOT_FOUND = "NOT_FOUND"
STATE = "STATE"
NO_ORGANIZATION = "NO_ORGANIZATION"
UNAUTHORIZED = "UNAUTHORIZED"


class AccountingError(Exception):
    """A business-rule failure that maps onto a ToolResult error_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
