"""
e2e_sync.py — H12.13 Opt-in end-to-end encrypted sync between devices.

The home GPU ↔ phone (and any other device the user owns) can sync personal
state, but the transport/server only ever sees **ciphertext**: records are
encrypted on the source device and decrypted only on a destination device that
holds the same shared secret. This preserves local-first/E2E — no plaintext
leaves a device.

Honest crypto, not a stub:
  - Uses ``cryptography`` Fernet (AES-128-CBC + HMAC-SHA256, authenticated) — so
    tampering and wrong-key decryption are *detected*, not silently accepted.
  - The key is derived from a **shared passphrase** (PBKDF2-HMAC-SHA256, 390k
    iters, fixed app salt so two devices with the same passphrase derive the same
    key) or a raw Fernet key. Security rests on the secrecy of that shared secret.
  - **Fail-closed:** if ``cryptography`` is unavailable or no shared secret is
    configured, sync is disabled — there is deliberately **no weak fallback** for
    an E2E feature.
  - **Opt-in:** off unless ``JARVIS_E2E_SYNC`` is set.

What's built here is the full E2E envelope + manifest (encrypt/decrypt,
tamper/own-device handling, digest). The actual device-to-device transport is a
host-side seam: :meth:`build_push` produces a manifest to send; :meth:`apply_pull`
consumes one that arrives.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("jarvis.e2e_sync")

# Fixed app salt: cross-device key derivation must be deterministic so two
# devices with the same passphrase land on the same key. Security comes from the
# passphrase, not the salt.
_SALT = b"jarvis-e2e-sync-v1"
_ENV_FLAG = "JARVIS_E2E_SYNC"
_ENV_KEY = "JARVIS_E2E_SYNC_KEY"


class E2ESyncError(Exception):
    """Raised when a record cannot be decrypted (tamper / wrong key / corrupt)."""


def _crypto():
    """Return the Fernet class, or None if cryptography is unavailable."""
    try:
        from cryptography.fernet import Fernet
        return Fernet
    except Exception:  # pragma: no cover - exercised only without cryptography
        return None


def _looks_like_fernet_key(s: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(s.encode())) == 32
    except Exception:
        return False


def _derive_key(passphrase: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def sync_enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


class E2ESync:
    """End-to-end encrypted sync envelope + manifest."""

    def __init__(self, key: Optional[str] = None, passphrase: Optional[str] = None,
                 device_id: str = "") -> None:
        self.device_id = device_id or os.environ.get("JARVIS_DEVICE_ID", "") or "device"
        self._fernet = None
        Fernet = _crypto()
        if Fernet is None:
            return
        secret = key or os.environ.get(_ENV_KEY, "")
        try:
            if secret and _looks_like_fernet_key(secret):
                self._fernet = Fernet(secret.encode())
            elif passphrase:
                self._fernet = Fernet(_derive_key(passphrase))
            elif secret:  # treat any other configured secret as a passphrase
                self._fernet = Fernet(_derive_key(secret))
        except Exception:
            logger.warning("E2E sync key setup failed — sync disabled", exc_info=True)
            self._fernet = None

    @property
    def available(self) -> bool:
        """Crypto present AND a shared secret configured."""
        return self._fernet is not None

    @property
    def backend(self) -> str:
        if _crypto() is None:
            return "unavailable"
        return "fernet" if self._fernet is not None else "no-key"

    def enabled(self) -> bool:
        return sync_enabled() and self.available

    def status(self) -> dict:
        return {"enabled": self.enabled(), "available": self.available,
                "backend": self.backend, "device_id": self.device_id}

    # ── envelope ─────────────────────────────────────────────────────────────

    def encrypt_record(self, record: dict) -> dict:
        if self._fernet is None:
            raise E2ESyncError("E2E sync unavailable (no crypto / no shared secret)")
        plaintext = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
        token = self._fernet.encrypt(plaintext).decode("ascii")
        return {"v": 1, "device": self.device_id, "ct": token, "ts": time.time()}

    def decrypt_record(self, envelope: dict) -> dict:
        if self._fernet is None:
            raise E2ESyncError("E2E sync unavailable (no crypto / no shared secret)")
        ct = (envelope or {}).get("ct")
        if not ct:
            raise E2ESyncError("envelope has no ciphertext")
        try:
            plaintext = self._fernet.decrypt(ct.encode("ascii"))
        except Exception as e:
            raise E2ESyncError("decryption failed (tamper / wrong key)") from e
        return json.loads(plaintext.decode("utf-8"))

    # ── manifest (the deferred transport works in these units) ───────────────

    def build_push(self, records: "list[dict]", kind: str = "memory") -> dict:
        if not self.enabled():
            return {"enabled": False, "kind": kind, "count": 0, "entries": []}
        entries = [self.encrypt_record(r) for r in (records or [])]
        digest = hashlib.sha256("".join(e["ct"] for e in entries).encode("ascii")).hexdigest()
        return {"enabled": True, "device": self.device_id, "kind": kind,
                "count": len(entries), "entries": entries, "digest": digest}

    def apply_pull(self, manifest: dict) -> "list[dict]":
        """Decrypt a manifest from another device. Skips own-device and any
        entry that fails authentication (never silently trusts bad ciphertext)."""
        if not self.enabled() or not manifest or not manifest.get("entries"):
            return []
        out: list[dict] = []
        for env in manifest["entries"]:
            if env.get("device") == self.device_id:
                continue  # don't re-ingest our own push
            try:
                out.append(self.decrypt_record(env))
            except E2ESyncError:
                logger.warning("E2E sync: dropping unverifiable entry", exc_info=True)
        return out
