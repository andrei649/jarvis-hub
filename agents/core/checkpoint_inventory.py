"""Read-only owner inventory for H011 checkpoint metadata.

This service provides previews, never restore or deletion authority.  Callers must
re-enumerate under their effect lock before acting on a preview generation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path
from urllib.parse import quote

from .commands import Principal
from .file_tools import FileScope, SnapshotStore

MAX_LIMIT = 500
MAX_INDEX_ROWS = 5_000
MAX_STORAGE_FILES = 10_000
_INCOMPLETE = {
    "capturing", "ready", "running", "restore_incomplete", "incomplete",
    "pending", "prepared", "failed",
}
_FILE_TERMINAL = {"restored"}
_GROUP_TERMINAL = {"restored", "no_process"}


class CheckpointInventory:
    """Owner-only, bounded metadata views of one scoped SnapshotStore."""

    def __init__(self, snapshots: SnapshotStore, scope: FileScope,
                 *, terminal_enabled: bool | None = None,
                 file_enabled: bool | None = None) -> None:
        self.snapshots = snapshots
        self.scope = scope
        self.terminal_enabled = terminal_enabled
        self.file_enabled = file_enabled

    @staticmethod
    def _authorize(principal: Principal) -> None:
        if type(principal) is not Principal or principal.admin is not True:
            raise PermissionError("admin_required")

    @staticmethod
    def _arguments(project: str | None, limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            raise ValueError("invalid_limit")
        if project is None:
            return
        if (type(project) is not str or not project or len(project) > 4096
                or not os.path.isabs(project)
                or os.path.normpath(project) != project
                or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in project)):
            raise ValueError("invalid_project")

    def _root_state(self, root: str, dev: int, ino: int) -> str:
        # Exact lexical root matching is intentional: never resolve or probe a
        # stored path outside the owner's configured scope.
        if root not in {str(item) for item in self.scope.roots}:
            return "unconfigured"
        try:
            info = os.stat(root, follow_symlinks=False)
        except OSError:
            return "unreachable"
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (dev, ino):
            return "changed"
        return "live"

    def _storage(self) -> tuple[dict, list[tuple], bool]:
        directory = self.snapshots.directory
        try:
            root_info = os.stat(directory, follow_symlinks=False)
        except FileNotFoundError:
            return {"state": "absent", "bytes": 0, "bytes_exact": True}, [], True
        except OSError:
            return {"state": "unreachable", "bytes": None, "bytes_exact": False}, [], False
        if not stat.S_ISDIR(root_info.st_mode):
            return {"state": "invalid", "bytes": None, "bytes_exact": False}, [], False
        names: list[tuple] = []
        total = 0
        exact = True
        pending = [(directory, "")]
        while pending:
            path, prefix = pending.pop()
            try:
                with os.scandir(path) as scan:
                    for entry in scan:
                        if len(names) >= MAX_STORAGE_FILES:
                            exact = False
                            break
                        relative = prefix + entry.name
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError:
                            names.append((relative, None))
                            exact = False
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            names.append((relative + "/", info.st_dev, info.st_ino,
                                          info.st_mtime_ns))
                            pending.append((Path(entry.path), relative + "/"))
                        elif stat.S_ISREG(info.st_mode):
                            names.append((relative, info.st_size, info.st_dev,
                                          info.st_ino, info.st_mtime_ns))
                            total += info.st_size
                        else:
                            names.append((relative, None))
                            exact = False
            except OSError:
                exact = False
                break
            if not exact and len(names) >= MAX_STORAGE_FILES:
                break
        names.sort()
        return ({"state": "ready", "bytes": total if exact else None,
                 "bytes_exact": exact}, names, exact)

    def _read_index(self) -> tuple[list[dict], bool, bool, str]:
        db_path = self.snapshots.directory / "history.sqlite3"
        try:
            info = os.stat(db_path, follow_symlinks=False)
        except FileNotFoundError:
            return [], False, True, "absent"
        except OSError:
            return [], False, False, "unreachable"
        if not stat.S_ISREG(info.st_mode):
            return [], False, False, "invalid"
        connection = None
        try:
            uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('entries','groups','group_files')")}
            if "entries" not in tables:
                return [], "groups" in tables, False, "invalid"
            rows: list[dict] = []
            complete = True
            bytes_exact = True
            file_rows = connection.execute(
                "SELECT * FROM entries ORDER BY id LIMIT ?",
                (MAX_INDEX_ROWS + 1,)).fetchall()
            if len(file_rows) > MAX_INDEX_ROWS:
                complete = False
            for row in file_rows[:MAX_INDEX_ROWS]:
                item = dict(row)
                item["_generation"] = dict(row)
                item["id"] = f"file:{item['id']}"
                item["type"] = "file"
                item["observed_post_bytes"] = (
                    item["post_size"] if item["post_existed"] == 1 and
                    type(item["post_size"]) is int and item["post_size"] >= 0 else
                    0 if item["post_existed"] == 0 else None
                )
                rows.append(item)
            has_groups = "groups" in tables
            if has_groups:
                group_rows = connection.execute(
                    "SELECT * FROM groups ORDER BY id LIMIT ?",
                    (MAX_INDEX_ROWS + 1,)).fetchall()
                if len(group_rows) > MAX_INDEX_ROWS or "group_files" not in tables:
                    complete = False
                group_bytes: dict[str, int] = {}
                group_refs: dict[str, set[str]] = {}
                group_metadata: dict[str, list[dict]] = {}
                if "group_files" in tables:
                    size_rows = connection.execute(
                        "SELECT * FROM group_files ORDER BY group_id,path LIMIT ?",
                        (MAX_INDEX_ROWS + 1,),
                    ).fetchall()
                    if len(size_rows) > MAX_INDEX_ROWS:
                        complete = False
                    for size_row in size_rows[:MAX_INDEX_ROWS]:
                        ident = size_row["group_id"]
                        size = size_row["post_size"]
                        group_metadata.setdefault(ident, []).append(dict(size_row))
                        group_refs.setdefault(ident, set()).update(
                            ref for ref in (size_row["pre_ref"], size_row["undo_ref"])
                            if isinstance(ref, str)
                        )
                        if size_row["post_existed"] == 1 and type(size) is int and size >= 0:
                            group_bytes[ident] = group_bytes.get(ident, 0) + size
                        elif size_row["post_existed"] != 0:
                            bytes_exact = False
                for row in group_rows[:MAX_INDEX_ROWS]:
                    item = dict(row)
                    item["_generation"] = {"group": dict(row),
                                            "files": group_metadata.get(row["id"], [])}
                    item["id"] = "group:" + str(item["id"])
                    item["type"] = "group"
                    item["observed_post_bytes"] = group_bytes.get(row["id"], 0)
                    item["_refs"] = group_refs.get(row["id"], set())
                    rows.append(item)
            if not complete or not bytes_exact:
                for item in rows:
                    item["observed_post_bytes"] = None
            return rows, has_groups, complete, "ready"
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            return [], False, False, "invalid"
        finally:
            if connection is not None:
                connection.close()

    def _inventory(self, project: str | None) -> dict:
        storage, storage_names, storage_complete = self._storage()
        if storage["state"] in {"invalid", "unreachable"}:
            rows, has_groups, index_complete, index_state = [], False, False, "invalid"
        else:
            rows, has_groups, index_complete, index_state = self._read_index()
        for row in rows:
            try:
                row["root_state"] = self._root_state(
                    row["root"], row["root_dev"], row["root_ino"])
            except (TypeError, ValueError):
                row["root_state"] = "unconfigured"
        if project is not None:
            rows = [row for row in rows if row["root"] == project]
        rows.sort(key=lambda row: (-float(row["created_at"]), row["id"]))
        complete = storage_complete and index_complete
        if index_state not in {"ready", "absent"}:
            complete = False
        return {"rows": rows, "store": storage, "storage_names": storage_names,
                "index_state": index_state, "groups_supported": has_groups,
                "complete": complete, "index_complete": index_complete}

    @staticmethod
    def _public_row(row: dict) -> dict:
        keys = ("id", "type", "path", "root", "root_dev", "root_ino",
                "root_state", "op", "status", "created_at", "observed_post_bytes")
        return {key: row[key] for key in keys if key in row}

    def status(self, principal: Principal, project: str | None = None,
               limit: int = 100) -> dict:
        self._authorize(principal)
        self._arguments(project, limit)
        view = self._inventory(project)
        rows = view["rows"]
        projects: dict[tuple[str, int, int], dict] = {}
        for row in rows:
            root = row["root"]
            identity = (root, row["root_dev"], row["root_ino"])
            item = projects.setdefault(identity, {
                "root": root, "root_state": row["root_state"],
                "root_dev": row["root_dev"], "root_ino": row["root_ino"],
                "files": 0, "groups": 0, "observed_post_bytes": 0,
            })
            item["files" if row["type"] == "file" else "groups"] += 1
            size = row["observed_post_bytes"]
            if item["observed_post_bytes"] is None or size is None:
                item["observed_post_bytes"] = None
            else:
                item["observed_post_bytes"] += size
        ordered = [projects[key] for key in sorted(projects)]
        counts = {
            "files": sum(row["type"] == "file" for row in rows),
            "groups": sum(row["type"] == "group" for row in rows),
            "incomplete": sum(str(row["status"]) in _INCOMPLETE or
                              "incomplete" in str(row["status"]) for row in rows),
        }
        return {
            "ok": view["complete"], "store": view["store"],
            "index_state": view["index_state"], "counts": counts,
            "counts_exact": view["index_complete"],
            "features": {
                "file_history": {"platform_supported": os.name == "posix",
                                 "supported": os.name == "posix",
                                 "enabled": ((view["index_state"] == "ready"
                                              if self.file_enabled is None else bool(self.file_enabled))
                                             and os.name == "posix")},
                "terminal_groups": {"platform_supported": os.name == "posix",
                                    "supported": os.name == "posix",
                                    "schema_present": view["groups_supported"],
                                    "enabled": bool(self.terminal_enabled) and os.name == "posix"},
            },
            "projects": ordered[:limit], "omitted": max(0, len(ordered) - limit),
            "truncated": not view["complete"] or len(ordered) > limit,
        }

    def list(self, principal: Principal, project: str | None = None,
             limit: int = 100) -> dict:
        self._authorize(principal)
        self._arguments(project, limit)
        view = self._inventory(project)
        rows = view["rows"]
        return {"ok": view["complete"], "items": [self._public_row(row) for row in rows[:limit]],
                "omitted": max(0, len(rows) - limit) if view["index_complete"] else None,
                "truncated": not view["complete"] or len(rows) > limit,
                "index_state": view["index_state"]}

    def maintenance_preview(self, principal: Principal, action: str,
                            project: str | None = None, limit: int = 100,
                            keep_orphans: bool = True) -> dict:
        self._authorize(principal)
        self._arguments(project, limit)
        if action not in {"prune", "clear", "clear-legacy"}:
            raise ValueError("invalid_action")
        if type(keep_orphans) is not bool:
            raise ValueError("invalid_keep_orphans")
        view = self._inventory(project)
        rows = view["rows"]
        if action == "clear-legacy":
            selected = []  # No positively identified Nerva legacy archive format.
        elif action == "clear":
            selected = rows
        else:
            selected = [row for row in rows if (
                str(row["status"]) not in _INCOMPLETE
                and "incomplete" not in str(row["status"])
                and ((row["root_state"] == "live" and
                      row["status"] in (_FILE_TERMINAL if row["type"] == "file" else _GROUP_TERMINAL))
                     or (not keep_orphans and row["root_state"] == "unreachable"))
            )]
        # Include the entire bounded index, root currentness and storage names;
        # an additional orphan or new snapshot record changes this generation.
        material = {
            "action": action, "project": project, "keep_orphans": keep_orphans,
            "index_state": view["index_state"], "complete": view["complete"],
            "rows": [(row["id"], row["root_state"], row["_generation"])
                     for row in rows],
            "storage": view["storage_names"],
            "candidates": [row["id"] for row in selected],
        }
        generation = hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        records = {name[:-5] for name, *_ in view["storage_names"]
                   if name.endswith(".json") and "/" not in name}
        shared = {ref for row in rows for ref in (
            row.get("pre_ref"), row.get("undo_ref"), *row.get("_refs", ()))
                  if ref in records}
        return {
            "ok": view["complete"], "action": action,
            "candidates": [self._public_row(row) for row in selected[:limit]],
            "omitted": max(0, len(selected) - limit) if view["index_complete"] else None,
            "truncated": not view["complete"] or len(selected) > limit,
            "complete": view["complete"] and len(selected) <= limit,
            "generation": generation, "reclaimable_bytes": None,
            "protected_shared_refs": len(shared),
            "legacy_format_identified": False,
        }
