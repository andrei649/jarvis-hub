"""DB schema-migration framework (H23.7) — forward-only, user_version-gated.

Offline, tmp_path. Covers the runner (fresh upgrade, legacy upgrade, idempotency,
atomic rollback, column_adder) and the two adopters (audit, marketplace) — that a
legacy DB missing the new columns is upgraded and stamped, and a fresh store ends
at the latest version.
"""
import sqlite3

import pytest

from agents.core.persistence.migrations import (
    apply_migrations, schema_version, column_adder,
)


def _conn(path):
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    c.commit()
    return c


def test_fresh_db_runs_all_and_stamps_version(tmp_path):
    c = _conn(tmp_path / "m.db")
    ran = []
    migs = [lambda conn: ran.append(1), lambda conn: ran.append(2)]
    out = apply_migrations(c, migs, name="t")
    assert out == 2
    assert ran == [1, 2]
    assert schema_version(c) == 2


def test_legacy_db_upgraded_by_column_adder(tmp_path):
    # A v0 DB whose table predates a column.
    c = _conn(tmp_path / "m.db")
    assert schema_version(c) == 0
    apply_migrations(c, [column_adder("t", "b", "TEXT DEFAULT ''")], name="t")
    cols = {r[1] for r in c.execute("PRAGMA table_info(t)").fetchall()}
    assert "b" in cols
    assert schema_version(c) == 1


def test_idempotent_second_call_is_noop(tmp_path):
    c = _conn(tmp_path / "m.db")
    calls = []
    migs = [lambda conn: calls.append(1)]
    apply_migrations(c, migs, name="t")
    apply_migrations(c, migs, name="t")          # already at v1 → skip
    assert calls == [1]
    assert schema_version(c) == 1


def test_only_pending_migrations_run(tmp_path):
    c = _conn(tmp_path / "m.db")
    apply_migrations(c, [lambda conn: None], name="t")   # → v1
    ran = []
    # add a second migration; only it should run
    apply_migrations(c, [lambda conn: ran.append("v1-skip"),
                         lambda conn: ran.append("v2-run")], name="t")
    assert ran == ["v2-run"]
    assert schema_version(c) == 2


def test_failed_migration_rolls_back_atomically(tmp_path):
    c = _conn(tmp_path / "m.db")

    def bad(conn):
        conn.execute("ALTER TABLE t ADD COLUMN c TEXT")  # real DDL...
        raise RuntimeError("boom")                       # ...then fail

    with pytest.raises(RuntimeError):
        apply_migrations(c, [bad], name="t")
    # version unchanged AND the DDL rolled back
    assert schema_version(c) == 0
    cols = {r[1] for r in c.execute("PRAGMA table_info(t)").fetchall()}
    assert "c" not in cols


def test_column_adder_noop_when_column_present(tmp_path):
    c = _conn(tmp_path / "m.db")
    c.execute("ALTER TABLE t ADD COLUMN b TEXT DEFAULT ''")  # already present, v still 0
    c.commit()
    apply_migrations(c, [column_adder("t", "b", "TEXT DEFAULT ''")], name="t")
    # no duplicate-column error; version stamped
    assert schema_version(c) == 1


# ── adopter regressions ──────────────────────────────────────────────

def _legacy_audit_db(path):
    """An audit DB at the pre-hash-chain schema (no row_hash/prev_hash), user_version 0."""
    c = sqlite3.connect(str(path))
    c.execute("""CREATE TABLE security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, event_type TEXT,
        findings_json TEXT, content_preview TEXT, action_taken TEXT)""")
    c.commit(); c.close()


def test_audit_adopter_upgrades_legacy_db(tmp_path):
    from agents.core.security.audit import AuditLogger
    db = tmp_path / "audit.db"
    _legacy_audit_db(db)
    a = AuditLogger(db_path=str(db))
    cols = {r[1] for r in a._conn.execute("PRAGMA table_info(security_events)").fetchall()}
    # v1 added the hash-chain columns; v2 (AUD-9) added the per-row hash_algo marker.
    assert {"row_hash", "prev_hash", "hash_algo"} <= cols
    assert a._conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_audit_adopter_fresh_db_at_latest_version(tmp_path):
    from agents.core.security.audit import AuditLogger
    a = AuditLogger(db_path=str(tmp_path / "audit.db"))
    assert a._conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_marketplace_adopter_upgrades_legacy_db(tmp_path):
    from agents.core.skills import marketplace as mp
    db = tmp_path / "marketplace.db"
    # legacy table without the moderation/signature columns
    c = sqlite3.connect(str(db))
    c.execute("""CREATE TABLE marketplace_skills (
        name TEXT PRIMARY KEY, version TEXT NOT NULL, description TEXT, author TEXT,
        agents TEXT, requires TEXT, package_zip BLOB NOT NULL, published_at TEXT NOT NULL)""")
    c.commit(); c.close()
    store = mp.SkillMarketplace(db_path=str(db))
    check = sqlite3.connect(str(db))
    cols = {r[1] for r in check.execute("PRAGMA table_info(marketplace_skills)").fetchall()}
    tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    ver = check.execute("PRAGMA user_version").fetchone()[0]
    check.close()
    assert {"review_status", "signature"} <= cols      # v1 moderation/signature columns
    assert "marketplace_skill_versions" in tables       # v2 rollback archive table
    assert "marketplace_acquired_skills" in tables      # v3 sandbox-only metadata index
    assert ver == 3                                      # all forward-only migrations applied
