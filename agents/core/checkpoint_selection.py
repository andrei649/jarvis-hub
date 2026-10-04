"""Owner-only, read-only H011 checkpoint selection and diff previews.

This module resolves an inventory row to the real scoped history plan. Its IDs,
signatures and previews are observations, never approval or restore authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .checkpoint_inventory import CheckpointInventory
from .commands import Principal
from .file_checkpoint_history import FileCheckpointHistory
from .file_tools import (
    FileScope,
    SnapshotStore,
    instruction_labels,
    looks_instruction_name,
)

_FILE_ID = re.compile(r"file:[1-9][0-9]*\Z")
_GROUP_ID = re.compile(r"group:[0-9a-f]{32}\Z")
_ORDINAL = re.compile(r"[1-9][0-9]*\Z")
_SCHEMA = frozenset({"entries", "groups", "group_files", "group_exclusions", "group_runs"})


def _refused(reason: str) -> dict:
    return {"ok": False, "reason": reason}


class CheckpointSelection:
    """Resolve one stable checkpoint ID without conferring effect authority."""

    def __init__(self, snapshots: SnapshotStore, configured_scope: FileScope) -> None:
        self.snapshots = snapshots
        self.configured_scope = configured_scope

    @staticmethod
    def _identifier(identifier: object) -> tuple[str | None, int | None]:
        if type(identifier) is int:
            return (None, identifier) if 1 <= identifier <= 500 else (None, None)
        if type(identifier) is not str or not 1 <= len(identifier) <= 64:
            return None, None
        if _FILE_ID.fullmatch(identifier) or _GROUP_ID.fullmatch(identifier):
            return identifier, None
        if _ORDINAL.fullmatch(identifier):
            ordinal = int(identifier)
            if 1 <= ordinal <= 500:
                return None, ordinal
        return None, None

    def _indexed_members(self, checkpoint_id: str) -> dict | None:
        """Read the complete schema and group members without opening SQLite for writes."""
        db_path = self.snapshots.directory / "history.sqlite3"
        try:
            info = os.stat(db_path, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                return None
            uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                if not _SCHEMA.issubset(tables):
                    return None
                if checkpoint_id.startswith("file:"):
                    return {"exclusions": [], "runs": []}
                group_id = checkpoint_id[6:]
                exclusions = [dict(row) for row in db.execute(
                    "SELECT * FROM group_exclusions WHERE group_id=? ORDER BY path LIMIT 5001",
                    (group_id,),
                )]
                runs = [dict(row) for row in db.execute(
                    "SELECT * FROM group_runs WHERE group_id=? ORDER BY id LIMIT 5001",
                    (group_id,),
                )]
                if len(exclusions) > 5000 or len(runs) > 5000:
                    return None
                return {"exclusions": exclusions, "runs": runs}
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None

    @staticmethod
    def _signature(row: dict, members: dict) -> str:
        material = {"indexed": row["_generation"], "members": members}
        return hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"), default=str,
        ).encode()).hexdigest()

    @staticmethod
    def _view_signature(rows: list[dict]) -> str:
        material = [(row["id"], row["root_state"], row["_generation"]) for row in rows]
        return hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"), default=str,
        ).encode()).hexdigest()

    def _resolve(self, principal: Principal, identifier: object,
                 project: str | None) -> tuple[dict | None, dict | None, str | None]:
        # This must stay first: even malformed input cannot make a guest probe a path.
        CheckpointInventory._authorize(principal)
        try:
            CheckpointInventory._arguments(project, 500)
        except ValueError:
            return None, None, "invalid_project"
        typed, ordinal = self._identifier(identifier)
        if typed is None and ordinal is None:
            return None, None, "invalid_identifier"
        inventory = CheckpointInventory(self.snapshots, self.configured_scope)
        listed = inventory.list(principal, limit=500)
        if listed["index_state"] == "absent":
            return None, None, "unknown_checkpoint"
        if (listed.get("ok") is not True or listed.get("truncated") is not False
                or listed.get("omitted") != 0 or listed["index_state"] != "ready"):
            return None, None, "inventory_incomplete"
        view = inventory._inventory(None)
        rows = view["rows"]
        if (not view["complete"] or view["index_state"] != "ready"
                or len(rows) != len(listed["items"])
                or [inventory._public_row(row) for row in rows] != listed["items"]):
            return None, None, "inventory_changed"
        visible = [row for row in rows if project is None or row["root"] == project]
        if ordinal is not None:
            if ordinal > len(visible):
                return None, None, "unknown_checkpoint"
            checkpoint_id = visible[ordinal - 1]["id"]
        else:
            checkpoint_id = typed
        row = next((item for item in rows if item["id"] == checkpoint_id), None)
        if row is None:
            return None, None, "unknown_checkpoint"
        if project is not None and row["root"] != project:
            return None, None, "project_mismatch"
        if row["root_state"] != "live":
            return None, None, "root_untrusted"
        members = self._indexed_members(checkpoint_id)
        if members is None:
            return None, None, "index_incomplete"
        try:
            scope = FileScope([Path(row["root"])])
            if scope.roots != (Path(row["root"]),):
                return None, None, "root_untrusted"
        except (OSError, ValueError):
            return None, None, "root_untrusted"
        return row, {"inventory": inventory, "members": members, "scope": scope,
                     "view_signature": self._view_signature(rows)}, None

    def _still_current(self, row: dict, context: dict) -> bool:
        inventory = context["inventory"]
        view = inventory._inventory(None)
        if (not view["complete"] or view["index_state"] != "ready"
                or len(view["rows"]) > 500
                or self._view_signature(view["rows"]) != context["view_signature"]):
            return False
        current = next((item for item in view["rows"] if item["id"] == row["id"]), None)
        if current is None or current["root_state"] != "live":
            return False
        members = self._indexed_members(row["id"])
        return (members is not None
                and self._signature(current, members)
                == self._signature(row, context["members"])
                and current["root"] == row["root"]
                and (current["root_dev"], current["root_ino"])
                == (row["root_dev"], row["root_ino"]))

    @staticmethod
    def _instruction_paths(row: dict, storage: dict | None) -> tuple[list[str], dict | None]:
        if row["type"] == "file":
            candidates = [row["path"]]
        elif storage is not None and type(storage.get("paths")) is list:
            candidates = [item["path"] for item in storage["paths"]]
        else:
            candidates = [item["path"] for item in row["_generation"]["files"]
                          if item.get("change_kind") in {"modified", "created", "deleted"}]
        sensitive = [path for path in candidates if looks_instruction_name(Path(path).name)]
        return sensitive, instruction_labels(*(Path(path).name for path in sensitive))

    @staticmethod
    def _metadata(row: dict, signature: str) -> dict:
        return {"checkpoint_id": row["id"], "root": row["root"],
                "root_dev": row["root_dev"], "root_ino": row["root_ino"],
                "indexed_signature": signature, "requires_authority": True}

    def plan(self, principal: Principal, identifier: object, *,
             project: str | None = None, paths: list[str] | tuple[str, ...] | None = None,
             force: bool = False) -> dict:
        CheckpointInventory._authorize(principal)
        if type(force) is not bool:
            return _refused("invalid_force")
        row, context, error = self._resolve(principal, identifier, project)
        if error:
            return _refused(error)
        if row["type"] == "file" and paths is not None:
            return _refused("unsupported_paths")
        history = FileCheckpointHistory(self.snapshots, context["scope"])
        storage = (history.plan_restore(int(row["id"][5:]), force=force)
                   if row["type"] == "file" else
                   history.plan_group_restore(row["id"][6:], paths=paths, force=force))
        if not self._still_current(row, context):
            return _refused("index_changed")
        signature = self._signature(row, context["members"])
        sensitive, labels = self._instruction_paths(row, storage)
        return {"ok": storage.get("ok") is True,
                **({"reason": storage.get("reason", "storage_refused")}
                   if storage.get("ok") is not True else {}),
                **self._metadata(row, signature), "storage_plan": storage,
                "instruction_sensitive_paths": sensitive,
                "instruction_labels": labels}

    def diff(self, principal: Principal, identifier: object, *,
             project: str | None = None, path: str | None = None,
             max_bytes: int = 65536) -> dict:
        CheckpointInventory._authorize(principal)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 65536:
            return _refused("invalid_max_bytes")
        row, context, error = self._resolve(principal, identifier, project)
        if error:
            return _refused(error)
        if path is not None:
            return _refused("unsupported_path_filter")
        history = FileCheckpointHistory(self.snapshots, context["scope"])
        storage = (history.diff(int(row["id"][5:]), max_bytes=max_bytes)
                   if row["type"] == "file" else
                   history.diff_group(row["id"][6:], max_bytes=max_bytes))
        if not self._still_current(row, context):
            return _refused("index_changed")
        signature = self._signature(row, context["members"])
        sensitive, labels = self._instruction_paths(row, None)
        return {"ok": storage.get("ok") is True,
                **({"reason": storage.get("reason", "storage_refused")}
                   if storage.get("ok") is not True else {}),
                **self._metadata(row, signature), "storage_diff": storage,
                "truncated": bool(storage.get("truncated") or
                                  storage.get("reason") == "diff_too_large"),
                "instruction_sensitive_paths": sensitive,
                "instruction_labels": labels}
