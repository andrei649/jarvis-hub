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

H153 gives a hook what a Hermes subscription carries: an event list (a delivery
whose event is not on it is skipped, never run) and a prompt template that decides
what the agent reads. ``delivery_event`` and ``render_prompt`` are the two halves.

File-backed store (JSON under ``memory_logs/webhooks.json``), pure-Python and
offline-testable. Tokens/signatures are compared with constant-time checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path
from typing import Optional, Union

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("webhooks.json")

# H153 — where a delivery names its event: the sender's header first (GitHub,
# GitLab, Bitbucket, then two generic spellings), else the payload's own field.
EVENT_HEADERS = ("x-github-event", "x-gitlab-event", "x-event-key", "x-event-type", "x-webhook-event")
EVENT_FIELDS = ("event", "type")
MAX_EVENTS = 32
MAX_EVENT_NAME = 64
MAX_PROMPT = 2_000
MAX_FIELD = 4_000        # one placeholder's value
MAX_RENDERED = 16_000    # the whole rendered prompt
_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)\}")


def compute_signature(secret: str, body: Union[bytes, str]) -> str:
    """HMAC-SHA256 of *body* under *secret*, as ``sha256=<hexdigest>``."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _event_name(value) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch if ch.isprintable() else " " for ch in value).strip()[:MAX_EVENT_NAME]


def delivery_event(headers, payload) -> str:
    """The event a delivery names (H153): the sender's header, else the payload's
    ``event`` or ``type`` string; "" when it names none. Printable and bounded."""
    for name in EVENT_HEADERS:
        found = _event_name(headers.get(name)) if headers is not None else ""
        if found:
            return found
    if isinstance(payload, dict):
        for key in EVENT_FIELDS:
            found = _event_name(payload.get(key))
            if found:
                return found
    return ""


def normalize_events(events) -> list[str]:
    """An event list as stored: stripped, and each name once whatever its case (the
    first spelling is kept)."""
    out: list[str] = []
    seen: set[str] = set()
    for item in events or []:
        name = str(item).strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name)
    return out


def event_subscribed(events: list[str], event: str) -> bool:
    """Whether *event* is on the list; names match whatever their case."""
    wanted = event.casefold()
    return any(name.casefold() == wanted for name in events)


def render_prompt(template: str, payload, event: str) -> str:
    """Fill a hook's prompt template (H153). ``{a.b.0}`` reads the JSON payload by
    key and list index, ``{event}`` is the delivery's event and ``{payload}`` the
    whole body. Nothing else is read: no attribute, format spec or conversion, and
    a value that is missing is empty. A string is used as is and anything else as
    JSON. Each value and the whole text are capped."""
    def value(path: str) -> str:
        if path == "event":
            return event
        node = payload
        if path != "payload":
            for part in path.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                    node = node[int(part)]
                else:
                    return ""
        if node is None:
            return ""
        text = node if isinstance(node, str) else json.dumps(node, ensure_ascii=False)
        return text[:MAX_FIELD]

    return _PLACEHOLDER.sub(lambda match: value(match.group(1)), template)[:MAX_RENDERED]


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
               signed: bool = False, events=None, prompt: str = "") -> dict:
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
            "enabled": True,
            "events": normalize_events(events),
            "prompt": str(prompt or ""),
            "created_at": time.time(),
            "calls": 0,
            "skipped": 0,
            "last_called": None,
        }
        self._hooks[hook_id] = record
        try:
            self._save()
        except Exception:
            del self._hooks[hook_id]  # memory never runs ahead of the file
            raise
        return dict(record)

    def get(self, hook_id: str) -> Optional[dict]:
        rec = self._hooks.get(hook_id)
        return dict(rec) if rec else None

    def delete(self, hook_id: str) -> bool:
        if hook_id in self._hooks:
            rec = self._hooks.pop(hook_id)
            try:
                self._save()
            except Exception:
                self._hooks[hook_id] = rec  # memory never runs ahead of the file
                raise
            return True
        return False

    def set_enabled(self, hook_id: str, enabled: bool) -> Optional[dict]:
        """Switch a hook on or off (H153); the masked record, or None when unknown.

        A disabled hook keeps its token and secret, so switching it back on needs no
        change at the sender. The trigger refuses it after authentication.
        """
        return self.update(hook_id, enabled=enabled)

    def update(self, hook_id: str, *, enabled: Optional[bool] = None, events=None,
               prompt: Optional[str] = None) -> Optional[dict]:
        """Change a hook's switch, event list or prompt template (H153): the masked
        record, or None when unknown. A save that fails undoes the change in memory."""
        rec = self._hooks.get(hook_id)
        if rec is None:
            return None
        before = {key: rec[key] for key in ("enabled", "events", "prompt") if key in rec}
        if enabled is not None:
            rec["enabled"] = bool(enabled)
        if events is not None:
            rec["events"] = normalize_events(events)
        if prompt is not None:
            rec["prompt"] = str(prompt)
        try:
            self._save()
        except Exception:
            for key in ("enabled", "events", "prompt"):  # memory never runs ahead of the file
                if key in before:
                    rec[key] = before[key]
                else:
                    rec.pop(key, None)
            raise
        return self._masked(rec)

    @staticmethod
    def is_enabled(rec: dict) -> bool:
        """A record written before the switch existed is on; otherwise only a literal
        true is (a hand-edited "false", 0 or null reads as off, never as on)."""
        return rec["enabled"] is True if "enabled" in rec else True

    @staticmethod
    def stored_events(rec: dict) -> Optional[list[str]]:
        """A hook's event list: empty (every event) for a record written before the
        field existed, and None when a hand edit left something that is not a list,
        which the trigger reads as "skip everything", never as "run everything"."""
        events = rec.get("events")
        if events is None:
            return []
        if not isinstance(events, list):
            return None
        return normalize_events(item for item in events if isinstance(item, str))

    def _masked(self, rec: dict) -> dict:
        safe = {k: v for k, v in rec.items() if k not in ("token", "signing_secret")}
        safe["token_hint"] = rec["token"][:4] + "…"
        safe["signed"] = bool(rec.get("signed"))
        safe["enabled"] = self.is_enabled(rec)
        events = self.stored_events(rec)
        safe["events"] = events or []
        if events is None:
            safe["events_unreadable"] = True
        safe["prompt"] = rec["prompt"] if isinstance(rec.get("prompt"), str) else ""
        safe["skipped"] = rec["skipped"] if isinstance(rec.get("skipped"), int) else 0
        return safe

    def list(self) -> list[dict]:
        """List webhooks with the token masked (never expose it after creation)."""
        out = [self._masked(rec) for rec in self._hooks.values()]
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

    def mark_skipped(self, hook_id: str, event: str) -> None:
        """A delivery the event list turned away (H153): counted apart from calls,
        with the event it named, so the owner can see what a sender posts."""
        rec = self._hooks.get(hook_id)
        if rec:
            rec["skipped"] = (rec["skipped"] if isinstance(rec.get("skipped"), int) else 0) + 1
            rec["last_skipped"] = time.time()
            rec["last_skipped_event"] = _event_name(event)
            self._save()
