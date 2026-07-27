"""
audit.py — SQLite audit logger with Merkle hash chain.

Port of OpenJarvis's Rust-backed audit logger to pure Python.
"""

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path
from agents.core.persistence.migrations import apply_migrations

from .types import ScanFinding, SecurityEvent, SecurityEventType, ThreatLevel

logger = logging.getLogger(__name__)


def _v1_hash_columns(conn: sqlite3.Connection) -> None:
    """v1 — Merkle hash-chain columns (row_hash/prev_hash). Guarded for legacy DBs
    that predate them (and a no-op on fresh DBs whose CREATE TABLE already has them)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(security_events)").fetchall()}
    if "row_hash" not in cols:
        conn.execute("ALTER TABLE security_events ADD COLUMN row_hash TEXT DEFAULT ''")
    if "prev_hash" not in cols:
        conn.execute("ALTER TABLE security_events ADD COLUMN prev_hash TEXT DEFAULT ''")


def _v2_hash_algo(conn: sqlite3.Connection) -> None:
    """v2 (AUD-9) — per-row hash algorithm marker. Legacy rows stay 'sha256'; rows
    written with a key configured are 'hmac-sha256'. Lets verify_chain handle a DB
    that spans the transition (key introduced mid-stream). Guarded + idempotent."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(security_events)").fetchall()}
    if "hash_algo" not in cols:
        conn.execute("ALTER TABLE security_events ADD COLUMN hash_algo TEXT DEFAULT 'sha256'")


# Forward-only, append-only. Never edit/reorder a shipped entry — only append.
_MIGRATIONS = [_v1_hash_columns, _v2_hash_algo]


class AuditLogger:
    def __init__(self, db_path: str = None):
        self._db_path = Path(db_path) if db_path is not None else data_path("security", "audit.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # threading.Lock serialises all writes; check_same_thread=False allows
        # the connection to be used from asyncio thread-pool workers (H7.4).
        self._lock = threading.Lock()
        # AUD-9: optional off-box HMAC key. When set, new rows are keyed
        # (hmac-sha256) so an attacker with DB write access can't recompute a
        # forged chain without the key. Default (unset) keeps the prior plain
        # sha256 behavior — opt-in hardening per the default-off convention.
        _key_raw = os.environ.get("JARVIS_AUDIT_KEY")
        self._key: Optional[bytes] = _key_raw.encode() if _key_raw else None
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        # WAL + synchronous=NORMAL: every turn appends one hash-chained audit row
        # on the async hot path; this keeps the commit cheap (~36x in-bench) while
        # preserving durability and the Merkle chain.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       REAL,
                event_type      TEXT,
                findings_json   TEXT,
                content_preview TEXT,
                action_taken    TEXT,
                row_hash        TEXT DEFAULT '',
                prev_hash       TEXT DEFAULT '',
                hash_algo       TEXT DEFAULT 'sha256'
            )
        """)
        # query() filters by event_type and a timestamp floor, ordering by
        # timestamp — and this table grows one row per turn, so it is among the
        # fastest-growing in the system. Index (event_type, timestamp) to keep
        # those lookups off a full table scan.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_security_events_type_ts "
            "ON security_events(event_type, timestamp)"
        )
        self._conn.commit()
        # Versioned, forward-only schema migrations (H23.7), replacing the former
        # ad-hoc _migrate_schema().
        apply_migrations(self._conn, _MIGRATIONS, name="audit")

    def _digest(self, algo: str, hash_input: str) -> Optional[str]:
        """Hash a chain row. ``hmac-sha256`` requires the key — returns None when
        an hmac row must be verified but no key is configured (caller treats that
        as 'cannot verify')."""
        data = hash_input.encode()
        if algo == "hmac-sha256":
            if not self._key:
                return None
            return hmac.new(self._key, data, hashlib.sha256).hexdigest()
        return hashlib.sha256(data).hexdigest()

    def log(self, event: SecurityEvent):
        # AUD-12: never persist the raw matched secret. The scanner keeps the real
        # value in-memory for redaction at the call site, but the durable audit row
        # stores only a [REDACTED:<pattern>] marker — so a reader of audit.db (or
        # the admin audit page) sees what was flagged, never the secret itself.
        findings_json = json.dumps([
            {
                "pattern_name": f.pattern_name,
                "matched_text": f"[REDACTED:{f.pattern_name}]",
                "threat_level": f.threat_level.value,
                "start": f.start,
                "end": f.end,
                "description": f.description,
            }
            for f in event.findings
        ])

        algo = "hmac-sha256" if self._key else "sha256"
        with self._lock:
            prev_hash = self._tail_hash_unlocked()
            hash_input = f"{prev_hash}|{event.timestamp}|{event.event_type.value}|{findings_json}|{event.content_preview}|{event.action_taken}"
            row_hash = self._digest(algo, hash_input)

            self._conn.execute(
                "INSERT INTO security_events (timestamp, event_type, findings_json, content_preview, action_taken, row_hash, prev_hash, hash_algo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event.timestamp, event.event_type.value, findings_json, event.content_preview, event.action_taken, row_hash, prev_hash, algo),
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

        with self._lock:
            raw_rows = self._conn.execute(sql, params).fetchall()
        events = []
        for row in raw_rows:
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

    def _tail_hash_unlocked(self) -> str:
        """Return the latest row_hash; caller must hold self._lock."""
        row = self._conn.execute("SELECT row_hash FROM security_events ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row and row[0] else ""

    def tail_hash(self) -> str:
        with self._lock:
            return self._tail_hash_unlocked()

    def verify_chain(self) -> tuple[bool, Optional[int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, timestamp, event_type, findings_json, content_preview, action_taken, row_hash, prev_hash, hash_algo FROM security_events ORDER BY id"
            ).fetchall()
        expected_prev = ""
        seen_hashed = False
        seen_keyed = False
        for row in rows:
            rid, ts, etype, fj, preview, action, stored_hash, stored_prev, algo = row
            # AUDIT-1 (adversarial audit 2026-07-25) — the algorithm is taken from the
            # row, and _digest only demands the key when the row says so. An attacker
            # with DB write access therefore downgraded EVERY row to plain sha256,
            # recomputed each hash and prev_hash with hashlib alone, and the chain
            # re-linked cleanly with a key configured. The shipped regression missed it
            # because it downgrades one row, so the break surfaced at the next row whose
            # prev_hash was still an HMAC.
            #
            # Two rules close it, and they have to work together:
            #   (a) here — once a keyed row has been seen, a later sha256 row is
            #       tampering. That kills a partial downgrade and any splice after the
            #       key was introduced.
            #   (b) after the loop — a non-empty chain with a key configured must
            #       contain at least one keyed row. That kills the FULL downgrade, which
            #       (a) alone cannot see: rewriting every row leaves nothing to compare
            #       against, and the result is indistinguishable from a legacy chain.
            # A legitimate mixed chain (legacy sha256 prefix, then hmac after the owner
            # set a key) still passes both.
            if algo == "hmac-sha256":
                seen_keyed = True
            elif seen_keyed:
                return False, rid
            if not stored_hash:
                # A blank row_hash is legitimate only for legacy rows written
                # before the Merkle columns existed (the v1 migration backfills
                # row_hash DEFAULT ''). Those can only be a contiguous prefix at
                # the head of the table. A blank hash appearing AFTER the chain
                # has started can only be an injected/tampered row — every real
                # row from log() carries a computed hash — so fail closed rather
                # than skip it (which previously let forged rows pass even in
                # HMAC mode, since leaving the hash blank dodged the HMAC check).
                if seen_hashed:
                    return False, rid
                continue
            if stored_prev != expected_prev:
                return False, rid
            hash_input = f"{stored_prev}|{ts}|{etype}|{fj}|{preview}|{action}"
            # Recompute with the row's own algorithm. An hmac-sha256 row can't be
            # verified without the key (_digest → None) → the chain fails closed.
            computed = self._digest(algo or "sha256", hash_input)
            if computed is None or computed != stored_hash:
                return False, rid
            expected_prev = stored_hash
            seen_hashed = True
        # Rule (b). With a key configured, a running install writes hmac rows — `log()`
        # picks the algorithm from key presence, not from the data. So a non-empty chain
        # carrying no keyed row at all means either every row was downgraded (the attack)
        # or the key was set on a legacy chain that has not logged since (a real state,
        # and one the owner must resolve deliberately rather than have verification
        # silently vouch for). Fail closed, and name the first row so the caller can act.
        if self._key and seen_hashed and not seen_keyed:
            return False, rows[0][0]
        return True, None

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM security_events").fetchone()
        return row[0] if row else 0

    def chain_status(self) -> dict:
        """``verify_chain`` plus the context that makes its verdict readable.

        A bare ``valid: true`` is the wrong shape for two different reasons, both raised
        by the adversarial audit (see ADV-009):

        * an **unkeyed** chain that verifies proves only that nobody edited a row without
          recomputing its hash. Anyone with file access can recompute the whole thing —
          that is integrity, not tamper evidence, and reporting it as plain "valid" reads
          as the stronger claim;
        * a **false** verdict now has two very different causes since AUDIT-1. "Someone
          rewrote your audit log" and "you set a key on a chain that predates it" want
          opposite responses from the owner, and the row id alone cannot tell them apart.

        Returns the booleans plus a plain-English ``reason``. ``verify_chain`` keeps its
        ``(bool, row_id)`` contract — this wraps it rather than replacing it.
        """
        valid, first_bad = self.verify_chain()
        with self._lock:
            algos = [(a or "sha256") for (a,) in self._conn.execute(
                "SELECT hash_algo FROM security_events ORDER BY id").fetchall()]
        keyed_rows = sum(1 for a in algos if a == "hmac-sha256")
        key_configured = bool(self._key)

        if not algos:
            integrity, reason = "empty", "no entries yet"
        elif keyed_rows == len(algos):
            integrity = "hmac-sha256"
            reason = "keyed: an edit cannot be recomputed without JARVIS_AUDIT_KEY"
        elif keyed_rows:
            integrity = "mixed"
            reason = (f"keyed for the newest {keyed_rows} of {len(algos)} entries; the "
                      "older ones predate the key and are integrity-only")
        else:
            integrity = "sha256"
            reason = ("unkeyed: integrity only, NOT tamper evidence — anyone with file "
                      "access can recompute this chain. Set JARVIS_AUDIT_KEY.")

        if not valid:
            if key_configured and not keyed_rows and algos:
                reason = ("a key is configured but no entry is keyed. Either every row "
                          "was rewritten, or the key was set on a chain that predates it "
                          "and nothing has been logged since. Log an event to re-anchor, "
                          "or investigate.")
            else:
                reason = f"chain broken at entry {first_bad}"

        return {
            "valid": valid,
            "first_invalid_id": first_bad,
            "entries": len(algos),
            "key_configured": key_configured,
            # the honest headline: only a fully keyed, verifying chain is tamper-evident
            "tamper_evident": bool(valid and algos and keyed_rows == len(algos)),
            "integrity": integrity,
            "reason": reason,
        }

    def prune_before(self, cutoff_ts: float) -> int:
        """Retention (H23.10): delete chain rows older than *cutoff_ts*, then
        re-anchor the surviving rows so ``verify_chain`` still passes.

        Pruning a Merkle chain orphans the new first row (its ``prev_hash`` points
        at a deleted row), so the remaining rows are re-linked from a fresh anchor
        and their hashes recomputed with each row's own algorithm. Tamper-evidence
        across the pruned boundary is intentionally given up — those rows are gone.
        If the surviving rows are HMAC-keyed but no key is available, the prune is
        refused (it would leave an unverifiable chain). Returns rows deleted.
        """
        with self._lock:
            survivors_algos = self._conn.execute(
                "SELECT hash_algo FROM security_events WHERE timestamp >= ?", (cutoff_ts,)
            ).fetchall()
            if not self._key and any((a or "sha256") == "hmac-sha256" for (a,) in survivors_algos):
                logger.warning("retention: refusing to prune audit (HMAC rows, no key to re-anchor)")
                return 0
            # Mirror of verify_chain's rule (b) (AUDIT-1): with a key configured, a chain
            # whose survivors are all sha256 is exactly the shape a full downgrade leaves,
            # so verification refuses it. Pruning into that shape would report success and
            # hand back a chain that no longer verifies. Re-anchoring the survivors under
            # the key instead would be worse — it would vouch, silently, for rows written
            # before the key existed. Refuse, and let the owner re-anchor deliberately.
            if self._key and survivors_algos and all(
                    (a or "sha256") != "hmac-sha256" for (a,) in survivors_algos):
                logger.warning(
                    "retention: refusing to prune audit (a key is configured but no "
                    "surviving row is keyed — the result would not verify)")
                return 0
            deleted = self._conn.execute(
                "DELETE FROM security_events WHERE timestamp < ?", (cutoff_ts,)
            ).rowcount or 0
            if deleted:
                rows = self._conn.execute(
                    "SELECT id, timestamp, event_type, findings_json, content_preview, action_taken, hash_algo "
                    "FROM security_events ORDER BY id"
                ).fetchall()
                prev = ""
                for rid, ts, etype, fj, preview, action, algo in rows:
                    rh = self._digest(algo or "sha256", f"{prev}|{ts}|{etype}|{fj}|{preview}|{action}")
                    if rh is None:  # pragma: no cover - guarded above
                        break
                    self._conn.execute(
                        "UPDATE security_events SET prev_hash=?, row_hash=? WHERE id=?", (prev, rh, rid)
                    )
                    prev = rh
            self._conn.commit()
        return deleted

    def close(self):
        self._conn.close()
