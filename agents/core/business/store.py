"""Bounded SQLite business state with dedicated SecretStore encryption key."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore

_FIELDS = {
    "orders": {"id", "status", "total", "currency", "created_at"},
    "products": {"id", "name", "stock_quantity"},
    "deals": {"id", "name", "amount", "currency", "stage"},
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BusinessStore:
    """One data-root workspace. Writes are serialized and each DB mutation commits atomically."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else data_path("business")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._secrets = SecretStore(self.root / "credentials.secret.json")
        self.db_path = self.root / "business.db"
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, industry TEXT NOT NULL, currency TEXT NOT NULL, local_only INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS connections (id TEXT PRIMARY KEY, provider TEXT NOT NULL, name TEXT NOT NULL, base_url TEXT NOT NULL, credentials_cipher TEXT NOT NULL, status TEXT NOT NULL, last_sync_at TEXT, error TEXT, record_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS snapshots (connection_id TEXT PRIMARY KEY REFERENCES connections(id) ON DELETE CASCADE, body TEXT NOT NULL, synced_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, action TEXT NOT NULL, label TEXT NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def _activity(self, db, action: str, label: str):
        db.execute("INSERT INTO activity(created_at,action,label) VALUES(?,?,?)", (_now(), action, label[:120]))
        db.execute("DELETE FROM activity WHERE id NOT IN (SELECT id FROM activity ORDER BY id DESC LIMIT 200)")

    def profile(self) -> dict:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT name,industry,currency,local_only FROM profile WHERE id=1").fetchone()
        return {"name": row["name"] if row else "", "industry": row["industry"] if row else "services", "currency": row["currency"] if row else "EUR", "local_only": bool(row["local_only"]) if row else True}

    def update_profile(self, profile: dict) -> dict:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO profile(id,name,industry,currency,local_only) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,industry=excluded.industry,currency=excluded.currency,local_only=excluded.local_only", (profile["name"], profile["industry"], profile["currency"], int(profile["local_only"])))
            self._activity(db, "profile_updated", profile["name"])
        return self.profile()

    @staticmethod
    def _public(row) -> dict:
        return {key: row[key] for key in ("id", "provider", "name", "base_url", "status", "last_sync_at", "error", "record_count")}

    def add_connection(self, provider: str, name: str, base_url: str, credentials: dict) -> dict:
        cid = uuid.uuid4().hex
        with self._lock:
            cipher = self._secrets.encrypt_value(json.dumps(credentials, ensure_ascii=False))
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT COUNT(*) FROM connections").fetchone()[0] >= 100:
                    raise ValueError("Connection limit reached")
                db.execute("INSERT INTO connections(id,provider,name,base_url,credentials_cipher,status) VALUES(?,?,?,?,?,?)", (cid, provider, name, base_url, cipher, "pending"))
                self._activity(db, "connection_added", name)
        return self.get_connection(cid)

    def get_connection(self, connection_id: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM connections WHERE id=?", (connection_id,)).fetchone()
        return self._public(row) if row else None

    def list_connections(self) -> list[dict]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM connections ORDER BY rowid DESC LIMIT 100").fetchall()
        return [self._public(row) for row in rows]

    def credentials(self, connection_id: str) -> dict | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT credentials_cipher FROM connections WHERE id=?", (connection_id,)).fetchone()
            return json.loads(self._secrets.decrypt_value(row[0])) if row else None

    def replace_snapshot(self, connection_id: str, snapshot: dict) -> dict:
        records = snapshot["records"]
        if not isinstance(records, dict) or set(records) != set(_FIELDS):
            raise ValueError("Invalid snapshot kinds")
        safe = {}
        for kind, items in records.items():
            if not isinstance(items, list) or len(items) > 500:
                raise ValueError("Snapshot limit exceeded")
            if any(not isinstance(item, dict) for item in items):
                raise ValueError("Invalid snapshot record")
            safe[kind] = [{key: value for key, value in item.items() if key in _FIELDS[kind]} for item in items]
        source_kind = snapshot.get("kind")
        if source_kind is not None and source_kind not in _FIELDS:
            raise ValueError("Invalid snapshot kind")
        body = json.dumps({"records": safe, "complete": bool(snapshot["complete"]), "coverage": str(snapshot["coverage"])[:500], "kind": source_kind}, allow_nan=False, ensure_ascii=False)
        if len(body.encode("utf-8")) > 2_000_000:
            raise ValueError("Snapshot too large")
        count = sum(len(items) for items in safe.values())
        at = _now()
        with self._lock, self._connect() as db:
            row = db.execute("SELECT name FROM connections WHERE id=?", (connection_id,)).fetchone()
            if row is None:
                raise KeyError(connection_id)
            db.execute("INSERT INTO snapshots(connection_id,body,synced_at) VALUES(?,?,?) ON CONFLICT(connection_id) DO UPDATE SET body=excluded.body,synced_at=excluded.synced_at", (connection_id, body, at))
            db.execute("UPDATE connections SET status=?,last_sync_at=?,error=NULL,record_count=? WHERE id=?", ("connected" if snapshot["complete"] else "partial", at, count, connection_id))
            self._activity(db, "connection_synced", row["name"])
        return self.get_connection(connection_id)

    def mark_sync_error(self, connection_id: str, error: str) -> dict:
        # Caller supplies a fixed, safe error message, never a raw provider response.
        with self._lock, self._connect() as db:
            row = db.execute("SELECT name FROM connections WHERE id=?", (connection_id,)).fetchone()
            if row is None:
                raise KeyError(connection_id)
            has_snapshot = db.execute("SELECT 1 FROM snapshots WHERE connection_id=?", (connection_id,)).fetchone()
            db.execute("UPDATE connections SET status=?,error=? WHERE id=?", ("stale" if has_snapshot else "error", error[:200], connection_id))
            self._activity(db, "connection_error", row["name"])
        return self.get_connection(connection_id)

    def snapshots(self) -> list[dict]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT c.id,c.name,s.body,s.synced_at FROM snapshots s JOIN connections c ON c.id=s.connection_id ORDER BY c.rowid DESC LIMIT 100").fetchall()
        return [{"connection_id": row["id"], "connection_name": row["name"], "synced_at": row["synced_at"], **json.loads(row["body"])} for row in rows]

    def snapshot_kind(self, connection_id: str) -> str | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT body FROM snapshots WHERE connection_id=?", (connection_id,)).fetchone()
        return json.loads(row[0]).get("kind") if row else None

    def remove_connection(self, connection_id: str) -> bool:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT name FROM connections WHERE id=?", (connection_id,)).fetchone()
            if row is None:
                return False
            db.execute("DELETE FROM connections WHERE id=?", (connection_id,))
            self._activity(db, "connection_removed", row["name"])
            return True

    def save_report(self, report: dict) -> dict:
        value = {**report, "id": uuid.uuid4().hex, "created_at": _now()}
        body = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(body.encode("utf-8")) > 500_000:
            raise ValueError("Report too large")
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO reports(id,created_at,body) VALUES(?,?,?)", (value["id"], value["created_at"], body))
            db.execute("DELETE FROM reports WHERE id NOT IN (SELECT id FROM reports ORDER BY created_at DESC,rowid DESC LIMIT 100)")
            self._activity(db, "report_created", str(report.get("title", "Report")))
        return value

    def list_reports(self) -> list[dict]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT body FROM reports ORDER BY created_at DESC,rowid DESC LIMIT 100").fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_activity(self) -> list[dict]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT created_at,action,label FROM activity ORDER BY id DESC LIMIT 200").fetchall()
        return [dict(row) for row in rows]
