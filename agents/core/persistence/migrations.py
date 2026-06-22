"""migrations.py — forward-only SQLite schema migrations gated by ``user_version``.

The hub's SQLite stores each define their schema inline with
``CREATE TABLE IF NOT EXISTS`` and, historically, evolved it with copy-pasted
``PRAGMA table_info`` + ``ALTER TABLE`` guards (audit.py, marketplace.py). This
gives them a single, tested, versioned path instead (H23.7).

A store declares an ordered list of migrations — ``migrations[i]`` upgrades the
DB from version ``i`` to ``i+1`` — and calls :func:`apply_migrations` after
creating its base schema. SQLite's ``PRAGMA user_version`` (a single integer in
the DB header) records the applied version; both ``user_version`` and DDL are
transactional, so each migration + its version bump apply atomically. Re-running
is a no-op once the DB is at the latest version.

**Forward-only, append-only.** Never edit or reorder a shipped migration — only
append a new one. A migration body should be idempotent where it might meet an
already-upgraded legacy DB (e.g. guard an ``ADD COLUMN`` with ``table_info``),
because a DB can sit at ``user_version=0`` yet already carry columns added by the
pre-framework ad-hoc code.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable

logger = logging.getLogger("jarvis.persistence")

# A migration mutates the connection's schema in place. It runs inside a
# transaction managed by apply_migrations; it must NOT commit/rollback itself.
Migration = Callable[[sqlite3.Connection], None]


def schema_version(conn: sqlite3.Connection) -> int:
    """Current ``PRAGMA user_version`` (0 for a fresh/never-migrated DB)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def apply_migrations(conn: sqlite3.Connection, migrations: list[Migration], *,
                     name: str = "") -> int:
    """Apply pending forward-only migrations; return the resulting version.

    ``migrations[i]`` upgrades version ``i`` → ``i+1``. Migrations already applied
    (``user_version`` > i) are skipped, so this is safe to call on every startup.
    Each migration and its ``user_version`` bump run in ONE transaction: if a
    migration raises, that step rolls back and the exception propagates, leaving
    the DB at the last good version (never half-migrated).
    """
    current = schema_version(conn)
    target = len(migrations)
    if current >= target:
        return current

    for version in range(current, target):
        migrate = migrations[version]
        try:
            # Explicit transaction so the schema change AND the version bump are
            # atomic regardless of the connection's isolation_level. user_version
            # cannot be parameterised; `version + 1` is a trusted int.
            conn.execute("BEGIN IMMEDIATE")
            migrate(conn)
            conn.execute(f"PRAGMA user_version = {version + 1}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("migration failed: %s v%d→%d", name or "<db>", version, version + 1)
            raise

    return schema_version(conn)


def column_adder(table: str, column: str, decl: str) -> Migration:
    """Build an idempotent ``ADD COLUMN`` migration.

    Guards with ``table_info`` so it is a no-op on a legacy DB that already has
    the column (added by pre-framework ad-hoc code at ``user_version=0``) — the
    framework still stamps the version afterwards. ``table`` and ``column`` are
    code-supplied identifiers (never user input), so interpolation is safe.
    """
    def _migrate(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    return _migrate
