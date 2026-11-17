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
* **Outbound (G14).** A peer may also carry an ``outbound`` address (URL, LAN flag, auth
  kind, timeout, capability tags; its bearer token lives in the secret store) so this hub
  can call it. Calling is ``agents/core/a2a_outbound.py`` (the adopted Hermes client tools,
  governed); this module only keeps and validates the addresses.

**A hostile or runaway peer (H563).** An authenticated peer still meets, in order: the
owner's allow switch (a credential is not permission — :meth:`A2ARegistry.set_peer_policy`
suspends a peer without revoking it), a per-peer rate limit (:data:`RATE_LIMIT` a minute,
counted only after the signature verified, so a stranger cannot spend a peer's budget) and
a per-conversation turn cap (a peer's tasks naming one ``context_id``; default
:data:`DEFAULT_TURN_CAP`, the owner may raise it per peer up to :data:`MAX_TURN_CAP`), which
stops two agents ping-ponging forever. Refusals are :class:`A2ARefused` with a fixed reason.
The task text the inbox shows is defanged and framed with an untrusted-provenance banner by
the adopted Hermes filter (``plugins/platforms/a2a/security.wrap_inbound``): injection markers
become ``[filtered]`` and every message, a ``/command`` included, is labelled as a remote
peer's. The routes write one line per exchange into the signed, hash-chained audit log.

File-backed (JSON under ``memory_logs/a2a.json``), pure-Python, offline-testable.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import urlsplit

from agents.core.automation_contracts import ContractTemplate, contract_denial, predicate
from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("a2a.json")

INBOUND_PENDING = "pending"
INBOUND_APPROVED = "approved"
INBOUND_REJECTED = "rejected"

_MAX_INBOX = 500  # bound the on-disk inbox
#: Inbound tasks one peer may send a minute (Hermes: 60 per identity).
RATE_LIMIT = 60
RATE_WINDOW_SECONDS = 60.0
#: Tasks one peer may send in one conversation (``context_id``) before it is refused,
#: and the most the owner may allow (Hermes: a cap of 5, a hard ceiling of 20).
DEFAULT_TURN_CAP = 5
MAX_TURN_CAP = 20
#: The most of a task's text kept for the inbox view.
MAX_VIEW_CHARS = 4000
#: Pending tasks one peer may hold in the inbox (one peer never crowds out the others).
MAX_PENDING_PER_PEER = 100
#: A timestamped request is accepted this many seconds either side of the hub's clock.
REPLAY_WINDOW_SECONDS = 300
#: Signed requests remembered against a replay (oldest dropped past this).
MAX_SEEN = 2000
_CONTEXT_RE = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class A2ARefused(PermissionError):
    """An authenticated peer's task refused by policy; ``reason`` is a fixed word and
    ``status`` the HTTP status the route answers with."""

    def __init__(self, reason: str, status: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def context_of(payload: Any) -> str | None:
    """The conversation a task belongs to (``context_id`` / ``contextId``, at the top or in
    ``task``), or None when the task names none. A named one that is not a short plain
    identifier is refused (ValueError, HTTP 400), so a malformed id never escapes the turn
    cap (H563 review m3)."""
    for holder in (payload, payload.get("task") if isinstance(payload, dict) else None):
        if isinstance(holder, dict):
            for key in ("context_id", "contextId"):
                if key not in holder or holder[key] is None:
                    continue
                value = holder[key]
                if not isinstance(value, str) or not _CONTEXT_RE.fullmatch(value):
                    raise ValueError("invalid context_id")
                return value
    return None


def _visible(text: str) -> str:
    """Control and format characters (bidi overrides, zero-width joiners) removed, newlines
    and tabs kept: what is filtered is what the reader sees (H563 review m6)."""
    import unicodedata

    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf"))


def inbound_view(peer_id: str, task: Any, *, fence: str | None = None) -> str:
    """What the owner (and anything that ever reads the inbox) sees of a peer's task: its
    text cleaned of invisible characters, defanged and framed as a remote peer's untrusted
    input (adopted Hermes filter), and closed by an end marker carrying a random *fence* the
    peer cannot know, so it cannot fake the end of its message (H563 review m6)."""
    from agents.vendor.hermes.plugins.platforms.a2a.security import wrap_inbound

    if isinstance(task, str):
        text = task
    elif isinstance(task, dict) and isinstance(task.get("text") or task.get("message"), str):
        text = task.get("text") or task.get("message")
    else:
        try:
            text = json.dumps(task, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = ""
    fence = fence or secrets.token_hex(6)
    return (wrap_inbound(_visible(peer_id), _visible(text[:MAX_VIEW_CHARS]))
            + f"\n[end of the message from A2A peer {_visible(peer_id)!r} · {fence}]")
_MAX_CONTRACT_BODY_BYTES = 64_000
A2A_INBOUND_CONTRACT_KIND = "a2a.inbound"


def _a2a_inbound_contract_template() -> ContractTemplate:
    def _kind_ok(view, now) -> bool:
        return view.get("kind") == A2A_INBOUND_CONTRACT_KIND

    def _peer_ok(view, now) -> bool:
        peer_id = view.get("peer_id")
        return isinstance(peer_id, str) and 0 < len(peer_id) <= 128

    def _task_shape_ok(view, now) -> bool:
        return view.get("task_type") in {"dict", "list", "scalar", "null"}

    def _body_size_ok(view, now) -> bool:
        body_len = view.get("body_len")
        return isinstance(body_len, int) and 0 <= body_len <= _MAX_CONTRACT_BODY_BYTES

    def _keys_ok(view, now) -> bool:
        keys = view.get("task_keys", ())
        return isinstance(keys, (list, tuple)) and all(isinstance(k, str) and len(k) <= 128 for k in keys)

    return ContractTemplate(
        kind=A2A_INBOUND_CONTRACT_KIND,
        constraints=(
            predicate("kind_matches", _kind_ok, reason="wrong_kind"),
            predicate("peer_id_valid", _peer_ok, reason="invalid_peer_id"),
            predicate("task_shape_valid", _task_shape_ok, reason="invalid_task_shape"),
            predicate("body_size_bounded", _body_size_ok, reason="body_too_large"),
            predicate("task_keys_safe", _keys_ok, reason="invalid_task_keys"),
        ),
        requires_approval=True,
        description="A2A inbound tasks must be authenticated, bounded, and land in owner approval.",
    )


A2A_INBOUND_CONTRACT = _a2a_inbound_contract_template()

# ── Outbound peer addresses (G14) ────────────────────────────────────────────

DEFAULT_OUTBOUND_TIMEOUT = 60
MAX_OUTBOUND_TIMEOUT = 90
#: Where a peer's bearer token lives in the secret store.
PEER_TOKEN_PREFIX = "a2a.peer."  # nosec B105 - a secret-store name prefix, not a secret


def peer_token_name(peer_id: str) -> str:
    return f"{PEER_TOKEN_PREFIX}{peer_id}"


def url_origin(url: str) -> tuple[str, str, int]:
    """``(scheme, host, port)`` of an http(s) URL, the unit a peer is pinned to."""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
    except ValueError:
        port = -1
    return scheme, host, port


def is_lan_host(host: str) -> bool:
    """True for a host a LAN peer may have: ``localhost``, a loopback or an RFC 1918 IPv4
    literal — exactly what the egress client's ``lan`` mode dials (``security/ssrf.py``)."""
    from agents.core.security.ssrf import resolve_and_validate

    host = (host or "").lower().rstrip(".").strip("[]")
    if host == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    _ips, error = resolve_and_validate(host, mode="lan")
    return error is None


def validate_outbound_url(url: str, *, allow_lan: bool = False) -> tuple[str, tuple[str, str, int]]:
    """Check a peer URL the owner typed; return it normalised and its origin.

    * ``https`` for a peer on the internet; ``http`` only for a LAN peer (a token in clear
      text crosses only the owner's own network).
    * No user info, query or fragment; a host, and not a cloud metadata name.
    * A LAN peer (``allow_lan``) must be named by ``localhost``, a loopback or an RFC 1918
      IPv4 literal: a DNS name that happens to resolve to the LAN is the rebinding case the
      SSRF guard refuses, so it is refused here too. Without ``allow_lan`` any private,
      loopback, link-local or reserved literal is refused; a DNS name is resolved and checked
      in public mode at every request by the egress client.
    Raises ``ValueError`` with a reason code.
    """
    from agents.core.security.ssrf import BLOCKED_HOSTS, resolve_and_validate

    raw = str(url or "").strip()
    if not raw or len(raw) > 2048 or "\\" in raw or any(ord(c) < 33 for c in raw):
        raise ValueError("invalid_url")
    parsed = urlsplit(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError("url_scheme_not_allowed")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("url_userinfo_not_allowed")
    if parsed.query or parsed.fragment:
        raise ValueError("url_query_not_allowed")
    scheme, host, port = url_origin(raw)
    if not host or port <= 0:
        raise ValueError("invalid_url")
    if host in BLOCKED_HOSTS:
        raise ValueError("url_host_blocked")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if allow_lan:
        if not is_lan_host(host):
            raise ValueError("lan_peer_needs_private_ip_literal")
    else:
        if host == "localhost" or host.endswith((".local", ".localhost")):
            raise ValueError("lan_address_needs_allow_lan")
        if literal is not None:
            _ips, error = resolve_and_validate(host.strip("[]"), mode="public")
            if error:
                raise ValueError("lan_address_needs_allow_lan")
        if scheme != "https":
            raise ValueError("https_required_for_internet_peer")
    path = parsed.path.rstrip("/")
    netloc = parsed.netloc.lower()
    return f"{scheme}://{netloc}{path}", (scheme, host, port)


def a2a_enabled() -> bool:
    """A2A is a network surface — off unless explicitly enabled."""
    from agents.core.env_config import env_flag
    return env_flag("JARVIS_A2A_ENABLED")


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


def _body_len(raw_body: Union[bytes, str]) -> int:
    if isinstance(raw_body, bytes):
        return len(raw_body)
    return len(raw_body.encode("utf-8", errors="replace"))


def _task_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return "scalar"


def _task_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    keys = [str(k) for k in value]
    return sorted(k[:128] for k in keys)[:40]


def _a2a_contract_denial(peer_id: str, payload: Any, *, raw_body_len: int = 0) -> str | None:
    has_task_field = isinstance(payload, dict) and "task" in payload
    task = payload.get("task") if has_task_field else payload
    contract_payload = {
        "kind": A2A_INBOUND_CONTRACT_KIND,
        "peer_id": peer_id,
        "has_task_field": has_task_field,
        "task_type": _task_type(task),
        "task_keys": _task_keys(task),
        "task_key_count": len(task.keys()) if isinstance(task, dict) else 0,
        "body_len": raw_body_len,
    }
    try:
        decision = A2A_INBOUND_CONTRACT.evaluate(contract_payload, now=time.time())
    except Exception:
        return "contract_error"
    return contract_denial(decision)


class A2ARegistry(JsonStore):
    """Peers (allowlist + secret), our Agent Card, and the pending inbound inbox."""

    def __init__(self, path: str | Path = DEFAULT_PATH, identity_secret: Optional[str] = None) -> None:
        super().__init__(path)
        #: peer_id -> monotonic times of its recent verified requests (H563 rate limit).
        self._recent: dict[str, list[float]] = {}
        self._identity_secret = identity_secret or os.environ.get("JARVIS_A2A_KEY", "").strip() or None

    def _serialize(self):
        return {"peers": self._peers, "inbox": self._inbox, "card": self._card, "seen": self._seen_list()}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._peers = raw.get("peers", {})
        self._inbox = raw.get("inbox", [])
        self._card = raw.get("card", {})
        seen = raw.get("seen")
        self._seen = [row for row in seen if isinstance(row, list) and len(row) == 3]\
            if isinstance(seen, list) else []

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

    def remove_peer(self, peer_id: str, secret_broker: Any = None) -> bool:
        if peer_id in self._peers:
            del self._peers[peer_id]
            with self._lock:
                self._save()
            if secret_broker is not None:
                with contextlib.suppress(Exception):
                    secret_broker.delete(peer_token_name(peer_id))
            return True
        return False

    def list_peers(self) -> list[dict]:
        """List peers with the secret masked (never re-exposed after creation).

        A peer the owner can also call (G14) carries ``outbound``: its URL, whether it is a
        LAN peer, the auth kind, timeout, tags and tenant — never its token."""
        rows = []
        for p in sorted(self._peers.values(), key=lambda r: r.get("added_at", 0), reverse=True):
            row = {"peer_id": p["peer_id"], "name": p.get("name", p["peer_id"]),
                   "secret_hint": (p["secret"][:4] + "…"), "added_at": p.get("added_at"),
                   "allowed": p.get("allowed", True) is not False,
                   "turn_cap": _turn_cap(p)}
            if isinstance(p.get("outbound"), dict):
                row["outbound"] = dict(p["outbound"])
            rows.append(row)
        return rows

    # ── Outbound (G14: this Nerva calls the peer) ────────────────────────────

    def set_outbound(self, peer_id: str, url: str, *, token: Optional[str] = None,
                     allow_lan: bool = False, timeout: int = DEFAULT_OUTBOUND_TIMEOUT,
                     capabilities: Optional[list] = None, tenant: str = "",
                     secret_broker: Any = None, keep_token: bool = False) -> dict:
        """Let this Nerva call an existing peer at *url*.

        The URL is checked by :func:`validate_outbound_url` (a LAN address only with
        ``allow_lan``). A bearer *token* goes to the secret store under
        :func:`peer_token_name`, never into ``a2a.json``; without a store a token is refused.
        ``keep_token`` keeps a token stored earlier when none is given."""
        rec = self._peers.get(peer_id)
        if rec is None:
            raise KeyError("unknown peer")
        url, _origin = validate_outbound_url(url, allow_lan=bool(allow_lan))
        caps = [str(c).strip()[:64] for c in (capabilities or []) if str(c).strip()][:20]
        try:
            timeout = max(5, min(int(timeout), MAX_OUTBOUND_TIMEOUT))
        except (TypeError, ValueError):
            raise ValueError("invalid_timeout") from None
        name = peer_token_name(peer_id)
        auth = "none"
        if token:
            if secret_broker is None:
                raise ValueError("secret_store_unavailable")
            secret_broker.put(name, str(token))
            auth = "bearer"
        elif keep_token and (rec.get("outbound") or {}).get("auth") == "bearer":
            auth = "bearer"
        elif secret_broker is not None:
            with contextlib.suppress(Exception):
                secret_broker.delete(name)
        rec["outbound"] = {"url": url, "allow_lan": bool(allow_lan), "auth": auth,
                           "timeout": timeout, "capabilities": caps,
                           "tenant": str(tenant or "")[:128], "updated_at": time.time()}
        with self._lock:
            self._save()
        return {"peer_id": peer_id, "outbound": dict(rec["outbound"])}

    def clear_outbound(self, peer_id: str, secret_broker: Any = None) -> bool:
        rec = self._peers.get(peer_id)
        if rec is None or "outbound" not in rec:
            return False
        rec.pop("outbound", None)
        with self._lock:
            self._save()
        if secret_broker is not None:
            with contextlib.suppress(Exception):
                secret_broker.delete(peer_token_name(peer_id))
        return True

    def outbound_peers(self) -> list[dict]:
        """Peers this Nerva may call: ``peer_id``, ``name`` and the ``outbound`` fields."""
        out = []
        for p in sorted(self._peers.values(), key=lambda r: r.get("peer_id", "")):
            ob = p.get("outbound")
            if isinstance(ob, dict) and ob.get("url"):
                out.append({"peer_id": p["peer_id"], "name": p.get("name", p["peer_id"]), **ob})
        return out

    def set_peer_policy(self, peer_id: str, *, allowed: Optional[bool] = None,
                        turn_cap: Optional[int] = None) -> dict:
        """The owner's switches for an authenticated peer (H563): ``allowed`` (a suspended
        peer keeps its credential and is refused with 403) and ``turn_cap`` (1 to
        :data:`MAX_TURN_CAP` tasks per conversation)."""
        if turn_cap is not None and (type(turn_cap) is not int or not 1 <= turn_cap <= MAX_TURN_CAP):
            raise ValueError("invalid_turn_cap")
        with self._lock:
            rec = self._peers.get(peer_id)
            if rec is None:
                raise KeyError("unknown peer")
            if turn_cap is not None:
                rec["turn_cap"] = turn_cap
            if allowed is not None:
                rec["allowed"] = bool(allowed)
            self._save()
            return {"peer_id": peer_id, "allowed": rec.get("allowed", True) is not False,
                    "turn_cap": _turn_cap(rec)}

    def _admit(self, peer_id: str) -> None:
        """The allow switch and the rate limit, for a peer whose signature verified."""
        rec = self._peers.get(peer_id) or {}
        if rec.get("allowed", True) is False:
            raise A2ARefused("peer_not_allowed", 403)
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._recent.get(peer_id, []) if now - t < RATE_WINDOW_SECONDS]
            if len(recent) >= RATE_LIMIT:
                self._recent[peer_id] = recent
                raise A2ARefused("rate_limited", 429)
            recent.append(now)
            self._recent[peer_id] = recent

    def verify_peer(self, peer_id: str, raw_body: Union[bytes, str], signature: str, *,
                    timestamp: Optional[str] = None, nonce: Optional[str] = None) -> bool:
        """Constant-time HMAC check that *raw_body* came from the allowlisted peer. With a
        *timestamp* and *nonce* (``X-A2A-Timestamp`` / ``X-A2A-Nonce``) the signature covers
        ``"<timestamp>.<nonce>." + body`` and the timestamp must be within
        :data:`REPLAY_WINDOW_SECONDS` of now (H563 review m4)."""
        rec = self._peers.get(peer_id)
        if not rec or not signature:
            return False
        signed = _signed_bytes(raw_body, timestamp, nonce)
        if signed is None:
            return False
        expected = _hmac(rec["secret"], signed)
        provided = signature.strip()
        if "=" not in provided:                          # accept a bare hexdigest
            provided = f"sha256={provided}"
        return hmac.compare_digest(expected, provided)

    # ── Inbound tasks (verified → pending; NEVER executed here) ───────────────

    def receive_task(self, peer_id: str, raw_body: Union[bytes, str], signature: str, *,
                     timestamp: Optional[str] = None, nonce: Optional[str] = None) -> dict:
        """Accept a signed task from an allowlisted peer into the pending inbox.

        Fails closed: disabled service, unknown peer, or bad signature all raise.
        The task is only *recorded* — approval/execution is a separate, human step.

        A signed request is accepted once (H563 review m4): its nonce (or, for a peer that
        signs the body alone, its signature) is remembered, and a replay is refused with
        ``replayed`` before it can spend the peer's rate limit, turn cap or inbox room. A
        peer's own retry of the same task goes through ``Idempotency-Key``, which answers
        with the first receipt before this point.
        """
        if not a2a_enabled():
            raise PermissionError("A2A is disabled (set JARVIS_A2A_ENABLED to enable)")
        if peer_id not in self._peers:
            raise PermissionError("unknown peer")
        if not self.verify_peer(peer_id, raw_body, signature, timestamp=timestamp, nonce=nonce):
            raise PermissionError("invalid signature")
        replay_key = hashlib.sha256(
            f"{peer_id}\x00{nonce if nonce else signature.strip().removeprefix('sha256=')}".encode()).hexdigest()
        with self._lock:
            seen = self._seen_list()
            if replay_key in {row[0] for row in seen}:
                raise A2ARefused("replayed", 409)
        self._admit(peer_id)
        try:
            payload = json.loads(raw_body if isinstance(raw_body, str) else raw_body.decode("utf-8"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid JSON body") from exc
        denied = _a2a_contract_denial(peer_id, payload, raw_body_len=_body_len(raw_body))
        if denied:
            raise PermissionError(f"contract denied: {denied}")

        context = context_of(payload)              # a malformed one raises ValueError (400)
        task = payload.get("task") if isinstance(payload, dict) and "task" in payload else payload
        view = inbound_view(peer_id, task)
        task_id = secrets.token_urlsafe(8)
        record = {
            "id": task_id,
            "peer_id": peer_id,
            "status": INBOUND_PENDING,
            "task": task,
            "view": view,
            "context_id": context,
            "received_at": time.time(),
        }
        with self._lock:
            if replay_key in {row[0] for row in seen}:      # the same request, concurrently
                raise A2ARefused("replayed", 409)
            cap = _turn_cap(self._peers.get(peer_id) or {})
            mine = [r for r in self._inbox if r.get("peer_id") == peer_id]
            if context is not None:
                turns = sum(1 for r in mine if r.get("context_id") == context)
            else:
                # H563 review m3: tasks naming no conversation share one per-peer bucket of
                # undecided tasks, so leaving the id out never escapes the cap.
                turns = sum(1 for r in mine if r.get("context_id") is None and r.get("status") == INBOUND_PENDING)
            if turns >= cap:
                raise A2ARefused("turn_cap", 429)
            if sum(1 for r in mine if r.get("status") == INBOUND_PENDING) >= MAX_PENDING_PER_PEER:
                raise A2ARefused("inbox_full", 429)
            if len(self._inbox) >= _MAX_INBOX:
                # Room is made from decided rows only: a pending task is never evicted for
                # another peer's (H563 review m5).
                decided = [r for r in self._inbox if r.get("status") != INBOUND_PENDING]
                if not decided:
                    raise A2ARefused("inbox_full", 429)
                drop = {id(r) for r in decided[:len(self._inbox) - _MAX_INBOX + 1]}
                self._inbox[:] = [r for r in self._inbox if id(r) not in drop]
            self._inbox.append(record)
            seen.append([replay_key, time.time(), bool(nonce)])
            self._prune_seen(seen)
            self._save()
        return {"id": task_id, "status": INBOUND_PENDING, "accepted": True}

    def _seen_list(self) -> list:
        """The remembered signed requests (caller holds the lock)."""
        if not isinstance(getattr(self, "_seen", None), list):
            self._seen = []
        return self._seen

    @staticmethod
    def _prune_seen(seen: list) -> None:
        """Timestamped requests are forgotten once outside the window (a replay of one is
        then refused by its timestamp); body-only ones are kept up to :data:`MAX_SEEN`."""
        horizon = time.time() - 2 * REPLAY_WINDOW_SECONDS
        seen[:] = [row for row in seen if not (row[2] and row[1] < horizon)][-MAX_SEEN:]

    def list_inbox(self, status: Optional[str] = None, *, raw: bool = False) -> list[dict]:
        """Inbox rows, newest first, with the cleaned and framed ``view`` (computed for a row
        stored before views existed). The peer's raw ``task`` only with *raw*."""
        items = []
        for r in self._inbox:
            if status is not None and r.get("status") != status:
                continue
            row = dict(r)
            if not isinstance(row.get("view"), str):
                row["view"] = inbound_view(str(row.get("peer_id") or "unknown"), row.get("task"))
            if not raw:
                row.pop("task", None)
            items.append(row)
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


def _signed_bytes(raw_body: Union[bytes, str], timestamp: Optional[str], nonce: Optional[str]) -> Optional[bytes]:
    """What the peer signed: the body alone, or ``"<ts>.<nonce>." + body`` with both headers
    (the timestamp in seconds, within the replay window; the nonce 8-128 plain characters).
    None when only one is given or either is malformed or stale."""
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    if timestamp is None and nonce is None:
        return body
    if not isinstance(timestamp, str) or not isinstance(nonce, str) or not timestamp.isdigit() \
            or len(timestamp) > 12 or not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", nonce):
        return None
    if abs(time.time() - int(timestamp)) > REPLAY_WINDOW_SECONDS:
        return None
    return f"{timestamp}.{nonce}.".encode() + body


def _turn_cap(rec: dict) -> int:
    cap = rec.get("turn_cap")
    return cap if type(cap) is int and 1 <= cap <= MAX_TURN_CAP else DEFAULT_TURN_CAP


_REGISTRY: Optional[A2ARegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> A2ARegistry:
    """The process's one registry, shared by the A2A routes and the outbound tools."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = A2ARegistry()
        return _REGISTRY
