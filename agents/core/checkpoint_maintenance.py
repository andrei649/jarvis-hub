"""Owner-authorized, at-most-once maintenance of H011 checkpoint index rows.

This is an effect primitive, not an approval source. The caller supplies a live
approval predicate; a preview and an operation key never confer authority.
Generic SnapshotStore records and blobs are deliberately retained.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from .checkpoint_inventory import _INCOMPLETE, MAX_INDEX_ROWS, CheckpointInventory
from .commands import Principal
from .file_checkpoint_history import HISTORY_SUPPORTED, _locked
from .file_tools import FileScope, SnapshotStore

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FILE_ID = re.compile(r"file:[1-9][0-9]*\Z")
_GROUP_ID = re.compile(r"group:[0-9a-f]{32}\Z")
_JOURNAL = """CREATE TABLE IF NOT EXISTS checkpoint_maintenance_ops (
    operation_key TEXT PRIMARY KEY,
    intent_sha TEXT NOT NULL,
    state TEXT NOT NULL,
    result_json TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
)"""


class _AuthorityRevoked(Exception):
    """The final live checker refused while the write transaction was open."""


def _refused(reason: str) -> dict:
    return {"ok": False, "status": "refused", "reason": reason, "removed": []}


def _uncertain(reason: str, *, journal_state: str = "uncertain") -> dict:
    return {"ok": False, "status": "partial", "reason": reason,
            "journal_state": journal_state, "removed": [], "retained_shared_data": True}


class CheckpointMaintenance:
    """Delete only exact selected history rows after a live external approval."""

    def __init__(self, snapshots: SnapshotStore, scope: FileScope) -> None:
        self.snapshots = snapshots
        self.scope = scope

    @staticmethod
    def _intent(action: str, project: str | None, generation: str,
                candidates: list[str], keep_orphans: bool) -> str:
        material = {"action": action, "project": project, "generation": generation,
                    "candidates": candidates, "keep_orphans": keep_orphans}
        return hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _validate(action: str, project: str | None, generation: str,
                  candidates: list[str], operation_key: str,
                  keep_orphans: bool) -> None:
        CheckpointInventory._arguments(project, 500)
        if type(action) is not str or action not in {"prune", "clear", "clear-legacy"}:
            raise ValueError("invalid_action")
        if type(keep_orphans) is not bool:
            raise ValueError("invalid_keep_orphans")
        if type(generation) is not str or _SHA256.fullmatch(generation) is None:
            raise ValueError("invalid_generation")
        if type(operation_key) is not str or _SHA256.fullmatch(operation_key) is None:
            raise ValueError("invalid_operation_key")
        if (type(candidates) is not list or len(candidates) > 500
                or any(type(item) is not str or len(item) > 64 or
                       (_FILE_ID.fullmatch(item) is None and _GROUP_ID.fullmatch(item) is None)
                       for item in candidates)
                or len(set(candidates)) != len(candidates)):
            raise ValueError("invalid_candidates")

    @staticmethod
    def _authority(check: Callable[[], bool] | None) -> bool:
        if not callable(check):
            return False
        try:
            return check() is True
        except Exception:
            return False

    @staticmethod
    def _row_signature(rows: list[dict]) -> str:
        material = [(row["id"], row["root_state"], row["_generation"]) for row in rows]
        return hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    @classmethod
    def _transaction_row_signature(cls, db: sqlite3.Connection,
                                   inventory: CheckpointInventory,
                                   project: str | None) -> str:
        """Recreate inventory's indexed-row fingerprint on the write connection."""
        db.row_factory = sqlite3.Row
        files = db.execute("SELECT * FROM entries ORDER BY id LIMIT ?",
                           (MAX_INDEX_ROWS + 1,)).fetchall()
        if len(files) > MAX_INDEX_ROWS:
            raise RuntimeError("index_truncated")
        rows = []
        for source in files:
            raw = dict(source)
            rows.append({"id": f"file:{raw['id']}", "root": raw["root"],
                         "root_state": inventory._root_state(
                             raw["root"], raw["root_dev"], raw["root_ino"]),
                         "created_at": raw["created_at"], "_generation": raw})
        tables = {item[0] for item in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('groups','group_files')")}
        if "groups" in tables:
            if "group_files" not in tables:
                raise RuntimeError("group_schema_incomplete")
            groups = db.execute("SELECT * FROM groups ORDER BY id LIMIT ?",
                                (MAX_INDEX_ROWS + 1,)).fetchall()
            members = db.execute("SELECT * FROM group_files ORDER BY group_id,path LIMIT ?",
                                 (MAX_INDEX_ROWS + 1,)).fetchall()
            if len(groups) > MAX_INDEX_ROWS or len(members) > MAX_INDEX_ROWS:
                raise RuntimeError("index_truncated")
            group_files: dict[str, list[dict]] = {}
            for member in members:
                group_files.setdefault(member["group_id"], []).append(dict(member))
            for source in groups:
                raw = dict(source)
                rows.append({"id": "group:" + str(raw["id"]), "root": raw["root"],
                             "root_state": inventory._root_state(
                                 raw["root"], raw["root_dev"], raw["root_ino"]),
                             "created_at": raw["created_at"],
                             "_generation": {"group": raw,
                                             "files": group_files.get(raw["id"], [])}})
        if project is not None:
            rows = [row for row in rows if row["root"] == project]
        rows.sort(key=lambda row: (-float(row["created_at"]), row["id"]))
        return cls._row_signature(rows)

    @staticmethod
    def _inspect_existing(db_path: Path, operation_key: str, intent_sha: str) -> dict | None:
        with closing(sqlite3.connect(db_path, timeout=0)) as connection:
            present = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='checkpoint_maintenance_ops'").fetchone()
            if present is None:
                return None
            row = connection.execute(
                "SELECT intent_sha,state,result_json FROM checkpoint_maintenance_ops "
                "WHERE operation_key=?", (operation_key,)).fetchone()
            if row is None:
                return None
            if row[0] != intent_sha:
                return _refused("operation_key_collision")
            if row[1] == "completed" and row[2] is not None:
                result = json.loads(row[2])
                if type(result) is not dict or result.get("ok") is not True:
                    return _refused("operation_uncertain")
                return result
            return _refused("operation_uncertain")

    @staticmethod
    def _delete_rows(db: sqlite3.Connection, candidates: list[str]) -> tuple[list[str], dict]:
        removed = []
        counts = {"entries": 0, "groups": 0, "group_files": 0,
                  "group_exclusions": 0, "group_runs": 0}
        for ident in candidates:
            if ident.startswith("file:"):
                cursor = db.execute("DELETE FROM entries WHERE id=?", (int(ident[5:]),))
                counts["entries"] += cursor.rowcount
            else:
                group_id = ident[6:]
                for table, statement in (
                    ("group_files", "DELETE FROM group_files WHERE group_id=?"),
                    ("group_exclusions", "DELETE FROM group_exclusions WHERE group_id=?"),
                    ("group_runs", "DELETE FROM group_runs WHERE group_id=?"),
                ):
                    counts[table] += db.execute(
                        statement, (group_id,)).rowcount
                cursor = db.execute("DELETE FROM groups WHERE id=?", (group_id,))
                counts["groups"] += cursor.rowcount
            if cursor.rowcount != 1:
                raise RuntimeError("candidate_changed")
            removed.append(ident)
        return removed, counts

    @staticmethod
    def _mark_uncertain(db_path: Path, operation_key: str) -> str:
        try:
            with closing(sqlite3.connect(db_path, timeout=0)) as db, db:
                db.execute("UPDATE checkpoint_maintenance_ops SET state='uncertain', "
                           "finished_at=? WHERE operation_key=? AND state='running'",
                           (time.time(), operation_key))
            return "uncertain"
        except sqlite3.Error:
            # A durable running claim is itself non-replayable after restart.
            return "running"

    def apply(self, principal: Principal, *, action: str, project: str | None,
              generation: str, candidates: list[str], operation_key: str,
              keep_orphans: bool = True,
              authority_check: Callable[[], bool] | None = None) -> dict:
        CheckpointInventory._authorize(principal)
        if not self._authority(authority_check):
            return _refused("authority_required")
        self._validate(action, project, generation, candidates, operation_key, keep_orphans)
        if not HISTORY_SUPPORTED:
            return _refused("unsupported_platform")
        inventory = CheckpointInventory(self.snapshots, self.scope)
        directory = self.snapshots.directory
        try:
            store_info = os.stat(directory, follow_symlinks=False)
        except FileNotFoundError:
            # The read-only preview is authoritative for this no-effect case.
            plan = inventory.maintenance_preview(
                principal, action, project=project, limit=500, keep_orphans=keep_orphans)
            if (plan["complete"] is True and plan["generation"] == generation
                    and not plan["candidates"] and not candidates):
                return {"ok": True, "status": "ok", "removed": [],
                        "retained_shared_data": True, "no_op": True}
            return _refused("stale_preview")
        except OSError:
            return _refused("store_unavailable")
        if not stat.S_ISDIR(store_info.st_mode):
            return _refused("store_invalid")
        db_path = directory / "history.sqlite3"
        try:
            db_info = os.stat(db_path, follow_symlinks=False)
        except OSError:
            return _refused("index_unavailable")
        if not stat.S_ISREG(db_info.st_mode):
            return _refused("index_invalid")
        intent_sha = self._intent(action, project, generation, candidates, keep_orphans)
        try:
            with _locked(directory):
                try:
                    prior = self._inspect_existing(db_path, operation_key, intent_sha)
                except (sqlite3.Error, ValueError, TypeError):
                    return _refused("journal_unavailable")
                if prior is not None:
                    return prior
                plan = inventory.maintenance_preview(
                    principal, action, project=project, limit=500,
                    keep_orphans=keep_orphans)
                actual_ids = [row["id"] for row in plan["candidates"]]
                if not plan["ok"] or not plan["complete"] or plan["truncated"]:
                    return _refused("inventory_incomplete")
                if plan["generation"] != generation or actual_ids != candidates:
                    return _refused("stale_preview")
                if not candidates:
                    return {"ok": True, "status": "ok", "removed": [],
                            "retained_shared_data": True, "no_op": True}
                view = inventory._inventory(project)
                if not view["complete"]:
                    return _refused("inventory_incomplete")
                rows = view["rows"]
                if any(str(row["status"]) in _INCOMPLETE or
                       "incomplete" in str(row["status"]) for row in rows):
                    return _refused("incomplete_history")
                if any(row["root_state"] in {"changed", "unconfigured"} for row in rows):
                    return _refused("root_untrusted")
                if keep_orphans and any(row["root_state"] == "unreachable" for row in rows):
                    return _refused("orphan_not_selected")
                selected = {row["id"]: row for row in rows if row["id"] in candidates}
                if len(selected) != len(candidates):
                    return _refused("stale_preview")
                if any(row["root_state"] == "unreachable" and keep_orphans
                       for row in selected.values()):
                    return _refused("orphan_not_selected")
                row_signature = self._row_signature(rows)
                # Durable claim is committed independently of physical deletion.
                try:
                    with closing(sqlite3.connect(db_path, timeout=0)) as db, db:
                        db.execute("BEGIN IMMEDIATE")
                        db.execute(_JOURNAL)
                        db.execute("INSERT INTO checkpoint_maintenance_ops "
                                   "(operation_key,intent_sha,state,created_at) "
                                   "VALUES (?,?,'running',?)",
                                   (operation_key, intent_sha, time.time()))
                except sqlite3.Error:
                    return _refused("journal_claim_failed")
                try:
                    current = inventory._inventory(project)
                    if not current["complete"] or self._row_signature(current["rows"]) != row_signature:
                        raise RuntimeError("state_changed_after_claim")
                    if not self._authority(authority_check):
                        state = self._mark_uncertain(db_path, operation_key)
                        return _uncertain("authority_revoked", journal_state=state)
                    # The callback can itself observe or change local state;
                    # bind the exact rows/root identities again after it ran.
                    current = inventory._inventory(project)
                    if not current["complete"] or self._row_signature(current["rows"]) != row_signature:
                        raise RuntimeError("state_changed_after_authority")
                    with closing(sqlite3.connect(db_path, timeout=0)) as db, db:
                        db.execute("BEGIN IMMEDIATE")
                        if self._transaction_row_signature(db, inventory, project) != row_signature:
                            raise RuntimeError("state_changed_in_transaction")
                        # No I/O or hook follows this literal live check before
                        # the first selected-row deletion.
                        if not self._authority(authority_check):
                            raise _AuthorityRevoked
                        removed, counts = self._delete_rows(db, candidates)
                        result = {"ok": True, "status": "ok", "removed": removed,
                                  "removed_counts": counts,
                                  "retained_shared_data": True, "retained_blobs": "all"}
                        db.execute("UPDATE checkpoint_maintenance_ops SET "
                                   "state='completed', result_json=?, finished_at=? "
                                   "WHERE operation_key=? AND state='running'",
                                   (json.dumps(result, sort_keys=True), time.time(), operation_key))
                    return result
                except _AuthorityRevoked:
                    state = self._mark_uncertain(db_path, operation_key)
                    return _uncertain("authority_revoked", journal_state=state)
                except Exception:
                    state = self._mark_uncertain(db_path, operation_key)
                    return _uncertain("effect_uncertain", journal_state=state)
        except (OSError, sqlite3.Error):
            return _refused("store_unavailable")
