"""
preferences.py — Preference Learning & Decision Journal (H6.5).

Records every human decision (accept/edit/reject/defer) on a blocked task and
computes an approval rate per (agent, kind, risk_tier) class. When a reversible
or external class is consistently approved, suggest raising its autonomy — a
suggestion, never an automatic change (gated on human confirmation).

Also keeps an append-only decision journal (JSONL): the decision, who made it,
and the task context, for later calibration. SQLite-backed, offline-testable.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.autonomy.preferences")

DEFAULT_DB = data_path("autonomy.db")
JOURNAL = data_path("autonomy_journal.jsonl")

# Approve here means the human let it run (accept/edit); reject/defer do not.
_APPROVE = {"accept", "edit"}

MIN_SAMPLES = 4
RAISE_THRESHOLD = 0.8


class PreferenceStore:
    def __init__(self, db_path: Optional[str] = None, journal_path: Optional[str] = None):
        if db_path is None:
            DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(DEFAULT_DB)
        self.db_path = db_path
        self.journal_path = Path(journal_path) if journal_path else JOURNAL
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    def initialize(self) -> "PreferenceStore":
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                kind TEXT NOT NULL,
                risk_tier INTEGER NOT NULL,
                action TEXT NOT NULL,
                approved INTEGER NOT NULL,
                decided_by TEXT,
                created_at TEXT NOT NULL
            )
        """)
        # approval_rate() and suggest_autonomy_raise() filter/group by the
        # (agent, kind, risk_tier) class on the autonomy decision path, and the
        # journal grows one row per decision. Index the class so those reads
        # stay fast as the preference history accumulates.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_preferences_class "
            "ON preferences(agent, kind, risk_tier)"
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()
        return self

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── record ────────────────────────────────────────────────────
    def record(self, task, action: str, decided_by: str = "user") -> None:
        """Record a decision on a task and append it to the journal."""
        action = (action or "").lower()
        approved = 1 if action in _APPROVE else 0
        agent = getattr(task, "agent", "?")
        kind = getattr(task, "kind", "?")
        tier = int(getattr(task, "risk_tier", 3))
        now = datetime.now(timezone.utc).isoformat()
        if self._conn:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO preferences (agent, kind, risk_tier, action, approved, decided_by, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (agent, kind, tier, action, approved, decided_by, now),
                )
                self._conn.commit()
        self._journal({
            "ts": now, "task_id": getattr(task, "id", None), "agent": agent,
            "kind": kind, "risk_tier": tier, "action": action,
            "approved": bool(approved), "decided_by": decided_by,
            "title": getattr(task, "title", ""),
        })

    def _journal(self, entry: dict) -> None:
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Decision journal write failed: {e}")

    # ── query ─────────────────────────────────────────────────────
    def approval_rate(self, agent: str, kind: str, risk_tier: int) -> Optional[float]:
        if not self._conn:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT AVG(approved) AS rate, COUNT(*) AS n FROM preferences "
                "WHERE agent=? AND kind=? AND risk_tier=?",
                (agent, kind, int(risk_tier)),
            ).fetchone()
        if not row or not row["n"]:
            return None
        return float(row["rate"])

    def suggest_autonomy_raise(self, min_samples: int = MIN_SAMPLES,
                               threshold: float = RAISE_THRESHOLD) -> list[dict]:
        """Classes consistently approved → candidates for higher autonomy.

        Only reversible/external tiers (1,2) are eligible; we never suggest
        auto-acting on irreversible/money actions.
        """
        if not self._conn:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT agent, kind, risk_tier, AVG(approved) AS rate, COUNT(*) AS n "
                "FROM preferences WHERE risk_tier IN (1, 2) "
                "GROUP BY agent, kind, risk_tier "
                "HAVING n >= ? AND rate >= ? ORDER BY rate DESC, n DESC",
                (min_samples, threshold),
            ).fetchall()
        return [{
            "agent": r["agent"], "kind": r["kind"], "risk_tier": r["risk_tier"],
            "approval_rate": round(float(r["rate"]), 3), "samples": r["n"],
            "suggestion": "raise autonomy → act autonomously on this class",
        } for r in rows]
