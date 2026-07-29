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
import threading
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.secrets")

# Serializes key/salt CREATION across threads in this process. `O_CREAT | O_EXCL`
# already makes it atomic against other processes; this closes the same race for the
# two worker threads `asyncio.to_thread` hands the backup routes.
_KEY_MATERIAL_LOCK = threading.Lock()

DEFAULT_STORE = data_path("security", "secrets.enc")

_PBKDF2_ITERATIONS = 390_000
_FALLBACK_PREFIX = b"xhmac1:"  # marks pure-Python fallback ciphertext (str API)
_FALLBACK_PREFIX_BYTES = b"xhmacb1:"  # marks pure-Python fallback ciphertext (bytes API)


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

    def _read_or_create_atomically(self, path: Path, mint) -> bytes:
        """Return *path*'s bytes, creating it from ``mint()`` iff it does not exist.

        First writer wins, and every loser reads what the winner wrote. Both call
        sites used to be `if path.exists(): read` / else `generate; write`, which is
        a check-then-act on key material — the worst place for one. Two callers that
        interleave each mint DIFFERENT material and each write it; the last write
        wins, and anything the loser already encrypted with its own key can never be
        decrypted again.

        That is reachable: `POST /api/admin/backup` and `/api/admin/backup/verify`
        both offload to real worker threads via `asyncio.to_thread`, and each builds
        a fresh SecretStore. On a first backup with JARVIS_BACKUP_KEY set as a
        passphrase, two concurrent requests race for the salt — and the archive
        written by the loser is unrecoverable, permanently, with verify reporting
        failure on it forever.

        `O_CREAT | O_EXCL` makes creation atomic against other processes; the
        module lock serializes threads within this one. On the losing branch we
        RE-READ rather than re-generate, which is the whole point.

        `O_BINARY` is not optional on Windows. Without it the CRT opens the
        descriptor in TEXT mode and rewrites every 0x0A byte to 0x0D 0x0A on the
        way out — so the creator returns the 16 random bytes it minted while every
        later reader reads 17 different ones, and the two derive different keys.
        A random salt trips it ~6% of the time (1 - (255/256)**16), silently, and
        the only symptom is "cannot decrypt secret (wrong key or corrupted)"
        against data that was written correctly. The read side is already binary
        (`read_bytes`), which is exactly what makes the halves disagree.
        """
        with _KEY_MATERIAL_LOCK:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                return path.read_bytes()
            try:
                material = mint()
                with os.fdopen(fd, "wb") as fh:   # os.write may write short; this may not
                    fd = None                     # fdopen owns it now — no double close
                    fh.write(material)
            finally:
                if fd is not None:
                    os.close(fd)
            _chmod_600(path)  # belt and braces: O_EXCL's mode is subject to umask
            return material

    def _load_or_create_salt(self) -> bytes:
        return self._read_or_create_atomically(
            self._salt_path(), lambda: _secrets.token_bytes(16))

    def _load_or_create_keyfile(self) -> bytes:
        kp = self._keyfile_path()
        existed = kp.exists()
        key = self._read_or_create_atomically(
            kp, lambda: base64.urlsafe_b64encode(_secrets.token_bytes(32)))
        if not existed:
            # FP: logs the key file path (kp), not the key bytes; the rule matches the message text.
            # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
            logger.info("Generated new secret-store key at %s (0600)", kp)
        return key.strip()

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

    def _fallback_encrypt_bytes(self, data: bytes) -> bytes:
        """Pure-Python core: HMAC-SHA256 keystream XOR + HMAC-SHA256 tag → raw blob."""
        key = base64.urlsafe_b64decode(self._key_b64)
        nonce = _secrets.token_bytes(16)
        keystream = _hmac_keystream(key, nonce, len(data))
        cipher = bytes(a ^ b for a, b in zip(data, keystream))
        tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        return nonce + tag + cipher

    def _fallback_decrypt_bytes(self, blob: bytes) -> bytes:
        key = base64.urlsafe_b64decode(self._key_b64)
        nonce, tag, cipher = blob[:16], blob[16:48], blob[48:]
        expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise SecretStoreError("cannot decrypt secret (wrong key or corrupted)")
        keystream = _hmac_keystream(key, nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, keystream))

    def _fallback_encrypt(self, data: bytes) -> str:
        """Pure-Python: HMAC-SHA256 keystream XOR + HMAC-SHA256 tag (base64 str token)."""
        blob = self._fallback_encrypt_bytes(data)
        return (_FALLBACK_PREFIX + base64.urlsafe_b64encode(blob)).decode("ascii")

    def _fallback_decrypt(self, token: bytes) -> str:
        try:
            blob = base64.urlsafe_b64decode(token[len(_FALLBACK_PREFIX):])
        except (ValueError, binascii.Error) as e:
            raise SecretStoreError("cannot decrypt secret (corrupted ciphertext)") from e
        return self._fallback_decrypt_bytes(blob).decode("utf-8")

    # ── public at-rest cipher (no persistence) ─────────────────────
    # Exposed so other stores (settings_db secret columns, backup archives) can
    # reuse this one key-managed cipher instead of re-implementing Fernet/fallback.
    def encrypt_value(self, plaintext: str) -> str:
        """Encrypt a single string value; returns a self-describing token."""
        return self._encrypt(plaintext)

    def decrypt_value(self, token: str) -> str:
        """Inverse of :meth:`encrypt_value`."""
        return self._decrypt(token)

    def encrypt_bytes(self, data: bytes) -> bytes:
        """Encrypt arbitrary bytes (e.g. a backup archive) → self-describing token."""
        if _HAS_CRYPTOGRAPHY:
            return Fernet(self._key_b64).encrypt(data)
        return _FALLBACK_PREFIX_BYTES + self._fallback_encrypt_bytes(data)

    def decrypt_bytes(self, token: bytes) -> bytes:
        """Inverse of :meth:`encrypt_bytes`."""
        if token.startswith(_FALLBACK_PREFIX_BYTES):
            return self._fallback_decrypt_bytes(token[len(_FALLBACK_PREFIX_BYTES):])
        if _HAS_CRYPTOGRAPHY:
            try:
                return Fernet(self._key_b64).decrypt(token)
            except InvalidToken as e:
                raise SecretStoreError("cannot decrypt (wrong key or corrupted)") from e
        raise SecretStoreError(
            "ciphertext requires the 'cryptography' package, which is not installed"
        )

    # ── persistence ───────────────────────────────────────────────
    def _load(self) -> dict[str, str]:
        if self._loaded:
            return self._cache
        if self.path.exists():
            try:
                self._cache = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                # FP: logs the exception, not any stored secret; the rule matches the message text.
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                logger.warning("Secret store unreadable (%s); starting empty", e)
                self._cache = {}
        else:
            self._cache = {}
        self._loaded = True
        return self._cache

    def _flush(self) -> None:
        # A UNIQUE temp file per write. This used to be one shared
        # `secrets.enc.tmp`: two concurrent writers both created it, the first
        # `replace()` consumed it, and the second raised
        # `FileNotFoundError: secrets.enc.tmp -> secrets.enc`, losing that write
        # entirely. mkstemp also creates at 0600, so the plaintext-free invariant
        # holds even in the window before the chmod.
        import tempfile

        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, ensure_ascii=False)
            _chmod_600(tmp)
            tmp.replace(self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)   # never leave a stray secrets file behind
            raise
        _chmod_600(self.path)

    def _mutate(self, apply) -> bool:
        """Run a read-modify-write against the store under the process-wide lock.

        `set`/`delete` were read-modify-write over a PER-INSTANCE cache: each
        SecretStore loaded the file once, mutated its own dict, and wrote the whole
        thing back. Two instances writing different names therefore raced, and the
        last writer's file silently lacked the other's secret — a lost credential
        with no error anywhere. Re-reading from disk inside the lock is what makes
        the two writes compose instead of clobbering.

        Scope is this process, which is where the concurrency is (the backup routes
        hand `asyncio.to_thread` two worker threads that each build a store). A
        second *process* writing the same file concurrently would still need an OS
        file lock; nothing in the hub does that today.
        """
        with _KEY_MATERIAL_LOCK:
            self._loaded = False          # discard the cache; another writer may have won
            store = self._load()
            changed = apply(store)
            if changed:
                self._flush()
            return changed

    # ── public API ────────────────────────────────────────────────
    def set(self, name: str, value: str) -> None:
        token = self._encrypt(value)      # encrypt outside the lock; it is pure

        def _apply(store):
            store[name] = token
            return True

        self._mutate(_apply)

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        store = self._load()
        token = store.get(name)
        if token is None:
            return default
        return self._decrypt(token)

    def delete(self, name: str) -> bool:
        def _apply(store):
            return store.pop(name, None) is not None

        return self._mutate(_apply)

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
