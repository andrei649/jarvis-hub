"""Governed local curator operations (H027).

Every effect is bound to a fresh preview, an owner decision and a live kernel
decision.  State and recovery data live in the runtime profile, never in the
shipped skills tree.  Read and preview do not create files.

Adapted from hermes-agent curator operation semantics (Nous Research, MIT;
see LICENSES/hermes-agent-MIT.txt). The storage and authority binding here are
Nerva specific.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import archive_safe
from . import references, switches
from .signing import source_snapshot
from .usage import (
    ORIGIN_AGENT,
    ORIGIN_IMPORT,
    STATE_ACTIVE,
    STATE_ARCHIVED,
    STATE_STALE,
    latest_activity_at,
)

READ_VIEWS = ("status", "usage", "list-unmanaged", "list-archived", "ledger", "backups")
MUTATIONS = ("run", "pause", "resume", "pin", "unpin", "adopt", "restore", "archive", "prune", "backup", "rollback", "purge")
_TARGET_OPS = {"pin", "unpin", "adopt", "archive"}
_FILE_EXCLUDES = {".git", "__pycache__", "node_modules", ".venv", "venv",
                  "PENDING_REVIEW", "ACQUIRED_SANDBOX_ONLY", "EXTERNAL_SOURCE"}
_MAX_JSON = 4 * 1024 * 1024
_MAX_FILES = 512
_MAX_BYTES = 32 * 1024 * 1024
_PUBLIC_TOKEN = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _public_token(value: Any) -> str:
    return value if isinstance(value, str) and _PUBLIC_TOKEN.fullmatch(value) else "unavailable"


def _identity(path: Path) -> list[int]:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("source_unavailable")
    info = path.stat(follow_symlinks=False)
    return [info.st_dev, info.st_ino]


def _tree_revision(path: Path) -> str:
    """Bind source bytes and control metadata, including signatures, to an archive."""
    snap = source_snapshot(path)
    controls = {}
    modes = {}
    for item in snap.files:
        candidate = path / item.relative_path
        mode = stat.S_IMODE(candidate.stat(follow_symlinks=False).st_mode)
        if mode & ~0o777:
            raise ValueError("source_unsafe_mode")
        modes[item.relative_path] = mode
    for name in ("SKILL.sig", "OWNER_APPROVED_IN_PROCESS", "EXTERNAL_SOURCE",
                 "PENDING_REVIEW", "ACQUIRED_SANDBOX_ONLY"):
        candidate = path / name
        if candidate.exists() or candidate.is_symlink():
            if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 256 * 1024:
                raise ValueError("archive_unavailable")
            mode = stat.S_IMODE(candidate.stat(follow_symlinks=False).st_mode)
            if mode & ~0o777:
                raise ValueError("source_unsafe_mode")
            controls[name] = {"sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(), "mode": mode}
    return _fingerprint({"source": snap.fingerprint, "modes": modes, "controls": controls})


def _empty() -> dict:
    return {"version": 1, "paused": False, "last_run": None, "last_report": None,
            "run_count": 0,
            "archives": {}, "backups": {}, "ledger": [], "adopted": {}, "requests": {}}


class CuratorOperations:
    """Owner-facing read/preview/request/apply service for the 17 curator verbs."""

    def __init__(self, loader, usage, curator, approvals, *, state_dir, archive_dir, get_setting,
                 holders=None):
        self.loader = loader
        self.usage = usage
        self.curator = curator
        self.approvals = approvals
        self.state_dir = Path(state_dir)
        self.archive_dir = Path(archive_dir)
        self.state_file = self.state_dir / "curator_operations.json"
        self.backup_dir = self.state_dir / "backups"
        self.get_setting = get_setting
        self.holders = holders
        self._lock = threading.RLock()
        self._seen_state = self.state_file.exists() or self.state_file.is_symlink()
        usage_path = getattr(usage, "path", None)
        self._seen_usage = bool(usage_path and (Path(usage_path).exists() or Path(usage_path).is_symlink()))

    def _state(self) -> dict:
        if not self.state_file.exists():
            if self._seen_state or self.state_file.is_symlink():
                raise ValueError("state_unreadable")
            return _empty()
        self._seen_state = True
        if self.state_file.is_symlink() or not self.state_file.is_file():
            raise ValueError("state_unreadable")
        with self.state_file.open("rb") as handle:
            raw = handle.read(_MAX_JSON + 1)
        if len(raw) > _MAX_JSON:
            raise ValueError("state_unreadable")
        try:
            state = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("state_unreadable") from exc
        expected = _empty()
        if not isinstance(state, dict) or state.get("version") != 1 or any(
            not isinstance(state.get(k), type(v)) for k, v in expected.items() if v is not None
        ):
            raise ValueError("state_unreadable")
        state.setdefault("last_report", None)  # state written before this read projection existed
        return state

    def _save(self, state: dict) -> None:
        if self.state_dir.is_symlink() or self.backup_dir.is_symlink() or self.archive_dir.is_symlink():
            raise ValueError("state_unreadable")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > _MAX_JSON:
            raise ValueError("state_full")
        fd, path = tempfile.mkstemp(prefix=".curator-", dir=self.state_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(path, 0o600)
            os.replace(path, self.state_file)
            self._seen_state = True
        finally:
            Path(path).unlink(missing_ok=True)

    def _usage(self, name: str) -> dict | None:
        # JsonStore can recover an invalid file as empty. Mutations must not do so.
        path = getattr(self.usage, "path", None)
        if path is not None and not Path(path).exists() and (self._seen_usage or Path(path).is_symlink()):
            raise ValueError("usage_unreadable")
        if path is not None and Path(path).exists():
            self._seen_usage = True
            if Path(path).is_symlink():
                raise ValueError("usage_unreadable")
            with Path(path).open("rb") as handle:
                raw = handle.read(_MAX_JSON + 1)
            if len(raw) > _MAX_JSON:
                raise ValueError("usage_unreadable")
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise ValueError("usage_unreadable") from exc
            if not isinstance(value, dict) or not isinstance(value.get("skills"), dict):
                raise ValueError("usage_unreadable")
        return self.usage.get(name)

    def _usage_slice(self, name: str) -> dict:
        rec = self._usage(name)
        return {"exists": rec is not None, "pinned": bool((rec or {}).get("pinned")),
                "state": str((rec or {}).get("state") or STATE_ACTIVE)}

    def _skill(self, name: str) -> tuple[Any, str, Path]:
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError("invalid_name")
        skill = getattr(self.loader, "skills", {}).get(name)
        if skill is None or getattr(skill, "name", name) != name:
            raise ValueError("skill_missing")
        path = Path(skill.path)
        if not path.is_dir() or path.is_symlink() or path.name != name:
            raise ValueError("source_unavailable")
        self._source_parent_allowed(path.parent)
        standing = self.loader.owner_standing(skill)
        if standing.get("unreadable") or standing.get("bundled"):
            raise ValueError("source_protected")
        for marker in ("EXTERNAL_SOURCE", "PENDING_REVIEW", "ACQUIRED_SANDBOX_ONLY"):
            if (path / marker).exists() or (path / marker).is_symlink():
                raise ValueError("source_protected")
        rec = self._usage(name)
        if rec and rec.get("origin") == ORIGIN_IMPORT:
            raise ValueError("source_protected")
        snap = standing.get("snapshot") or source_snapshot(path)
        if not snap or snap.read_bytes("SKILL.md") is None:
            raise ValueError("source_unavailable")
        return skill, snap.fingerprint, path

    def _source_parent_allowed(self, parent: Path) -> None:
        if type(self.loader).__module__ == "agents.core.skills.loader":
            from .loader import _writable_skills_dir

            if parent.is_symlink() or parent.resolve() != _writable_skills_dir().resolve():
                raise ValueError("source_protected")

    def _quarantined(self, name: str) -> bool:
        """True while a skill awaits owner review or is sandbox-only (marker files)."""
        skill = getattr(self.loader, "skills", {}).get(name)
        if skill is None:
            return False
        path = Path(skill.path)
        return any((path / marker).exists() or (path / marker).is_symlink()
                   for marker in ("PENDING_REVIEW", "ACQUIRED_SANDBOX_ONLY"))

    def _managed(self, name: str, state: dict) -> bool:
        rec = self._usage(name)
        if rec and rec.get("origin") == ORIGIN_AGENT:
            return True
        adopted = state["adopted"].get(name)
        if adopted:
            try:
                return adopted == self._skill(name)[1]
            except (OSError, ValueError):
                return False
        return False

    def _references_clear(self, name: str, skill) -> None:
        if not callable(self.holders):
            raise ValueError("references_unavailable")
        try:
            holders = self.holders()
            if holders is None:
                raise ValueError("references_unavailable")
            if references.outside(name, skill, None, holders):
                raise ValueError("source_referenced")
            names = references.identities(skill)
            for other_name, other in self.loader.skills.items():
                if other_name == name:
                    continue
                for _relative, body in references.text_files(Path(other.path)):
                    if references.mention_lines(body, names):
                        raise ValueError("source_referenced")
            if switches.off_reason(skill, current=switches.strict_state()) == "everywhere":
                raise ValueError("source_switched_off")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("references_unavailable") from exc

    def _age(self, rec: dict | None) -> int | None:
        rec = rec or {}
        anchor = latest_activity_at(rec)
        if anchor is None:
            try:
                anchor = datetime.fromisoformat(str(rec.get("created_at")))
                if anchor.tzinfo is None:
                    anchor = anchor.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                return None
        return (datetime.now(UTC) - anchor).days

    def _limit(self, filters: dict | None) -> int:
        try:
            return max(1, min(200, int((filters or {}).get("limit", 50))))
        except (TypeError, ValueError):
            return 50

    def read(self, view: str, filters: dict | None = None) -> dict:
        with self._lock:
            try:
                state = self._state()
                limit = self._limit(filters)
                if view == "status":
                    enabled = bool(self.get_setting("cognition.review_enabled", False))
                    records = [self._usage(name) or {} for name in self.loader.skills]
                    by_state: dict[str, int] = {}
                    for rec in records:
                        key = str(rec.get("state") or STATE_ACTIVE)
                        by_state[key] = by_state.get(key, 0) + 1
                    recent = sorted(((latest_activity_at(rec).isoformat(), name)
                                     for name, rec in zip(self.loader.skills, records, strict=True)
                                     if latest_activity_at(rec)), reverse=True)[:5]
                    runs = [row for row in reversed(state["ledger"]) if row.get("operation") == "run"]
                    return {"ok": True, "enabled": enabled, "paused": state["paused"],
                            "run_count": state["run_count"], "last_run": state["last_run"],
                            "last_summary": (runs[0].get("receipt") if runs else None),
                            "interval_days": 1, "pinned_count": sum(bool(rec.get("pinned")) for rec in records),
                            "by_state": by_state, "activity_leaders": [name for _at, name in recent],
                            "stale_days": self.get_setting("learning.curator_stale_days", 30),
                            "archive_days": self.get_setting("learning.curator_archive_days", 90),
                            "managed": sum(self._managed(n, state) for n in self.loader.skills),
                            "unmanaged": len(self._unmanaged(state)),
                            "archives": len(state["archives"]), "backups": len(state["backups"])}
                if view == "usage":
                    items = []
                    for name in sorted(self.loader.skills):
                        rec = self._usage(name) or {}
                        try:
                            skill = self.loader.skills[name]
                            standing = self.loader.owner_standing(skill)
                            snap = standing.get("snapshot") or source_snapshot(Path(skill.path))
                            digest = snap.fingerprint
                            if standing.get("bundled"):
                                origin = "bundled"
                            elif rec.get("origin") == ORIGIN_AGENT:
                                origin = ORIGIN_AGENT
                            elif rec.get("origin") == ORIGIN_IMPORT or (Path(skill.path) / "EXTERNAL_SOURCE").exists():
                                origin = ORIGIN_IMPORT
                            else:
                                origin = "unknown"
                        except (OSError, ValueError, KeyError, TypeError):
                            digest = None
                            origin = "unknown"
                        items.append({"name": name, "origin": origin, "fingerprint": digest,
                                      "use_count": int(rec.get("use_count") or 0),
                                      "view_count": int(rec.get("view_count") or 0),
                                      "patch_count": int(rec.get("patch_count") or 0),
                                      "last_activity_at": (latest_activity_at(rec).isoformat()
                                                           if latest_activity_at(rec) else None),
                                      "pinned": bool(rec.get("pinned")),
                                      "state": rec.get("state", STATE_ACTIVE)})
                    for archive_id, archived in state["archives"].items():
                        if _tree_revision(self.archive_dir / archived["folder"]) != archived.get("tree_revision"):
                            raise ValueError("archive_unavailable")
                        rec = self._usage(archived["name"]) or {}
                        items.append({"name": archived["name"], "archive_id": archive_id,
                                      "origin": archived.get("origin", "unknown"),
                                      "fingerprint": archived["fingerprint"],
                                      "use_count": int(rec.get("use_count") or 0),
                                      "view_count": int(rec.get("view_count") or 0),
                                      "patch_count": int(rec.get("patch_count") or 0),
                                      "last_activity_at": (latest_activity_at(rec).isoformat()
                                                           if latest_activity_at(rec) else None),
                                      "pinned": bool(rec.get("pinned")), "state": STATE_ARCHIVED})
                    origin_filter = (filters or {}).get("origin")
                    if origin_filter:
                        items = [item for item in items if item["origin"] == origin_filter]
                    sort = (filters or {}).get("sort", "name")
                    if sort == "activity":
                        items.sort(key=lambda item: (item["use_count"] + item["view_count"], item["name"]), reverse=True)
                    elif sort == "recent":
                        items.sort(key=lambda item: item["last_activity_at"] or "", reverse=True)
                    return {"ok": True, "items": items[:limit], "total": len(items)}
                if view == "list-unmanaged":
                    items = self._unmanaged(state)
                    return {"ok": True, "items": items[:limit], "total": len(items)}
                if view == "list-archived":
                    items = []
                    for key, value in state["archives"].items():
                        path = self.archive_dir / value["folder"]
                        if (path.is_symlink() or _tree_revision(path) != value.get("tree_revision")):
                            raise ValueError("archive_unavailable")
                        items.append({"id": key, "name": value["name"], "at": value["at"],
                                      "fingerprint": value["fingerprint"]})
                    items.sort(key=lambda item: item["at"], reverse=True)
                    return {"ok": True, "items": items[:limit], "total": len(items)}
                if view == "ledger":
                    items = list(reversed(state["ledger"]))
                    name = (filters or {}).get("name")
                    if name:
                        items = [item for item in items if name in item.get("targets", [])]
                    return {"ok": True, "items": items[:limit], "total": len(items)}
                if view == "backups":
                    items = [{"id": key, "at": val["at"], "reason": val.get("reason", "")}
                             for key, val in state["backups"].items()]
                    items.sort(key=lambda item: item["at"], reverse=True)
                    return {"ok": True, "items": items[:limit], "total": len(items)}
                return {"ok": False, "status": "refused", "reason": "unknown_view"}
            except (OSError, ValueError, KeyError, TypeError):
                return {"ok": False, "status": "refused", "reason": "state_unavailable"}

    def legacy_status(self) -> dict:
        """Existing cognition API shape, derived only from committed governed runs."""
        with self._lock:
            try:
                state = self._state()
                last_run = state.get("last_run")
                report = state.get("last_report")
                if not isinstance(report, dict) or not last_run or report.get("date") != str(last_run)[:10]:
                    report = None
                else:
                    lifecycle = report.get("lifecycle") or {}
                    report = {"date": report["date"],
                              "lifecycle": {"considered": int(lifecycle.get("considered", 0)),
                                            "stale": list(lifecycle.get("stale", [])),
                                            "archived": list(lifecycle.get("archived", []))},
                              "proposals": report.get("proposals")}
                return {"available": True, "last_run": str(last_run)[:10] if last_run else None,
                        "last_result": report}
            except (OSError, ValueError, KeyError, TypeError):
                return {"available": False, "last_run": None, "last_result": None}

    def _unmanaged(self, state: dict) -> list[dict]:
        items = []
        for name in sorted(self.loader.skills):
            try:
                _skill, digest, _path = self._skill(name)
                if not self._managed(name, state):
                    items.append({"name": name, "fingerprint": digest,
                                  "reason": "origin_unknown", "age_days": self._age(self._usage(name))})
            except ValueError:
                continue
        return items

    def _days(self, operation: str, args: dict) -> int:
        default = self.get_setting("learning.curator_archive_days", 90) if operation == "prune" else self.get_setting("learning.curator_purge_days", 0)
        days = args.get("days", default)
        if isinstance(days, bool) or not isinstance(days, int) or days < 1 or days > 36500:
            raise ValueError("invalid_days" if operation == "prune" else "purge_disabled")
        return days

    def _backup_source_ok(self, path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("backup_source_unavailable")
        for item in path.rglob("*"):
            if item.is_symlink():
                raise ValueError("backup_source_unavailable")
            if item.is_file() and any(part in _FILE_EXCLUDES for part in item.relative_to(path).parts):
                raise ValueError("backup_excluded_artifacts")

    def _snapshot_scope_ok(self, saved: dict, state: dict) -> None:
        if saved.get("scope") != "managed_slice":
            return
        active = saved.get("skills", {})
        archived = saved.get("archives", {})
        current_active: dict[str, dict] = {}
        archived_names = {row["name"] for row in archived.values()}
        for name in self.loader.skills:
            if name not in active and name not in archived_names and not self._managed(name, state):
                continue
            _skill, fingerprint, path = self._skill(name)
            current_active[name] = {"fingerprint": fingerprint, "tree_revision": _tree_revision(path),
                                    "parent": str(path.parent), "identity": _identity(path)}
        current_archived = state["archives"]
        origin_id = saved.get("created_by_ledger_id")
        origin_index = next((i for i, row in enumerate(state["ledger"]) if row.get("id") == origin_id), None)
        if origin_index is None:
            raise ValueError("snapshot_scope_changed")
        # A safety backup is captured inside its rollback entry before the move;
        # that same entry can prove the subsequent transition.
        later = [row for row in state["ledger"][origin_index:] if row.get("status") == "applied"]
        claims: set[tuple[str, str]] = set()

        def claim(side: str, key: str) -> None:
            token = (side, key)
            if token in claims:
                raise ValueError("snapshot_scope_changed")
            claims.add(token)

        def archive_lineage(archive_id: str) -> bool:
            return any(archive_id in row.get("receipt", {}).get("archive_ids", [])
                       for row in later if row.get("operation") in {"archive", "prune", "run", "rollback"})

        def restore_lineage(archive_id: str, name: str, identity: list[int]) -> bool:
            for row in later:
                if ((row.get("operation") == "restore" and archive_id in row.get("target_ids", []) or
                     row.get("operation") == "rollback" and archive_id in row.get("receipt", {}).get("removed_archives", []))
                    and row.get("receipt", {}).get("restored_identity", {}).get(name) == identity):
                    return True
            return False

        for name, selected in active.items():
            before = selected.get("usage")
            now = self._usage(name)
            if before and now and before.get("origin") != now.get("origin"):
                raise ValueError("snapshot_origin_changed")
            current = current_active.get(name)
            if current is not None:
                if any(current.get(key) != selected.get(key)
                       for key in ("fingerprint", "tree_revision")):
                    raise ValueError("rollback_conflict")
                if any(current.get(key) != selected.get(key)
                       for key in ("parent", "identity")):
                    raise ValueError("snapshot_scope_changed")
                claim("active", name)
                continue
            candidates = [(archive_id, row) for archive_id, row in current_archived.items()
                          if row.get("name") == name and row.get("fingerprint") == selected.get("fingerprint")
                          and row.get("tree_revision") == selected.get("tree_revision")
                          and row.get("source_parent") == selected.get("parent")
                          and _identity(self.archive_dir / row["folder"]) == row.get("identity")
                          and archive_lineage(archive_id)]
            if len(candidates) != 1:
                raise ValueError("snapshot_scope_changed")
            claim("archive", candidates[0][0])

        for archive_id, selected in archived.items():
            current = current_archived.get(archive_id)
            if current is not None:
                if current != selected or _identity(self.archive_dir / current["folder"]) != selected.get("identity"):
                    raise ValueError("snapshot_scope_changed")
                claim("archive", archive_id)
                continue
            name = selected["name"]
            active_now = current_active.get(name)
            if (active_now is None or active_now["fingerprint"] != selected["fingerprint"] or
                active_now["tree_revision"] != selected["tree_revision"] or
                active_now["parent"] != selected["source_parent"] or
                not restore_lineage(archive_id, name, active_now["identity"])):
                raise ValueError("snapshot_scope_changed")
            claim("active", name)

        actual = {("active", name) for name in current_active}
        actual.update(("archive", archive_id) for archive_id in current_archived)
        if claims != actual:
            raise ValueError("snapshot_scope_changed")

    def _control_superseded(self, state: dict, original: dict) -> bool:
        operation = original.get("operation")
        if operation not in {"pin", "unpin", "pause", "resume"}:
            return False
        name = (original.get("targets") or [None])[0]
        found = False
        for row in state["ledger"]:
            if row.get("id") == original.get("id"):
                found = True
                continue
            if not found or row.get("status") != "applied":
                continue
            later = row.get("operation")
            if operation in {"pin", "unpin"}:
                if later in {"pin", "unpin"} and name in row.get("targets", []):
                    return True
                undo = row.get("receipt", {}).get("undo", {})
                if later == "rollback" and (undo.get("kind") == "usage" and undo.get("name") == name or
                                             row.get("receipt", {}).get("backup_id")):
                    return True
            elif (later in {"pause", "resume"} or
                  later == "rollback" and (
                      row.get("receipt", {}).get("backup_id") or
                      row.get("receipt", {}).get("undo", {}).get("kind") == "pause"
                  )):
                return True
        return False

    def _plan(self, operation: str, args: dict, state: dict) -> dict:
        if operation not in MUTATIONS or not isinstance(args, dict):
            raise ValueError("invalid_operation")
        if operation == "run" and not isinstance(args.get("consolidate", False), bool):
            raise ValueError("invalid_consolidate")
        if operation in {"run", "prune"} and not bool(self.get_setting("cognition.review_enabled", False)):
            raise ValueError("curator_disabled")
        targets = []
        if operation == "adopt" and args.get("all_unmanaged"):
            targets = [{"name": x["name"], "fingerprint": x["fingerprint"]} for x in self._unmanaged(state)]
        elif operation in _TARGET_OPS:
            name = args.get("name")
            _skill, digest, _path = self._skill(name)
            rec = self._usage(name) or {}
            if operation == "adopt":
                if self._managed(name, state):
                    raise ValueError("already_managed")
            elif operation == "archive" and not self._managed(name, state):
                raise ValueError("unmanaged")
            if operation == "archive" and rec.get("pinned"):
                raise ValueError("pinned")
            if operation == "archive":
                self._references_clear(name, _skill)
            if operation == "pin" and rec.get("pinned") or operation == "unpin" and not rec.get("pinned"):
                raise ValueError("already_set")
            targets = [{"name": name, "fingerprint": digest, "path": str(_path),
                        "tree_revision": _tree_revision(_path), "usage": _fingerprint(rec)}]
        elif operation in {"run", "prune"}:
            days = self._days("prune", args) if operation == "prune" else None
            for name in sorted(self.loader.skills):
                rec = self._usage(name) or {}
                if rec.get("origin") != ORIGIN_AGENT and name not in state["adopted"]:
                    continue
                if self._quarantined(name):
                    continue  # awaiting review: not part of a lifecycle pass; a direct target still refuses
                _skill, digest, path = self._skill(name)
                if name in state["adopted"] and state["adopted"][name] != digest:
                    raise ValueError("adopted_source_drifted")
                if rec.get("pinned") or rec.get("state") == STATE_ARCHIVED:
                    continue
                age = self._age(rec)
                if age is None:
                    continue
                if operation == "prune" and age < days:
                    continue
                try:
                    self._references_clear(name, _skill)
                except ValueError as exc:
                    if str(exc) == "source_switched_off":
                        continue
                    raise
                targets.append({"name": name, "fingerprint": digest, "path": str(path),
                                "tree_revision": _tree_revision(path),
                                "usage": _fingerprint(rec), "age_days": age})
        elif operation in {"restore", "purge"}:
            if operation == "restore":
                ids = [args.get("archive_id")]
            else:
                days = self._days("purge", args)
                ids = args.get("archive_ids") or list(state["archives"])
            for archive_id in ids:
                record = state["archives"].get(archive_id)
                if not record:
                    raise ValueError("archive_missing")
                path = self.archive_dir / record["folder"]
                if path.parent != self.archive_dir or path.is_symlink() or not path.is_dir():
                    raise ValueError("archive_unavailable")
                snap = source_snapshot(path)
                if snap.fingerprint != record["fingerprint"] or _tree_revision(path) != record.get("tree_revision"):
                    raise ValueError("archive_drifted")
                if _identity(path) != record.get("identity"):
                    raise ValueError("archive_drifted")
                if operation == "purge":
                    if (self._usage(record["name"]) or {}).get("pinned"):
                        raise ValueError("pinned")
                    self._references_clear(record["name"], type("ArchivedSkill", (), {"name": record["name"], "path": path})())
                    at = datetime.fromisoformat(record["at"])
                    age = (datetime.now(UTC) - max(at, datetime.fromtimestamp(path.stat().st_mtime, UTC))).days
                    if age < days:
                        continue
                targets.append({"id": archive_id, "name": record["name"], "fingerprint": snap.fingerprint,
                                "tree_revision": record["tree_revision"], "folder": record["folder"]})
            if operation == "restore" and record["name"] in self.loader.skills:
                raise ValueError("destination_occupied")
            if operation == "restore":
                destination = Path(record["source_parent"]) / record["name"]
                self._source_parent_allowed(destination.parent)
                if destination.exists() or destination.is_symlink():
                    raise ValueError("destination_occupied")
                switches.strict_state()
        elif operation == "rollback":
            ledger_id, backup_id = args.get("ledger_id"), args.get("backup_id")
            if not ledger_id and not backup_id and state["backups"]:
                backup_id = max(state["backups"], key=lambda key: state["backups"][key]["at"])
            if bool(ledger_id) == bool(backup_id):
                raise ValueError("rollback_target_required")
            collection = state["ledger"] if ledger_id else state["backups"]
            record = next((row for row in collection if row.get("id") == ledger_id), None) if ledger_id else collection.get(backup_id)
            if not record:
                raise ValueError("rollback_target_missing")
            if ledger_id and record.get("status") != "applied":
                raise ValueError("rollback_target_unavailable")
            if ledger_id:
                if self._control_superseded(state, record):
                    raise ValueError("rollback_superseded")
                source_op = record.get("operation")
                if source_op not in {"archive", "restore", "pin", "unpin", "pause", "resume",
                                     "adopt", "prune", "run", "purge", "rollback"}:
                    raise ValueError("rollback_unsupported")
                if source_op in {"archive", "prune", "run"}:
                    for archive_id in record.get("receipt", {}).get("archive_ids", []):
                        archived = state["archives"].get(archive_id)
                        if not archived or _tree_revision(self.archive_dir / archived["folder"]) != archived.get("tree_revision"):
                            raise ValueError("rollback_conflict")
                if source_op == "purge" or (source_op == "rollback" and not record.get("receipt", {}).get("undo")):
                    recovery_id = record.get("receipt", {}).get("backup_id")
                    if not recovery_id or recovery_id not in state["backups"]:
                        raise ValueError("rollback_target_unavailable")
            if backup_id:
                self._snapshot_scope_ok(record, state)
                self._verify_backup(self.backup_dir / f"{backup_id}.tar.gz", record["digest"])
                for name, saved in record.get("skills", {}).items():
                    self._source_parent_allowed(Path(saved["parent"]))
                    if name in self.loader.skills and (
                        self._skill(name)[1] != saved["fingerprint"] or
                        _tree_revision(Path(self.loader.skills[name].path)) != saved.get("tree_revision")
                    ):
                        raise ValueError("rollback_conflict")
                    destination = Path(saved["parent"]) / name
                    if name not in self.loader.skills and (destination.exists() or destination.is_symlink()):
                        raise ValueError("rollback_conflict")
                for archive_id, saved in record.get("archives", {}).items():
                    current_archive = state["archives"].get(archive_id)
                    if current_archive and current_archive != saved:
                        raise ValueError("rollback_conflict")
                    destination = self.archive_dir / saved["folder"]
                    if current_archive is None and (destination.exists() or destination.is_symlink()):
                        raise ValueError("rollback_conflict")
                for _archive_id, current_archive in state["archives"].items():
                    path = self.archive_dir / current_archive["folder"]
                    if path.is_symlink() or source_snapshot(path).fingerprint != current_archive["fingerprint"]:
                        raise ValueError("archive_drifted")
                    if _tree_revision(path) != current_archive.get("tree_revision"):
                        raise ValueError("archive_drifted")
            targets = [{"id": ledger_id or backup_id, "fingerprint": _fingerprint(record)}]
        elif operation in {"backup", "pause", "resume"}:
            if operation == "pause" and state["paused"] or operation == "resume" and not state["paused"]:
                raise ValueError("already_set")
            if operation == "backup":
                targets = [{"name": n, "fingerprint": self._skill(n)[1],
                            "tree_revision": _tree_revision(self._skill(n)[2]),
                            "identity": _identity(self._skill(n)[2])} for n in sorted(self.loader.skills)
                           if self._managed(n, state)]
                for target in targets:
                    self._backup_source_ok(self._skill(target["name"])[2])
                for archive_id, archived in state["archives"].items():
                    path = self.archive_dir / archived["folder"]
                    self._backup_source_ok(path)
                    if path.is_symlink() or source_snapshot(path).fingerprint != archived["fingerprint"]:
                        raise ValueError("archive_drifted")
                    if _tree_revision(path) != archived.get("tree_revision"):
                        raise ValueError("archive_drifted")
                    targets.append({"name": archived["name"], "archive_id": archive_id,
                                    "fingerprint": archived["fingerprint"],
                                    "tree_revision": archived["tree_revision"],
                                    "identity": archived["identity"]})
        if operation not in {"pause", "resume", "backup", "run"} and not targets:
            raise ValueError("no_targets")
        plan = {"operation": operation, "args": args, "targets": targets,
                "state_revision": _fingerprint({k: state[k] for k in ("paused", "archives", "adopted", "backups")})}
        return plan

    def preview(self, operation: str, args: dict | None = None) -> dict:
        with self._lock:
            try:
                plan = self._plan(operation, args or {}, self._state())
                return {"ok": True, "status": "preview", "operation": operation,
                        "targets": [{k: v for k, v in item.items() if k not in {"path", "folder"}} for item in plan["targets"]],
                        "preview_fingerprint": _fingerprint(plan)}
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return {"ok": False, "status": "refused", "operation": operation,
                        "reason": str(exc) if isinstance(exc, ValueError) else "state_unavailable"}

    def _authorize(self, authorize, plan: dict, phase: str, *, card_id: str | None = None) -> str:
        if not callable(authorize):
            return "error"
        operation = plan["operation"]
        payload = {"kind": "skill.generation" if operation in {"run", "pause", "resume", "adopt", "backup"} else "skill.install",
                   "operation": operation, "phase": phase, "preview_fingerprint": _fingerprint(plan),
                   "targets": [{"name": row.get("name"), "fingerprint": row.get("fingerprint")} for row in plan["targets"]],
                   "actor": "curator" if phase == "scheduled" else "owner", "origin": "generated" if phase == "scheduled" else "owner",
                   "risk_tier": 3 if operation == "purge" else 2}
        if card_id:
            payload["card_id"] = card_id
        try:
            result = authorize(payload)
        except Exception:
            return "error"
        return result if type(result) is str and result in {"grant", "queue", "deny"} else "error"

    def request(self, operation: str, args: dict | None = None, *, preview_fingerprint: str,
                actor: str, authorize) -> dict:
        with self._lock:
            result = self.preview(operation, args)
            if not result["ok"] or result["preview_fingerprint"] != preview_fingerprint:
                return {"ok": False, "status": "refused", "reason": "stale_preview"}
            if actor != "owner":
                return {"ok": False, "status": "refused", "reason": "untrusted_actor"}
            try:
                state = self._state()
                plan = self._plan(operation, args or {}, state)
                verdict = self._authorize(authorize, plan, "request")
                if verdict not in {"grant", "queue"}:
                    return {"ok": False, "status": "refused", "reason": "authorization_denied"}
                card = self.approvals.request({"tool": f"skill.curator.{operation}", "agent": "curator",
                                               "risk_tier": 3 if operation == "purge" else 2,
                                               "summary": f"Curator {operation}",
                                               "args": {"operation": operation, "args": args or {},
                                                        "preview_fingerprint": preview_fingerprint,
                                                        "targets": plan["targets"]}})
                state["requests"][card["id"]] = {"plan": plan, "status": "pending"}
                self._save(state)
                return {"ok": True, "status": "pending", "card_id": card["id"],
                        "request_id": card["id"], "preview_fingerprint": preview_fingerprint,
                        "targets": result["targets"]}
            except (OSError, ValueError, KeyError, TypeError):
                return {"ok": False, "status": "refused", "reason": "state_unavailable"}

    def apply_decision(self, card_id: str, *, authorize) -> dict:
        with self._lock:
            try:
                state = self._state()
                request = state["requests"].get(card_id)
                card = self.approvals.get(card_id)
                if not request or request.get("status") != "pending" or not card or card.get("status") != "approved" or card.get("decided_by") != "user":
                    return {"ok": False, "status": "refused", "reason": "approval_missing"}
                plan = request["plan"]
                if card.get("tool") != f"skill.curator.{plan['operation']}" or card.get("args") != {
                    "operation": plan["operation"], "args": plan["args"],
                    "preview_fingerprint": _fingerprint(plan), "targets": plan["targets"]}:
                    return {"ok": False, "status": "refused", "reason": "approval_mismatch"}
                current = self._plan(plan["operation"], plan["args"], state)
                if _fingerprint(current) != _fingerprint(plan):
                    return {"ok": False, "status": "refused", "reason": "stale_preview"}
                verdict = self._authorize(authorize, plan, "apply", card_id=card_id)
                if verdict not in {"grant", "queue"}:
                    return {"ok": False, "status": "refused", "reason": "authorization_denied"}
                applied = self._apply(plan, state, card_id=card_id, actor="owner")
                if (applied.get("ok") and plan["operation"] == "run" and plan["args"].get("consolidate")):
                    applied["proposals"] = self.apply_proposals()
                    if not applied["proposals"].get("ok"):
                        applied["status"] = "partial_recovery"
                        applied["ok"] = False
                return applied
            except (OSError, ValueError, KeyError, TypeError):
                return {"ok": False, "status": "refused", "reason": "state_unavailable"}

    def run_scheduled(self, *, authorize) -> dict:
        with self._lock:
            try:
                state = self._state()
                if state["paused"]:
                    return {"ok": False, "status": "skipped", "reason": "paused"}
                if state["last_run"] and str(state["last_run"])[:10] == datetime.now(UTC).date().isoformat():
                    return {"ok": False, "status": "skipped", "reason": "already_ran_today"}
                plan = self._plan("run", {}, state)
                if self._authorize(authorize, plan, "scheduled") != "grant":
                    return {"ok": False, "status": "refused", "reason": "authorization_denied"}
                return self._apply(plan, state, card_id=None, actor="curator")
            except (OSError, ValueError, KeyError, TypeError):
                return {"ok": False, "status": "refused", "reason": "state_unavailable"}

    def apply_proposals(self) -> dict:
        """Journal the existing exact-card proposal pass; pause does not gate it."""
        with self._lock:
            try:
                state = self._state()
                before = {}
                proposals = getattr(self.curator, "_proposals", None)
                candidates = []
                if proposals is not None:
                    candidates = proposals.list("approved") + proposals.list("pending")
                for name in {row.get("skill") for row in candidates if isinstance(row, dict)}:
                    skill = self.loader.skills.get(name)
                    if skill is not None:
                        before[name] = source_snapshot(Path(skill.path)).fingerprint
                if not candidates:
                    result = self.curator.apply_decisions()
                    self._note_proposal_result(state, result)
                    if state.get("last_report") is not None:
                        self._save(state)
                    return {**result, "ok": True, "status": "no_changes"}
                ledger_id = uuid.uuid4().hex[:16]
                entry = {"id": ledger_id, "at": _now(), "operation": "approved_proposals",
                         "actor": "owner", "card_id": None, "targets": [], "before": before,
                         "after": None, "status": "in_progress"}
                state["ledger"].append(entry)
                self._save(state)
                result = self.curator.apply_decisions()
                after = {}
                for name in before:
                    skill = self.loader.skills.get(name)
                    if skill is not None:
                        after[name] = source_snapshot(Path(skill.path)).fingerprint
                entry["targets"] = sorted(name for name in set(before) | set(after)
                                          if before.get(name) != after.get(name))
                entry["after"] = after
                entry["outcomes"] = [{k: row.get(k) for k in ("skill", "proposal_id", "ok", "reason", "state")
                                      if k in row} for row in result.get("outcomes", [])][:200]
                entry["status"] = "applied"
                self._note_proposal_result(state, result)
                self._save(state)
                return {**result, "ok": True, "status": "applied", "ledger_id": ledger_id}
            except Exception:
                if "entry" in locals():
                    entry["status"] = "partial_recovery"
                    with contextlib.suppress(Exception):
                        self._save(state)
                return {"ok": False, "status": "partial_recovery", "reason": "proposal_journal_unavailable"}

    def _note_proposal_result(self, state: dict, result: dict) -> None:
        report = state.get("last_report")
        if not isinstance(report, dict) or report.get("date") != datetime.now(UTC).date().isoformat():
            return
        report["proposals"] = {
            key: [_public_token(item) for item in result.get(key, [])][:200]
            for key in ("applied", "rejected", "stale", "failed")
        }
        report["proposals"]["outcomes"] = [
            {key: (row[key] if key == "ok" and isinstance(row[key], bool) else _public_token(row[key]))
             for key in ("skill", "ok", "reason", "state") if key in row}
            for row in result.get("outcomes", []) if isinstance(row, dict)
        ][:200]

    def _capture(self, targets: list[dict], *, label: str) -> tuple[str, str]:
        """Write a bounded, verified recovery tar before any filesystem mutation."""
        if self.backup_dir.is_symlink():
            raise ValueError("backup_unavailable")
        self.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_id = uuid.uuid4().hex[:16]
        target = self.backup_dir / f"{backup_id}.tar.gz"
        manifest: dict[str, str] = {}
        modes: dict[str, int] = {}
        total = 0
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as archive:
            for item in targets:
                source = Path(item["path"])
                if source.is_symlink() or not source.is_dir():
                    raise ValueError("source_unavailable")
                for path in sorted(source.rglob("*")):
                    if path.is_symlink():
                        raise ValueError("linked_source")
                    if path.is_dir():
                        continue
                    if any(part in _FILE_EXCLUDES for part in path.relative_to(source).parts):
                        raise ValueError("backup_excluded_artifacts")
                    if not path.is_file():
                        raise ValueError("unsafe_backup_source")
                    if len(manifest) >= _MAX_FILES:
                        raise ValueError("backup_too_large")
                    if path.stat().st_size > _MAX_BYTES - total:
                        raise ValueError("backup_too_large")
                    with path.open("rb") as handle:
                        data = handle.read(_MAX_BYTES - total + 1)
                    total += len(data)
                    if total > _MAX_BYTES:
                        raise ValueError("backup_too_large")
                    bucket = item.get("bucket", "skills")
                    key = item.get("key", item["name"])
                    member = f"{bucket}/{key}/{path.relative_to(source).as_posix()}"
                    info = tarfile.TarInfo(member)
                    info.size = len(data)
                    mode = stat.S_IMODE(path.stat().st_mode)
                    if mode & ~0o777:
                        raise ValueError("unsafe_backup_mode")
                    info.mode = mode
                    archive.addfile(info, io.BytesIO(data))
                    manifest[member] = hashlib.sha256(data).hexdigest()
                    modes[member] = mode
                if item.get("fingerprint") and source_snapshot(source).fingerprint != item["fingerprint"]:
                    raise ValueError("source_drifted")
                if item.get("tree_revision") and _tree_revision(source) != item["tree_revision"]:
                    raise ValueError("source_drifted")
                if item.get("identity") and _identity(source) != item["identity"]:
                    raise ValueError("source_drifted")
            body = json.dumps({"label": label, "files": manifest, "modes": modes}, sort_keys=True).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        self._verify_backup(target, digest)
        return backup_id, digest

    def _unpack_backup(self, target: Path, digest: str, stage: Path) -> tuple[dict, dict]:
        """Verify the recovery tar and unpack it into the empty directory *stage*.

        The tar is only ever read through ``archive_safe``: it refuses unsafe names, links
        and special members, enforces the member and byte caps, and tar metadata never
        chooses a destination. File modes travel in the digest-bound manifest, not in tar
        headers, because ``archive_safe`` writes plain regular files.
        """
        if target.is_symlink() or not target.is_file() or target.stat().st_size > _MAX_BYTES * 2:
            raise ValueError("backup_unavailable")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("backup_corrupt")
        limits = archive_safe.ArchiveLimits(max_members=_MAX_FILES + 1, max_bytes=_MAX_BYTES + _MAX_JSON)
        try:
            written = archive_safe.extract_tar_path(target, stage, limits=limits, compression="gz")
        except archive_safe.ArchiveRejected as exc:
            raise ValueError("backup_corrupt" if "corrupt" in str(exc) else "backup_unsafe") from exc
        names = {"/".join(parts) for parts in written}
        manifest_path = stage / "manifest.json"
        if "manifest.json" not in names or manifest_path.stat().st_size > _MAX_JSON:
            raise ValueError("backup_corrupt")
        try:
            manifest = json.loads(manifest_path.read_bytes())
            files = manifest["files"]
            modes = manifest["modes"]
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise ValueError("backup_corrupt") from exc
        if not isinstance(files, dict) or not isinstance(modes, dict):
            raise ValueError("backup_corrupt")
        if set(files) != names - {"manifest.json"} or set(modes) != set(files):
            raise ValueError("backup_corrupt")
        for name, expected in files.items():
            parts = name.split("/")
            if not name.startswith(("skills/", "archives/")) or len(parts) < 3:
                raise ValueError("backup_corrupt")
            path = stage.joinpath(*parts)
            if path.stat().st_size > _MAX_BYTES:
                raise ValueError("backup_unsafe")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("backup_corrupt")
            mode = modes[name]
            if not isinstance(mode, int) or isinstance(mode, bool) or mode < 0 or mode & ~0o777:
                raise ValueError("backup_unsafe")
        manifest_path.unlink()
        return files, modes

    def _verify_backup(self, target: Path, digest: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="curator-verify-", dir=self.state_dir) as stage:
            files, _modes = self._unpack_backup(target, digest, Path(stage))
        return files

    def _apply(self, plan: dict, state: dict, *, card_id: str | None, actor: str) -> dict:
        operation = plan["operation"]
        ledger_id = uuid.uuid4().hex[:16]
        entry = {"id": ledger_id, "at": _now(), "operation": operation, "actor": actor,
                 "card_id": card_id, "targets": [x.get("name") for x in plan["targets"]],
                 "target_ids": [x.get("id") or x.get("archive_id") for x in plan["targets"]],
                 "before": [x.get("fingerprint") for x in plan["targets"]],
                 "after": None, "status": "in_progress"}
        state["ledger"].append(entry)
        self._save(state)  # durable intent before any effect
        try:
            outcome = self._effect(plan, state, entry)
            usage_path = getattr(self.usage, "path", None)
            if usage_path is not None and Path(usage_path).exists():
                self._seen_usage = True
            entry["after"] = outcome.get("after", [])
            entry["receipt"] = {key: value for key, value in outcome.items()
                                if key in {"archive_ids", "backup_id", "archived", "stale", "prior_usage",
                                           "prior_paused", "prior_run", "undo", "removed_archives",
                                           "restored_identity"}}
            entry["status"] = "applied"
            if card_id:
                state["requests"][card_id]["status"] = "applied"
            self._save(state)
            return {"ok": True, "status": "applied", "ledger_id": ledger_id, **outcome}
        except Exception:
            entry["status"] = "partial_recovery"
            with contextlib.suppress(Exception):
                self._save(state)
            return {"ok": False, "status": "partial_recovery", "reason": "mutation_incomplete", "ledger_id": ledger_id}

    def _effect(self, plan: dict, state: dict, entry: dict) -> dict:
        operation, args, targets = plan["operation"], plan["args"], plan["targets"]
        if operation in {"pause", "resume"}:
            prior_paused = state["paused"]
            state["paused"] = operation == "pause"
            return {"after": [state["paused"]], "prior_paused": prior_paused}
        if operation in {"pin", "unpin"}:
            prior_usage = {targets[0]["name"]: self._usage_slice(targets[0]["name"])}
            self.usage.pin(targets[0]["name"], operation == "pin")
            return {"after": [operation == "pin"], "prior_usage": prior_usage}
        if operation == "adopt":
            for target in targets:
                state["adopted"][target["name"]] = target["fingerprint"]
            return {"after": [x["fingerprint"] for x in targets]}
        if operation == "backup":
            active = [x for x in targets if "archive_id" not in x]
            archived = [x for x in targets if "archive_id" in x]
            selected = [{"name": x["name"], "fingerprint": x["fingerprint"],
                         "tree_revision": x["tree_revision"], "identity": x["identity"],
                         "path": str(self._skill(x["name"])[2])} for x in active]
            selected += [{"name": x["name"], "key": x["archive_id"], "bucket": "archives",
                          "fingerprint": x["fingerprint"], "tree_revision": x["tree_revision"],
                          "identity": x["identity"],
                          "path": str(self.archive_dir / state["archives"][x["archive_id"]]["folder"])}
                         for x in archived]
            backup_id, digest = self._capture(selected, label="manual")
            state["backups"][backup_id] = {"at": _now(), "digest": digest, "scope": "managed_slice",
                                            "created_by_ledger_id": entry["id"],
                                            "reason": str(args.get("reason", ""))[:120],
                                            "skills": {x["name"]: {"fingerprint": x["fingerprint"],
                                                                      "tree_revision": x["tree_revision"],
                                                                      "identity": x["identity"],
                                                                      "parent": str(self._skill(x["name"])[2].parent),
                                                                      "usage": self._usage(x["name"])} for x in active},
                                            "archives": {x["archive_id"]: state["archives"][x["archive_id"]] for x in archived},
                                            "state_snapshot": {key: copy.deepcopy(state[key]) for key in ("paused", "adopted", "last_run", "last_report", "run_count")}}
            return {"backup_id": backup_id, "after": [digest]}
        if operation in {"archive", "prune", "run"}:
            archived, stale, archive_ids = [], [], []
            prior_usage = {target["name"]: self._usage_slice(target["name"]) for target in targets}
            prior_run = {"last_run": state["last_run"], "run_count": state["run_count"],
                         "last_report": copy.deepcopy(state.get("last_report"))}
            archive_days = int(self.get_setting("learning.curator_archive_days", 90) or 90)
            stale_days = int(self.get_setting("learning.curator_stale_days", 30) or 30)
            for target in targets:
                name = target["name"]
                age = target.get("age_days")
                if operation == "run" and (age is None or age <= stale_days):
                    continue
                if operation == "run" and age <= archive_days:
                    self.usage.set_state(name, STATE_STALE)
                    stale.append(name)
                    continue
                _skill, digest, source = self._skill(name)
                if digest != target["fingerprint"]:
                    raise ValueError("source_drifted")
                if _tree_revision(source) != target["tree_revision"]:
                    raise ValueError("source_drifted")
                archive_id = uuid.uuid4().hex[:16]
                dest = self.archive_dir / archive_id
                entry.setdefault("pending_archive_ids", []).append(archive_id)
                self._save(state)
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(dest))
                state["archives"][archive_id] = {"name": name, "folder": archive_id, "at": _now(),
                                                  "fingerprint": digest, "source_parent": str(source.parent),
                                                  "tree_revision": _tree_revision(dest),
                                                  "identity": _identity(dest),
                                                  "origin": (self._usage(name) or {}).get("origin", "unknown")}
                self.loader.skills.pop(name, None)
                self.usage.set_state(name, STATE_ARCHIVED)
                archived.append(name)
                archive_ids.append(archive_id)
            if operation == "run":
                state["last_report"] = {"date": datetime.now(UTC).date().isoformat(),
                                        "lifecycle": {"considered": len(targets),
                                                      "stale": list(stale),
                                                      "archived": list(archived)},
                                        "proposals": None}
                state["last_run"] = _now()
                state["run_count"] += 1
            return {"archived": archived, "stale": stale, "archive_ids": archive_ids,
                    "prior_usage": prior_usage, "prior_run": prior_run,
                    "after": archived + stale}
        if operation == "restore":
            target = targets[0]
            record = state["archives"][target["id"]]
            source = self.archive_dir / record["folder"]
            dest = Path(record["source_parent"]) / record["name"]
            if dest.exists() or dest.is_symlink() or _tree_revision(source) != record.get("tree_revision"):
                raise ValueError("restore_conflict")
            shutil.move(str(source), str(dest))
            state["archives"].pop(target["id"])
            self.usage.set_state(record["name"], STATE_ACTIVE)
            self._rediscover()
            if record["name"] not in self.loader.skills:
                raise ValueError("restore_not_loaded")
            return {"archive_ids": [target["id"]], "removed_archives": [target["id"]],
                    "restored_identity": {record["name"]: _identity(dest)},
                    "after": [source_snapshot(dest).fingerprint]}
        if operation == "purge":
            captures = []
            for target in targets:
                record = state["archives"][target["id"]]
                captures.append({"name": record["name"], "key": target["id"], "bucket": "archives",
                                 "fingerprint": target["fingerprint"], "tree_revision": target["tree_revision"],
                                 "path": str(self.archive_dir / record["folder"])})
            backup_id, digest = self._capture(captures, label="pre-purge")
            state["backups"][backup_id] = {"at": _now(), "digest": digest, "scope": "archives", "reason": "pre-purge",
                                            "skills": {},
                                            "archives": {x["id"]: state["archives"][x["id"]] for x in targets}}
            self._save(state)
            for target in targets:
                if _tree_revision(self.archive_dir / target["id"]) != target["tree_revision"]:
                    raise ValueError("archive_drifted")
                shutil.rmtree(self.archive_dir / target["id"])
                state["archives"].pop(target["id"])
            return {"backup_id": backup_id, "after": []}
        if operation == "rollback":
            return self._rollback(args, state, journal_id=entry["id"])
        raise ValueError("invalid_operation")

    def _rediscover(self) -> None:
        discover = getattr(self.loader, "discover", None)
        if callable(discover):
            discover()

    def _rollback(self, args: dict, state: dict, *, journal_id: str) -> dict:
        # The exact prior managed slice is captured before any rollback. The source
        # operation is never replayed; only already captured local bytes are restored.
        ledger_id = args.get("ledger_id")
        if ledger_id:
            original = next(row for row in state["ledger"] if row["id"] == ledger_id)
            action = original["operation"]
            receipt = original.get("receipt", {})
            if original["status"] != "applied":
                raise ValueError("rollback_unsupported")
            if action in {"pin", "unpin"}:
                name = original["targets"][0]
                current = self._usage_slice(name)
                if current["pinned"] != (action == "pin"):
                    raise ValueError("rollback_conflict")
                prior = receipt["prior_usage"][name]
                if current["exists"]:
                    self.usage.reconcile_controls(name, pinned=prior["pinned"])
                elif prior["exists"]:
                    raise ValueError("usage_unreadable")
                return {"after": [prior["pinned"]],
                        "undo": {"kind": "usage", "name": name, "state": current}}
            if action in {"pause", "resume"}:
                if state["paused"] != (action == "pause"):
                    raise ValueError("rollback_conflict")
                current_paused = state["paused"]
                state["paused"] = receipt["prior_paused"]
                return {"after": [state["paused"]],
                        "undo": {"kind": "pause", "value": current_paused}}
            if action == "adopt":
                current_adopted = {name: state["adopted"].get(name) for name in original["targets"]}
                for target_name in original["targets"]:
                    state["adopted"].pop(target_name, None)
                return {"after": [], "undo": {"kind": "adopt", "values": current_adopted}}
            if action == "rollback" and receipt.get("undo"):
                undo = receipt["undo"]
                if undo["kind"] == "usage":
                    name = undo["name"]
                    before = self._usage_slice(name)
                    if before["exists"]:
                        self.usage.reconcile_controls(name, pinned=undo["state"]["pinned"])
                    elif undo["state"]["exists"]:
                        raise ValueError("usage_unreadable")
                    return {"after": [undo["state"]["pinned"]],
                            "undo": {"kind": "usage", "name": name, "state": before}}
                if undo["kind"] == "pause":
                    before = state["paused"]
                    state["paused"] = undo["value"]
                    return {"after": [state["paused"]], "undo": {"kind": "pause", "value": before}}
                if undo["kind"] == "adopt":
                    before = {name: state["adopted"].get(name) for name in undo["values"]}
                    for name, value in undo["values"].items():
                        if value is None:
                            state["adopted"].pop(name, None)
                        else:
                            state["adopted"][name] = value
                    return {"after": list(undo["values"].values()),
                            "undo": {"kind": "adopt", "values": before}}
            if action in {"purge", "rollback"}:
                return self._rollback({"backup_id": receipt["backup_id"]}, state,
                                      journal_id=journal_id)
            if action == "restore":
                name = original["targets"][0]
                skill, digest, path = self._skill(name)
                if digest != original.get("after", [None])[0]:
                    raise ValueError("rollback_conflict")
                backup_id, backup_digest = self._capture([{"name": name, "path": str(path)}], label="pre-rollback")
                state["backups"][backup_id] = {"at": _now(), "digest": backup_digest, "scope": "named",
                                                "reason": "pre-rollback", "skills": {name: {"fingerprint": digest,
                                                    "tree_revision": _tree_revision(path),
                                                    "parent": str(path.parent), "usage": self._usage(name)}}, "archives": {}}
                archive_id = uuid.uuid4().hex[:16]
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(self.archive_dir / archive_id))
                state["archives"][archive_id] = {"name": name, "folder": archive_id, "at": _now(),
                                                  "fingerprint": digest, "source_parent": str(path.parent),
                                                  "tree_revision": _tree_revision(self.archive_dir / archive_id),
                                                  "identity": _identity(self.archive_dir / archive_id),
                                                  "origin": (self._usage(name) or {}).get("origin", "unknown")}
                self.loader.skills.pop(name, None)
                self.usage.set_state(name, STATE_ARCHIVED)
                return {"backup_id": backup_id, "archive_ids": [archive_id], "after": [digest]}
            if action in {"archive", "prune", "run"}:
                archive_ids = receipt.get("archive_ids", [])
                recover = [state["archives"][archive_id] for archive_id in archive_ids]
                selected = [{"name": record["name"], "key": archive_id, "bucket": "archives",
                             "path": str(self.archive_dir / record["folder"])}
                            for archive_id, record in zip(archive_ids, recover, strict=True)]
                backup_id, digest = self._capture(selected, label="pre-rollback")
                state["backups"][backup_id] = {"at": _now(), "digest": digest, "scope": "archives",
                                                "reason": "pre-rollback", "skills": {},
                                                "archives": {archive_id: state["archives"][archive_id]
                                                             for archive_id in archive_ids}}
                self._save(state)
                for archive_id, record in zip(archive_ids, recover, strict=True):
                    source = self.archive_dir / record["folder"]
                    destination = Path(record["source_parent"]) / record["name"]
                    self._source_parent_allowed(destination.parent)
                    if destination.exists() or destination.is_symlink() or _tree_revision(source) != record.get("tree_revision"):
                        raise ValueError("rollback_conflict")
                    shutil.move(str(source), str(destination))
                    state["archives"].pop(archive_id)
                for name, prior in receipt.get("prior_usage", {}).items():
                    current = self._usage_slice(name)
                    if current["exists"]:
                        self.usage.reconcile_controls(name, state=prior["state"], pinned=prior["pinned"])
                    elif prior["exists"]:
                        raise ValueError("usage_unreadable")
                if action == "run":
                    state["last_run"] = receipt["prior_run"]["last_run"]
                    state["run_count"] = receipt["prior_run"]["run_count"]
                    state["last_report"] = receipt["prior_run"].get("last_report")
                self._rediscover()
                if any(record["name"] not in self.loader.skills for record in recover):
                    raise ValueError("restore_not_loaded")
                return {"backup_id": backup_id, "removed_archives": archive_ids,
                        "restored_identity": {record["name"]: _identity(Path(record["source_parent"]) / record["name"])
                                              for record in recover},
                        "after": [record["fingerprint"] for record in recover]}
            raise ValueError("rollback_unsupported")
        backup_id = args.get("backup_id") or max(state["backups"], key=lambda key: state["backups"][key]["at"])
        record = state["backups"][backup_id]
        self._snapshot_scope_ok(record, state)
        archive_path = self.backup_dir / f"{backup_id}.tar.gz"
        self._verify_backup(archive_path, record["digest"])
        active = record.get("skills", {})
        archived = record.get("archives", {})
        current_active = []
        for name in sorted(self.loader.skills):
            if self._managed(name, state):
                skill, digest, path = self._skill(name)
                current_active.append({"name": name, "path": str(path), "fingerprint": digest,
                                       "tree_revision": _tree_revision(path)})
        current_archived = [{"name": rec["name"], "key": archive_id, "bucket": "archives",
                             "path": str(self.archive_dir / rec["folder"]), "fingerprint": rec["fingerprint"],
                             "tree_revision": rec["tree_revision"]}
                            for archive_id, rec in state["archives"].items()]
        # A current owner edit to a saved skill is a conflict, not consent to replace it.
        for name, saved in active.items():
            if name in self.loader.skills and (
                self._skill(name)[1] != saved["fingerprint"] or
                _tree_revision(Path(self.loader.skills[name].path)) != saved.get("tree_revision")
            ):
                raise ValueError("rollback_conflict")
        safety_id, safety_digest = self._capture(current_active + current_archived, label="pre-rollback")
        state["backups"][safety_id] = {"at": _now(), "digest": safety_digest,
                                       "scope": "managed_slice", "reason": "pre-rollback",
                                       "created_by_ledger_id": journal_id,
                                       "skills": {x["name"]: {"fingerprint": x["fingerprint"],
                                                                    "tree_revision": _tree_revision(Path(x["path"])),
                                                                    "identity": _identity(Path(x["path"])),
                                                                    "parent": str(Path(x["path"]).parent),
                                                                    "usage": self._usage(x["name"])} for x in current_active},
                                       "archives": dict(state["archives"]),
                                       "state_snapshot": {key: copy.deepcopy(state[key]) for key in ("paused", "adopted", "last_run", "last_report", "run_count")}}
        self._save(state)
        # Unpack into a private stage through archive_safe (re-verifying every hash).
        # Tar metadata never chooses a destination.
        with tempfile.TemporaryDirectory(prefix="curator-rollback-", dir=self.state_dir) as stage_name:
            stage = Path(stage_name)
            files, modes = self._unpack_backup(archive_path, record["digest"], stage)
            for name in files:
                parts = name.split("/")
                if parts[0] == "skills" and parts[1] not in active:
                    raise ValueError("backup_target_mismatch")
                if parts[0] == "archives" and parts[1] not in archived:
                    raise ValueError("backup_target_mismatch")
                os.chmod(stage.joinpath(*parts), modes[name])
            placed: list[Path] = []
            restored_archive_ids: list[str] = []
            displaced: list[tuple[Path, Path, dict]] = []
            displaced_active: list[tuple[Path, Path, dict | None]] = []
            try:
                if record.get("scope") == "managed_slice":
                    for current in current_active:
                        if current["name"] in active:
                            continue
                        source = Path(current["path"])
                        hold = stage / "superseded-skills" / current["name"]
                        hold.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(source), str(hold))
                        displaced_active.append((hold, source, self._usage(current["name"])))
                        self.loader.skills.pop(current["name"], None)
                for archive_id, old in list(state["archives"].items()):
                    if archive_id in archived or (record.get("scope") != "managed_slice" and
                                                  not (record.get("scope") == "named" and old["name"] in active)):
                        continue
                    source = self.archive_dir / old["folder"]
                    hold = stage / "superseded" / archive_id
                    hold.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(hold))
                    displaced.append((hold, source, old))
                    state["archives"].pop(archive_id)
                for name, saved in active.items():
                    destination = Path(saved["parent"]) / name
                    if destination.exists() or destination.is_symlink():
                        continue  # exact fingerprint was verified above
                    source = stage / "skills" / name
                    if not source.is_dir() or _tree_revision(source) != saved.get("tree_revision"):
                        raise ValueError("backup_corrupt")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(destination))
                    placed.append(destination)
                for name, saved in active.items():
                    prior = saved.get("usage") or {}
                    current = self._usage(name)
                    if current is None and prior:
                        raise ValueError("usage_unreadable")
                    if current is not None:
                        self.usage.reconcile_controls(
                            name, state=prior.get("state", STATE_ACTIVE),
                            pinned=bool(prior.get("pinned")),
                            expected_origin=prior.get("origin"),
                        )
                for archive_id, saved in archived.items():
                    if archive_id in state["archives"]:
                        continue
                    source = stage / "archives" / archive_id
                    destination = self.archive_dir / saved["folder"]
                    if not source.is_dir() or _tree_revision(source) != saved.get("tree_revision"):
                        raise ValueError("backup_corrupt")
                    self.archive_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(destination))
                    placed.append(destination)
                    state["archives"][archive_id] = {**saved, "identity": _identity(destination)}
                    restored_archive_ids.append(archive_id)
                    if self._usage(saved["name"]) is not None:
                        self.usage.reconcile_controls(saved["name"], state=STATE_ARCHIVED,
                                                      expected_origin=saved.get("origin"))
                if record.get("scope") == "managed_slice":
                    for key in ("paused", "adopted", "last_run", "last_report", "run_count"):
                        state[key] = record["state_snapshot"][key]
                self._rediscover()
                if any(name not in self.loader.skills for name in active):
                    raise ValueError("restore_not_loaded")
            except Exception:
                for path in reversed(placed):
                    if path.is_dir():
                        shutil.rmtree(path)
                for hold, destination, old in reversed(displaced):
                    if hold.exists():
                        shutil.move(str(hold), str(destination))
                        state["archives"][destination.name] = old
                for hold, destination, prior_usage in reversed(displaced_active):
                    if hold.exists():
                        shutil.move(str(hold), str(destination))
                        if prior_usage is not None:
                            self.usage.reconcile_controls(
                                destination.name, state=prior_usage.get("state", STATE_ACTIVE),
                                pinned=bool(prior_usage.get("pinned")),
                                expected_origin=prior_usage.get("origin"),
                            )
                for name in active:
                    if name not in self.loader.skills:
                        self.usage.restore_record(name, None)
                raise
        restored_names = [name for name in active if name in self.loader.skills]
        return {"backup_id": safety_id,
                "removed_archives": [destination.name for _hold, destination, _old in displaced],
                "restored_identity": {name: _identity(Path(saved["parent"]) / name)
                                      for name, saved in active.items() if name in restored_names},
                "archive_ids": restored_archive_ids,
                "after": [record["digest"]]}


__all__ = ["CuratorOperations", "READ_VIEWS", "MUTATIONS"]
