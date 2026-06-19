"""
a2a.py — H16.2 Agent-to-Agent (A2A) endpoint with a signed Agent Card.

Lets a *known, allowlisted* peer agent hand work to this Jarvis — opt-in and
fail-closed by design:

* **Off by default.** Nothing is reachable unless ``JARVIS_A2A_ENABLED`` is set.
* **Allowlist + shared-secret HMAC.** Each peer is provisioned a secret; every
  inbound request is HMAC-SHA256-signed over the raw body and verified
  constant-time (mirrors the H16.4 signed-webhook scheme). Unknown peer or bad
  signature → rejected.
* **Never auto-executes.** A verified task lands in a pending inbox the owner
  approves or rejects out-of-band — exactly like the H6.2 decision queue. A2A
  cannot, by construction, run anything on its own.
* **Signed Agent Card.** Our advertised identity (name + capabilities) is
  HMAC-signed with an opt-in identity key (``JARVIS_A2A_KEY``) as a tamper-
  evidence marker; unsigned (advisory) when no key is set.

File-backed (JSON under ``memory_logs/a2a.json``), pure-Python, offline-testable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional, Union

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("a2a.json")

INBOUND_PENDING = "pending"
INBOUND_APPROVED = "approved"
INBOUND_REJECTED = "rejected"

_MAX_INBOX = 500  # bound the on-disk inbox


def a2a_enabled() -> bool:
    """A2A is a network surface — off unless explicitly enabled."""
    return os.environ.get("JARVIS_A2A_ENABLED", "").lower() in ("1", "true", "yes")


def _hmac(secret: str, body: Union[bytes, str]) -> str:
    if isinstance(body, str):
        body = body.encode("utf-8")
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _canonical(card: dict) -> bytes:
    """Deterministic bytes for signing — sorted keys, no signature field."""
    body = {k: card[k] for k in sorted(card) if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_card(card: dict, secret: str) -> str:
    return _hmac(secret, _canonical(card))


class A2ARegistry(JsonStore):
    """Peers (allowlist + secret), our Agent Card, and the pending inbound inbox."""

    def __init__(self, path: str | Path = DEFAULT_PATH, identity_secret: Optional[str] = None) -> None:
        super().__init__(path)
        self._identity_secret = identity_secret or os.environ.get("JARVIS_A2A_KEY", "").strip() or None

    def _serialize(self):
        return {"peers": self._peers, "inbox": self._inbox, "card": self._card}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._peers = raw.get("peers", {})
        self._inbox = raw.get("inbox", [])
        self._card = raw.get("card", {})

    # ── Our Agent Card ───────────────────────────────────────────────────────

    def set_card(self, name: str, capabilities: list, **extra) -> dict:
        self._card = {"name": name, "capabilities": list(capabilities), "version": "1.0"}
        self._card.update(extra)
        with self._lock:
            self._save()
        return self.agent_card()

    def agent_card(self) -> dict:
        """Return the (optionally HMAC-signed) Agent Card we advertise to peers."""
        base = dict(self._card) if self._card else {"name": "jarvis", "capabilities": [], "version": "1.0"}
        card = {k: base[k] for k in sorted(base) if k != "signature"}
        card["signature"] = sign_card(card, self._identity_secret) if self._identity_secret else None
        return card

    # ── Peers (allowlist) ────────────────────────────────────────────────────

    def add_peer(self, peer_id: str, secret: Optional[str] = None, name: str = "") -> dict:
        """Allowlist a peer; the shared secret is returned ONCE."""
        if not peer_id:
            raise ValueError("peer_id is required")
        secret = secret or secrets.token_urlsafe(32)
        self._peers[peer_id] = {
            "peer_id": peer_id, "name": name or peer_id, "secret": secret, "added_at": time.time(),
        }
        with self._lock:
            self._save()
        return {"peer_id": peer_id, "name": name or peer_id, "secret": secret}

    def remove_peer(self, peer_id: str) -> bool:
        if peer_id in self._peers:
            del self._peers[peer_id]
            with self._lock:
                self._save()
            return True
        return False

    def list_peers(self) -> list[dict]:
        """List peers with the secret masked (never re-exposed after creation)."""
        return [
            {"peer_id": p["peer_id"], "name": p.get("name", p["peer_id"]),
             "secret_hint": (p["secret"][:4] + "…"), "added_at": p.get("added_at")}
            for p in sorted(self._peers.values(), key=lambda r: r.get("added_at", 0), reverse=True)
        ]

    def verify_peer(self, peer_id: str, raw_body: Union[bytes, str], signature: str) -> bool:
        """Constant-time HMAC check that *raw_body* came from the allowlisted peer."""
        rec = self._peers.get(peer_id)
        if not rec or not signature:
            return False
        expected = _hmac(rec["secret"], raw_body)
        provided = signature.strip()
        if "=" not in provided:                          # accept a bare hexdigest
            provided = f"sha256={provided}"
        return hmac.compare_digest(expected, provided)

    # ── Inbound tasks (verified → pending; NEVER executed here) ───────────────

    def receive_task(self, peer_id: str, raw_body: Union[bytes, str], signature: str) -> dict:
        """Accept a signed task from an allowlisted peer into the pending inbox.

        Fails closed: disabled service, unknown peer, or bad signature all raise.
        The task is only *recorded* — approval/execution is a separate, human step.
        """
        if not a2a_enabled():
            raise PermissionError("A2A is disabled (set JARVIS_A2A_ENABLED to enable)")
        if peer_id not in self._peers:
            raise PermissionError("unknown peer")
        if not self.verify_peer(peer_id, raw_body, signature):
            raise PermissionError("invalid signature")
        try:
            payload = json.loads(raw_body if isinstance(raw_body, str) else raw_body.decode("utf-8"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid JSON body") from exc

        task_id = secrets.token_urlsafe(8)
        record = {
            "id": task_id,
            "peer_id": peer_id,
            "status": INBOUND_PENDING,
            "task": payload.get("task") if isinstance(payload, dict) and "task" in payload else payload,
            "received_at": time.time(),
        }
        self._inbox.append(record)
        del self._inbox[:-_MAX_INBOX]                     # keep the inbox bounded
        with self._lock:
            self._save()
        return {"id": task_id, "status": INBOUND_PENDING, "accepted": True}

    def list_inbox(self, status: Optional[str] = None) -> list[dict]:
        items = [dict(r) for r in self._inbox if status is None or r.get("status") == status]
        return items[::-1]

    def decide(self, task_id: str, approve: bool) -> dict:
        """Approve or reject a pending inbound task. Approval does NOT execute it."""
        for rec in self._inbox:
            if rec["id"] == task_id:
                if rec["status"] != INBOUND_PENDING:
                    raise ValueError(f"task {task_id} already {rec['status']}")
                rec["status"] = INBOUND_APPROVED if approve else INBOUND_REJECTED
                rec["decided_at"] = time.time()
                with self._lock:
                    self._save()
                return dict(rec)
        raise ValueError(f"task {task_id} not found")
