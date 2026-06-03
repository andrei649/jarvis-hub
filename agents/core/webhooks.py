"""
webhooks.py — H10.8 Inbound Webhook Triggers.

A token-authenticated inbound trigger: ``POST /api/webhooks/{id}`` activates a
pre-configured agent (or workflow) with the request payload as input. External
systems (n8n, GitHub, cron services) can poke a Jarvis agent without holding any
Jarvis credentials beyond a per-webhook token.

File-backed store (JSON under ``memory_logs/webhooks.json``), pure-Python and
offline-testable. Tokens are generated with ``secrets`` and compared with a
constant-time check.
"""

from __future__ import annotations

import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path("memory_logs/webhooks.json")


def extract_input(payload) -> str:
    """Derive the agent input text from an arbitrary JSON payload."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("text", "message", "prompt", "input", "body"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


class WebhookStore:
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._hooks: dict[str, dict] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._hooks = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._hooks = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._hooks, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # atomic

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(self, target: str, target_type: str = "agent", name: str = "") -> dict:
        """Create a webhook; returns the full record incl. the (only) token."""
        if target_type not in ("agent", "workflow"):
            raise ValueError(f"invalid target_type: {target_type}")
        hook_id = secrets.token_urlsafe(8)
        token = secrets.token_urlsafe(24)
        record = {
            "id": hook_id,
            "token": token,
            "target": target,
            "target_type": target_type,
            "name": name or target,
            "created_at": time.time(),
            "calls": 0,
            "last_called": None,
        }
        self._hooks[hook_id] = record
        self._save()
        return dict(record)

    def get(self, hook_id: str) -> Optional[dict]:
        rec = self._hooks.get(hook_id)
        return dict(rec) if rec else None

    def delete(self, hook_id: str) -> bool:
        if hook_id in self._hooks:
            del self._hooks[hook_id]
            self._save()
            return True
        return False

    def list(self) -> list[dict]:
        """List webhooks with the token masked (never expose it after creation)."""
        out = []
        for rec in self._hooks.values():
            safe = {k: v for k, v in rec.items() if k != "token"}
            safe["token_hint"] = rec["token"][:4] + "…"
            out.append(safe)
        return sorted(out, key=lambda r: r["created_at"], reverse=True)

    # ── auth + accounting ────────────────────────────────────────────────────

    def verify(self, hook_id: str, token: str) -> bool:
        rec = self._hooks.get(hook_id)
        if not rec or not token:
            return False
        return hmac.compare_digest(rec["token"], token)

    def mark_called(self, hook_id: str) -> None:
        rec = self._hooks.get(hook_id)
        if rec:
            rec["calls"] += 1
            rec["last_called"] = time.time()
            self._save()
