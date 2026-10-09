"""Encrypted, profile-scoped Nous auth state and conservative token usability checks.

JWT decoding here reads expiry and scope metadata only. It does not authenticate a
JWT; the provider remains responsible for signature verification on inference.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore

_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z", re.ASCII)
_MAX_STATE_BYTES = 64 * 1024
_MAX_CIPHERTEXT_CHARS = 256 * 1024
_MAX_JWT_CHARS = 16 * 1024
_BUSY_TIMEOUT_SECONDS = 5


def _profile_name(profile: str) -> str:
    if not isinstance(profile, str) or _PROFILE.fullmatch(profile) is None:
        raise ValueError("invalid Nous profile name")
    return profile


class NousAuthStore:
    """A separate SQLite transaction per profile operation; plaintext is never stored."""

    def __init__(self, path: str | Path | None = None, *, cipher: SecretStore | None = None):
        self.path = Path(path) if path is not None else data_path("security", "nous-auth.sqlite3")
        self._cipher = cipher

    def _get_cipher(self) -> SecretStore:
        if self._cipher is None:
            self._cipher = SecretStore(self.path.with_name("nous-auth-cipher.json"))
        return self._cipher

    def _decode(self, payload: str) -> dict:
        if not isinstance(payload, str) or len(payload) > _MAX_CIPHERTEXT_CHARS:
            raise ValueError("invalid Nous profile state")
        plaintext = self._get_cipher().decrypt_value(payload)
        if len(plaintext.encode("utf-8")) > _MAX_STATE_BYTES:
            raise ValueError("invalid Nous profile state")
        try:
            state = json.loads(plaintext)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Nous profile state") from exc
        if not isinstance(state, dict):
            raise ValueError("invalid Nous profile state")
        return state

    @staticmethod
    def _encode(state: dict) -> str:
        try:
            plaintext = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError("invalid Nous profile state") from exc
        if len(plaintext.encode("utf-8")) > _MAX_STATE_BYTES:
            raise ValueError("Nous profile state exceeds size limit")
        return plaintext

    def read(self, profile: str = "default") -> dict:
        """Return a fresh dict without creating a database or key for absent state."""
        profile = _profile_name(profile)
        if not self.path.is_file():
            return {}
        uri = self.path.resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_SECONDS) as db:
                row = db.execute(
                    "SELECT payload FROM nous_profiles WHERE profile = ?", (profile,)
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return {}
            raise
        return self._decode(row[0]) if row else {}

    @contextmanager
    def transaction(self, profile: str = "default") -> Iterator[dict]:
        """Lock, read, mutate, then encrypt and commit one profile atomically.

        BEGIN IMMEDIATE takes a database write reservation before the read. Peers
        therefore see the committed result of the previous transaction even when
        they use separate store objects or processes.
        """
        profile = _profile_name(profile)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=_BUSY_TIMEOUT_SECONDS, isolation_level=None)
        try:
            db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_SECONDS * 1000}")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS nous_profiles "
                "(profile TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            row = db.execute(
                "SELECT payload FROM nous_profiles WHERE profile = ?", (profile,)
            ).fetchone()
            state = self._decode(row[0]) if row else {}
            yield state
            if state:
                plaintext = self._encode(state)
                encrypted = self._get_cipher().encrypt_value(plaintext)
                db.execute(
                    "INSERT INTO nous_profiles (profile, payload) VALUES (?, ?) "
                    "ON CONFLICT(profile) DO UPDATE SET payload=excluded.payload",
                    (profile, encrypted),
                )
            else:
                db.execute("DELETE FROM nous_profiles WHERE profile = ?", (profile,))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


def _jwt_payload(token: str) -> dict | None:
    if not isinstance(token, str) or len(token) > _MAX_JWT_CHARS or _JWT.fullmatch(token) is None:
        return None
    header_part, payload_part, _signature = token.split(".")
    try:
        header = json.loads(base64.urlsafe_b64decode(header_part + "=" * (-len(header_part) % 4)))
        payload = json.loads(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        return None
    if str(header.get("alg", "")).lower() == "none":
        return None
    return payload


def _expiry(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            expiry = float(value)
        except OverflowError:
            return None
    elif isinstance(value, str):
        try:
            expiry = float(value)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return None
                expiry = parsed.timestamp()
            except (ValueError, OverflowError, OSError):
                return None
    else:
        return None
    return expiry if math.isfinite(expiry) else None


def _has_inference_scope(value: object) -> bool:
    if isinstance(value, str):
        entries = (value,)
    elif isinstance(value, (list, tuple, set)) and all(isinstance(item, str) for item in value):
        entries = value
    else:
        return False
    return any(
        "inference:invoke" in re.split(r"[\s,]+", entry)
        for entry in entries
    )


def usable_inference_token(
    state: dict, *, now: float | None = None, min_ttl: float = 120
) -> str | None:
    """Choose a scoped, unexpired JWT; opaque or malformed strings never qualify."""
    if not isinstance(state, dict):
        return None
    now_value = time.time() if now is None else _expiry(now)
    ttl = _expiry(min_ttl)
    if now_value is None or ttl is None or ttl < 0:
        return None
    for key in ("agent_key", "access_token"):
        token = state.get(key)
        claims = _jwt_payload(token)
        if claims is None:
            continue
        expiry = _expiry(claims["exp"]) if "exp" in claims else _expiry(state.get("expires_at"))
        if expiry is None or expiry <= now_value + ttl:
            continue
        scope_values = (state.get("scope"), claims.get("scope"), claims.get("scp"))
        if any(_has_inference_scope(scope) for scope in scope_values):
            return token
    return None
