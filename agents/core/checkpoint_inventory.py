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

from .checkpoint_payloads import CheckpointPayloadStore, PayloadRefusal, _ref
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
_FILE_COMPLETE = {"applied", "restored"}
_GROUP_COMPLETE = {"finished", "restored", "no_process"}
MAX_KEEP_LAST = 5_000
MAX_RETENTION_BYTES = 1 << 40
MAX_GC_CANDIDATES = 500


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

    def _read_index(self) -> tuple[list[dict], list[dict], bool, bool, str]:
        db_path = self.snapshots.directory / "history.sqlite3"
        try:
            info = os.stat(db_path, follow_symlinks=False)
        except FileNotFoundError:
            return [], [], False, True, "absent"
        except OSError:
            return [], [], False, False, "unreachable"
        if not stat.S_ISREG(info.st_mode):
            return [], [], False, False, "invalid"
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
                return [], [], "groups" in tables, False, "invalid"
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
            raw_group_files: list[dict] = []
            if "group_files" in tables:
                child_rows = connection.execute(
                    "SELECT * FROM group_files ORDER BY group_id,path LIMIT ?",
                    (MAX_INDEX_ROWS + 1,),
                ).fetchall()
                raw_group_files = [dict(child) for child in child_rows[:MAX_INDEX_ROWS]]
                if len(child_rows) > MAX_INDEX_ROWS or not has_groups:
                    complete = False
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
                    group_ids = {row["id"] for row in group_rows[:MAX_INDEX_ROWS]}
                    for size_row in raw_group_files:
                        ident = size_row["group_id"]
                        if ident not in group_ids:
                            complete = False
                        size = size_row["post_size"]
                        group_metadata.setdefault(ident, []).append(size_row)
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
            return rows, raw_group_files, has_groups, complete, "ready"
        except (sqlite3.Error, KeyError, TypeError, ValueError):
            return [], [], False, False, "invalid"
        finally:
            if connection is not None:
                connection.close()

    def _inventory(self, project: str | None) -> dict:
        storage, storage_names, storage_complete = self._storage()
        if storage["state"] in {"invalid", "unreachable"}:
            rows, raw_group_files, has_groups, index_complete, index_state = [], [], False, False, "invalid"
        else:
            rows, raw_group_files, has_groups, index_complete, index_state = self._read_index()
        for row in rows:
            try:
                row["root_state"] = self._root_state(
                    row["root"], row["root_dev"], row["root_ino"])
            except (TypeError, ValueError):
                row["root_state"] = "unconfigured"
        rows.sort(key=lambda row: (-float(row["created_at"]), row["id"]))
        complete = storage_complete and index_complete
        if index_state not in {"ready", "absent"}:
            complete = False
        try:
            owned = CheckpointPayloadStore(self.snapshots).inventory() if complete else None
        except PayloadRefusal:
            owned = None
        if owned is None or owned["complete"] is not True:
            complete = False
        else:
            generic_records = ({name[:-5] for name, *_ in storage_names
                                if name.endswith(".json") and "/" not in name
                                and _ref(name[:-5])}
                               if owned["state"] == "ready" else set())
            for row in rows:
                record_refs, _ = self._row_refs(row)
                if (owned["state"] == "ready" and
                        any(ref not in owned["records"] and ref not in generic_records
                            for ref in record_refs)):
                    complete = False
                    break
                members = row["_generation"].get("files", []) if row["type"] == "group" else [row]
                if any((post := member.get("post_sha")) is not None and
                       (not _ref(post) or post not in owned["blobs"])
                       for member in members):
                    complete = False
                    break
        if not complete:
            storage["bytes"] = None
            storage["bytes_exact"] = False
        all_rows = rows
        rows = [row for row in all_rows if row["root"] == project] if project is not None else all_rows
        return {"rows": rows, "all_rows": all_rows, "raw_group_files": raw_group_files,
                "owned": owned,
                "store": storage, "storage_names": storage_names,
                "index_state": index_state, "groups_supported": has_groups,
                "complete": complete, "index_complete": index_complete}

    @staticmethod
    def _row_refs(row: dict) -> tuple[set[str], set[str]]:
        members = row["_generation"].get("files", []) if row["type"] == "group" else [row]
        records = {ref for member in members for ref in
                   (member.get("pre_ref"), member.get("undo_ref")) if isinstance(ref, str)}
        blobs = {ref for member in members for ref in (member.get("post_sha"),)
                 if isinstance(ref, str)}
        return records, blobs

    @staticmethod
    def _complete_row(row: dict) -> bool:
        return row["status"] in (_FILE_COMPLETE if row["type"] == "file" else _GROUP_COMPLETE)

    @staticmethod
    def _reference_breakdown(remaining: list[dict], owned: dict | None,
                             storage_names: list[tuple], complete: bool) -> dict:
        keys = ("generic_retained_records", "generic_index_referenced_records",
                "shared_owned_records", "shared_owned_blobs",
                "retained_direct_post_blobs", "protected_owned_records",
                "protected_owned_blobs", "unreferenced_owned_records",
                "unreferenced_owned_blobs")
        if not complete or owned is None:
            return {"complete": False, **dict.fromkeys(keys)}
        generic_names = {name[:-5] for name, *_ in storage_names
                         if name.endswith(".json") and "/" not in name
                         and _ref(name[:-5])}
        generic_refs: set[str] = set()
        direct_post: set[str] = set()
        record_holders: dict[str, set[tuple]] = {}
        blob_holders: dict[str, set[tuple]] = {}
        for row in remaining:
            identity = (row["root"], row["root_dev"], row["root_ino"])
            records, posts = CheckpointInventory._row_refs(row)
            for ref in records:
                if ref in generic_names and ref not in owned["records"]:
                    generic_refs.add(ref)
                if ref in owned["records"]:
                    record_holders.setdefault(ref, set()).add(identity)
                    blob_holders.setdefault(owned["records"][ref]["blob_sha"], set()).add(identity)
            for sha in posts:
                if sha in owned["blobs"]:
                    direct_post.add(sha)
                    blob_holders.setdefault(sha, set()).add(identity)
        return {"complete": True,
                "generic_retained_records": len(generic_names),
                "generic_index_referenced_records": len(generic_refs),
                "shared_owned_records": sum(len(holders) > 1 for holders in record_holders.values()),
                "shared_owned_blobs": sum(len(holders) > 1 for holders in blob_holders.values()),
                "retained_direct_post_blobs": len(direct_post),
                "protected_owned_records": len(record_holders),
                "protected_owned_blobs": len(blob_holders),
                "unreferenced_owned_records": len(owned["records"]) - len(record_holders),
                "unreferenced_owned_blobs": len(owned["blobs"]) - len(blob_holders)}

    @staticmethod
    def _categories(names: list[tuple], owned: dict | None, exact: bool) -> dict:
        categories = {"index_bytes": 0, "operation_journal_bytes": 0,
                      "generic_snapshot_bytes": 0, "owned_payload_bytes": None,
                      "other_overhead_bytes": 0}
        if not exact or owned is None or not owned["complete"]:
            return dict.fromkeys(categories)
        categories["owned_payload_bytes"] = owned["physical_bytes"]
        for name, *parts in names:
            if name.endswith("/") or len(parts) != 4:
                continue
            size = parts[0]
            if name.startswith("checkpoint_payloads-v1/"):
                continue
            if name.startswith("history.sqlite3"):
                key = "index_bytes"
            elif name.startswith("checkpoint_operations.sqlite3"):
                key = "operation_journal_bytes"
            elif ((name.endswith(".json") and "/" not in name and _ref(name[:-5]))
                  or (name.startswith("blobs/") and _ref(name[6:]))):
                key = "generic_snapshot_bytes"
            else:
                key = "other_overhead_bytes"
            categories[key] += size
        return categories

    def _accounting(self, view: dict) -> tuple[dict, dict[tuple, dict]]:
        owned = view["owned"]
        if owned is None or not view["complete"]:
            return ({"complete": False, "physical_bytes": None, "shared_bytes": None,
                     "unreferenced_bytes": None}, {})
        records, blobs = owned["records"], owned["blobs"]
        owners: dict[tuple[str, str], set[tuple]] = {}
        logical: dict[tuple, int | None] = {}
        row_logical: dict[str, int | None] = {}
        for row in view["all_rows"]:
            identity = (row["root"], row["root_dev"], row["root_ino"])
            record_refs, post_refs = self._row_refs(row)
            bytes_used = 0
            seen_blobs = set(post_refs)
            for ref in record_refs:
                if ref in records:
                    owners.setdefault(("record", ref), set()).add(identity)
                    if bytes_used is not None:
                        bytes_used += records[ref]["physical_size"]
                    seen_blobs.add(records[ref]["blob_sha"])
                else:
                    bytes_used = None
            for sha in seen_blobs:
                if sha in blobs:
                    owners.setdefault(("blob", sha), set()).add(identity)
                    if bytes_used is not None:
                        bytes_used += blobs[sha]["physical_size"]
                else:
                    bytes_used = None
            row_logical[row["id"]] = bytes_used
            previous = logical.get(identity, 0)
            logical[identity] = None if previous is None or bytes_used is None else previous + bytes_used
        per_project = {identity: {"logical_checkpoint_bytes": logical.get(identity),
                                  "unique_owned_bytes": 0, "orphan_bytes": 0}
                       for identity in logical}
        shared = unreferenced = 0
        for kind, assets in (("record", records), ("blob", blobs)):
            for ref, asset in assets.items():
                holders = owners.get((kind, ref), set())
                size = asset["physical_size"]
                if not holders:
                    unreferenced += size
                elif len(holders) > 1:
                    shared += size
                else:
                    identity = next(iter(holders))
                    per_project[identity]["unique_owned_bytes"] += size
        for identity, item in per_project.items():
            row = next((row for row in view["all_rows"] if
                        (row["root"], row["root_dev"], row["root_ino"]) == identity), None)
            if row is not None and row["root_state"] in {"unreachable", "unconfigured"}:
                item["orphan_bytes"] = item["unique_owned_bytes"]
        return ({"complete": True, "physical_bytes": owned["physical_bytes"],
                 "shared_bytes": shared, "unreferenced_bytes": unreferenced,
                 "marker_bytes": owned["marker_bytes"], "row_logical": row_logical}, per_project)

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
        accounting, project_bytes = self._accounting(view)
        view["store"]["categories"] = self._categories(
            view["storage_names"], view["owned"], view["store"]["bytes_exact"])
        projects: dict[tuple[str, int, int], dict] = {}
        for row in rows:
            root = row["root"]
            identity = (root, row["root_dev"], row["root_ino"])
            item = projects.setdefault(identity, {
                "root": root, "root_state": row["root_state"],
                "root_dev": row["root_dev"], "root_ino": row["root_ino"],
                "files": 0, "groups": 0, "observed_post_bytes": 0,
                "logical_checkpoint_bytes": project_bytes.get(identity, {}).get("logical_checkpoint_bytes"),
                "unique_owned_bytes": project_bytes.get(identity, {}).get("unique_owned_bytes"),
                "orphan_bytes": project_bytes.get(identity, {}).get("orphan_bytes"),
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
            "owned_payloads": {key: value for key, value in accounting.items()
                               if key != "row_logical"},
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
                            keep_orphans: bool | None = None,
                            keep_last: int | None = None,
                            max_bytes: int | None = None,
                            include_orphans: bool = False) -> dict:
        self._authorize(principal)
        self._arguments(project, limit)
        if action not in {"prune", "clear", "clear-legacy"}:
            raise ValueError("invalid_action")
        if keep_orphans is not None and type(keep_orphans) is not bool:
            raise ValueError("invalid_keep_orphans")
        if keep_orphans is not None:
            include_orphans = not keep_orphans
        if type(include_orphans) is not bool:
            raise ValueError("invalid_include_orphans")
        if keep_last is not None and (type(keep_last) is not int or not 1 <= keep_last <= MAX_KEEP_LAST):
            raise ValueError("invalid_keep_last")
        if max_bytes is not None and (type(max_bytes) is not int or not 1 <= max_bytes <= MAX_RETENTION_BYTES):
            raise ValueError("invalid_max_bytes")
        if action != "prune" and (keep_last is not None or max_bytes is not None or include_orphans):
            raise ValueError("invalid_retention_action")
        view = self._inventory(project)
        rows = view["rows"]
        all_rows = view["all_rows"]
        accounting, _ = self._accounting(view)
        if action == "clear-legacy":
            selected = []  # No positively identified Nerva legacy archive format.
        elif action == "clear":
            selected = [row for row in rows if self._complete_row(row)]
        else:
            selected = []
            budget_unknown = False
            by_project: dict[tuple, list[dict]] = {}
            for row in rows:
                identity = (row["root"], row["root_dev"], row["root_ino"])
                by_project.setdefault(identity, []).append(row)
            for project_rows in by_project.values():
                complete = [row for row in project_rows if self._complete_row(row)]
                live = [row for row in complete if row["root_state"] == "live"]
                # The inventory is newest-first; a retained newest complete row
                # stays protected even when the requested byte cap is impossible.
                logical = accounting.get("row_logical", {})
                retained_live = [row for row in project_rows if row["root_state"] == "live"]
                current_bytes = (sum(logical[row["id"]] for row in retained_live)
                                 if all(logical.get(row["id"]) is not None
                                        for row in retained_live) else None)
                if max_bytes is not None and current_bytes is None:
                    budget_unknown = True
                min_keep = keep_last if keep_last is not None else 1
                if keep_last is None and max_bytes is None:
                    chosen = [row for row in live[1:] if row["status"] in (
                        _FILE_TERMINAL if row["type"] == "file" else _GROUP_TERMINAL)]
                else:
                    chosen = live[min_keep:] if keep_last is not None else []
                    if current_bytes is not None:
                        current_bytes -= sum(logical[row["id"]] for row in chosen)
                    chosen_ids = {row["id"] for row in chosen}
                    if max_bytes is not None and current_bytes is not None:
                        for row in reversed(live[min_keep:]):
                            if current_bytes <= max_bytes:
                                break
                            if row["id"] not in chosen_ids:
                                chosen.append(row)
                                chosen_ids.add(row["id"])
                                current_bytes -= logical[row["id"]]
                selected.extend(chosen)
                if include_orphans:
                    selected.extend(row for row in complete if row["root_state"] in
                                    {"unreachable", "unconfigured"})
            selected.sort(key=lambda row: (-float(row["created_at"]), row["id"]))
        if action != "prune":
            budget_unknown = False
        remaining_eligible_rows = 0
        if action == "clear" and len(selected) > MAX_LIMIT:
            remaining_eligible_rows = len(selected) - MAX_LIMIT
            selected = selected[:MAX_LIMIT]
        selected_ids = {row["id"] for row in selected}
        remaining = [row for row in all_rows if row["id"] not in selected_ids]
        owned = view["owned"]
        gc_records: list[str] = []
        gc_blobs: list[str] = []
        reclaimable = None
        if view["complete"] and owned is not None:
            retained_records: set[str] = set()
            retained_blobs: set[str] = set()
            for row in remaining:
                records, blobs = self._row_refs(row)
                retained_records.update(records)
                retained_blobs.update(blobs)
            gc_records = sorted(set(owned["records"]) - retained_records) if action != "clear-legacy" else []
            for ref in retained_records:
                if ref in owned["records"]:
                    retained_blobs.add(owned["records"][ref]["blob_sha"])
            gc_blobs = sorted(set(owned["blobs"]) - retained_blobs) if action != "clear-legacy" else []
            reclaimable = sum(owned["records"][ref]["physical_size"] for ref in gc_records)
            reclaimable += sum(owned["blobs"][sha]["physical_size"] for sha in gc_blobs)
        if budget_unknown:
            gc_records, gc_blobs, reclaimable = [], [], None
        remaining_eligible_assets = 0
        if action == "clear" and len(gc_records) + len(gc_blobs) > MAX_GC_CANDIDATES:
            all_records, all_blobs = gc_records, gc_blobs
            gc_records = all_records[:MAX_GC_CANDIDATES]
            retained_owned_records = set(owned["records"]) - set(gc_records)
            retained_owned_blobs = {owned["records"][ref]["blob_sha"]
                                    for ref in retained_owned_records}
            gc_blobs = [sha for sha in all_blobs if sha not in retained_owned_blobs][
                :MAX_GC_CANDIDATES - len(gc_records)]
            remaining_eligible_assets = len(all_records) + len(all_blobs) - len(gc_records) - len(gc_blobs)
            reclaimable = sum(owned["records"][ref]["physical_size"] for ref in gc_records)
            reclaimable += sum(owned["blobs"][sha]["physical_size"] for sha in gc_blobs)
        gc_candidate_overflow = action != "clear" and len(gc_records) + len(gc_blobs) > MAX_GC_CANDIDATES
        if gc_candidate_overflow:
            reclaimable = None
        # Include the entire bounded index, root currentness and storage names;
        # an additional orphan or new snapshot record changes this generation.
        material = {
            "action": action, "project": project, "include_orphans": include_orphans,
            "keep_last": keep_last, "max_bytes": max_bytes,
            "index_state": view["index_state"], "complete": view["complete"],
            "rows": [(row["id"], row["root_state"], row["_generation"])
                     for row in all_rows],
            "raw_group_files": view["raw_group_files"],
            "owned": ({**owned, "identity": {
                **owned["identity"],
                "generic": {key: owned["identity"]["generic"][key]
                            for key in ("dev", "ino")},
            }} if owned is not None and "generic" in owned["identity"] else owned),
            # The controller's approval/claim journal changes during this operation;
            # it contains no checkpoint payload and cannot invalidate its own preview.
            "storage": [item for item in view["storage_names"] if item[0] not in {
                "checkpoint_operations.sqlite3", "checkpoint_operations.sqlite3-wal",
                "checkpoint_operations.sqlite3-shm", "checkpoint_operations.sqlite3-journal",
            }],
            "candidates": [row["id"] for row in selected],
            "gc_records": gc_records, "gc_blobs": gc_blobs,
        }
        generation = hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        reference_breakdown = self._reference_breakdown(
            remaining, owned, view["storage_names"], view["complete"])
        remaining_over_bytes = None
        if max_bytes is not None and accounting.get("row_logical") is not None:
            totals: dict[tuple, int | None] = {}
            for row in remaining:
                if row["root_state"] != "live":
                    continue
                identity = (row["root"], row["root_dev"], row["root_ino"])
                size = accounting["row_logical"].get(row["id"])
                prior = totals.get(identity, 0)
                totals[identity] = None if prior is None or size is None else prior + size
            if all(total is not None for total in totals.values()):
                remaining_over_bytes = sum(max(0, total - max_bytes) for total in totals.values())
        return {
            "ok": view["complete"] and not gc_candidate_overflow and not budget_unknown,
            "action": action,
            "candidates": [self._public_row(row) for row in selected[:limit]],
            "omitted": max(0, len(selected) - limit) if view["index_complete"] else None,
            "truncated": (not view["complete"] or len(selected) > limit or
                          gc_candidate_overflow or budget_unknown),
            "complete": (view["complete"] and len(selected) <= limit and
                         not gc_candidate_overflow and not budget_unknown),
            "generation": generation, "reclaimable_bytes": reclaimable,
            "owned_gc": {"records": gc_records[:MAX_GC_CANDIDATES],
                         "blobs": gc_blobs[:max(0, MAX_GC_CANDIDATES - len(gc_records))],
                         "omitted": max(0, len(gc_records) + len(gc_blobs) - MAX_GC_CANDIDATES),
                         "reclaimable_bytes": reclaimable,
                         "complete": view["complete"] and not gc_candidate_overflow
                         and not budget_unknown},
            "batch": {"remaining_eligible_rows": remaining_eligible_rows,
                      "remaining_eligible_assets": remaining_eligible_assets,
                      "needs_fresh_approval": bool(remaining_eligible_rows or remaining_eligible_assets)},
            "protected_rows": len(remaining),
            "retention": {"keep_last": keep_last, "max_bytes": max_bytes,
                          "include_orphans": include_orphans,
                          "bytes_basis": "logical_checkpoint_bytes",
                          "remaining_over_bytes": remaining_over_bytes,
                          "budget_unattainable": (max_bytes is not None and
                                                  (remaining_over_bytes is None or
                                                   remaining_over_bytes > 0))},
            "reference_breakdown": reference_breakdown,
            "legacy_format_identified": False,
        }
