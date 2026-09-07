"""
pairing.py — H12.19 Inbound sender pairing / approval (anti-abuse).

Today an unknown sender on a chat channel is silently dropped against a static
``allowed_users`` list. This adds a *governed pairing flow* — the human-sender
mirror of the H16.2 A2A peer allowlist:

* **Opt-in.** Off unless ``channels.pairing_enabled`` (env ``JARVIS_CHANNEL_PAIRING``).
  Disabled → ``is_allowed`` returns True for everyone, so behavior is unchanged.
* **Known senders pass.** An approved ``(channel, sender_id)`` is allowed through
  immediately.
* **Unknown senders are held, not run.** First contact from an unknown sender
  creates a *pending* request the owner approves / rejects / blocks out-of-band —
  exactly like the A2A inbox / H6.2 decision queue. Nothing the unknown sender
  says reaches the orchestrator until approved.
* **Optional pairing code.** The owner can set a rotating code; a sender that
  presents it is auto-approved (self-service) without an owner tap.
* **Deeplink pairing (the 60-second path).** The owner mints a single-use,
  short-lived token and opens ``https://t.me/<bot>?start=<token>`` on their phone;
  Telegram delivers ``/start <token>`` and the first sender to redeem it is
  approved. This is the activation lever — copying a code between two devices is
  where people give up — and it is safe because the token is **one-use**, expires
  in minutes, is compared in constant time, and is never logged. A link that could
  pair twice would pair whoever saw the screen after the owner did.
* **Anti-abuse.** Pairing attempts are rate-limited per ``(channel, sender)`` and
  the pending list is bounded, so an unknown sender can't flood the inbox.

File-backed (JSON under ``memory_logs/sender_pairing.json``), pure-Python,
offline-testable.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from ..persistence import JsonStore

DEFAULT_PATH = data_path("sender_pairing.json")

ALLOWED = "allowed"
PENDING = "pending"
BLOCKED = "blocked"
UNKNOWN = "unknown"

_MAX_PENDING = 200          # bound the pending inbox (anti-flood)
_ATTEMPT_WINDOW = 600.0     # rate-limit window for pairing attempts (10 min)
_MAX_ATTEMPTS = 5           # attempts allowed per (channel, sender) per window

# Deeplink tokens. Short by design: the link is meant to be tapped in the next
# minute, on a phone the owner is holding. A longer window buys nothing and keeps
# a working credential alive in a chat log or a screenshot.
DEEPLINK_TTL_SECONDS = 300.0
_MAX_DEEPLINKS = 20         # bound outstanding links; minting a new one is cheap
# 32 bytes of urlsafe randomness. Telegram's `start` payload allows 64 chars, and
# guessing this is not a threat model anyone needs to worry about.
_DEEPLINK_BYTES = 24


def pairing_enabled() -> bool:
    """Pairing is an inbound gate — off unless explicitly enabled.

    Mirrors ``a2a_enabled``: the network/channel surface is closed by default so
    a fresh single-user deployment keeps its current ``allowed_users`` behavior.
    """
    from agents.core.env_config import env_flag
    return env_flag("JARVIS_CHANNEL_PAIRING")


def _key(channel: str, sender_id: str) -> str:
    return f"{channel}:{sender_id}"


class SenderPairing(JsonStore):
    """Per-``(channel, sender)`` allow/pending/block state + an optional code."""

    def __init__(self, path: "str | Path | None" = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return {
            "senders": self._senders, "code": self._code, "attempts": self._attempts,
            "deeplinks": self._deeplinks,
        }

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._senders = raw.get("senders", {})
        self._code = raw.get("code") or None
        self._attempts = raw.get("attempts", {})
        self._deeplinks = raw.get("deeplinks", {})

    # ── pairing code (optional self-service) ──────────────────────────────────

    def set_code(self, code: Optional[str]) -> None:
        """Set/rotate the pairing code; ``None``/empty clears it (no self-pair)."""
        self._code = (code or "").strip() or None
        with self._lock:
            self._save()

    def has_code(self) -> bool:
        return bool(self._code)

    def _code_matches(self, code: Optional[str]) -> bool:
        if not self._code or not code:
            return False
        import hmac as _hmac
        return _hmac.compare_digest(self._code, str(code).strip())

    # ── state queries ─────────────────────────────────────────────────────────

    def status(self, channel: str, sender_id: str) -> str:
        rec = self._senders.get(_key(channel, sender_id))
        return rec["status"] if rec else UNKNOWN

    def is_allowed(self, channel: str, sender_id: str) -> bool:
        """Gate used by channels/gateway. When pairing is disabled, allow all."""
        if not pairing_enabled():
            return True
        return self.status(channel, sender_id) == ALLOWED

    # ── inbound first-contact ─────────────────────────────────────────────────

    def _record_attempt(self, key: str) -> int:
        now = time.time()
        hits = [t for t in self._attempts.get(key, []) if now - t < _ATTEMPT_WINDOW]
        hits.append(now)
        self._attempts[key] = hits
        # Garbage-collect dead keys: sender ids are attacker-chosen on webhook
        # channels, so without this the anti-flood map (and its JSON file) grows
        # one entry per fake sender forever — the anti-abuse layer becomes the
        # abuse vector. Sweep stale/empty keys once the map gets large.
        if len(self._attempts) > 1000:
            self._attempts = {
                k: fresh
                for k, v in self._attempts.items()
                if (fresh := [t for t in v if now - t < _ATTEMPT_WINDOW])
            }
        return len(hits)

    def _set(self, channel: str, sender_id: str, status: str, name: str = "") -> dict:
        key = _key(channel, sender_id)
        existing = self._senders.get(key, {})
        rec = {
            "channel": channel,
            "sender_id": sender_id,
            "name": name or existing.get("name", "") or sender_id,
            "status": status,
            "created_at": existing.get("created_at", time.time()),
            "updated_at": time.time(),
        }
        self._senders[key] = rec
        return rec

    def request(self, channel: str, sender_id: str, code: Optional[str] = None,
                name: str = "") -> dict:
        """Inbound first-contact from a sender. Records intent; NEVER executes.

        Returns ``{"status": …, "allowed": bool}``. A blocked sender or an
        already-allowed sender short-circuits. A correct code auto-approves;
        otherwise a (bounded, rate-limited) pending request is created.
        """
        if not channel or not sender_id:
            raise ValueError("channel and sender_id are required")
        key = _key(channel, sender_id)
        current = self.status(channel, sender_id)

        if current == BLOCKED:
            return {"status": BLOCKED, "allowed": False}
        if current == ALLOWED:
            return {"status": ALLOWED, "allowed": True}

        # Rate-limit pairing attempts (anti-abuse) — applies to unknown/pending.
        attempts = self._record_attempt(key)
        if attempts > _MAX_ATTEMPTS:
            with self._lock:
                self._save()
            return {"status": "rate_limited", "allowed": False}

        # A correct code is self-service approval (no owner tap needed).
        if self._code_matches(code):
            self._set(channel, sender_id, ALLOWED, name)
            with self._lock:
                self._save()
            return {"status": ALLOWED, "allowed": True, "paired_by": "code"}

        # Otherwise hold for owner approval (idempotent; bounded inbox).
        if current != PENDING:
            self._evict_if_full()
            self._set(channel, sender_id, PENDING, name)
        with self._lock:
            self._save()
        return {"status": PENDING, "allowed": False}

    def _evict_if_full(self) -> None:
        pend = [(k, r) for k, r in self._senders.items() if r.get("status") == PENDING]
        if len(pend) >= _MAX_PENDING:
            pend.sort(key=lambda kv: kv[1].get("created_at", 0))
            for k, _ in pend[: len(pend) - _MAX_PENDING + 1]:
                del self._senders[k]

    # ── owner decisions ───────────────────────────────────────────────────────

    def approve(self, channel: str, sender_id: str, name: str = "") -> dict:
        """Approve a sender — now allowed through. (Owner action.)"""
        rec = self._set(channel, sender_id, ALLOWED, name)
        with self._lock:
            self._save()
        return rec

    def reject(self, channel: str, sender_id: str) -> bool:
        """Drop a pending request without blocking (sender may try again)."""
        key = _key(channel, sender_id)
        if self._senders.get(key, {}).get("status") == PENDING:
            del self._senders[key]
            with self._lock:
                self._save()
            return True
        return False

    def block(self, channel: str, sender_id: str, name: str = "") -> dict:
        """Block a sender — future contact is dropped silently. (Owner action.)"""
        rec = self._set(channel, sender_id, BLOCKED, name)
        with self._lock:
            self._save()
        return rec

    def unpair(self, channel: str, sender_id: str) -> bool:
        """Revoke any state for a sender (approved or blocked → unknown)."""
        key = _key(channel, sender_id)
        if key in self._senders:
            del self._senders[key]
            with self._lock:
                self._save()
            return True
        return False

    def decide(self, channel: str, sender_id: str, action: str, name: str = "") -> dict:
        """Convenience dispatcher for the management endpoint."""
        action = (action or "").lower()
        if action == "approve":
            return self.approve(channel, sender_id, name)
        if action == "block":
            return self.block(channel, sender_id, name)
        if action == "reject":
            return {"rejected": self.reject(channel, sender_id)}
        if action == "unpair":
            return {"unpaired": self.unpair(channel, sender_id)}
        raise ValueError(f"unknown action: {action}")

    # ── listing ───────────────────────────────────────────────────────────────

    def list_senders(self, status: Optional[str] = None) -> list[dict]:
        items = [dict(r) for r in self._senders.values()
                 if status is None or r.get("status") == status]
        return sorted(items, key=lambda r: r.get("updated_at", 0), reverse=True)

    def summary(self) -> dict:
        counts = {ALLOWED: 0, PENDING: 0, BLOCKED: 0}
        for r in self._senders.values():
            counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
        return {"enabled": pairing_enabled(), "has_code": self.has_code(),
                "deeplinks_outstanding": self.outstanding_deeplinks(), **counts}

    # ── deeplink pairing (the 60-second path) ─────────────────────────────────

    def mint_deeplink(
        self, channel: str = "telegram", *, now: Optional[float] = None,
        ttl: float = DEEPLINK_TTL_SECONDS,
    ) -> dict:
        """Mint one single-use pairing token. The caller builds the URL.

        Returns ``{"token", "channel", "expires_at", "ttl"}``. The token is the
        credential: it is returned exactly once, to an admin-guarded caller, and
        the store keeps only what it needs to redeem it.
        """
        import secrets as _secrets

        moment = time.time() if now is None else float(now)
        token = _secrets.token_urlsafe(_DEEPLINK_BYTES)
        with self._lock:
            self._expire_deeplinks(moment)
            if len(self._deeplinks) >= _MAX_DEEPLINKS:
                # Drop the oldest rather than refusing: minting is the owner's
                # deliberate act, and a full table is a stale table.
                oldest = min(self._deeplinks, key=lambda k: self._deeplinks[k]["created_at"])
                self._deeplinks.pop(oldest, None)
            self._deeplinks[token] = {
                "channel": str(channel or "telegram"),
                "created_at": moment,
                "expires_at": moment + max(1.0, float(ttl)),
            }
            self._save()
        return {
            "token": token,
            "channel": channel,
            "expires_at": moment + max(1.0, float(ttl)),
            "ttl": max(1.0, float(ttl)),
        }

    def redeem_deeplink(
        self, token: Optional[str], channel: str, sender_id: str, *,
        name: str = "", now: Optional[float] = None,
    ) -> dict:
        """Spend a deeplink token and approve this sender. One use, ever.

        The token is compared in constant time against each outstanding entry and
        removed the moment it matches — before the sender is approved — so two
        redemptions racing each other resolve to exactly one winner. A token for a
        different channel is refused rather than honoured: a link minted for
        Telegram must not pair a Discord account.
        """
        import hmac as _hmac

        candidate = str(token or "").strip()
        moment = time.time() if now is None else float(now)
        if not candidate:
            return {"ok": False, "reason": "no_token"}
        with self._lock:
            self._expire_deeplinks(moment)
            matched = None
            for stored in list(self._deeplinks):
                if _hmac.compare_digest(stored, candidate):
                    matched = stored
                    break
            if matched is None:
                # Wrong, already spent, or expired all look the same from outside,
                # on purpose: distinguishing them tells a guesser which it was.
                return {"ok": False, "reason": "invalid_or_expired_token"}
            entry = self._deeplinks.pop(matched)
            self._save()
        if entry.get("channel") and entry["channel"] != channel:
            return {"ok": False, "reason": "wrong_channel"}
        record = self.approve(channel, sender_id, name=name)
        return {"ok": True, "status": ALLOWED, "channel": channel,
                "sender_id": sender_id, "record": record}

    def _expire_deeplinks(self, now: float) -> int:
        """Drop expired tokens. Caller holds the lock."""
        dead = [t for t, e in self._deeplinks.items() if float(e.get("expires_at", 0)) <= now]
        for token in dead:
            self._deeplinks.pop(token, None)
        return len(dead)

    def outstanding_deeplinks(self, *, now: Optional[float] = None) -> int:
        """How many links are live. The tokens themselves are never returned."""
        moment = time.time() if now is None else float(now)
        return sum(
            1 for e in self._deeplinks.values()
            if float(e.get("expires_at", 0)) > moment
        )

    def revoke_deeplinks(self) -> int:
        """Invalidate every outstanding link. Returns how many were dropped."""
        with self._lock:
            count = len(self._deeplinks)
            self._deeplinks = {}
            self._save()
        return count

    # ── gateway helper ────────────────────────────────────────────────────────

    def gate_inbound(self, channel: str, sender_id: str, code: Optional[str] = None,
                     name: str = "") -> dict:
        """Resolve an inbound message into an allow/hold decision for the gateway.

        Disabled or a known-allowed sender → ``allowed=True`` (route normally).
        Otherwise record the attempt and return a friendly hold message.
        """
        if not pairing_enabled() or self.status(channel, sender_id) == ALLOWED:
            return {"allowed": True, "status": ALLOWED if sender_id else UNKNOWN}
        result = self.request(channel, sender_id, code=code, name=name)
        if result["allowed"]:
            return result
        msgs = {
            BLOCKED: "",  # blocked senders get no reply (silent drop)
            PENDING: "Thanks — your message is awaiting approval by the owner.",
            "rate_limited": "Too many attempts. Please wait before trying again.",
        }
        result["message"] = msgs.get(result["status"], "")
        return result
