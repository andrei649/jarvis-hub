"""Governed permanent consent for one verified sender's reset or undo command.

The selector contains a digest of the channel identity and command operation.
Requesting permanence only creates an owner decision task; execution of that
approved task is the ledger's sole widening path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Literal

from agents.core.permission_ledger import PermissionLedger, PermissionRequestError

PendingKey = tuple[str, str, str]
ConsentDecision = Literal["allow", "ask", "deny"]


def _operation(command: str) -> str:
    if not isinstance(command, str):
        raise PermissionRequestError("invalid_session_command")
    name = command.strip().lower()
    if name in {"/new", "new", "/reset", "reset"}:
        return "reset"
    if name in {"/undo", "undo"}:
        return "undo"
    raise PermissionRequestError("invalid_session_command")


def session_command_digest(key: PendingKey, command: str) -> str:
    """Hash the verified channel/route/sender identity and operation.

    The caller must supply the already verified pending identity in its native
    order: channel, stable route (including topic), verified sender. All three
    parts are required.
    """
    if (type(key) is not tuple or len(key) != 3
            or any(not isinstance(part, str) for part in key)
            or any(not part for part in key)
            or any(len(part) > 256 or part != part.strip()
                   or any(ord(char) < 32 or ord(char) == 127 for char in part)
                   for part in key)):
        raise PermissionRequestError("invalid_pending_key")
    operation = _operation(command)
    canonical = json.dumps(
        ["session_command", *key, operation], separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SessionCommandConsent:
    """Consult required grants and queue a permanent opt-out for owner review."""

    def __init__(
        self,
        ledger: PermissionLedger | None,
        govern_enqueue: Callable[..., int] | None,
    ) -> None:
        self.ledger = ledger
        self.govern_enqueue = govern_enqueue

    def check(self, key: PendingKey, command: str) -> ConsentDecision:
        selector = session_command_digest(key, command)
        if self.ledger is None:
            return "ask"
        return self.ledger.check_required("session_command", selector)

    def request_always(self, key: PendingKey, command: str, requested_by: str) -> int:
        selector = session_command_digest(key, command)
        if self.ledger is None:
            raise PermissionRequestError("permission_ledger_unavailable")
        if not callable(self.govern_enqueue):
            raise PermissionRequestError("governed_intake_unavailable")
        return self.ledger.request(
            "session_command", selector, "always", requested_by, self.govern_enqueue,
        )


__all__ = ["SessionCommandConsent", "session_command_digest"]
