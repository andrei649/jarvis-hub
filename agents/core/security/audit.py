"""
audit.py — SQLite audit logger with Merkle hash chain.

Port of OpenJarvis's Rust-backed audit logger to pure Python.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .types import ScanFinding, SecurityEvent, SecurityEventType, ThreatLevel


class AuditLogger:
    def __init__(self, db_path: str = "memory_logs/security/audit.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       REAL,
                event_type      TEXT,
                findings_json   TEXT,
                content_preview TEXT,
                action_taken    TEXT,
                row_hash        TEXT DEFAULT '',
                prev_hash       TEXT DEFAULT ''
            )
        """)
        self._conn.commit()
        self._migrate_schema()

    def _migrate_schema(self):
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(security_events)").fetchall()}
        if "row_hash" not in columns:
            self._conn.execute("ALTER TABLE security_events ADD COLUMN row_hash TEXT DEFAULT ''")
        if "prev_hash" not in columns:
            self._conn.execute("ALTER TABLE security_events ADD COLUMN prev_hash TEXT DEFAULT ''")
        self._conn.commit()

    def log(self, event: SecurityEvent):
        findings_json = json.dumps([
            {
                "pattern_name": f.pattern_name,
                "matched_text": f.matched_text,
                "threat_level": f.threat_level.value,
                "start": f.start,
                "end": f.end,
                "description": f.description,
            }
            for f in event.findings
        ])

        prev_hash = self.tail_hash()
        hash_input = f"{prev_hash}|{event.timestamp}|{event.event_type.value}|{findings_json}|{event.content_preview}|{event.action_taken}"
        row_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        self._conn.execute(
            "INSERT INTO security_events (timestamp, event_type, findings_json, content_preview, action_taken, row_hash, prev_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event.timestamp, event.event_type.value, findings_json, event.content_preview, event.action_taken, row_hash, prev_hash),
        )
        self._conn.commit()

    def query(self, event_type: Optional[str] = None, since: Optional[float] = None, limit: int = 100) -> list[SecurityEvent]:
        sql = "SELECT timestamp, event_type, findings_json, content_preview, action_taken FROM security_events WHERE 1=1"
        params: list = []
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        events = []
        for row in self._conn.execute(sql, params).fetchall():
            ts, etype, findings_json, preview, action = row
            findings_raw = json.loads(findings_json) if findings_json else []
            findings = [
                ScanFinding(
                    pattern_name=f["pattern_name"],
                    matched_text=f["matched_text"],
                    threat_level=ThreatLevel(f["threat_level"]),
                    start=f["start"],
                    end=f["end"],
                    description=f.get("description", ""),
                )
                for f in findings_raw
            ]
            events.append(SecurityEvent(
                event_type=SecurityEventType(etype),
                timestamp=ts,
                findings=findings,
                content_preview=preview or "",
                action_taken=action or "",
            ))
        return events

    def tail_hash(self) -> str:
        row = self._conn.execute("SELECT row_hash FROM security_events ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row and row[0] else ""

    def verify_chain(self) -> tuple[bool, Optional[int]]:
        rows = self._conn.execute(
            "SELECT id, timestamp, event_type, findings_json, content_preview, action_taken, row_hash, prev_hash FROM security_events ORDER BY id"
        ).fetchall()
        expected_prev = ""
        for row in rows:
            rid, ts, etype, fj, preview, action, stored_hash, stored_prev = row
            if not stored_hash:
                continue
            if stored_prev != expected_prev:
                return False, rid
            hash_input = f"{stored_prev}|{ts}|{etype}|{fj}|{preview}|{action}"
            computed = hashlib.sha256(hash_input.encode()).hexdigest()
            if computed != stored_hash:
                return False, rid
            expected_prev = stored_hash
        return True, None

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM security_events").fetchone()
        return row[0] if row else 0

    def close(self):
        self._conn.close()
