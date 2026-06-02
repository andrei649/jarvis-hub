"""
secrets.py — Encrypted-at-rest secret store (H12.1).

The "anti-OpenClaw" story: nothing sensitive (API keys, channel tokens, SOUL
fragments, memory excerpts) is ever written to disk in plaintext. Everything
goes through this `SecretStore`, which encrypts values at rest.

Key-derivation story (explicit on purpose):

1. A master key is read from the ``JARVIS_SECRET_KEY`` environment variable
   when present. It may be a raw 32-byte urlsafe-base64 Fernet key, or any
   passphrase — a passphrase is stretched with PBKDF2-HMAC-SHA256 (390k
   iterations) over a per-store salt that lives next to the encrypted file.
2. If the env var is absent, a random 32-byte key is generated on first use and
   persisted to a sibling ``*.key`` file with ``0600`` permissions. This keeps
   local-first deployments working with zero configuration while never leaving
   secrets in plaintext.

Backends:

- Preferred: ``cryptography``'s Fernet (AES-128-CBC + HMAC-SHA256, authenticated).
- Pure-Python fallback (no ``cryptography`` installed): an HMAC-SHA256 keystream
  XOR cipher with an appended HMAC tag. This is intentionally simple and clearly
  labelled — it keeps secrets off disk in plaintext when the optional dependency
  is missing, but Fernet is the recommended path.

On-disk format is a JSON map ``{name: token}`` where each ``token`` is the
self-describing ciphertext produced by the active backend.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.secrets")

DEFAULT_STORE = Path("memory_logs") / "security" / "secrets.enc"

_PBKDF2_ITERATIONS = 390_000
_FALLBACK_PREFIX = b"xhmac1:"  # marks pure-Python fallback ciphertext


# ── cryptography availability ──────────────────────────────────────
try:  # pragma: no cover - import guard
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore

    _HAS_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - exercised only without the dep
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore
    _HAS_CRYPTOGRAPHY = False


class SecretStoreError(Exception):
    """Raised when a secret cannot be decrypted (wrong key / corruption)."""


def _derive_key(passphrase: bytes, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 → 32-byte urlsafe-base64 key (Fernet-compatible)."""
    raw = hashlib.pbkdf2_hmac("sha256", passphrase, salt, _PBKDF2_ITERATIONS, dklen=32)
    return base64.urlsafe_b64encode(raw)


def _looks_like_fernet_key(value: str) -> bool:
    """A raw Fernet key is 32 url-safe-base64 bytes → 44 chars ending in '='."""
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
        return len(decoded) == 32
    except Exception:
        return False


class SecretStore:
    """Encrypts secrets at rest. Drop-in get/set/delete dict-like API."""

    def __init__(self, path: Optional[str | Path] = None, *, key: Optional[str] = None):
        self.path = Path(path) if path else DEFAULT_STORE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key_b64 = self._resolve_key(key)
        self._cache: dict[str, str] = {}
        self._loaded = False

    # ── key management ────────────────────────────────────────────
    def _salt_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".salt")

    def _keyfile_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".key")

    def _resolve_key(self, explicit: Optional[str]) -> bytes:
        """Return a 32-byte urlsafe-base64 key, deriving/persisting as needed."""
        env_key = explicit if explicit is not None else os.environ.get("JARVIS_SECRET_KEY", "")
        if env_key:
            if _looks_like_fernet_key(env_key):
                return env_key.encode("ascii")
            # Passphrase → stretch over a persisted per-store salt.
            return _derive_key(env_key.encode("utf-8"), self._load_or_create_salt())
        # No configured key → generate + persist a random key (0600).
        return self._load_or_create_keyfile()

    def _load_or_create_salt(self) -> bytes:
        sp = self._salt_path()
        if sp.exists():
            return sp.read_bytes()
        salt = _secrets.token_bytes(16)
        sp.write_bytes(salt)
        _chmod_600(sp)
        return salt

    def _load_or_create_keyfile(self) -> bytes:
        kp = self._keyfile_path()
        if kp.exists():
            return kp.read_bytes().strip()
        key = base64.urlsafe_b64encode(_secrets.token_bytes(32))
        kp.write_bytes(key)
        _chmod_600(kp)
        logger.info("Generated new secret-store key at %s (0600)", kp)
        return key

    # ── encryption backends ───────────────────────────────────────
    def _encrypt(self, plaintext: str) -> str:
        data = plaintext.encode("utf-8")
        if _HAS_CRYPTOGRAPHY:
            return Fernet(self._key_b64).encrypt(data).decode("ascii")
        return self._fallback_encrypt(data)

    def _decrypt(self, token: str) -> str:
        raw = token.encode("ascii")
        if raw.startswith(_FALLBACK_PREFIX):
            return self._fallback_decrypt(raw)
        if _HAS_CRYPTOGRAPHY:
            try:
                return Fernet(self._key_b64).decrypt(raw).decode("utf-8")
            except InvalidToken as e:
                raise SecretStoreError("cannot decrypt secret (wrong key or corrupted)") from e
        raise SecretStoreError(
            "ciphertext requires the 'cryptography' package, which is not installed"
        )

    def _fallback_encrypt(self, data: bytes) -> str:
        """Pure-Python: HMAC-SHA256 keystream XOR + HMAC-SHA256 tag."""
        key = base64.urlsafe_b64decode(self._key_b64)
        nonce = _secrets.token_bytes(16)
        keystream = _hmac_keystream(key, nonce, len(data))
        cipher = bytes(a ^ b for a, b in zip(data, keystream))
        tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        blob = nonce + tag + cipher
        return (_FALLBACK_PREFIX + base64.urlsafe_b64encode(blob)).decode("ascii")

    def _fallback_decrypt(self, token: bytes) -> str:
        key = base64.urlsafe_b64decode(self._key_b64)
        try:
            blob = base64.urlsafe_b64decode(token[len(_FALLBACK_PREFIX):])
        except (ValueError, binascii.Error) as e:
            raise SecretStoreError("cannot decrypt secret (corrupted ciphertext)") from e
        nonce, tag, cipher = blob[:16], blob[16:48], blob[48:]
        expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise SecretStoreError("cannot decrypt secret (wrong key or corrupted)")
        keystream = _hmac_keystream(key, nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, keystream)).decode("utf-8")

    # ── persistence ───────────────────────────────────────────────
    def _load(self) -> dict[str, str]:
        if self._loaded:
            return self._cache
        if self.path.exists():
            try:
                self._cache = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Secret store unreadable (%s); starting empty", e)
                self._cache = {}
        else:
            self._cache = {}
        self._loaded = True
        return self._cache

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        _chmod_600(tmp)
        tmp.replace(self.path)
        _chmod_600(self.path)

    # ── public API ────────────────────────────────────────────────
    def set(self, name: str, value: str) -> None:
        store = self._load()
        store[name] = self._encrypt(value)
        self._flush()

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        store = self._load()
        token = store.get(name)
        if token is None:
            return default
        return self._decrypt(token)

    def delete(self, name: str) -> bool:
        store = self._load()
        if name in store:
            del store[name]
            self._flush()
            return True
        return False

    def names(self) -> list[str]:
        return sorted(self._load().keys())

    def __contains__(self, name: str) -> bool:
        return name in self._load()

    @property
    def backend(self) -> str:
        return "fernet" if _HAS_CRYPTOGRAPHY else "hmac-fallback"

    # ── migration helper ──────────────────────────────────────────
    def migrate_plaintext(self, items: dict[str, str], *, overwrite: bool = False) -> int:
        """Encrypt a batch of plaintext secrets (e.g. from a .env dump).

        Returns the number of secrets written. Existing names are skipped
        unless ``overwrite=True``.
        """
        store = self._load()
        written = 0
        for name, value in items.items():
            if value is None:
                continue
            if name in store and not overwrite:
                continue
            store[name] = self._encrypt(str(value))
            written += 1
        if written:
            self._flush()
        return written


def _hmac_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Deterministic keystream from HMAC-SHA256 in counter mode."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _chmod_600(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows/odd FS
        pass
