"""
secret_broker.py — H15.4 Secret broker (just-in-time credential injection).

The direct anti-thesis to leaking credentials into an agent's context (overlap
with H12.1). The agent only ever sees **handles** like ``{{secret:github_token}}``;
the real value is injected **at action time, behind approval**, and never enters
the prompt/LLM context. `redact()` is the defense-in-depth backstop that scrubs
any known secret value that slips into text (logs, traces, context).
"""

from __future__ import annotations

import logging
import re
import threading

from agents.core.secrets import SecretStoreError

logger = logging.getLogger("jarvis.security.secret_broker")

_HANDLE = re.compile(r"\{\{\s*secret:([A-Za-z0-9_.\-]+)\s*\}\}")


class _DictStore:
    """In-memory fallback store (used when no encrypted SecretStore is provided)."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def set(self, name: str, value: str) -> None:
        self._d[name] = value

    def get(self, name: str, default=None):
        return self._d.get(name, default)

    def delete(self, name: str) -> bool:
        return self._d.pop(name, None) is not None

    def names(self) -> list[str]:
        return sorted(self._d.keys())


class SecretBroker:
    def __init__(self, store=None) -> None:
        self._store = store if store is not None else _DictStore()
        self._lock = threading.Lock()

    def _safe_get(self, name: str):
        """Fetch one secret, degrading to None if it can't be decrypted.

        The encrypted SecretStore raises SecretStoreError on a wrong key or
        corrupted entry. Without this guard, one bad secret makes redact()/
        inject()/has() raise for *every* call — the defense-in-depth scrubbing
        path would take down the very features it protects (e.g. all tool-RPC).
        """
        try:
            return self._store.get(name)
        except SecretStoreError:
            logger.warning("secret %r could not be decrypted — skipping", name)
            return None

    # ── management (values in, never out) ────────────────────────────────────

    def put(self, name: str, value: str) -> None:
        with self._lock:
            self._store.set(name, value)

    def has(self, name: str) -> bool:
        return self._safe_get(name) is not None

    def names(self) -> list[str]:
        return list(self._store.names())

    def delete(self, name: str) -> bool:
        return self._store.delete(name)

    @staticmethod
    def reference(name: str) -> str:
        """The handle the agent embeds — never the value."""
        return f"{{{{secret:{name}}}}}"

    # ── just-in-time injection (behind approval) ─────────────────────────────

    def inject(self, text: str, approved: bool = False) -> dict:
        """Resolve ``{{secret:NAME}}`` handles to real values — only if *approved*.

        Returns {text, injected:[names], blocked:[names]}. When not approved (or a
        secret is missing) the handle is replaced with a safe placeholder and the
        value is never revealed.
        """
        injected: list[str] = []
        blocked: list[str] = []

        def repl(m: re.Match) -> str:
            name = m.group(1)
            if not approved:
                blocked.append(name)
                return f"[secret:{name} blocked — approval required]"
            value = self._safe_get(name)
            if value is None:
                blocked.append(name)
                return f"[secret:{name} not found]"
            injected.append(name)
            return value

        out = _HANDLE.sub(repl, text or "")
        return {"text": out, "injected": injected, "blocked": blocked}

    def has_handles(self, text: str) -> bool:
        return bool(_HANDLE.search(text or ""))

    def redact(self, text: str) -> str:
        """Mask any known secret value that appears in *text* (defense-in-depth)."""
        out = text or ""
        with self._lock:
            names = list(self._store.names())
        for name in names:
            value = self._safe_get(name)
            if value and value in out:
                out = out.replace(value, f"[REDACTED:{name}]")
        return out
