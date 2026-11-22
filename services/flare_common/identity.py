"""Identity of the signed-in user for the current request/task.

Set by the auth gate, read by the agent so tool calls and prompts run in the
same company context as the browser session.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

Identity = dict[str, Any]

_identity_var: ContextVar[Identity | None] = ContextVar("identity", default=None)


def set_identity(identity: Identity | None) -> Token[Identity | None]:
    return _identity_var.set(identity)


def reset_identity(token: Token[Identity | None]) -> None:
    _identity_var.reset(token)


def get_identity() -> Identity | None:
    return _identity_var.get()
