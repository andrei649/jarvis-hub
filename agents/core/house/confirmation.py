"""Durable one-shot owner confirmation for security-sensitive house tasks."""

from __future__ import annotations

import hashlib
import math
import secrets
import sqlite3
import threading
import time
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

_KEY_REF = "{{secret:house_confirmation_key}}"


class ConfirmationError(RuntimeError):
    """A strong-confirmation ceremony was invalid or expired."""


def _secret(secret_broker, key_ref: str) -> bytes:
    if secret_broker is None:
        raise ConfirmationError("confirmation key is unavailable")
    try:
        result = secret_broker.inject(key_ref, approved=True)
    except Exception as exc:
        raise ConfirmationError("confirmation key is unavailable") from exc
    if not isinstance(result, Mapping) or result.get("blocked"):
        raise ConfirmationError("confirmation key is unavailable")
    value = result.get("text")
    if not isinstance(value, str) or not 32 <= len(value) <= 4_096:
        raise ConfirmationError("confirmation key is invalid")
    return hashlib.sha256(b"jarvis-house-confirm-v1\0" + value.encode()).digest()


def _text(value: object, *, label: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfirmationError(f"{label} is required")
    result = value.strip()
    if len(result) > limit:
        raise ConfirmationError(f"{label} exceeds its size limit")
    return result


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfirmationError(f"{label} must be finite")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ConfirmationError(f"{label} must be finite")
    return result


class StrongConfirmationStore:
    """Stores token/receipt hashes only and consumes confirmation atomically."""

    def __init__(
        self,
        path: str | Path,
        *,
        secret_broker=None,
        key_ref: str = _KEY_REF,
        clock=None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = _secret(secret_broker, key_ref)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    capability TEXT NOT NULL,
                    target TEXT NOT NULL,
                    intended_state TEXT NOT NULL,
                    challenge_hash TEXT NOT NULL UNIQUE,
                    receipt_hash TEXT,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    consumed INTEGER NOT NULL DEFAULT 0,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_house_confirm_task "
                "ON confirmations(task_id, confirmed, consumed, expires_at)"
            )

    def _hash(self, label: str, token: str) -> str:
        return hashlib.sha256(self._key + label.encode() + b"\0" + token.encode()).hexdigest()

    @staticmethod
    def _binding(
        *, task_id: int, capability: str, target: str, intended_state: str
    ) -> tuple[int, str, str, str]:
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
            raise ConfirmationError("task binding is invalid")
        return (
            task_id,
            _text(capability, label="capability", limit=64),
            _text(target, label="target", limit=128),
            _text(intended_state, label="intended_state", limit=128),
        )

    def mint(
        self,
        *,
        task_id: int,
        capability: str,
        target: str,
        intended_state: str,
        ttl_seconds: float = 120.0,
    ) -> dict:
        binding = self._binding(
            task_id=task_id,
            capability=capability,
            target=target,
            intended_state=intended_state,
        )
        ttl = _finite(ttl_seconds, label="ttl_seconds")
        if not 1 <= ttl <= 600:
            raise ConfirmationError("ttl_seconds is outside its bounds")
        now = _finite(self._clock(), label="clock")
        token = secrets.token_urlsafe(32)
        challenge_hash = self._hash("challenge", token)
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO confirmations (
                    task_id, capability, target, intended_state, challenge_hash,
                    expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (*binding, challenge_hash, now + ttl, now),
            )
        return {
            "status": "challenge_minted",
            "confirmation_id": int(cursor.lastrowid),
            "token": token,
            "task_id": binding[0],
            "capability": binding[1],
            "target": binding[2],
            "intended_state": binding[3],
            "expires_at": now + ttl,
        }

    def confirm(
        self,
        token: str,
        *,
        task_id: int,
        capability: str,
        target: str,
        intended_state: str,
    ) -> dict:
        token = _text(token, label="challenge token", limit=256)
        binding = self._binding(
            task_id=task_id,
            capability=capability,
            target=target,
            intended_state=intended_state,
        )
        challenge_hash = self._hash("challenge", token)
        now = _finite(self._clock(), label="clock")
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM confirmations WHERE challenge_hash=?", (challenge_hash,)
            ).fetchone()
            if row is None:
                raise ConfirmationError("challenge token is invalid")
            row_binding = (
                row["task_id"],
                row["capability"],
                row["target"],
                row["intended_state"],
            )
            if row_binding != binding:
                raise ConfirmationError("challenge binding does not match")
            if float(row["expires_at"]) < now:
                raise ConfirmationError("challenge expired")
            if row["confirmed"]:
                raise ConfirmationError("challenge already confirmed")
            receipt = secrets.token_urlsafe(32)
            receipt_hash = self._hash("receipt", receipt)
            changed = connection.execute(
                "UPDATE confirmations SET receipt_hash=?, confirmed=1 WHERE id=? AND confirmed=0",
                (receipt_hash, row["id"]),
            ).rowcount
            if changed != 1:
                raise ConfirmationError("challenge already confirmed")
        return {
            "status": "confirmed",
            "confirmation_id": int(row["id"]),
            "receipt": receipt,
        }

    def consume(
        self,
        *,
        task_id: int,
        capability: str,
        target: str,
        intended_state: str,
    ) -> bool:
        binding = self._binding(
            task_id=task_id,
            capability=capability,
            target=target,
            intended_state=intended_state,
        )
        now = _finite(self._clock(), label="clock")
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM confirmations
                WHERE task_id=? AND capability=? AND target=? AND intended_state=?
                  AND confirmed=1 AND consumed=0 AND receipt_hash IS NOT NULL
                  AND expires_at>=?
                ORDER BY id DESC LIMIT 1
                """,
                (*binding, now),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            changed = connection.execute(
                "UPDATE confirmations SET consumed=1 WHERE id=? AND consumed=0",
                (row["id"],),
            ).rowcount
            connection.commit()
            return changed == 1
