"""H127 — Matrix end-to-end encryption: the trust layer, and no plaintext downgrade.

What exists. :class:`~agents.core.channels.webhook_channels.MatrixChannel` speaks the
client-server API with a bearer token. Until this module it posted a plaintext
``m.room.message`` into any room — an *encrypted* room included, where every other
member's client shows it as "not encrypted" — and silently dropped every
``m.room.encrypted`` event it received.

What this module adds, with the ``cryptography`` package the hub already pins:

* **Encrypted-room detection** (:func:`room_encryption`): ``GET
  /rooms/{room}/state/m.room.encryption`` — 200 with an ``algorithm`` is encrypted, 404
  is not, anything else is *unknown* and treated as encrypted (fail closed). Cached per
  room for :data:`ROOM_CACHE_SECONDS`; encryption in Matrix cannot be turned off.
* **No plaintext downgrade** (:func:`send_decision`): a send into an encrypted room is
  refused while Nerva cannot encrypt — which is today, see below — unless the owner set
  the channel's ``encrypted_rooms`` to ``allow_plaintext``. Once an Olm/Megolm backend is
  present, a send to a room with a device the owner has not verified is refused unless
  ``allow_unverified_devices`` is on.
* **Proxy mode** (``encrypted_rooms: proxy``): the owner points ``homeserver`` at a local
  E2EE proxy such as pantalaimon, which encrypts and decrypts for this client; honoured
  only for a loopback homeserver URL, so plaintext never leaves the machine.
* **Device verification** (:func:`verify_device_keys`, :func:`verify_cross_signed`):
  device keys from ``/keys/query`` are checked against their own Ed25519 self-signature
  over the spec's canonical JSON, and a device can be trusted through the user's
  cross-signing keys (master → self-signing → device) once the owner has verified that
  user's master key. Trust is the owner's: :class:`DeviceTrustStore` records the
  fingerprints the owner compared out of band, in an encrypted store under the data dir
  (``<data>/matrix/crypto_store.enc``, the hub's ``SecretStore``: Fernet, key in the
  protected key file), never in ``.env`` and never readable through a secret handle.
  A key that changed for a verified device is *not* trusted (``changed``).
  Without ``JARVIS_SECRET_KEY`` the store's key file sits beside it (``.key``, 0600), so the
  encryption protects a copied store, not a reader of the data dir.
* **Encrypted inbound is visible** (:func:`note_undecryptable`): an ``m.room.encrypted``
  event is counted per room and logged once per room, instead of disappearing.

What it does not do — the honest gap. Olm (pairwise, double ratchet over Curve25519)
and Megolm (group ratchet) are not implemented here: neither ``matrix-nio[e2e]``,
``python-olm`` nor ``vodozemac`` is pinned in the requirements, and hand-rolled ratchet
code is the wrong place to economise. :func:`olm_backend` reports which one is
importable (none today), so ``can_encrypt`` stays False and encrypted rooms stay
refused (or go through the owner's local proxy). Key backup and secret-storage recovery
(``MATRIX_RECOVERY_KEY``) are not built either.

Owner tools: ``python -m agents.core.channels.matrix_e2ee`` (``status``, ``devices``,
``verify USER DEVICE ED25519``, ``verify-master USER KEY``, ``revoke USER DEVICE``).
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import logging
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("jarvis.channels.matrix_e2ee")

#: How long an *unencrypted* answer is trusted: a room can be switched to encrypted at any
#: time, so this is short (review); an encrypted answer never expires.
ROOM_CACHE_SECONDS = 30.0
ENCRYPTED_ROOMS_REFUSE = "refuse"
ENCRYPTED_ROOMS_ALLOW_PLAINTEXT = "allow_plaintext"
#: The homeserver URL is a local E2EE proxy (pantalaimon) that encrypts and decrypts for
#: this client; only honoured for a loopback homeserver, so plaintext never crosses a network.
ENCRYPTED_ROOMS_PROXY = "proxy"
_DEVICE = re.compile(r"[A-Za-z0-9._=+/-]{1,128}\Z")
_STORE_ENTRY = "matrix.trust"
_LOCK = threading.Lock()


# ── canonical JSON and signatures (Matrix spec, appendices: signing JSON) ─────

def canonical_json(value: Any) -> bytes:
    """The spec's canonical JSON: sorted keys, no insignificant whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _unpadded_b64decode(text: str) -> bytes:
    if not isinstance(text, str) or not text or len(text) > 128:
        raise ValueError("bad base64")
    return base64.b64decode(text + "=" * (-len(text) % 4), validate=True)


def _signable(obj: Mapping[str, Any]) -> dict:
    return {k: v for k, v in obj.items() if k not in ("signatures", "unsigned")}


def verify_signature(obj: Mapping[str, Any], user_id: str, key_id: str, public_key: str) -> bool:
    """Whether *obj* carries a valid Ed25519 signature by ``user_id``/``key_id``."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        sig = obj["signatures"][user_id][key_id]
        key = Ed25519PublicKey.from_public_bytes(_unpadded_b64decode(public_key))
        key.verify(_unpadded_b64decode(sig), canonical_json(_signable(obj)))
        return True
    except Exception:
        return False


def verify_device_keys(device: Mapping[str, Any], user_id: str, device_id: str) -> str | None:
    """The device's Ed25519 key when ``/keys/query`` returned a well-formed, self-signed
    entry for exactly this user and device; None otherwise."""
    if not isinstance(device, Mapping):
        return None
    if device.get("user_id") != user_id or device.get("device_id") != device_id:
        return None
    keys = device.get("keys")
    if not isinstance(keys, Mapping):
        return None
    ed = keys.get(f"ed25519:{device_id}")
    try:
        if len(_unpadded_b64decode(ed)) != 32:
            return None
    except Exception:
        return None
    return ed if verify_signature(device, user_id, f"ed25519:{device_id}", ed) else None


def _single_key(cross_key: Mapping[str, Any], user_id: str, usage: str) -> tuple[str, str] | None:
    if not isinstance(cross_key, Mapping) or cross_key.get("user_id") != user_id:
        return None
    usages = cross_key.get("usage")
    keys = cross_key.get("keys")
    if not isinstance(usages, list) or usage not in usages or not isinstance(keys, Mapping):
        return None
    if len(keys) != 1:
        return None
    key_id, key = next(iter(keys.items()))
    if not (isinstance(key_id, str) and key_id.startswith("ed25519:") and isinstance(key, str)):
        return None
    return key_id, key


def verify_cross_signed(device: Mapping[str, Any], user_id: str, device_id: str,
                        master: Mapping[str, Any], self_signing: Mapping[str, Any],
                        trusted_master: str) -> bool:
    """A device trusted through cross-signing: the owner verified the user's master key
    (*trusted_master*), the self-signing key is signed by it, and the device is signed
    by the self-signing key (and by itself)."""
    if verify_device_keys(device, user_id, device_id) is None:
        return False
    m = _single_key(master, user_id, "master")
    s = _single_key(self_signing, user_id, "self_signing")
    if m is None or s is None or m[1] != trusted_master:
        return False
    return (verify_signature(self_signing, user_id, m[0], m[1])
            and verify_signature(device, user_id, s[0], s[1]))


def fingerprint(ed25519_key: str) -> str:
    """The key as people compare it: groups of four characters."""
    return " ".join(ed25519_key[i:i + 4] for i in range(0, len(ed25519_key), 4))


# ── the backend that would encrypt ───────────────────────────────────────────

def olm_backend() -> str | None:
    """The Olm/Megolm implementation importable here, or None. None is pinned today."""
    for module in ("vodozemac", "olm"):
        try:
            if importlib.util.find_spec(module) is not None:
                return module
        except Exception:  # nosec B112 — a broken import path reads as absent
            logger.debug("olm backend probe failed for %s", module)
    return None


def can_encrypt() -> bool:
    """Whether this hub can send Megolm-encrypted events. False until a backend is pinned
    *and* wired; a merely importable module does not make it True."""
    return False


# ── the owner's trust decisions, encrypted at rest ───────────────────────────

class DeviceTrustStore:
    """Verified device and master keys per Matrix user, in the hub's encrypted store."""

    def __init__(self, path: Path | None = None, *, store: Any = None) -> None:
        self._path = path
        self._store = store

    def _secret_store(self):
        if self._store is None:
            from agents.core.paths import data_path
            from agents.core.secrets import SecretStore

            path = self._path or data_path("matrix", "crypto_store.enc")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._store = SecretStore(path)
        return self._store

    def _load(self) -> dict:
        raw = self._secret_store().get(_STORE_ENTRY)
        if not raw:
            return {"devices": {}, "masters": {}}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("matrix trust store malformed")
        data.setdefault("devices", {})
        data.setdefault("masters", {})
        return data

    def _save(self, data: dict) -> None:
        self._secret_store().set(_STORE_ENTRY, json.dumps(data, sort_keys=True))

    @staticmethod
    def _check(user_id: str, device_id: str | None, key: str) -> None:
        from .webhook_channels import _matrix_id

        if not _matrix_id(user_id, "@"):
            raise ValueError("user id must look like @name:server")
        if device_id is not None and not _DEVICE.fullmatch(device_id or ""):
            raise ValueError("bad device id")
        try:
            if len(_unpadded_b64decode(key)) != 32:
                raise ValueError
        except Exception:
            raise ValueError("key must be an unpadded base64 Ed25519 key") from None

    def verify_device(self, user_id: str, device_id: str, ed25519_key: str) -> dict:
        key = ed25519_key.replace(" ", "")
        self._check(user_id, device_id, key)
        with _LOCK:
            data = self._load()
            data["devices"].setdefault(user_id, {})[device_id] = {"ed25519": key, "at": time.time()}
            self._save(data)
        return {"user_id": user_id, "device_id": device_id, "fingerprint": fingerprint(key)}

    def verify_master(self, user_id: str, master_key: str) -> dict:
        key = master_key.replace(" ", "")
        self._check(user_id, None, key)
        with _LOCK:
            data = self._load()
            data["masters"][user_id] = {"ed25519": key, "at": time.time()}
            self._save(data)
        return {"user_id": user_id, "fingerprint": fingerprint(key)}

    def revoke(self, user_id: str, device_id: str | None = None) -> bool:
        with _LOCK:
            data = self._load()
            if device_id is None:
                found = data["masters"].pop(user_id, None) is not None
            else:
                found = data["devices"].get(user_id, {}).pop(device_id, None) is not None
            self._save(data)
        return found

    def master(self, user_id: str) -> str | None:
        row = self._load()["masters"].get(user_id)
        return row.get("ed25519") if isinstance(row, dict) else None

    def device_state(self, user_id: str, device_id: str, current_key: str | None,
                     *, master: Mapping | None = None, self_signing: Mapping | None = None,
                     device: Mapping | None = None) -> str:
        """``verified`` | ``cross_signed`` | ``changed`` (a verified device now shows another
        key) | ``unverified``."""
        row = self._load()["devices"].get(user_id, {}).get(device_id)
        if isinstance(row, dict):
            return "verified" if current_key and row.get("ed25519") == current_key else "changed"
        trusted = self.master(user_id)
        if (trusted and device is not None and master is not None and self_signing is not None
                and verify_cross_signed(device, user_id, device_id, master, self_signing, trusted)):
            return "cross_signed"
        return "unverified"

    def listing(self) -> dict:
        data = self._load()
        return {
            "devices": [{"user_id": u, "device_id": d, "fingerprint": fingerprint(r.get("ed25519", ""))}
                        for u, rows in sorted(data["devices"].items()) for d, r in sorted(rows.items())],
            "masters": [{"user_id": u, "fingerprint": fingerprint(r.get("ed25519", ""))}
                        for u, r in sorted(data["masters"].items())],
        }


# ── per-room state and the send decision ─────────────────────────────────────

def valid_room_id(room: Any) -> bool:
    """A Matrix room id as the spec bounds it, and safe in a URL path: ``!local:server``,
    printable, no whitespace, no ``/`` or ``\\`` and no dot segment (review)."""
    from .webhook_channels import _matrix_id

    if not _matrix_id(room, "!") or "/" in room or "\\" in room:
        return False
    local = room[1:].split(":", 1)[0]
    return local not in ("", ".", "..")


def quote_room(room: str) -> str:
    """The one quoting used for a room id in every request path (the encryption check and
    the send), so both name the same room."""
    return quote(room, safe="!:")


@dataclass(frozen=True)
class RoomEncryption:
    encrypted: bool
    algorithm: str = ""
    known: bool = True


_room_cache: dict[str, tuple[float, RoomEncryption]] = {}
_undecryptable: dict[str, int] = {}


def reset_for_tests() -> None:
    _room_cache.clear()
    _undecryptable.clear()


async def room_encryption(transport: Any, homeserver: str, token: str, room: str,
                          *, now: float | None = None) -> RoomEncryption:
    """Whether *room* is encrypted. An answer the hub cannot read is *unknown*, which the
    send decision treats as encrypted."""
    now = time.monotonic() if now is None else now
    cached = _room_cache.get(room)
    if cached and cached[0] > now and cached[1].known:
        return cached[1]
    if not valid_room_id(room):
        return RoomEncryption(True, known=False)
    url = (f"{homeserver.rstrip('/')}/_matrix/client/v3/rooms/{quote_room(room)}"
           "/state/m.room.encryption/")
    try:
        resp = await transport.request("GET", url, headers={"Authorization": f"Bearer {token}"}, json=None)
        status = getattr(resp, "status_code", None)
        if status == 404:
            # Only the spec's "no such state event" (404 M_NOT_FOUND, JSON) means the room
            # is not encrypted. 404 M_UNRECOGNIZED (an endpoint the server or a proxy does
            # not route), an HTML error page, or anything else is unknown (review).
            try:
                body = resp.json()
            except Exception:
                body = None
            if isinstance(body, dict) and body.get("errcode") == "M_NOT_FOUND":
                state = RoomEncryption(False)
            else:
                state = RoomEncryption(True, known=False)
        elif status == 200:
            body = resp.json()
            algorithm = body.get("algorithm") if isinstance(body, dict) else None
            state = RoomEncryption(True, algorithm if isinstance(algorithm, str) else "")
        else:
            state = RoomEncryption(True, known=False)
    except Exception:
        logger.debug("matrix room encryption state unavailable", exc_info=True)
        state = RoomEncryption(True, known=False)
    if state.known:
        if len(_room_cache) > 1024:
            _room_cache.clear()
        # Encryption cannot be switched off in a room: an encrypted answer never expires.
        expiry = float("inf") if state.encrypted else now + ROOM_CACHE_SECONDS
        _room_cache[room] = (expiry, state)
    return state


@dataclass(frozen=True)
class SendDecision:
    allowed: bool
    reason: str
    encrypt: bool = False


def send_decision(state: RoomEncryption, config: Mapping[str, Any], *,
                  devices_verified: bool | None = None) -> SendDecision:
    """May a message go into this room, and how?"""
    if not state.encrypted:
        return SendDecision(True, "room_not_encrypted")
    if can_encrypt():
        if devices_verified is False and config.get("allow_unverified_devices") is not True:
            return SendDecision(False, "unverified_devices")
        return SendDecision(True, "encrypted", encrypt=True)
    mode = config.get("encrypted_rooms")
    if mode == ENCRYPTED_ROOMS_PROXY:
        if _loopback(str(config.get("homeserver") or "")):
            return SendDecision(True, "encrypted_by_local_proxy")
        return SendDecision(False, "proxy_not_loopback")
    if mode == ENCRYPTED_ROOMS_ALLOW_PLAINTEXT and state.known:
        return SendDecision(True, "plaintext_allowed_by_owner")
    return SendDecision(False, "e2ee_unavailable" if state.known else "encryption_state_unknown")


def _loopback(url: str) -> bool:
    import ipaddress
    from urllib.parse import urlsplit

    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def note_undecryptable(room: str) -> int:
    """Count an ``m.room.encrypted`` event Nerva could not read; log once per room."""
    count = _undecryptable.get(room, 0) + 1
    if len(_undecryptable) > 1024 and room not in _undecryptable:
        _undecryptable.clear()
    _undecryptable[room] = count
    if count == 1:
        logger.warning("matrix: an end-to-end encrypted message in %s could not be read "
                       "(no Olm/Megolm backend); it was not answered", room[:64])
    return count


def status(config: Mapping[str, Any] | None = None) -> dict:
    config = config or {}
    return {
        "olm_backend": olm_backend(),
        "can_encrypt": can_encrypt(),
        "encrypted_rooms": config.get("encrypted_rooms") or ENCRYPTED_ROOMS_REFUSE,
        "allow_unverified_devices": config.get("allow_unverified_devices") is True,
        "undecryptable": dict(_undecryptable),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agents.core.channels.matrix_e2ee",
                                     description="Matrix end-to-end encryption trust (H127)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("devices")
    v = sub.add_parser("verify", help="trust a device whose Ed25519 key you compared out of band")
    v.add_argument("user_id")
    v.add_argument("device_id")
    v.add_argument("ed25519_key")
    m = sub.add_parser("verify-master", help="trust a user's cross-signing master key")
    m.add_argument("user_id")
    m.add_argument("master_key")
    r = sub.add_parser("revoke")
    r.add_argument("user_id")
    r.add_argument("device_id", nargs="?")
    args = parser.parse_args(argv)
    store = DeviceTrustStore()
    try:
        if args.cmd == "status":
            # The undecryptable counters live in the running hub's process; this command
            # cannot see them (they are logged there), so it does not claim any.
            out: Any = {k: v for k, v in status().items() if k != "undecryptable"}
            out["undecryptable"] = "logged by the running hub (one warning per room)"
        elif args.cmd == "devices":
            out = store.listing()
        elif args.cmd == "verify":
            out = store.verify_device(args.user_id, args.device_id, args.ed25519_key)
        elif args.cmd == "verify-master":
            out = store.verify_master(args.user_id, args.master_key)
        else:
            out = {"revoked": store.revoke(args.user_id, args.device_id)}
    except ValueError as exc:
        print(f"refused: {exc}")
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
