"""
webhooks.py — H10.8 Inbound Webhook Triggers · H16.4 Signed ambient sources.

A token-authenticated inbound trigger: ``POST /api/webhooks/{id}`` activates a
pre-configured agent (or workflow) with the request payload as input. External
systems (n8n, GitHub, cron services) can poke a Jarvis agent without holding any
Jarvis credentials beyond a per-webhook token.

H16.4 adds **signed sources**: a webhook can be created with ``signed=True``,
which provisions an HMAC signing secret. Inbound requests must then carry an
``X-Signature-256: sha256=<hmac>`` header computed over the raw body — a
cryptographically attested source (GitHub/Stripe-style), rather than a bearer
token that travels in the URL.

File-backed store (JSON under ``memory_logs/webhooks.json``), pure-Python and
offline-testable. Tokens/signatures are compared with constant-time checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Optional, Union

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("webhooks.json")


def compute_signature(secret: str, body: Union[bytes, str]) -> str:
    """HMAC-SHA256 of *body* under *secret*, as ``sha256=<hexdigest>``."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


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


class WebhookStore(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._hooks

    def _deserialize(self, raw) -> None:
        self._hooks = raw if isinstance(raw, dict) else {}

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(self, target: str, target_type: str = "agent", name: str = "",
               signed: bool = False) -> dict:
        """Create a webhook; returns the full record incl. the (only) token.

        When *signed*, also provisions an HMAC ``signing_secret`` (returned once)
        and requires a valid ``X-Signature-256`` header on every trigger.
        """
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
            "signed": bool(signed),
            "signing_secret": secrets.token_urlsafe(32) if signed else None,
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
            safe = {k: v for k, v in rec.items() if k not in ("token", "signing_secret")}
            safe["token_hint"] = rec["token"][:4] + "…"
            safe["signed"] = bool(rec.get("signed"))
            out.append(safe)
        return sorted(out, key=lambda r: r["created_at"], reverse=True)

    # ── auth + accounting ────────────────────────────────────────────────────

    def verify(self, hook_id: str, token: str) -> bool:
        rec = self._hooks.get(hook_id)
        if not rec or not token:
            return False
        return hmac.compare_digest(rec["token"], token)

    def verify_signature(self, hook_id: str, raw_body: Union[bytes, str], signature: str) -> bool:
        """H16.4 — constant-time HMAC check of a signed source's request body."""
        rec = self._hooks.get(hook_id)
        if not rec or not rec.get("signing_secret") or not signature:
            return False
        expected = compute_signature(rec["signing_secret"], raw_body)
        provided = signature.strip()
        if "=" not in provided:                       # allow a bare hexdigest
            provided = f"sha256={provided}"
        return hmac.compare_digest(expected, provided)

    def mark_called(self, hook_id: str) -> None:
        rec = self._hooks.get(hook_id)
        if rec:
            rec["calls"] += 1
            rec["last_called"] = time.time()
            self._save()
