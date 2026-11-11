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
# ``h034.``: the external secret sources' own config and bootstrap tokens.
# ``integration.``: keys the owner set in the HUD's Integrations panel (integration_keys);
# they reach their provider through the process environment, never through a handle.
# ``integration.skill.``: a skill's declared variables (H342, skills/skill_secrets); they reach
# only that skill's code, never the process environment or a handle.
# ``mcp.secret.`` / ``mcp.oauth.``: an MCP server's own secrets and OAuth tokens (G9); they
# reach that server only (spawn env, connect header), never through a handle.
_INTERNAL_PREFIX = ("h034.", "integration.", "mcp.secret.", "mcp.oauth.")
_REDACT_INTERNAL = ("h034.token.", "integration.key.", "integration.skill.", "mcp.secret.", "mcp.oauth.")


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


def _shared_with_turn(name: str) -> bool:
    """H496: the broker's secrets are the owner's; a guest turn gets one only when the
    owner shared that secret with guests. Undecidable reads as not shared."""
    try:
        from agents.core.security.credential_scope import KIND_SECRET, allowed

        return allowed(KIND_SECRET, name)
    except Exception:
        return False


class SecretBroker:
    def __init__(self, store=None, *, sources=None) -> None:
        self._store = store if store is not None else _DictStore()
        self._sources = sources
        self._lock = threading.Lock()

    def _safe_get(self, name: str, *, external: bool = False, owner_id: str | None = None,
                  background: bool = False):
        """Fetch one secret, degrading to None if it can't be decrypted.

        The encrypted SecretStore raises SecretStoreError on a wrong key or
        corrupted entry. Without this guard, one bad secret makes redact()/
        inject()/has() raise for *every* call — the defense-in-depth scrubbing
        path would take down the very features it protects (e.g. all tool-RPC).
        """
        if name.startswith(_INTERNAL_PREFIX):
            return None
        try:
            value = self._store.get(name)
            if value is None and external and self._sources is not None:
                return self._sources.resolve(name, owner_id=owner_id, background=background)
            return value
        except SecretStoreError:
            logger.warning("secret %r could not be decrypted — skipping", name)
            return None

    # ── management (values in, never out) ────────────────────────────────────

    def put(self, name: str, value: str) -> None:
        if name.startswith(_INTERNAL_PREFIX):
            raise ValueError("reserved secret name")
        with self._lock:
            self._store.set(name, value)

    def has(self, name: str) -> bool:
        return self._safe_get(name) is not None

    def names(self) -> list[str]:
        return [name for name in self._store.names() if not name.startswith(_INTERNAL_PREFIX)]

    def delete(self, name: str) -> bool:
        if name.startswith(_INTERNAL_PREFIX):
            return False
        return self._store.delete(name)

    @staticmethod
    def reference(name: str) -> str:
        """The handle the agent embeds — never the value."""
        return f"{{{{secret:{name}}}}}"

    # ── just-in-time injection (behind approval) ─────────────────────────────

    def inject(self, text: str, approved: bool = False, *, owner_id: str | None = None,
               background: bool = False) -> dict:
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
            if not _shared_with_turn(name):
                blocked.append(name)
                return f"[secret:{name} blocked — not shared with this identity]"
            value = self._safe_get(name, external=True, owner_id=owner_id, background=background)
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
            try:
                value = (self._store.get(name) if name.startswith(_REDACT_INTERNAL)
                         else self._safe_get(name))
            except SecretStoreError:
                value = None
            if value and value in out:
                out = out.replace(value, f"[REDACTED:{name}]")
        if self._sources is not None:
            for name, value in self._sources.redaction_values():
                if value and value in out:
                    out = out.replace(value, f"[REDACTED:{name}]")
        return out
