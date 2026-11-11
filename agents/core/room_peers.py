"""room_peers.py — H658 remote room members: a member of a shared session (room) that
lives on another machine, running under a capability the target machine issued and
can revoke.

Two roles, one module (every hub can play both):

* **Target** — the hub whose tools run. Its owner invites a member into a room; the
  invitation becomes usable only after the owner accepts its approval card on this
  machine. The target then *issues* the member's grant — signed with its own key,
  expiring, scoped to (room, authority epoch, member, target hub) and bound to an
  **execution-policy digest** — and checks it, plus revocation, on every call.
* **Member host** — the hub where the member lives. It redeems the invitation bundle
  over the transport, pins the target's key, keeps the grant out of every serializer and
  sends signed calls.

Transport and authentication (no new unauthenticated listener):

* Every hub has an Ed25519 identity key. Keys are **pinned** both ways: the member host
  pins the target key carried by the owner-transferred bundle; the target pins the
  member's key at accept time and verifies every later request against that pin only.
  The member hub's id on the target is derived from that key, never from a body claim;
  the membership stays ``pending_confirmation`` until the target owner approves a
  ``roompeer.confirm`` card showing the key's fingerprint, and one member id holds at
  most one active membership per room.
* Every request is signed over ``method | path | timestamp | nonce | sha256(body) |
  sha256(grant)``, carries a fresh nonce (replay cache) and a timestamp inside the skew
  window; every response to an authenticated request is signed by the target over the
  request nonce, status and body, and the member host refuses a response that does not
  verify against the pinned key. Unauthenticated refusals are unsigned and their audit
  rows coalesced per client per minute. The replay cache is per signer, bounded, and
  persisted beside the state file, so a restart does not reopen a replay window.
* Plain http is accepted only to a loopback peer, or with ``JARVIS_ROOM_PEERS_ALLOW_HTTP``.
* The invitation code's proof key is stored wrapped under a key derived from the grant
  key (owner-only key file), never in the clear. Key rotation is not implemented yet.
* Room credentials ride their own scheme, ``Authorization: NervaRoom <grant>``, so a room
  grant can never be confused with the install's admin/user tokens; the peer routes do
  not accept those tokens and the admin/user guards do not accept a grant.
* The grant is HMAC-SHA256 signed by the target's grant key; a stolen grant alone is
  useless without the member's private key.

Execution on the target (``op: dispatch``): the member principal is
``roommember:<room>:<member>@<member hub>`` — never the owner's. Inline calls, the queued
intake and approved execution all run with a non-admin ``room_peer`` turn principal and
the ``inbound`` action origin (:func:`member_turn`): a guest for the H496 credential seams,
untrusted for taint. Only tools a guest could be offered are offerable (never the
owner-operator tools, a G11 conversation-scoped tool or a trusted-execution tool). A
revocation withholds the result of an inline call still running and withdraws the
member's cards that have not run. Each call crosses the
target's Action Kernel (``room.remote_call``, kill-switch scope ``room:<room id>``, the
member's capability token from the H17.3 broker) — the kernel is mandatory here, a hub
without a bound kernel refuses. A read-only tool the kernel grants runs inline through
the ToolRPC surface as that principal; a gated tool, or any kernel QUEUE, becomes a
``roompeer.call`` approval card on the target owner's queue, re-checked (membership,
revocation, policy digest, kill-switch) when the approved task executes. Both sides
audit every step.

Execution-policy digest: SHA-256 over the member's tool allowlist (with each tool's live
gated flag, the handler's module:qualname and registration id, and its G11 visibility
rule), permissions and call budget. Status reads and renewals have an hourly budget too. Narrowing the policy, or a tool changing its
gating, moves the digest: every outstanding grant is refused with
``room_reauthorization_required`` and renewal is refused on a digest mismatch — the
member must be invited again.

Epoch: each room's authority epoch bumps on every membership change (join, revoke);
an older-epoch grant is refused with ``room_epoch_stale`` and must be renewed, which is
refused for a revoked member.
"""

from __future__ import annotations

import base64
import collections
import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import re
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from agents.core.paths import data_path

from .persistence import JsonStore

logger = logging.getLogger("jarvis.room_peers")

DEFAULT_STATE_PATH = data_path("room_peers.json")
DEFAULT_KEY_PATH = data_path("room_peers_keys.json")

ENV_FLAG = "JARVIS_ROOM_PEERS"
#: Review n2: a peer reached over plain http on a non-loopback address only when the
#: owner says so explicitly (a LAN without TLS); https otherwise.
ENV_ALLOW_HTTP = "JARVIS_ROOM_PEERS_ALLOW_HTTP"
SCHEME = "NervaRoom"
GRANT_PREFIX = "nrg1"
BUNDLE_PREFIX = "nrb1"
SIG_CONTEXT = "nerva-room-v1"
RESP_CONTEXT = "nerva-room-resp-v1"

PATH_ACCEPT = "/api/room-peers/peer/accept"
PATH_CALL = "/api/room-peers/peer/call"
PATH_RENEW = "/api/room-peers/peer/renew"

H_NONCE = "x-nerva-room-nonce"
H_TS = "x-nerva-room-timestamp"
H_SIG = "x-nerva-room-signature"
H_PROOF = "x-nerva-room-proof"

PERMISSIONS = ("dispatch", "status")
KERNEL_KIND = "room.remote_call"
CALL_KIND = "roompeer.call"
INVITE_KIND = "roompeer.invite"
CONFIRM_KIND = "roompeer.confirm"
#: The channel a remote member's turn is bound with on the target (review M1): not a
#: trusted turn channel, so ``tool_profiles.classify_turn`` places it on the inbound
#: surface as a guest and H496 ``credential_scope`` hands it no owner credential.
ROOM_PEER_CHANNEL = "room_peer"

DISPATCH_TTL = 3_600.0          # a grant may dispatch for an hour …
STATUS_TTL = 7 * 86_400.0       # … read its own task status and renew for a week
INVITE_TTL = 86_400.0
MAX_SKEW = 60.0
MAX_BODY = 64_000
MAX_TOOLS = 32
MAX_REPLAY_SIGNERS = 4_096     # distinct signers (memberships, invitations) in the cache
MAX_REPLAY_PER_SIGNER = 512    # one signer's live nonces; a full bucket refuses only it
MAX_REFUSAL_CLIENTS = 1_024
MAX_MEMBER_TASKS = 256
DEFAULT_CALLS_PER_HOUR = 60
MIN_OPS_PER_HOUR = 60          # status/renew budget floor (4 x the call budget above it)
CODE_PROOF_CONTEXT = b"nerva-room-code-proof-v1"
CODE_WRAP_CONTEXT = b"nerva-room-code-wrap-v1"

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_TOOL = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class RoomPeerError(ValueError):
    """A refusal with a stable reason code (and the HTTP status it maps to)."""

    def __init__(self, reason: str, status: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def room_peers_enabled() -> bool:
    from agents.core.env_config import env_flag

    return env_flag(ENV_FLAG)


# ── encoding / crypto helpers ───────────────────────────────────────────────

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    if not isinstance(text, str) or len(text) > 16_384:
        raise ValueError("bad_base64")
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fingerprint(public_key_b64: str) -> str:
    """Short human-comparable fingerprint of a public key (shown to both owners)."""
    try:
        raw = _b64d(public_key_b64)
    except Exception:
        return ""
    digest = _sha(raw)
    return ":".join(digest[i:i + 4] for i in range(0, 16, 4))


def signing_base(method: str, path: str, ts: str, nonce: str, body: bytes, grant: str = "") -> bytes:
    return "\n".join([SIG_CONTEXT, method.upper(), path, ts, nonce, _sha(body),
                      _sha(grant.encode("utf-8"))]).encode("utf-8")


def response_base(nonce: str, status: int, body: bytes) -> bytes:
    return "\n".join([RESP_CONTEXT, nonce, str(int(status)), _sha(body)]).encode("utf-8")


def _load_private(raw_b64: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.from_private_bytes(_b64d(raw_b64))


def _public_b64(private) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = private.public_key().public_bytes(serialization.Encoding.Raw,
                                            serialization.PublicFormat.Raw)
    return _b64e(raw)


def verify_signature(public_key_b64: str, signature_b64: str, message: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = Ed25519PublicKey.from_public_bytes(_b64d(public_key_b64))
        key.verify(_b64d(signature_b64), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def policy_digest(policy: dict, tool_profiles: dict) -> str:
    """SHA-256 over the member's execution policy: each tool's live gated flag, the
    identity of the handler behind it (module:qualname plus the registration id, which
    changes on every re-registration) and its G11 visibility rule, the permissions and
    the call budget."""
    def _tool(name: str) -> dict:
        prof = tool_profiles.get(name) or {}
        return {"name": name, "gated": bool(prof.get("gated", True)),
                "registered": name in tool_profiles,
                "handler": str(prof.get("handler") or ""),
                "registration": str(prof.get("registration") or ""),
                "visibility": str(prof.get("visibility") or "")}

    body = {
        "tools": [_tool(t) for t in sorted(policy.get("tools") or [])],
        "permissions": sorted(policy.get("permissions") or []),
        "max_calls_per_hour": int(policy.get("max_calls_per_hour") or 0),
    }
    return _sha(_canonical(body))


def code_key(code: str) -> bytes:
    """The HMAC key an invitation code proves itself with. The target never stores it in
    the clear: it keeps it wrapped under a key derived from its grant key (review n3)."""
    return hmac.new(CODE_PROOF_CONTEXT, str(code).encode("utf-8"), hashlib.sha256).digest()


def member_hub_for_key(public_key_b64: str) -> str:
    """The member hub's id on the target: derived from the key it proved possession of
    at accept, never from a claim in the request body (review m2)."""
    try:
        raw = _b64d(public_key_b64)
    except Exception:
        return ""
    return _sha(raw)[:32]


def _is_loopback(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_secure_peer_url(url: str) -> None:
    """Review n2: https, or plain http to a loopback address, or the owner's explicit
    ``JARVIS_ROOM_PEERS_ALLOW_HTTP`` opt-in for a LAN without TLS."""
    parts = urlsplit(str(url or ""))
    if parts.scheme == "https" or (parts.scheme == "http" and _is_loopback(parts.hostname or "")):
        return
    from agents.core.env_config import env_flag

    if parts.scheme == "http" and env_flag(ENV_ALLOW_HTTP):
        return
    raise RoomPeerError("https_required")


@contextlib.contextmanager
def member_turn(member: dict):
    """Review M1: run a remote member's work as a guest from an untrusted origin.

    Binds the turn principal (channel ``room_peer``, not admin) and the ``inbound``
    action origin, so the H496 credential seams treat the call as a guest (no owner
    credential unless the owner shared it), the tool posture is inbound/guest, and what
    the member sends reads as untrusted (taint, memory's untrusted-turn guard)."""
    from agents.core.action_origin import (
        INBOUND_ACTION_ORIGIN,
        bind_action_origin,
        reset_action_origin,
    )
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal

    principal = Principal(channel=ROOM_PEER_CHANNEL, sender=str(member.get("principal") or ""),
                          admin=False, chat=str(member.get("room_id") or ""), scope="group")
    p_token = bind_turn_principal(principal)
    o_token = bind_action_origin(INBOUND_ACTION_ORIGIN)
    try:
        yield
    finally:
        reset_action_origin(o_token)
        reset_turn_principal(p_token)


def withdraw_queued_task(queue: Any, task_id: int, reason: str) -> bool:
    """Withdraw a revoked member's card that has not run (review m1): a card still
    waiting, or approved but not started, is rejected with the reason as its decision.
    ``False`` when it already started or finished (an approved card that slips past is
    refused anyway by :meth:`RoomPeerService.execute`)."""
    from agents.core.autonomy.queue import TERMINAL, TaskStatus

    task = queue.get(task_id)
    if task is None:
        return False
    status = TaskStatus(getattr(task.status, "value", task.status))
    if status in TERMINAL or status is TaskStatus.RUNNING:
        return False
    decision = f"withdrawn: {reason}"
    if status is TaskStatus.APPROVED:
        queue.transition(task_id, TaskStatus.BLOCKED, decided_by="room_peers", decision=decision,
                         expected_status=TaskStatus.APPROVED)
        status = TaskStatus.BLOCKED
    queue.transition(task_id, TaskStatus.REJECTED, decided_by="room_peers", decision=decision,
                     result={"status": "withdrawn", "reason": reason}, expected_status=status)
    return True


def encode_bundle(bundle: dict) -> str:
    return f"{BUNDLE_PREFIX}.{_b64e(_canonical(bundle))}"


def decode_bundle(text: str) -> dict:
    text = (text or "").strip()
    prefix, _, body = text.partition(".")
    if prefix != BUNDLE_PREFIX or not body:
        raise RoomPeerError("bad_bundle")
    try:
        bundle = json.loads(_b64d(body))
    except Exception:
        raise RoomPeerError("bad_bundle") from None
    if not isinstance(bundle, dict):
        raise RoomPeerError("bad_bundle")
    return bundle


# ── transports ──────────────────────────────────────────────────────────────

class HttpRoomTransport:
    """The real cross-machine transport: the hub's governed egress client.

    Each target's host is added to the ``room-peers`` manifest's allowlist when a link
    is made, so the egress client's SSRF guard, breaker and ledger apply (a LAN target is
    reached only by an IP literal, as for the A2A peers)."""

    plugin = "room-peers"

    async def post(self, url: str, headers: dict, body: bytes) -> tuple[int, dict, bytes]:
        from agents.core.http_client import PluginHTTPClient
        from agents.core.plugin_gate import register_dynamic_domain

        register_dynamic_domain(self.plugin, url)
        client = PluginHTTPClient.for_plugin(self.plugin)
        resp = await client.post(url, content=body, headers=headers)
        raw = resp.content[:MAX_BODY * 4]
        return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, raw


# ── stores ──────────────────────────────────────────────────────────────────

class _StateStore(JsonStore):
    def _serialize(self):
        return self.data

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.data = {
            "epochs": dict(raw.get("epochs") or {}),
            "invitations": dict(raw.get("invitations") or {}),
            "members": dict(raw.get("members") or {}),
            "revoked_grants": dict(raw.get("revoked_grants") or {}),
            "links": dict(raw.get("links") or {}),
        }

    def save(self) -> None:
        with self._lock:
            self._save()


class _ReplayStore(JsonStore):
    """Review n1: the nonce replay cache survives a restart, so a request captured before
    one cannot be replayed inside its window after it. Per signer, bounded."""

    def _serialize(self):
        return self.data

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        signers = raw.get("signers") if isinstance(raw.get("signers"), dict) else {}
        self.data = {"signers": {str(k): {str(n): float(e) for n, e in v.items()
                                          if isinstance(e, (int, float)) and math.isfinite(e)}
                                 for k, v in signers.items() if isinstance(v, dict)}}

    def save(self) -> None:
        with self._lock:
            self._save()


def _replay_path(state_path) -> Path | None:
    if not state_path:
        return None
    path = Path(state_path)
    return path.with_name(f"{path.stem}_replay.json")


class _KeyStore(JsonStore):
    """Identity key, grant key and the member host's grants. Owner-only file (0600),
    never read by any serializer that answers a route."""

    def _serialize(self):
        return self.data

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.data = {"identity": raw.get("identity") or "", "grant_key": raw.get("grant_key") or "",
                     "link_grants": dict(raw.get("link_grants") or {})}

    def save(self) -> None:
        with self._lock:
            self._save()


# public field allowlists — a credential can only appear if named here, and none is
_INVITE_FIELDS = ("id", "room_id", "member_id", "policy", "status", "target_url", "created_at",
                  "expires_at", "task_id", "membership_id", "bundle_issued")
_MEMBER_FIELDS = ("id", "room_id", "member_id", "member_hub", "claimed_hub", "principal", "policy",
                  "status", "joined_at", "confirmed_at", "revoked_at", "joined_epoch", "calls",
                  "confirm_task_id", "refused_reason")
_LINK_FIELDS = ("id", "room_id", "room_name", "member_id", "target_hub", "target_url",
                "membership_id", "epoch", "policy_digest", "expires_at", "status_expires_at",
                "status", "label", "joined_at", "last_reason")


def _pick(rec: dict, fields) -> dict:
    return {k: rec[k] for k in fields if k in rec}


def _xor(a: bytes, b: bytes) -> bytes:
    if len(a) != len(b):
        raise ValueError("length mismatch")
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


class RoomPeerService:
    """Target-side issuer/verifier and member-host client for remote room members."""

    def __init__(self, *, state_path: str | Path | None = DEFAULT_STATE_PATH,
                 key_path: str | Path | None = DEFAULT_KEY_PATH,
                 hub_id: Any = None, rooms: Callable | None = None,
                 tool_rpc: Callable | None = None, kernel: Callable | None = None,
                 capability_broker: Any = None, kill_switch: Any = None,
                 enqueue: Callable | None = None, task_reader: Callable | None = None,
                 withdraw: Callable | None = None,
                 settings: Callable[[str, Any], Any] | None = None,
                 audit: Any = None, transport: Any = None, clock: Callable | None = None,
                 enabled: Callable[[], bool] | None = None,
                 dispatch_ttl: float = DISPATCH_TTL, status_ttl: float = STATUS_TTL,
                 invite_ttl: float = INVITE_TTL, max_skew: float = MAX_SKEW) -> None:
        self._state = _StateStore(state_path)
        self._keys = _KeyStore(key_path)
        self._replay = _ReplayStore(_replay_path(state_path))
        self._hub_id = hub_id
        self._rooms = rooms
        self._tool_rpc = tool_rpc
        self._kernel = kernel
        self._broker = capability_broker
        self._kill = kill_switch
        self._enqueue = enqueue
        self._task_reader = task_reader
        self._withdraw = withdraw
        self._settings = settings or (lambda key, default: default)
        self._audit = audit
        self._transport = transport or HttpRoomTransport()
        self._clock = clock or time.time
        self._enabled = enabled or room_peers_enabled
        self.dispatch_ttl = float(dispatch_ttl)
        self.status_ttl = max(float(status_ttl), self.dispatch_ttl)
        self.invite_ttl = float(invite_ttl)
        self.max_skew = float(max_skew)
        self._lock = threading.RLock()
        self._broker_tokens: dict[str, str] = {}   # membership id → live broker token id
        self._calls: dict[str, collections.deque] = {}
        self._ops: dict[str, collections.deque] = {}
        # client address → [minute, count, first reason] for coalesced refusal audit rows
        self._refusals: collections.OrderedDict[str, list] = collections.OrderedDict()
        self._ensure_keys()

    # ── identity ────────────────────────────────────────────────────────────

    def _ensure_keys(self) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        with self._lock:
            changed = False
            if not self._keys.data.get("identity"):
                raw = Ed25519PrivateKey.generate().private_bytes(
                    serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                    serialization.NoEncryption())
                self._keys.data["identity"] = _b64e(raw)
                changed = True
            if not self._keys.data.get("grant_key"):
                self._keys.data["grant_key"] = _b64e(secrets.token_bytes(32))
                changed = True
            if changed:
                self._keys.save()
            self._private = _load_private(self._keys.data["identity"])
            self.public_key = _public_b64(self._private)
            self._grant_key = _b64d(self._keys.data["grant_key"])

    def hub(self) -> str:
        hub = self._hub_id
        if hub is None:
            from agents.core.install_identity import install_id

            hub = install_id() or ""
        elif callable(hub):
            hub = hub() or ""
        return str(hub)

    def enabled(self) -> bool:
        try:
            return bool(self._enabled())
        except Exception:
            return False

    def _now(self) -> float:
        return float(self._clock())

    def _sign(self, message: bytes) -> str:
        return _b64e(self._private.sign(message))

    def sign_response(self, nonce: str, status: int, body: bytes) -> str:
        return self._sign(response_base(nonce, status, body))

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _provided(provider):
        try:
            return provider() if callable(provider) else None
        except Exception:
            return None

    def _room(self, room_id: str) -> dict | None:
        rooms = self._provided(self._rooms)
        if rooms is None:
            return None
        try:
            return rooms.get(room_id)
        except Exception:
            return None

    def _tools_server(self):
        return self._provided(self._tool_rpc)

    def _tool_profiles(self, tools) -> dict:
        server = self._tools_server()
        out = {}
        if server is None:
            return out
        for name in tools or []:
            try:
                prof = server.remote_profile(name)
            except Exception:
                prof = None
            if prof is not None:
                out[name] = prof
        return out

    def _digest_for(self, member: dict) -> str:
        policy = member.get("policy") or {}
        return policy_digest(policy, self._tool_profiles(policy.get("tools")))

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="room_peers", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # pragma: no cover - audit is best-effort
            logger.debug("room peer audit failed", exc_info=True)

    @staticmethod
    def _norm_policy(tools, permissions, max_calls) -> dict:
        tool_list = sorted({str(t).strip() for t in (tools or []) if str(t).strip()})
        if not tool_list:
            raise RoomPeerError("tools_required")
        if len(tool_list) > MAX_TOOLS or not all(_TOOL.match(t) for t in tool_list):
            raise RoomPeerError("bad_tools")
        perms = sorted({str(p).strip() for p in (permissions or ["dispatch", "status"])})
        if not perms or any(p not in PERMISSIONS for p in perms):
            raise RoomPeerError("bad_permissions")
        try:
            calls = int(DEFAULT_CALLS_PER_HOUR if max_calls is None else max_calls)
        except (TypeError, ValueError):
            raise RoomPeerError("bad_call_budget") from None
        if not 1 <= calls <= 10_000:
            raise RoomPeerError("bad_call_budget")
        return {"tools": tool_list, "permissions": perms, "max_calls_per_hour": calls}

    def _guest_may_be_offered(self, name: str) -> bool:
        """Review M1: a remote member is a guest of this hub. A tool kept for the owner at
        the operator surface (``memory``, ``delegate_task``), a session-scoped tool on the
        shared session, a third-party MCP tool the owner has not named in
        ``llm.guest_tools``, or anything else the tool-profile resolver withholds from a
        guest is never offered. The gated flag is set aside here: a gated call from a
        member is always an approval card on this hub."""
        from .tool_profiles import (
            OWNER_OPERATOR_TOOLS,
            PRINCIPAL_GUEST,
            SURFACE_OPERATOR,
            ToolPosture,
            resolve_tools,
        )

        if name in OWNER_OPERATOR_TOOLS:
            return False
        try:
            offered, _withheld = resolve_tools(
                [{"name": name, "gated": False}],
                posture=ToolPosture(SURFACE_OPERATOR, PRINCIPAL_GUEST),
                settings=self._settings, shared_session=True)
        except Exception:
            logger.warning("room peer offer check failed closed", exc_info=True)
            return False
        return bool(offered)

    def _offerable(self, name: str, prof: dict | None) -> str | None:
        """``None`` when *name* may be offered to a remote member, else the reason."""
        if prof is None:
            return "unknown_tool"
        if prof.get("trusted_execution"):
            # runs only from a trusted local execution context; never offered remotely
            return "tool_not_offerable"
        if prof.get("visibility"):
            # G11: offered to one conversation only; a member on another machine is not it
            return "tool_not_offerable"
        if not self._guest_may_be_offered(name):
            return "tool_not_offerable"
        return None

    def _check_tools_offerable(self, tools) -> None:
        server = self._tools_server()
        if server is None:
            raise RoomPeerError("tool_surface_unavailable", 503)
        for name in tools:
            reason = self._offerable(name, server.remote_profile(name))
            if reason is not None:
                raise RoomPeerError(reason)

    def _epoch(self, room_id: str) -> int:
        return int(self._state.data["epochs"].get(room_id, 1))

    def _bump_epoch(self, room_id: str) -> int:
        epoch = self._epoch(room_id) + 1
        self._state.data["epochs"][room_id] = epoch
        return epoch

    # ── capability token (H17.3 broker) ─────────────────────────────────────

    def _broker_token(self, member: dict) -> str:
        if self._broker is None:
            return ""
        mid = member["id"]
        token = self._broker_tokens.get(mid)
        if token and self._broker.get(token):
            return token
        caps = [f"room.tool:{t}" for t in member["policy"]["tools"]]
        token = self._broker.issue(caps, source=f"room:{member['room_id']}/{member['principal']}",
                                   task_id=mid, ttl=self.status_ttl)["id"]
        self._broker_tokens[mid] = token
        return token

    def _drop_broker_token(self, mid: str) -> None:
        token = self._broker_tokens.pop(mid, None)
        if token and self._broker is not None:
            self._broker.revoke(token)

    # ── grants ──────────────────────────────────────────────────────────────

    def _issue_grant(self, member: dict) -> dict:
        now = self._now()
        claims = {
            "v": 1, "gid": secrets.token_urlsafe(12), "mid": member["id"],
            "room": member["room_id"], "epoch": self._epoch(member["room_id"]),
            "member": member["member_id"], "member_hub": member["member_hub"],
            "target": self.hub(), "perms": list(member["policy"]["permissions"]),
            "pd": self._digest_for(member), "iat": now,
            "exp": now + self.dispatch_ttl, "sexp": now + self.status_ttl,
        }
        body = f"{GRANT_PREFIX}.{_b64e(_canonical(claims))}"
        mac = hmac.new(self._grant_key, body.encode("ascii"), hashlib.sha256).digest()
        return {"grant": f"{body}.{_b64e(mac)}", "claims": claims}

    def _verify_grant(self, token: str) -> dict:
        parts = (token or "").split(".")
        if len(parts) != 3 or parts[0] != GRANT_PREFIX:
            raise RoomPeerError("rejected", 401)
        body = f"{parts[0]}.{parts[1]}"
        expected = hmac.new(self._grant_key, body.encode("ascii"), hashlib.sha256).digest()
        try:
            given = _b64d(parts[2])
        except Exception:
            raise RoomPeerError("rejected", 401) from None
        if not hmac.compare_digest(expected, given):
            raise RoomPeerError("rejected", 401)
        try:
            claims = json.loads(_b64d(parts[1]))
        except Exception:
            raise RoomPeerError("rejected", 401) from None
        if not isinstance(claims, dict) or claims.get("v") != 1:
            raise RoomPeerError("rejected", 401)
        if claims.get("target") != self.hub():
            raise RoomPeerError("rejected", 401)
        return claims

    def _revoke_grant_id(self, gid: str, sexp: float) -> None:
        revoked = self._state.data["revoked_grants"]
        now = self._now()
        for key in [k for k, v in revoked.items() if float(v) < now]:
            revoked.pop(key, None)
        revoked[gid] = float(sexp)

    # ── replay ──────────────────────────────────────────────────────────────

    def _check_fresh(self, signer: str, nonce: str, ts: str) -> None:
        if not isinstance(nonce, str) or not 16 <= len(nonce) <= 128:
            raise RoomPeerError("rejected", 401)
        try:
            when = float(ts)
        except (TypeError, ValueError):
            raise RoomPeerError("rejected", 401) from None
        if not math.isfinite(when):
            # review n1: abs(now - nan) > skew is False, so a "nan" stamp would pass
            raise RoomPeerError("rejected", 401)
        now = self._now()
        if abs(now - when) > self.max_skew:
            raise RoomPeerError("stale_timestamp", 401)
        with self._lock:
            signers = self._replay.data["signers"]
            bucket = {n: e for n, e in (signers.get(signer) or {}).items() if e > now}
            if nonce in bucket:
                raise RoomPeerError("replayed", 401)
            if len(bucket) >= MAX_REPLAY_PER_SIGNER:
                # one signer filling its own bucket refuses only that signer (review m4)
                raise RoomPeerError("replay_cache_full", 503)
            if signer not in signers and len(signers) >= MAX_REPLAY_SIGNERS:
                for key in [k for k, v in signers.items() if not any(e > now for e in v.values())]:
                    signers.pop(key, None)
                if len(signers) >= MAX_REPLAY_SIGNERS:
                    raise RoomPeerError("replay_cache_full", 503)
            bucket[nonce] = now + 2 * self.max_skew
            signers[signer] = bucket
            self._replay.save()

    def _record_refusal(self, reason: str, path: str, client: str) -> None:
        """Review m4: one audit row per client address per minute; the refusals folded
        into it are written as a count when that client's next minute starts."""
        client = str(client or "unknown")[:64]
        minute = int(self._now() // 60)
        with self._lock:
            row = self._refusals.get(client)
            if row is not None and row[0] == minute:
                row[1] += 1
                return
            self._refusals[client] = [minute, 1, reason]
            self._refusals.move_to_end(client)
            while len(self._refusals) > MAX_REFUSAL_CLIENTS:
                self._refusals.popitem(last=False)
        if row is not None and row[1] > 1:
            self._record("roompeer.peer_refused_coalesced", row[2], client=client,
                         minute_start=row[0] * 60, count=row[1])
        self._record("roompeer.peer_refused", reason, path=path, client=client)

    # ══ target: owner operations ═════════════════════════════════════════════

    def status(self) -> dict:
        with self._lock:
            data = self._state.data
            return {
                "enabled": self.enabled(),
                "hub": self.hub(),
                "key_fingerprint": fingerprint(self.public_key),
                "epochs": dict(data["epochs"]),
                "invitations": [_pick(i, _INVITE_FIELDS) for i in data["invitations"].values()],
                "members": [_pick(m, _MEMBER_FIELDS) | {"key_fingerprint": fingerprint(m.get("member_key", ""))}
                            for m in data["members"].values()],
                "links": [_pick(lk, _LINK_FIELDS) | {"target_key_fingerprint": fingerprint(lk.get("target_key", ""))}
                          for lk in data["links"].values()],
            }

    def _terms_digest(self, inv: dict) -> str:
        return _sha(_canonical({k: inv[k] for k in ("id", "room_id", "member_id", "policy", "target_url")}))

    def invite(self, room_id: str, member_id: str, tools, *, target_url: str,
               permissions=None, max_calls_per_hour=None) -> dict:
        """Create an invitation and raise its approval card on this (the target) hub."""
        if not self.enabled():
            raise RoomPeerError("room_peers_disabled", 404)
        if not self.hub():
            raise RoomPeerError("install_identity_unavailable", 503)
        member_id = str(member_id or "").strip().lower()
        if not _ID.match(member_id):
            raise RoomPeerError("bad_member_id")
        room = self._room(room_id)
        if room is None:
            raise RoomPeerError("unknown_room", 404)
        policy = self._norm_policy(tools, permissions, max_calls_per_hour)
        self._check_tools_offerable(policy["tools"])
        from agents.core.a2a import is_lan_host, url_origin, validate_outbound_url

        try:
            _scheme, host, _port = url_origin(str(target_url or ""))
            url, _origin = validate_outbound_url(target_url, allow_lan=is_lan_host(host))
        except ValueError as exc:
            raise RoomPeerError(str(exc) or "invalid_url") from None
        require_secure_peer_url(url)
        if self._enqueue is None:
            raise RoomPeerError("approval_queue_unavailable", 503)
        now = self._now()
        inv = {"id": secrets.token_hex(8), "room_id": room_id, "member_id": member_id,
               "policy": policy, "status": "pending_approval", "target_url": url,
               "created_at": now, "expires_at": now + self.invite_ttl,
               "bundle_issued": False}
        title = (f"Invite remote member '{member_id}' into room '{room.get('name', room_id)}' "
                 f"— tools: {', '.join(policy['tools'])}; may {', '.join(policy['permissions'])}")
        task_id = self._enqueue("jarvis", INVITE_KIND, title,
                                payload={"invite_id": inv["id"], "room_id": room_id,
                                         "member_id": member_id, "policy": policy,
                                         "target_url": url, "target": room_id,
                                         "terms": self._terms_digest(inv)},
                                risk_tier=3, autonomy_level="ask", origin="generated")
        inv["task_id"] = task_id
        with self._lock:
            self._state.data["invitations"][inv["id"]] = inv
            self._state.save()
        self._record("roompeer.invite", f"room {room_id} member {member_id}",
                     invite_id=inv["id"], task_id=task_id, tools=policy["tools"])
        return {"invitation": _pick(inv, _INVITE_FIELDS), "task_id": task_id}

    def approve_invitation(self, invite_id: str, terms: str) -> dict:
        with self._lock:
            inv = self._state.data["invitations"].get(invite_id)
            if inv is None:
                return {"status": "failed", "reason": "unknown_invitation"}
            if inv["status"] != "pending_approval":
                return {"status": "failed", "reason": f"invitation_{inv['status']}"}
            if not hmac.compare_digest(self._terms_digest(inv), str(terms or "")):
                return {"status": "failed", "reason": "terms_changed"}
            if inv["expires_at"] < self._now():
                inv["status"] = "expired"
                self._state.save()
                return {"status": "failed", "reason": "invitation_expired"}
            inv["status"] = "approved"
            self._state.save()
        self._record("roompeer.invite_approved", invite_id, room=inv["room_id"])
        return {"status": "ok", "invite_id": invite_id}

    def issue_bundle(self, invite_id: str) -> dict:
        """The one-time code for an approved invitation, as a bundle the owner hands to the
        member host. A new call replaces the previous code (only its digest is kept)."""
        with self._lock:
            inv = self._state.data["invitations"].get(invite_id)
            if inv is None:
                raise RoomPeerError("unknown_invitation", 404)
            if inv["status"] == "pending_approval":
                raise RoomPeerError("invitation_pending_approval", 409)
            if inv["status"] != "approved":
                raise RoomPeerError(f"invitation_{inv['status']}", 409)
            if inv["expires_at"] < self._now():
                raise RoomPeerError("invitation_expired", 409)
            code = secrets.token_urlsafe(24)
            # review n3: the stored value is not the proof key; it is wrapped under a key
            # derived from the grant key, which lives only in the owner-only key file
            inv["code_box"] = _xor(code_key(code), self._code_wrap(inv["id"])).hex()
            inv.pop("code_key", None)
            inv["bundle_issued"] = True
            self._state.save()
            room = self._room(inv["room_id"]) or {}
            bundle = {"v": 1, "invite_id": inv["id"], "code": code, "target_hub": self.hub(),
                      "target_url": inv["target_url"], "target_key": self.public_key,
                      "room_id": inv["room_id"], "room_name": room.get("name", ""),
                      "member_id": inv["member_id"]}
        self._record("roompeer.bundle_issued", invite_id)
        return {"bundle": encode_bundle(bundle), "key_fingerprint": fingerprint(self.public_key)}

    def set_policy(self, membership_id: str, tools, permissions=None, max_calls_per_hour=None) -> dict:
        """Change a member's execution policy. The digest moves, so every outstanding
        grant is refused and renewal fails: the member must be invited again."""
        policy = self._norm_policy(tools, permissions, max_calls_per_hour)
        self._check_tools_offerable(policy["tools"])
        with self._lock:
            member = self._state.data["members"].get(membership_id)
            if member is None or member["status"] != "active":
                raise RoomPeerError("unknown_member", 404)
            member["policy"] = policy
            self._drop_broker_token(membership_id)
            self._state.save()
        digest = self._digest_for(member)
        self._record("roompeer.policy_changed", membership_id, room=member["room_id"],
                     tools=policy["tools"], digest=digest)
        return {"member": _pick(member, _MEMBER_FIELDS), "policy_digest": digest}

    def _code_wrap(self, invite_id: str) -> bytes:
        return hmac.new(self._grant_key, CODE_WRAP_CONTEXT + b"|" + str(invite_id).encode("utf-8"),
                        hashlib.sha256).digest()

    def confirm_member(self, membership_id: str, key_fingerprint: str) -> dict:
        """The owner confirmed the accepting key's fingerprint (review m2): only then is a
        membership active. Refused when the key differs from the one shown, or another
        active membership already holds this member id in the room."""
        with self._lock:
            member = self._state.data["members"].get(str(membership_id or ""))
            if member is None:
                return {"status": "failed", "reason": "unknown_member"}
            if member["status"] != "pending_confirmation":
                return {"status": "failed", "reason": f"membership_{member['status']}"}
            if not hmac.compare_digest(fingerprint(member["member_key"]), str(key_fingerprint or "")):
                return {"status": "failed", "reason": "key_changed"}
            if self._room(member["room_id"]) is None:
                return {"status": "failed", "reason": "room_gone"}
            clash = any(m is not member and m["room_id"] == member["room_id"]
                        and m["member_id"] == member["member_id"] and m["status"] == "active"
                        for m in self._state.data["members"].values())
            if clash:
                member["status"] = "refused"
                member["refused_reason"] = "member_id_in_use"
                self._state.save()
                reason = "member_id_in_use"
            else:
                member["status"] = "active"
                member["confirmed_at"] = self._now()
                self._state.save()
                self._broker_token(member)
                reason = ""
        if reason:
            self._record("roompeer.confirm_refused", reason, membership=membership_id,
                         room=member["room_id"])
            return {"status": "failed", "reason": reason}
        self._record("roompeer.confirmed", membership_id, room=member["room_id"],
                     key=fingerprint(member["member_key"]))
        return {"status": "ok", "membership_id": membership_id}

    def _remember_task(self, member: dict, task_id) -> None:
        with self._lock:
            tasks = [t for t in member.get("tasks") or [] if t != task_id] + [task_id]
            member["tasks"] = tasks[-MAX_MEMBER_TASKS:]
            self._state.save()

    def _withdraw_tasks(self, member: dict) -> list:
        """Withdraw the member's cards that have not run (review m1)."""
        if self._withdraw is None:
            return []
        withdrawn = []
        for task_id in list(member.get("tasks") or []):
            try:
                if self._withdraw(task_id, "membership_revoked"):
                    withdrawn.append(task_id)
            except Exception:
                logger.warning("room peer card %s not withdrawn", task_id, exc_info=True)
        return withdrawn

    def revoke_member(self, membership_id: str) -> dict:
        with self._lock:
            member = self._state.data["members"].get(membership_id)
            if member is None:
                raise RoomPeerError("unknown_member", 404)
            if member["status"] in ("active", "pending_confirmation"):
                member["status"] = "revoked"
                member["revoked_at"] = self._now()
                epoch = self._bump_epoch(member["room_id"])
                self._drop_broker_token(membership_id)
                self._state.save()
            else:
                epoch = self._epoch(member["room_id"])
        withdrawn = self._withdraw_tasks(member)
        self._record("roompeer.revoked", membership_id, room=member["room_id"], epoch=epoch,
                     withdrawn=withdrawn)
        return {"revoked": membership_id, "epoch": epoch, "withdrawn": withdrawn}

    # ══ target: peer endpoints ═══════════════════════════════════════════════

    async def handle_peer(self, path: str, headers: dict, raw: bytes,
                          client: str = "") -> tuple[int, dict, bool]:
        """One peer request → ``(status, JSON body, sign)``. ``sign`` is true only once the
        request authenticated (code proof or pinned-key signature, fresh nonce): the route
        signs those responses against the request nonce and leaves every unauthenticated
        refusal unsigned, so this hub never signs a nonce a stranger chose (review n4)."""
        if not self.enabled():
            return 404, {"error": "room peers disabled"}, False
        headers = {str(k).lower(): v for k, v in (headers or {}).items()}
        if len(raw or b"") > MAX_BODY:
            return 413, {"error": "too_large"}, False
        ctx = {"authed": False}
        try:
            if path == PATH_ACCEPT:
                return 200, self._peer_accept(headers, raw, ctx), True
            if path in (PATH_CALL, PATH_RENEW):
                member, claims, body = self._peer_auth(path, headers, raw, ctx)
                if path == PATH_RENEW:
                    return 200, self._peer_renew(member, claims), True
                status, answer = await self._peer_call(member, claims, body)
                return status, answer, True
            return 404, {"error": "not found"}, False
        except RoomPeerError as exc:
            if exc.status == 401 or not ctx["authed"]:
                self._record_refusal(exc.reason, path, client)
                return (401, {"error": "rejected"}, False) if exc.status == 401 else (
                    exc.status, {"ok": False, "reason": exc.reason}, False)
            self._record("roompeer.peer_refused", exc.reason, path=path, client=str(client)[:64])
            return exc.status, {"ok": False, "reason": exc.reason}, True

    def _peer_accept(self, headers: dict, raw: bytes, ctx: dict) -> dict:
        if self._enqueue is None:
            raise RoomPeerError("approval_queue_unavailable", 503)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise RoomPeerError("rejected", 401) from None
        if not isinstance(body, dict):
            raise RoomPeerError("rejected", 401)
        invite_id = str(body.get("invite_id") or "")
        claimed_hub = str(body.get("member_hub") or "")
        member_key = str(body.get("member_key") or "")
        nonce, ts = headers.get(H_NONCE, ""), headers.get(H_TS, "")
        base = signing_base("POST", PATH_ACCEPT, ts, nonce, raw)
        with self._lock:
            inv = self._state.data["invitations"].get(invite_id)
            if inv is None or inv["status"] != "approved" or not inv.get("code_box"):
                raise RoomPeerError("rejected", 401)
            if inv["expires_at"] < self._now():
                raise RoomPeerError("rejected", 401)
            try:
                proof_key = _xor(bytes.fromhex(inv["code_box"]), self._code_wrap(inv["id"]))
            except ValueError:
                raise RoomPeerError("rejected", 401) from None
            proof = hmac.new(proof_key, base, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(proof, str(headers.get(H_PROOF, ""))):
                raise RoomPeerError("rejected", 401)
            try:
                if len(_b64d(member_key)) != 32:
                    raise ValueError
            except Exception:
                raise RoomPeerError("rejected", 401) from None
            if not verify_signature(member_key, headers.get(H_SIG, ""), base):
                raise RoomPeerError("rejected", 401)
            self._check_fresh(f"invite:{invite_id}", nonce, ts)
            ctx["authed"] = True
            # the claim is kept for display only; the identity is the proven key
            if (not _HEX32.match(claimed_hub) or claimed_hub == self.hub()
                    or member_key == self.public_key):
                raise RoomPeerError("bad_member_hub", 400)
            if self._room(inv["room_id"]) is None:
                raise RoomPeerError("room_gone", 410)
            member_hub = member_hub_for_key(member_key)
            mid = secrets.token_hex(8)
            member = {"id": mid, "room_id": inv["room_id"], "member_id": inv["member_id"],
                      "member_hub": member_hub, "claimed_hub": claimed_hub,
                      "member_key": member_key,
                      "principal": f"roommember:{inv['room_id']}:{inv['member_id']}@{member_hub}",
                      "policy": inv["policy"], "status": "pending_confirmation",
                      "joined_at": self._now(), "calls": 0, "tasks": []}
            member["joined_epoch"] = self._bump_epoch(inv["room_id"])
            self._state.data["members"][mid] = member
            inv["status"] = "accepted"
            inv["membership_id"] = mid
            inv.pop("code_box", None)
            self._state.save()
            grant = self._issue_grant(member)
        key_fp = fingerprint(member_key)
        room = self._room(member["room_id"]) or {}
        title = (f"Confirm remote member '{member['member_id']}' in room "
                 f"'{room.get('name', member['room_id'])}': its machine's key fingerprint is "
                 f"{key_fp} — compare it with the one the member's hub shows before approving")
        try:
            task_id = self._enqueue("jarvis", CONFIRM_KIND, title,
                                    payload={"membership_id": mid, "room_id": member["room_id"],
                                             "member_id": member["member_id"],
                                             "key_fingerprint": key_fp, "member_hub": member_hub,
                                             "target": member["room_id"]},
                                    risk_tier=3, autonomy_level="ask", origin="generated")
        except Exception:
            logger.warning("room peer confirmation card not raised", exc_info=True)
            with self._lock:
                member["status"] = "refused"
                member["refused_reason"] = "approval_queue_unavailable"
                self._state.save()
            raise RoomPeerError("approval_queue_unavailable", 503) from None
        with self._lock:
            member["confirm_task_id"] = task_id
            self._state.save()
        self._record("roompeer.accepted", mid, room=member["room_id"], member=member["member_id"],
                     member_hub=member_hub, claimed_hub=claimed_hub, key=key_fp,
                     confirm_task=task_id)
        return self._grant_answer(member, grant)

    def _grant_answer(self, member: dict, grant: dict) -> dict:
        claims = grant["claims"]
        room = self._room(member["room_id"]) or {}
        return {"ok": True, "membership_id": member["id"], "grant": grant["grant"],
                "membership_status": member["status"],
                "key_fingerprint": fingerprint(member["member_key"]),
                "epoch": claims["epoch"], "policy_digest": claims["pd"],
                "expires_at": claims["exp"], "status_expires_at": claims["sexp"],
                "room_id": member["room_id"], "room_name": room.get("name", ""),
                "target_hub": claims["target"], "principal": member["principal"],
                "policy": member["policy"]}

    def _peer_auth(self, path: str, headers: dict, raw: bytes, ctx: dict):
        auth = str(headers.get("authorization", ""))
        scheme, _, token = auth.partition(" ")
        if scheme != SCHEME or not token:
            raise RoomPeerError("rejected", 401)
        token = token.strip()
        claims = self._verify_grant(token)
        nonce, ts = headers.get(H_NONCE, ""), headers.get(H_TS, "")
        with self._lock:
            member = self._state.data["members"].get(str(claims.get("mid")))
            if member is None:
                raise RoomPeerError("rejected", 401)
            base = signing_base("POST", path, ts, nonce, raw, token)
            if not verify_signature(member["member_key"], headers.get(H_SIG, ""), base):
                raise RoomPeerError("rejected", 401)
            self._check_fresh(f"member:{member['id']}", nonce, ts)
            # authenticated: from here on the refusals name their reason
            ctx["authed"] = True
            if member["status"] == "pending_confirmation":
                raise RoomPeerError("membership_pending_confirmation", 403)
            if member["status"] != "active":
                raise RoomPeerError("membership_revoked", 403)
            if claims.get("gid") in self._state.data["revoked_grants"]:
                raise RoomPeerError("grant_revoked", 403)
            if (claims.get("room") != member["room_id"] or claims.get("member") != member["member_id"]
                    or claims.get("member_hub") != member["member_hub"]):
                raise RoomPeerError("rejected", 401)
            if self._room(member["room_id"]) is None:
                raise RoomPeerError("room_gone", 410)
            if float(claims.get("sexp", 0)) < self._now():
                raise RoomPeerError("grant_expired", 403)
            if not hmac.compare_digest(str(claims.get("pd", "")), self._digest_for(member)):
                raise RoomPeerError("room_reauthorization_required", 403)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise RoomPeerError("bad_body") from None
        if not isinstance(body, dict):
            raise RoomPeerError("bad_body")
        return member, claims, body

    def _peer_renew(self, member: dict, claims: dict) -> dict:
        self._take_ops_budget(member)
        with self._lock:
            self._revoke_grant_id(str(claims.get("gid")), float(claims.get("sexp", 0)))
            grant = self._issue_grant(member)
            self._state.save()
        self._record("roompeer.renewed", member["id"], room=member["room_id"],
                     epoch=grant["claims"]["epoch"])
        return self._grant_answer(member, grant)

    async def _peer_call(self, member: dict, claims: dict, body: dict) -> tuple[int, dict]:
        if int(claims.get("epoch", -1)) != self._epoch(member["room_id"]):
            raise RoomPeerError("room_epoch_stale", 403)
        op = body.get("op")
        perms = member["policy"]["permissions"]
        if op == "status":
            if "status" not in perms:
                raise RoomPeerError("permission_denied", 403)
            self._take_ops_budget(member)
            return 200, self._member_task_status(member, body.get("task_id"))
        if op != "dispatch":
            raise RoomPeerError("bad_op")
        if "dispatch" not in perms:
            raise RoomPeerError("permission_denied", 403)
        if float(claims.get("exp", 0)) < self._now():
            raise RoomPeerError("grant_expired", 403)
        tool = str(body.get("tool") or "")
        args = body.get("args") or {}
        if not isinstance(args, dict):
            raise RoomPeerError("bad_args")
        if tool not in member["policy"]["tools"]:
            raise RoomPeerError("tool_not_granted", 403)
        self._take_call_budget(member)
        return await self._dispatch(member, tool, args)

    def _take_call_budget(self, member: dict) -> None:
        now = self._now()
        with self._lock:
            window = self._calls.setdefault(member["id"], collections.deque())
            while window and window[0] <= now - 3_600:
                window.popleft()
            if len(window) >= int(member["policy"]["max_calls_per_hour"]):
                raise RoomPeerError("call_budget_exhausted", 429)
            window.append(now)
            member["calls"] = int(member.get("calls", 0)) + 1

    def _take_ops_budget(self, member: dict) -> None:
        """Review m4: status reads and renewals count toward an hourly budget of their own
        (four times the call budget, at least ``MIN_OPS_PER_HOUR``)."""
        now = self._now()
        limit = max(MIN_OPS_PER_HOUR, 4 * int(member["policy"]["max_calls_per_hour"]))
        with self._lock:
            window = self._ops.setdefault(member["id"], collections.deque())
            while window and window[0] <= now - 3_600:
                window.popleft()
            if len(window) >= limit:
                raise RoomPeerError("ops_budget_exhausted", 429)
            window.append(now)

    def _tool_refusal(self, server, tool: str) -> str | None:
        """The live checks every remote call meets at dispatch, intake and execution:
        still registered, offerable to a guest, and visible (G11) right now."""
        prof = server.remote_profile(tool) if server is not None else None
        if prof is None:
            return "tool_unavailable"
        if self._offerable(tool, prof) is not None:
            return "tool_not_offerable"
        if not prof.get("visible", True):
            return "tool_unavailable"
        return None

    async def _dispatch(self, member: dict, tool: str, args: dict) -> tuple[int, dict]:
        from .kernel import Action, Capability, Verdict

        server = self._tools_server()
        refusal = self._tool_refusal(server, tool)
        if refusal is not None:
            raise RoomPeerError(refusal, 409 if refusal == "tool_unavailable" else 403)
        prof = server.remote_profile(tool)
        kernel = self._provided(self._kernel)
        if kernel is None:
            raise RoomPeerError("kernel_unavailable", 503)
        principal = member["principal"]
        payload = {"room": member["room_id"], "member": member["member_id"],
                   "member_hub": member["member_hub"], "tool": tool,
                   "args_keys": sorted(str(k) for k in args), "target": tool,
                   "risk_tier": 2 if prof["gated"] else 0}
        action = Action(kind=KERNEL_KIND, agent=principal,
                        title=f"Remote member {member['member_id']} in room {member['room_id']}: {tool}",
                        payload=payload, scope=f"room:{member['room_id']}", origin="room_peer")
        cap = Capability(token_id=self._broker_token(member), name=f"room.tool:{tool}")
        decision = kernel(action, cap)
        if decision.verdict is Verdict.DENY:
            self._record("roompeer.kernel_denied", tool, membership=member["id"],
                         principal=principal, reason=decision.reason)
            return 403, {"ok": False, "reason": "kernel_denied", "detail": decision.reason}
        if decision.verdict is Verdict.GRANT and not prof["gated"]:
            return await self._run_inline(member, tool, args)
        return 202, self._queue_call(member, tool, args, decision.reason)

    async def _run_inline(self, member: dict, tool: str, args: dict) -> tuple[int, dict]:
        server = self._tools_server()
        policy_before = self._digest_for(member)
        with member_turn(member):
            result = await server.handle({"tool": tool, "args": args}, actor=member["principal"])
        # review m1: a revocation (or policy change) that landed while the call ran keeps
        # its result from leaving this hub
        with self._lock:
            current = self._state.data["members"].get(member["id"])
            still = (current is not None and current["status"] == "active"
                     and hmac.compare_digest(policy_before, self._digest_for(current)))
        if not still:
            reason = ("membership_revoked" if current is None or current["status"] != "active"
                      else "room_reauthorization_required")
            self._record("roompeer.result_withheld", tool, membership=member["id"],
                         principal=member["principal"], reason=reason)
            return 403, {"ok": False, "reason": reason}
        self._record("roompeer.call", tool, membership=member["id"],
                     principal=member["principal"], ok=bool(result.get("ok")))
        return (200 if result.get("ok") else 422), result

    def _queue_call(self, member: dict, tool: str, args: dict, why: str) -> dict:
        if self._enqueue is None:
            raise RoomPeerError("approval_queue_unavailable", 503)
        server = self._tools_server()
        labels, denial = server.classify_call(tool, args)
        if denial is not None:
            raise RoomPeerError(denial, 422)
        room = self._room(member["room_id"]) or {}
        title = (f"Remote member '{member['member_id']}' (room '{room.get('name', member['room_id'])}', "
                 f"from {member['member_hub'][:8]}) asks to run '{tool}'")
        if labels.get("notice"):
            title = f"{title} — {labels['notice']}"
        payload = {"membership_id": member["id"], "room": member["room_id"],
                   "member": member["member_id"], "tool": tool, "args": args, "target": tool,
                   "pd": self._digest_for(member), **labels}
        from agents.core.action_origin import INBOUND_ACTION_ORIGIN

        # review M1: the governed intake sees an untrusted origin, so the member's
        # arguments are taint-marked and the card can never be relaxed below ask
        with member_turn(member):
            task_id = self._enqueue(member["principal"], CALL_KIND, title, payload=payload,
                                    risk_tier=2, autonomy_level="ask",
                                    origin=INBOUND_ACTION_ORIGIN)
        self._remember_task(member, task_id)
        self._record("roompeer.call_queued", tool, membership=member["id"],
                     principal=member["principal"], task_id=task_id, kernel_reason=why)
        return {"ok": False, "reason": "approval_required", "tool": tool, "task_id": task_id}

    def _member_task_status(self, member: dict, task_id) -> dict:
        if type(task_id) is not int or self._task_reader is None:
            raise RoomPeerError("bad_task_id")
        try:
            task = self._task_reader(task_id)
        except Exception:
            task = None
        payload = getattr(task, "payload", None) if task is not None else None
        # review m2: the task belongs to this membership, not merely to a principal string
        if (task is None or getattr(task, "agent", None) != member["principal"]
                or getattr(task, "kind", None) != CALL_KIND or not isinstance(payload, dict)
                or payload.get("membership_id") != member["id"]):
            raise RoomPeerError("unknown_task", 404)
        status = getattr(task, "status", "")
        status = getattr(status, "value", status)
        out = {"ok": True, "task_id": task_id, "status": str(status)}
        result = getattr(task, "result", None)
        if isinstance(result, dict):
            out["result"] = result
        return out

    # ── approved task execution (target) ────────────────────────────────────

    async def execute(self, task) -> dict:
        kind = str(getattr(task, "kind", "") or "")
        payload = getattr(task, "payload", None) or {}
        if kind == INVITE_KIND:
            return self.approve_invitation(str(payload.get("invite_id", "")), payload.get("terms", ""))
        if kind == CONFIRM_KIND:
            return self.confirm_member(str(payload.get("membership_id", "")),
                                       str(payload.get("key_fingerprint", "")))
        if kind != CALL_KIND:
            return {"status": "failed", "reason": "unknown_kind"}
        from .security.capability import authorize as _capability_authorize

        with self._lock:
            member = self._state.data["members"].get(str(payload.get("membership_id", "")))
        tool = str(payload.get("tool", ""))
        if member is None or member["status"] != "active":
            self._record("roompeer.execute_refused", "membership_revoked", task=getattr(task, "id", None))
            return {"status": "failed", "reason": "membership_revoked", "tool": tool}
        if getattr(task, "agent", None) != member["principal"]:
            return {"status": "failed", "reason": "principal_mismatch", "tool": tool}
        if tool not in member["policy"]["tools"]:
            return {"status": "failed", "reason": "tool_not_granted", "tool": tool}
        if not hmac.compare_digest(str(payload.get("pd", "")), self._digest_for(member)):
            self._record("roompeer.execute_refused", "policy_changed", task=getattr(task, "id", None))
            return {"status": "failed", "reason": "room_reauthorization_required", "tool": tool}
        if self._room(member["room_id"]) is None:
            return {"status": "failed", "reason": "room_gone", "tool": tool}
        if self._broker is not None and self._kill is not None:
            gate = _capability_authorize(self._broker, self._kill, self._broker_token(member),
                                         f"room.tool:{tool}", scope=f"room:{member['room_id']}")
            if not gate.get("allowed"):
                return {"status": "failed", "reason": "kernel_denied", "detail": gate.get("reason"),
                        "tool": tool}
        server = self._tools_server()
        if server is None:
            return {"status": "failed", "reason": "tool_surface_unavailable", "tool": tool}
        refusal = self._tool_refusal(server, tool)
        if refusal is not None:
            self._record("roompeer.execute_refused", refusal, task=getattr(task, "id", None))
            return {"status": "failed", "reason": refusal, "tool": tool}
        inner = SimpleNamespace(id=getattr(task, "id", None), agent=member["principal"],
                                kind=f"toolrpc.{tool}",
                                payload={k: v for k, v in payload.items()
                                         if k not in ("membership_id", "room", "member", "pd")})
        with member_turn(member):
            result = await server.execute(inner)
        self._record("roompeer.execute", tool, membership=member["id"], principal=member["principal"],
                     task=getattr(task, "id", None), status=result.get("status"))
        return result

    # ══ member host ══════════════════════════════════════════════════════════

    def _signed_headers(self, path: str, body: bytes, grant: str = "") -> tuple[dict, str]:
        nonce = secrets.token_urlsafe(18)
        ts = f"{self._now():.3f}"
        base = signing_base("POST", path, ts, nonce, body, grant)
        headers = {"content-type": "application/json", H_NONCE: nonce, H_TS: ts,
                   H_SIG: self._sign(base)}
        if grant:
            headers["authorization"] = f"{SCHEME} {grant}"
        return headers, nonce

    def build_request(self, path: str, body: dict, grant: str = "",
                      proof_key: bytes | None = None) -> tuple[bytes, dict, str]:
        """One signed peer request: ``(raw body, headers, nonce)``. ``proof_key`` (the
        SHA-256 of an invitation code) adds the accept-time proof of the code."""
        raw = _canonical(body)
        headers, nonce = self._signed_headers(path, raw, grant)
        if proof_key is not None:
            base = signing_base("POST", path, headers[H_TS], nonce, raw)
            headers[H_PROOF] = hmac.new(proof_key, base, hashlib.sha256).hexdigest()
        return raw, headers, nonce

    async def _exchange(self, url: str, path: str, target_key: str, body: dict,
                        grant: str = "", proof_key: bytes | None = None) -> tuple[int, dict]:
        raw, headers, nonce = self.build_request(path, body, grant, proof_key)
        try:
            status, resp_headers, resp = await self._transport.post(url.rstrip("/") + path, headers, raw)
        except Exception as exc:
            logger.warning("room peer transport failed: %s", type(exc).__name__)
            return 0, {"ok": False, "reason": "transport_failed"}
        sig = {str(k).lower(): v for k, v in (resp_headers or {}).items()}.get(H_SIG, "")
        if not verify_signature(target_key, sig, response_base(nonce, status, resp)):
            return 0, {"ok": False, "reason": "response_unverified"}
        try:
            answer = json.loads(resp or b"{}")
        except ValueError:
            return 0, {"ok": False, "reason": "response_unverified"}
        return status, answer if isinstance(answer, dict) else {"ok": False}

    async def join(self, bundle_text: str, label: str = "") -> dict:
        if not self.enabled():
            raise RoomPeerError("room_peers_disabled", 404)
        bundle = decode_bundle(bundle_text)
        for key in ("invite_id", "code", "target_hub", "target_url", "target_key", "room_id", "member_id"):
            if not isinstance(bundle.get(key), str) or not bundle[key]:
                raise RoomPeerError("bad_bundle")
        if not _HEX32.match(bundle["target_hub"]):
            raise RoomPeerError("bad_bundle")
        own = self.hub()
        if not own:
            raise RoomPeerError("install_identity_unavailable", 503)
        if bundle["target_hub"] == own:
            raise RoomPeerError("same_install")
        try:
            if len(_b64d(bundle["target_key"])) != 32:
                raise ValueError
        except Exception:
            raise RoomPeerError("bad_bundle") from None
        from agents.core.a2a import is_lan_host, url_origin, validate_outbound_url

        try:
            _s, host, _p = url_origin(bundle["target_url"])
            url, _o = validate_outbound_url(bundle["target_url"], allow_lan=is_lan_host(host))
        except ValueError as exc:
            raise RoomPeerError(str(exc) or "invalid_url") from None
        require_secure_peer_url(url)
        body = {"v": 1, "invite_id": bundle["invite_id"], "member_hub": own, "member_key": self.public_key}
        status, answer = await self._exchange(
            url, PATH_ACCEPT, bundle["target_key"], body, proof_key=code_key(bundle["code"]))
        if status != 200 or not answer.get("ok") or not isinstance(answer.get("grant"), str):
            self._record("roompeer.join_refused", answer.get("reason") or answer.get("error") or "refused",
                         target=bundle["target_hub"])
            raise RoomPeerError(answer.get("reason") or "join_refused", 502 if status == 0 else 403)
        if answer.get("target_hub") != bundle["target_hub"]:
            raise RoomPeerError("response_unverified", 502)
        lid = secrets.token_hex(8)
        link = {"id": lid, "room_id": bundle["room_id"], "room_name": answer.get("room_name") or bundle.get("room_name", ""),
                "member_id": bundle["member_id"], "target_hub": bundle["target_hub"], "target_url": url,
                "target_key": bundle["target_key"], "label": str(label or "")[:80],
                "joined_at": self._now(), "status": "active"}
        with self._lock:
            self._apply_grant(link, answer)
            self._state.data["links"][lid] = link
            self._state.save()
        self._record("roompeer.joined", lid, room=link["room_id"], target=link["target_hub"],
                     key=fingerprint(link["target_key"]))
        return _pick(link, _LINK_FIELDS)

    def _apply_grant(self, link: dict, answer: dict) -> None:
        link.update({"membership_id": answer.get("membership_id"), "epoch": answer.get("epoch"),
                     "policy_digest": answer.get("policy_digest"),
                     "expires_at": answer.get("expires_at"),
                     "status_expires_at": answer.get("status_expires_at"),
                     "policy": answer.get("policy")})
        self._keys.data["link_grants"][link["id"]] = answer["grant"]
        self._keys.save()

    def _link(self, link_id: str) -> tuple[dict, str]:
        with self._lock:
            link = self._state.data["links"].get(link_id)
            grant = self._keys.data["link_grants"].get(link_id, "")
        if link is None:
            raise RoomPeerError("unknown_link", 404)
        if link.get("status") != "active" or not grant:
            raise RoomPeerError(f"link_{link.get('status') or 'inactive'}", 409)
        return link, grant

    async def renew(self, link_id: str) -> dict:
        link, grant = self._link(link_id)
        status, answer = await self._exchange(link["target_url"], PATH_RENEW, link["target_key"],
                                              {"v": 1}, grant)
        if status != 200 or not answer.get("ok"):
            reason = answer.get("reason") or answer.get("error") or "renew_refused"
            self._mark_link(link_id, reason)
            self._record("roompeer.renew_refused", reason, link=link_id)
            return {"ok": False, "reason": reason}
        with self._lock:
            self._apply_grant(link, answer)
            self._state.save()
        self._record("roompeer.renewed_link", link_id, epoch=answer.get("epoch"))
        return {"ok": True, "link": _pick(link, _LINK_FIELDS)}

    def _mark_link(self, link_id: str, reason: str) -> None:
        with self._lock:
            link = self._state.data["links"].get(link_id)
            if link is None:
                return
            link["last_reason"] = reason
            if reason in ("membership_revoked", "room_reauthorization_required", "room_gone"):
                link["status"] = "revoked" if reason == "membership_revoked" else "needs_invitation"
                self._keys.data["link_grants"].pop(link_id, None)
                self._keys.save()
            self._state.save()

    async def remote_call(self, link_id: str, tool: str, args: dict | None = None, *,
                          op: str = "dispatch", task_id: int | None = None) -> dict:
        if not self.enabled():
            raise RoomPeerError("room_peers_disabled", 404)
        if self._kill is not None and self._kill.is_halted("global"):
            return {"ok": False, "reason": "kill_switch_engaged"}
        body = {"v": 1, "op": op}
        if op == "dispatch":
            body.update({"tool": str(tool or ""), "args": dict(args or {})})
        else:
            body["task_id"] = task_id
        for attempt in (0, 1):
            link, grant = self._link(link_id)
            status, answer = await self._exchange(link["target_url"], PATH_CALL, link["target_key"],
                                                  body, grant)
            reason = answer.get("reason") or ""
            if attempt == 0 and status == 403 and reason in ("room_epoch_stale", "grant_expired"):
                renewed = await self.renew(link_id)
                if renewed.get("ok"):
                    continue
                answer = renewed
            break
        if status in (401, 403, 410) and reason:
            self._mark_link(link_id, reason)
        self._record("roompeer.remote_call", str(tool or op), link=link_id, status=status,
                     reason=reason, task_id=answer.get("task_id"))
        answer = dict(answer)
        answer.setdefault("status_code", status)
        return answer

    def leave(self, link_id: str) -> dict:
        with self._lock:
            link = self._state.data["links"].pop(link_id, None)
            self._keys.data["link_grants"].pop(link_id, None)
            self._keys.save()
            self._state.save()
        if link is None:
            raise RoomPeerError("unknown_link", 404)
        self._record("roompeer.left", link_id, room=link.get("room_id"))
        return {"left": link_id}
