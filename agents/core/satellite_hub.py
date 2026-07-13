"""Paired local mic satellites and a contention-guarded inference rail.

H30.6 adds a narrow authenticated identity boundary for room-aware voice.  A
satellite's room comes only from an owner-configured pairing; client event data
can never choose it.  Credentials are held as in-memory digests, bound to one
transport and peer, expire, and require a fresh nonce/timestamp.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("jarvis.satellite_hub")

_MAX_ID = 80
_MAX_ROOM = 80
_MAX_PEER = 128
_MAX_TRANSPORT = 32
_MAX_NONCE = 128
_MIN_NONCE = 8
_MAX_CREDENTIAL = 1_024
_SENSITIVE_META_KEYS = frozenset(
    {"credential", "credential_digest", "password", "secret", "token"}
)


def _text(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{label} is required")
    if len(result) > limit:
        raise ValueError(f"{label} exceeds its size limit")
    return result


def _timestamp(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite timestamp")
    return result


def _credential_digest(token: str) -> str:
    value = _text(token, label="token", limit=_MAX_CREDENTIAL)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _public_meta(meta: Optional[dict]) -> dict:
    if not isinstance(meta, dict):
        return {}
    return {
        str(key)[:80]: value
        for key, value in meta.items()
        if str(key).strip().lower() not in _SENSITIVE_META_KEYS
    }


@dataclass(frozen=True)
class SatellitePairing:
    """Owner-provisioned local identity. Raw credentials are never retained."""

    satellite_id: str
    room_id: str
    credential_digest: str
    allowed_peer: str
    allowed_transport: str
    expires_at: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "satellite_id",
            _text(self.satellite_id, label="satellite_id", limit=_MAX_ID),
        )
        object.__setattr__(self, "room_id", _text(self.room_id, label="room_id", limit=_MAX_ROOM))
        digest = _text(self.credential_digest, label="credential_digest", limit=64).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("credential_digest must be a SHA-256 hex digest")
        object.__setattr__(self, "credential_digest", digest)
        object.__setattr__(
            self,
            "allowed_peer",
            _text(self.allowed_peer, label="allowed_peer", limit=_MAX_PEER),
        )
        object.__setattr__(
            self,
            "allowed_transport",
            _text(
                self.allowed_transport,
                label="allowed_transport",
                limit=_MAX_TRANSPORT,
            ).lower(),
        )
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, label="expires_at"))

    @classmethod
    def from_token(
        cls,
        *,
        satellite_id: str,
        room_id: str,
        token: str,
        allowed_peer: str,
        allowed_transport: str,
        expires_at: float,
    ) -> SatellitePairing:
        return cls(
            satellite_id=satellite_id,
            room_id=room_id,
            credential_digest=_credential_digest(token),
            allowed_peer=allowed_peer,
            allowed_transport=allowed_transport,
            expires_at=expires_at,
        )


@dataclass(frozen=True)
class SatellitePrincipal:
    satellite_id: str
    room_id: str
    peer: str
    transport: str
    authenticated_at: float
    credential_expires_at: float


@dataclass(frozen=True)
class _SatelliteClaim:
    satellite_id: str
    credential: str
    nonce: str
    timestamp: float
    peer: str
    transport: str


def _normalized_claim(
    *,
    satellite_id: object,
    credential: object,
    nonce: object,
    timestamp: object,
    peer: object,
    transport: object,
) -> _SatelliteClaim:
    nonce_value = _text(nonce, label="nonce", limit=_MAX_NONCE)
    if len(nonce_value) < _MIN_NONCE:
        raise ValueError("nonce is too short")
    return _SatelliteClaim(
        satellite_id=_text(satellite_id, label="satellite_id", limit=_MAX_ID),
        credential=_text(credential, label="credential", limit=_MAX_CREDENTIAL),
        nonce=nonce_value,
        timestamp=_timestamp(timestamp, label="timestamp"),
        peer=_text(peer, label="peer", limit=_MAX_PEER),
        transport=_text(transport, label="transport", limit=_MAX_TRANSPORT).lower(),
    )


class NullInference:
    """Offline default — echoes the payload, no GPU or network."""

    async def process(self, kind: str, data) -> dict:
        return {"engine": "null", "kind": kind, "text": str(data)}


class SatelliteHub:
    """Paired satellite registry plus one shared local-inference contention rail."""

    def __init__(
        self,
        inference=None,
        max_concurrency: int = 1,
        *,
        pairings: Iterable[SatellitePairing] = (),
        clock=None,
        max_clock_skew: float = 30.0,
        replay_ttl: float = 120.0,
        max_replay_nonces: int = 1_024,
    ) -> None:
        self._inf = inference or NullInference()
        self.max_concurrency = max(1, int(max_concurrency))
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self._sats: dict[str, dict] = {}
        self._pairings: dict[str, SatellitePairing] = {}
        self._seen_nonces: dict[tuple[str, str], float] = {}
        self._lock = threading.RLock()
        self._inflight = 0
        self._peak_inflight = 0
        self._clock = clock or time.time
        self._max_clock_skew = max(1.0, float(max_clock_skew))
        self._replay_ttl = max(self._max_clock_skew * 2, float(replay_ttl))
        self._max_replay_nonces = max(1, min(int(max_replay_nonces), 10_000))
        for pairing in pairings:
            self.pair(pairing)

    # ── registry / owner pairing ───────────────────────────────────────────

    def register(self, satellite_id: str, meta: Optional[dict] = None) -> dict:
        sid = _text(str(satellite_id), label="satellite_id", limit=_MAX_ID)
        public_meta = _public_meta(meta)
        with self._lock:
            if sid not in self._sats:
                self._sats[sid] = {
                    "id": sid,
                    "meta": public_meta,
                    "calls": 0,
                    "registered_at": float(self._clock()),
                    "last_seen": 0.0,
                }
            elif meta is not None:
                self._sats[sid]["meta"] = public_meta
            return dict(self._sats[sid])

    def pair(self, pairing: SatellitePairing) -> dict:
        if not isinstance(pairing, SatellitePairing):
            raise ValueError("pairing must be a SatellitePairing")
        with self._lock:
            self._pairings[pairing.satellite_id] = pairing
            registered = self.register(
                pairing.satellite_id,
                {"room": pairing.room_id, "paired": True},
            )
            return registered

    def unregister(self, satellite_id: str) -> bool:
        sid = str(satellite_id)
        with self._lock:
            self._pairings.pop(sid, None)
            for key in [key for key in self._seen_nonces if key[0] == sid]:
                self._seen_nonces.pop(key, None)
            return self._sats.pop(sid, None) is not None

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(value) for value in self._sats.values()]

    def get(self, satellite_id: str) -> Optional[dict]:
        with self._lock:
            value = self._sats.get(str(satellite_id))
            return dict(value) if value else None

    def authenticate(
        self,
        *,
        satellite_id: object,
        credential: object,
        nonce: object,
        timestamp: object,
        peer: object,
        transport: object,
    ) -> dict:
        """Validate one local pairing claim and mint a room-bound principal."""
        try:
            claim = _normalized_claim(
                satellite_id=satellite_id,
                credential=credential,
                nonce=nonce,
                timestamp=timestamp,
                peer=peer,
                transport=transport,
            )
        except ValueError:
            return {"ok": False, "reason": "malformed_claim"}

        now = _timestamp(self._clock(), label="clock")
        with self._lock:
            pairing = self._pairings.get(claim.satellite_id)
            if pairing is None:
                return {"ok": False, "reason": "unknown_satellite"}
            refusal = self._pairing_refusal(pairing, claim, now)
            if refusal:
                return {"ok": False, "reason": refusal}
            replay_refusal = self._record_nonce_locked(claim, now)
            if replay_refusal:
                return {"ok": False, "reason": replay_refusal}

            return {
                "ok": True,
                "principal": SatellitePrincipal(
                    satellite_id=claim.satellite_id,
                    room_id=pairing.room_id,
                    peer=claim.peer,
                    transport=claim.transport,
                    authenticated_at=now,
                    credential_expires_at=pairing.expires_at,
                ),
            }

    def _pairing_refusal(
        self,
        pairing: SatellitePairing,
        claim: _SatelliteClaim,
        now: float,
    ) -> str:
        if pairing.allowed_transport != claim.transport:
            return "transport_refused"
        if not hmac.compare_digest(pairing.allowed_peer, claim.peer):
            return "peer_refused"
        if pairing.expires_at < now:
            return "credential_expired"
        if abs(now - claim.timestamp) > self._max_clock_skew:
            return "stale_timestamp"
        if not hmac.compare_digest(
            pairing.credential_digest,
            _credential_digest(claim.credential),
        ):
            return "credential_refused"
        return ""

    def _record_nonce_locked(self, claim: _SatelliteClaim, now: float) -> str:
        for key, expires_at in list(self._seen_nonces.items()):
            if expires_at <= now:
                self._seen_nonces.pop(key, None)
        nonce_key = (claim.satellite_id, claim.nonce)
        if nonce_key in self._seen_nonces:
            return "replayed_nonce"
        if len(self._seen_nonces) >= self._max_replay_nonces:
            return "replay_cache_full"
        self._seen_nonces[nonce_key] = now + self._replay_ttl
        return ""

    def validate_principal(self, principal: object) -> dict:
        """Revalidate a live connection before each room-context selection."""
        if not isinstance(principal, SatellitePrincipal):
            return {"ok": False, "reason": "satellite_identity_refused"}
        now = _timestamp(self._clock(), label="clock")
        with self._lock:
            pairing = self._pairings.get(principal.satellite_id)
            if pairing is None:
                return {"ok": False, "reason": "pairing_revoked"}
            if pairing.expires_at < now or principal.credential_expires_at < now:
                return {"ok": False, "reason": "credential_expired"}
            if not (
                hmac.compare_digest(pairing.room_id, principal.room_id)
                and hmac.compare_digest(pairing.allowed_peer, principal.peer)
                and hmac.compare_digest(pairing.allowed_transport, principal.transport)
                and pairing.expires_at == principal.credential_expires_at
            ):
                return {"ok": False, "reason": "pairing_changed"}
            return {"ok": True}

    # ── inference dispatch ─────────────────────────────────────────────────

    async def dispatch(self, satellite_id: str, payload, kind: str = "transcribe") -> dict:
        sid = str(satellite_id)
        with self._lock:
            if sid not in self._sats:
                return {"ok": False, "reason": "unknown_satellite", "satellite": sid}

        async with self._sem:
            with self._lock:
                self._inflight += 1
                self._peak_inflight = max(self._peak_inflight, self._inflight)
            try:
                result = await self._inf.process(kind, payload)
            except Exception:
                logger.warning("satellite inference failed", exc_info=True)
                with self._lock:
                    self._inflight -= 1
                return {"ok": False, "reason": "inference_error", "satellite": sid}
            with self._lock:
                self._inflight -= 1
                self._sats[sid]["calls"] += 1
                self._sats[sid]["last_seen"] = float(self._clock())
        return {"ok": True, "satellite": sid, "kind": kind, "result": result}

    def stats(self) -> dict:
        with self._lock:
            return {
                "satellites": len(self._sats),
                "paired": len(self._pairings),
                "max_concurrency": self.max_concurrency,
                "peak_inflight": self._peak_inflight,
                "by_satellite": {key: value["calls"] for key, value in self._sats.items()},
            }
