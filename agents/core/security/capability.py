"""
capability.py — H17.3 Capability gating + out-of-band kill-switch.

Two controls the agent **cannot escalate**, aligned with EU AI Act Art.14
(human oversight) and the NIST agentic profile:

* **Capability tokens** — minted out-of-band (by the orchestrator/human), scoped
  to a set of capabilities, a source, and a task, and time-limited. An action
  must present a token that *already* grants the capability; tokens are
  read-only (no method grows a token's grants), so the agent can't escalate.
* **Kill-switch** — an out-of-band halt checked before every authorized action.
  Engaging/disengaging is an operator action (admin endpoint); the agent can't
  turn it off. The halt state is persisted so a restart preserves it.

`authorize()` combines both: halted scope OR missing capability → blocked.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from ..persistence import JsonStore
from typing import Optional

DEFAULT_KILL_PATH = Path("memory_logs/kill_switch.json")
GLOBAL = "global"


class CapabilityBroker:
    """Mints and validates scoped, expiring capability tokens (in-memory)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, dict] = {}

    def issue(self, capabilities: list[str], source: str = "", task_id: str = "",
              ttl: float = 3600.0, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else float(now)
        token_id = secrets.token_urlsafe(16)
        token = {
            "id": token_id,
            "capabilities": sorted(set(capabilities or [])),
            "source": source,
            "task_id": task_id,
            "issued_at": now,
            "expires_at": now + float(ttl),
        }
        with self._lock:
            self._tokens[token_id] = token
        return dict(token)

    def revoke(self, token_id: str) -> bool:
        with self._lock:
            return self._tokens.pop(token_id, None) is not None

    def check(self, token_id: str, capability: str, now: Optional[float] = None) -> bool:
        """True iff the token exists, is unexpired, and *already* grants capability."""
        now = time.time() if now is None else float(now)
        with self._lock:
            tok = self._tokens.get(token_id)
        if tok is None or now >= tok["expires_at"]:
            return False
        return capability in tok["capabilities"]

    def get(self, token_id: str) -> Optional[dict]:
        with self._lock:
            tok = self._tokens.get(token_id)
            return dict(tok) if tok else None

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(t) for t in self._tokens.values()]


class KillSwitch(JsonStore):
    """Out-of-band halt; persisted so a restart preserves an engaged halt."""

    def __init__(self, path: str | Path = DEFAULT_KILL_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._halted

    def _deserialize(self, raw) -> None:
        self._halted = raw if isinstance(raw, dict) else {}


    def engage(self, scope: str = GLOBAL, reason: str = "") -> dict:
        with self._lock:
            entry = {"scope": scope, "reason": reason, "at": time.time()}
            self._halted[scope] = entry
            self._save()
            return dict(entry)

    def disengage(self, scope: str = GLOBAL) -> bool:
        with self._lock:
            removed = self._halted.pop(scope, None) is not None
            if removed:
                self._save()
            return removed

    def is_halted(self, scope: str = GLOBAL) -> bool:
        """A scope is halted if it, or the GLOBAL scope, is engaged."""
        with self._lock:
            return GLOBAL in self._halted or scope in self._halted

    def status(self) -> dict:
        with self._lock:
            return {"halted": dict(self._halted), "global": GLOBAL in self._halted}


def authorize(
    broker: CapabilityBroker,
    kill: KillSwitch,
    token_id: str,
    capability: str,
    scope: str = GLOBAL,
    now: Optional[float] = None,
) -> dict:
    """Gate an action: blocked if the scope is halted or the capability is missing."""
    if kill.is_halted(scope):
        return {"allowed": False, "reason": f"kill-switch engaged for scope '{scope}'"}
    if not broker.check(token_id, capability, now=now):
        return {"allowed": False, "reason": "no valid capability token for this action"}
    return {"allowed": True, "reason": ""}
