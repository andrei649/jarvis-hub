"""Bounded owner KV notes, separate from the model's previous output."""

from __future__ import annotations

from datetime import UTC, datetime

MAX_KEY_CHARS = 128
MAX_VALUE_BYTES = 16 * 1024
MAX_JOB_BYTES = 64 * 1024
MAX_KEYS = 256


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid Unicode") from exc
    return value


def _key(value: object) -> str:
    value = _text(value, "key")
    if not value or len(value) > MAX_KEY_CHARS or not all(char.isprintable() for char in value):
        raise ValueError("notepad key must be 1-128 printable characters")
    return value


class JobNotepadKV:
    def __init__(self, store) -> None:
        self.store = store
        with store._lock:
            store._conn.execute("""CREATE TABLE IF NOT EXISTS job_notepad_kv (
                job_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(job_id,key))""")
            store._conn.commit()

    @staticmethod
    def _require_job(conn, job_id: str) -> None:
        if conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
            raise KeyError(job_id)

    def snapshot_locked(self, conn, job_id: str) -> list[dict]:
        self._require_job(conn, job_id)
        return [dict(row) for row in conn.execute(
            "SELECT key,value,updated_at FROM job_notepad_kv WHERE job_id=? ORDER BY key", (job_id,))]

    def list(self, job_id: str) -> list[dict]:
        with self.store._lock:
            return self.snapshot_locked(self.store._conn, str(job_id))

    def get(self, job_id: str, key: str) -> str | None:
        key = _key(key)
        with self.store._lock:
            conn = self.store._conn
            self._require_job(conn, str(job_id))
            row = conn.execute("SELECT value FROM job_notepad_kv WHERE job_id=? AND key=?",
                               (str(job_id), key)).fetchone()
        return row["value"] if row else None

    def set(self, job_id: str, key: str, value: str) -> None:
        key, value = _key(key), _text(value, "value")
        if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
            raise ValueError("notepad value exceeds 16 KiB")
        job_id = str(job_id)
        with self.store._lock:
            conn = self.store._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self.snapshot_locked(conn, job_id)
                existing = {row["key"]: row["value"] for row in rows}
                existing[key] = value
                if len(existing) > MAX_KEYS or sum(len(k.encode("utf-8")) + len(v.encode("utf-8"))
                                                    for k, v in existing.items()) > MAX_JOB_BYTES:
                    raise ValueError("notepad job budget exceeded")
                conn.execute("""INSERT INTO job_notepad_kv(job_id,key,value,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(job_id,key) DO UPDATE SET value=excluded.value,
                    updated_at=excluded.updated_at""", (job_id, key, value, datetime.now(UTC).isoformat()))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def delete(self, job_id: str, key: str) -> bool:
        key, job_id = _key(key), str(job_id)
        with self.store._lock:
            conn = self.store._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._require_job(conn, job_id)
                removed = conn.execute("DELETE FROM job_notepad_kv WHERE job_id=? AND key=?",
                                       (job_id, key)).rowcount
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return bool(removed)
