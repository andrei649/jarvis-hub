"""batch.py — several skills edited in one atomic, rolled-back-on-failure call (H665).

Hermes's ``skill_manage`` takes one ``operations`` array — ``create``, ``patch``,
``write_file``, ``remove_file``, ``delete`` — across any number of skills and applies it
atomically: "any failure rolls every touched skill back". A ``create`` must come before
that skill's other operations and a ``delete`` must be the call's only operation. Nerva
offers the same batch two ways, both through :func:`run_batch`:

* the owner, directly: ``POST /api/skills/batch`` (admin), with ``dry_run`` to see the
  diffs first;
* the model, governed: ``skill_propose {operations}`` checks the batch with a dry run here
  (a failing operation comes back with a teaching payload the model corrects from), then
  records it in :class:`SkillBatchStore` with one approval card. Only the owner's decision
  on that card applies it (``routers/actions.py``), against the trees it was checked on.

How a batch lands. Every operation is applied, in order, to a *staging copy* of each
touched skill, beside the live folder (same filesystem, so a rename is atomic). Nothing
live is touched until every operation succeeded and every resulting SKILL.md passes the
H350 check and keeps its skill's name. Then the live folders are swapped for their staged
copies one rename at a time; any failure in the swap — or in renewing a signature or an
owner approval the old bytes had — renames every already-swapped folder back, so a partial
batch is never observable. The replaced folders go to an archive (reversible), the loader
reloads what changed and forgets what was deleted.

The failing operation's answer teaches: ``failed_op`` (its index, action, skill and file),
``hints`` (what to change), and ``file_preview`` (the file as the batch had left it at that
point, with line numbers, around the place that failed).
"""

from __future__ import annotations

import difflib
import logging
import os
import posixpath
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents.core.persistence import JsonStore

logger = logging.getLogger("jarvis.skills.batch")

CARD_TOOL = "skill.batch_proposal"
ACTIONS = ("create", "patch", "write_file", "remove_file", "delete")
MAX_OPS = 20
MAX_SKILL_MD_CHARS = 100_000
MAX_FILE_BYTES = 1_048_576
ALLOWED_SUBDIRS = ("references", "templates", "scripts", "assets")
MAX_NAME = 64
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
OP_FIELDS = ("name", "action", "content", "old_string", "new_string", "replace_all", "file_path",
             "file_content")
_FIELDS_BY_ACTION = {
    "create": {"content"},
    "patch": {"content", "old_string", "new_string", "replace_all", "file_path"},
    "write_file": {"file_path", "file_content"},
    "remove_file": {"file_path"},
    "delete": set(),
}
_SKILL_FILE = "SKILL.md"
PREVIEW_LINES = 40
PREVIEW_CHARS = 4000
MAX_DIFF_CHARS = 8000
#: Batches never overlap within a process: one batch's swap is never another's base.
_BATCH_LOCK = threading.Lock()
#: The swap's rename; tests replace it to fail at a chosen step.
_rename = os.rename


class BatchError(Exception):
    """One refusal, with what the model needs to correct it."""

    def __init__(self, reason: str, detail: str, *, index: int | None = None, op: dict | None = None,
                 hints: list[str] | None = None, preview: dict | None = None, extra: dict | None = None):
        super().__init__(detail)
        self.reason, self.detail, self.index, self.op = reason, detail, index, op
        self.hints = list(hints or [])
        self.preview = preview
        self.extra = dict(extra or {})

    def payload(self, *, rolled_back: list[str] | None = None) -> dict:
        out: dict[str, Any] = {"ok": False, "applied": False, "reason": self.reason, "detail": self.detail}
        if self.index is not None:
            op = self.op or {}
            out["failed_op"] = {"index": self.index, "action": op.get("action"), "name": op.get("name"),
                                **({"file_path": op["file_path"]} if op.get("file_path") else {})}
        if self.hints:
            out["hints"] = self.hints
        if self.preview:
            out["file_preview"] = self.preview
        out["rolled_back"] = list(rolled_back or [])
        out.update(self.extra)
        return out


# ── the teaching payload ─────────────────────────────────────────────────────────────

def file_preview(skill: str, rel: str, text: str, *, around: int | None = None) -> dict:
    """``text`` as numbered lines, a window of :data:`PREVIEW_LINES` around line ``around``
    (1-based; the head when None), at most :data:`PREVIEW_CHARS` characters."""
    lines = text.split("\n")
    start = 0 if around is None else max(0, around - 1 - PREVIEW_LINES // 2)
    window = lines[start:start + PREVIEW_LINES]
    shown, used = [], 0
    for offset, line in enumerate(window):
        row = f"{start + offset + 1:>4}| {line}"
        if used + len(row) + 1 > PREVIEW_CHARS:
            break
        shown.append(row)
        used += len(row) + 1
    return {"skill": skill, "path": rel, "total_lines": len(lines), "first_line": start + 1,
            "content": "\n".join(shown), "truncated": start > 0 or start + len(shown) < len(lines)}


def _closest_line(text: str, needle: str) -> tuple[int, str] | None:
    """The 1-based line of ``text`` most like the first line of ``needle``."""
    first = next((ln for ln in needle.split("\n") if ln.strip()), "")
    if not first:
        return None
    lines = text.split("\n")
    best = difflib.get_close_matches(first, lines, n=1, cutoff=0.5)
    if not best:
        stripped = [ln.strip() for ln in lines]
        best_stripped = difflib.get_close_matches(first.strip(), stripped, n=1, cutoff=0.5)
        if not best_stripped:
            return None
        index = stripped.index(best_stripped[0])
        return index + 1, lines[index]
    index = lines.index(best[0])
    return index + 1, lines[index]


# ── shape and order ──────────────────────────────────────────────────────────────────

def clean_rel(raw: Any, *, allow_skill_md: bool) -> str | None:
    """A relative POSIX path inside a skill: ``SKILL.md`` (when allowed) or a file under one
    of :data:`ALLOWED_SUBDIRS`. None when it would leave the skill or the allowed tree."""
    if not isinstance(raw, str) or not raw or len(raw) > 256 or "\\" in raw or "\x00" in raw:
        return None
    if raw.startswith("/") or not raw.isprintable():
        return None
    clean = posixpath.normpath(raw)
    if clean == _SKILL_FILE:
        return clean if allow_skill_md else None
    parts = clean.split("/")
    if len(parts) < 2 or parts[0] not in ALLOWED_SUBDIRS or any(p in ("", ".", "..") for p in parts):
        return None
    return clean


def _path_hint(action: str) -> str:
    where = ", ".join(f"{d}/" for d in ALLOWED_SUBDIRS)
    if action == "patch":
        return f"file_path is SKILL.md (the default) or a file under {where} relative to the skill's folder"
    return f"file_path is relative to the skill's folder and starts with one of {where} (e.g. references/api.md)"


def normalize(operations: Any) -> list[dict]:
    """The operations checked for shape and order; raises :class:`BatchError`."""
    if not isinstance(operations, list) or not operations:
        raise BatchError("skill_batch_empty", "operations is a list of 1 to "
                         f"{MAX_OPS} operations, each naming its skill and action",
                         hints=["a single edit is a list of one"])
    if len(operations) > MAX_OPS:
        raise BatchError("skill_batch_too_many", f"{len(operations)} operations; a batch takes at most {MAX_OPS}",
                         hints=["split the work into several batches"])
    out: list[dict] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise BatchError("skill_batch_bad_op", f"operation {index} is not an object", index=index, op={})
        op = dict(raw)
        unknown = sorted(str(k) for k in op if k not in OP_FIELDS)
        if unknown:
            hints = [f"an operation takes {', '.join(OP_FIELDS)}"]
            if "category" in unknown:
                hints.append("Nerva keeps each skill one folder deep under the skills root: leave category out")
            raise BatchError("skill_batch_unknown_field", f"operation {index} has an unknown field {unknown[0]!r}",
                             index=index, op=op, hints=hints)
        action, name = op.get("action"), op.get("name")
        if action not in ACTIONS:
            raise BatchError("skill_batch_bad_action", f"operation {index}: action is one of {', '.join(ACTIONS)}",
                             index=index, op=op)
        if not isinstance(name, str) or not name or len(name) > MAX_NAME:
            raise BatchError("skill_batch_bad_name", f"operation {index}: name is a skill name of 1 to "
                             f"{MAX_NAME} characters", index=index, op=op)
        extra = sorted(k for k in op if k not in ("name", "action") and k not in _FIELDS_BY_ACTION[action])
        if extra:
            raise BatchError("skill_batch_bad_field", f"operation {index}: {action} does not take {extra[0]!r}",
                             index=index, op=op,
                             hints=[f"{action} takes name, action"
                                    + "".join(f", {f}" for f in sorted(_FIELDS_BY_ACTION[action]))])
        _check_fields(index, op)
        if action == "create":
            if not NAME_RE.match(name):
                raise BatchError("skill_batch_bad_name", f"operation {index}: a new skill's name is lowercase "
                                 "letters, digits, '.', '_' or '-', starting with a letter or digit",
                                 index=index, op=op, hints=[f"try {re.sub(r'[^a-z0-9._-]+', '-', name.lower())!r}"])
            if name in seen:
                raise BatchError("skill_batch_create_not_first",
                                 f"operation {index} creates {name!r}, which operation {seen[name]} already "
                                 "names: a create must come before that skill's other operations",
                                 index=index, op=op,
                                 hints=[f"move the create of {name!r} to before operation {seen[name]}"])
        if action == "delete" and len(operations) > 1:
            raise BatchError("skill_batch_delete_not_alone",
                             f"operation {index} deletes {name!r}: a delete must be the batch's only operation",
                             index=index, op=op,
                             hints=["send the delete in a call of its own, before or after this batch"])
        seen.setdefault(name, index)
        out.append(op)
    return out


def _check_fields(index: int, op: dict) -> None:
    action = op["action"]

    def text(field: str, *, required: bool, allow_empty: bool = False, limit: int = MAX_SKILL_MD_CHARS):
        value = op.get(field)
        if value is None:
            if required:
                raise BatchError("skill_batch_missing_field", f"operation {index}: {action} needs {field}",
                                 index=index, op=op)
            return
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            raise BatchError("skill_batch_bad_field", f"operation {index}: {field} is text"
                             + ("" if allow_empty else " that is not empty"), index=index, op=op)
        if len(value) > limit:
            raise BatchError("skill_batch_too_large", f"operation {index}: {field} is {len(value):,} characters; "
                             f"at most {limit:,}", index=index, op=op,
                             hints=["move reference material into references/ files"])

    if action == "create":
        text("content", required=True)
    elif action == "patch":
        if "content" in op:
            if "old_string" in op or "new_string" in op or "replace_all" in op:
                raise BatchError("skill_batch_bad_field", f"operation {index}: a patch is either content (the "
                                 "whole new file) or old_string/new_string, not both", index=index, op=op)
            text("content", required=True)
        else:
            text("old_string", required=True)
            text("new_string", required=True, allow_empty=True)
            if "replace_all" in op and not isinstance(op["replace_all"], bool):
                raise BatchError("skill_batch_bad_field", f"operation {index}: replace_all is true or false",
                                 index=index, op=op)
        if "file_path" in op and clean_rel(op["file_path"], allow_skill_md=True) is None:
            raise BatchError("skill_batch_bad_path", f"operation {index}: {op['file_path']!r} is not a file "
                             "a patch may change", index=index, op=op, hints=[_path_hint("patch")])
    elif action in ("write_file", "remove_file"):
        if clean_rel(op.get("file_path"), allow_skill_md=False) is None:
            raise BatchError("skill_batch_bad_path", f"operation {index}: {op.get('file_path')!r} is not a "
                             f"supporting-file path", index=index, op=op, hints=[_path_hint(action)])
        if action == "write_file":
            text("file_content", required=True, allow_empty=True, limit=MAX_FILE_BYTES)


# ── staging ──────────────────────────────────────────────────────────────────────────

class _Target:
    """One touched skill: where it lives, its staged copy, what vouched for its bytes."""

    def __init__(self, name: str, live: Path, *, existing: bool, skill: Any = None):
        self.name, self.live, self.existing, self.skill = name, live, existing, skill
        self.stage_root: Path | None = None
        self.staged: Path | None = None
        self.old: Path | None = None
        self.deleted = False
        self.standing: dict = {}
        self.before_fp: str | None = None
        self.before_files: dict[str, bytes] = {}
        self.touched_md_at: int | None = None
        self.renewed = False


def _has_link(root: Path) -> bool:
    from .signing import _is_link_like

    if _is_link_like(root):
        return True
    return any(_is_link_like(p) for p in root.rglob("*"))


def _files_of(root: Path) -> dict[str, bytes]:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


def _fingerprint(root: Path) -> str:
    from .signing import source_fingerprint

    return source_fingerprint(root)


def _skills_root(create_root: Path | None) -> Path:
    if create_root is not None:
        return Path(create_root)
    from .loader import _writable_skills_dir

    return _writable_skills_dir()


def _resolve(name: str, index: int, op: dict, loader: Any, targets: dict[str, _Target],
             create_root: Path) -> _Target:
    if name in targets:
        target = targets[name]
        if op["action"] == "create":       # normalize() already refused this order
            raise BatchError("skill_batch_create_not_first", f"{name!r} is created twice", index=index, op=op)
        return target
    skills = getattr(loader, "skills", {}) or {}
    if op["action"] == "create":
        live = create_root / name
        existing = skills.get(name)
        if existing is not None or live.exists():
            where = Path(existing.path) if existing is not None else live
            preview = None
            try:
                preview = file_preview(name, _SKILL_FILE, (where / _SKILL_FILE).read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                preview = None
            raise BatchError("skill_batch_exists", f"a skill named {name!r} already exists", index=index, op=op,
                             preview=preview,
                             hints=[f"to change it, patch it: {{name: {name!r}, action: 'patch', old_string, "
                                    "new_string}", "or create the new skill under another name"])
        target = _Target(name, live, existing=False)
    else:
        skill = skills.get(name)
        if skill is None:
            raise BatchError("skill_batch_unknown_skill", f"no skill named {name!r} exists", index=index, op=op,
                             hints=["call skills_list for the names", "to make a new skill, put a create for "
                                    "it before its other operations in this batch"])
        live = Path(skill.path)
        target = _Target(name, live, existing=True, skill=skill)
        _check_standing(target, loader, index, op)
    targets[name] = target
    return target


def _check_standing(target: _Target, loader: Any, index: int, op: dict) -> None:
    from .loader import _shipped_location

    live = target.live
    if (live / "PENDING_REVIEW").exists():
        raise BatchError("skill_batch_pending_review", f"{target.name!r} awaits the owner's review "
                         "(quarantine): it cannot be edited until it is approved or discarded",
                         index=index, op=op)
    standing_of = getattr(loader, "owner_standing", None)
    try:
        standing = standing_of(target.skill) if callable(standing_of) else {}
    except Exception:
        logger.warning("skill batch: the standing of %s could not be read", target.name, exc_info=True)
        standing = {"unreadable": True}
    if standing.get("bundled") or not getattr(target.skill, "external", True) or _shipped_location(live):
        raise BatchError("skill_batch_bundled", f"{target.name!r} ships with Nerva and cannot be changed here",
                         index=index, op=op,
                         hints=["create a new skill that extends it instead"])
    if standing.get("unreadable"):
        raise BatchError("skill_batch_unreadable", f"{target.name!r} could not be read just now; nothing was "
                         "changed", index=index, op=op, hints=["try again"])
    if standing.get("key_missing"):
        raise BatchError("skill_batch_signing_key_missing", f"{target.name!r} is signed with a key this hub does "
                         "not have now, so its signature could not be renewed", index=index, op=op)
    target.standing = {k: standing.get(k) for k in ("signed", "approved")}


def _stage(target: _Target, batch_id: str) -> None:
    parent = target.live.parent
    target.stage_root = parent / f".skill-batch-{batch_id}"
    (target.stage_root / "new").mkdir(parents=True, exist_ok=True)
    (target.stage_root / "old").mkdir(parents=True, exist_ok=True)
    target.staged = target.stage_root / "new" / target.live.name
    if target.existing:
        if _has_link(target.live):
            raise BatchError("skill_batch_linked", f"{target.name!r} contains a link; a batch does not edit "
                             "linked skills")
        target.before_fp = _fingerprint(target.live)
        target.before_files = _files_of(target.live)
        shutil.copytree(target.live, target.staged, symlinks=True)
    else:
        target.staged.mkdir()


def _read_text(target: _Target, rel: str, index: int, op: dict) -> str:
    path = target.staged / rel
    if not path.is_file():
        files = sorted(p.relative_to(target.staged).as_posix() for p in target.staged.rglob("*") if p.is_file())
        raise BatchError("skill_batch_file_missing", f"{target.name!r} has no file {rel!r}", index=index, op=op,
                         hints=["its files: " + (", ".join(files[:30]) or "none"),
                                "write_file creates a supporting file"])
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise BatchError("skill_batch_binary", f"{rel!r} of {target.name!r} is not text, so it cannot be "
                         "patched", index=index, op=op, hints=["replace it whole with write_file"]) from None
    return text.replace("\r\n", "\n")


def _write(target: _Target, rel: str, text: str) -> None:
    path = target.staged / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _apply_op(target: _Target, index: int, op: dict) -> None:
    action = op["action"]
    if action == "create":
        _write(target, _SKILL_FILE, op["content"])
        target.touched_md_at = index
    elif action == "delete":
        target.deleted = True
    elif action == "write_file":
        rel = clean_rel(op["file_path"], allow_skill_md=False)
        if (target.staged / rel).is_dir():
            raise BatchError("skill_batch_bad_path", f"{rel!r} is a folder in {target.name!r}", index=index, op=op,
                             hints=[_path_hint(action)])
        if len(op["file_content"].encode("utf-8")) > MAX_FILE_BYTES:
            raise BatchError("skill_batch_too_large", f"file_content is over {MAX_FILE_BYTES:,} bytes",
                             index=index, op=op)
        _write(target, rel, op["file_content"])
    elif action == "remove_file":
        rel = clean_rel(op["file_path"], allow_skill_md=False)
        if not (target.staged / rel).is_file():
            files = sorted(p.relative_to(target.staged).as_posix() for p in target.staged.rglob("*") if p.is_file())
            raise BatchError("skill_batch_file_missing", f"{target.name!r} has no file {rel!r}", index=index,
                             op=op, hints=["its files: " + (", ".join(files[:30]) or "none")])
        (target.staged / rel).unlink()
        parent = (target.staged / rel).parent
        while parent != target.staged and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    elif action == "patch":
        rel = clean_rel(op.get("file_path", _SKILL_FILE), allow_skill_md=True)
        current = _read_text(target, rel, index, op)
        if "content" in op:
            new = op["content"]
        else:
            old, replacement = op["old_string"].replace("\r\n", "\n"), op["new_string"].replace("\r\n", "\n")
            count = current.count(old)
            if count == 0:
                close = _closest_line(current, old)
                hints = ["old_string must match the file exactly, spaces and line breaks included",
                         "read the file with skill_view first; file_preview below is the file as this batch "
                         "has it at this operation"]
                if close is not None:
                    hints.append(f"the closest line is {close[0]}: {close[1].strip()[:200]!r}")
                raise BatchError("skill_batch_patch_no_match", f"old_string is not in {rel!r} of {target.name!r}",
                                 index=index, op=op, hints=hints,
                                 preview=file_preview(target.name, rel, current,
                                                      around=close[0] if close else None))
            if count > 1 and not op.get("replace_all"):
                first = current[:current.index(old)].count("\n") + 1
                raise BatchError("skill_batch_patch_ambiguous", f"old_string occurs {count} times in {rel!r} of "
                                 f"{target.name!r}", index=index, op=op,
                                 hints=["add surrounding lines to old_string so it matches once",
                                        "or set replace_all: true to change every occurrence"],
                                 preview=file_preview(target.name, rel, current, around=first))
            new = current.replace(old, replacement) if op.get("replace_all") else current.replace(old, replacement, 1)
        _write(target, rel, new)
        if rel == _SKILL_FILE:
            target.touched_md_at = index


def _final_check(target: _Target, loader: Any, ops: list[dict], last_index: dict[str, int]) -> None:
    """Every SKILL.md the batch leaves must pass H350 and keep its skill's name."""
    from .validate import validate_skill_md

    if target.deleted:
        return
    index = target.touched_md_at if target.touched_md_at is not None else last_index[target.name]
    op = ops[index]
    md = target.staged / _SKILL_FILE
    try:
        text = md.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        raise BatchError("skill_batch_invalid_skill_md", f"{target.name!r} would be left without a readable "
                         "SKILL.md", index=index, op=op) from None
    if len(text) > MAX_SKILL_MD_CHARS:
        raise BatchError("skill_batch_too_large", f"{target.name!r}'s SKILL.md would be {len(text):,} characters; "
                         f"at most {MAX_SKILL_MD_CHARS:,}", index=index, op=op,
                         hints=["move reference material into references/ files"])
    problems = validate_skill_md(text)
    if problems:
        line = next((p.line for p in problems if p.line is not None), None)
        raise BatchError("skill_batch_invalid_skill_md", f"{target.name!r}'s SKILL.md would not be valid: "
                         + "; ".join(str(p) for p in problems), index=index, op=op,
                         hints=["a SKILL.md opens with frontmatter: ---, name: <name>, description: Use when "
                                "<trigger>. <what it does>., ---, then the body"],
                         preview=file_preview(target.name, _SKILL_FILE, text, around=line),
                         extra={"problems": [p.as_dict() for p in problems]})
    naming = getattr(loader, "manifest_name", None)
    try:
        declared = naming(target.staged, text) if callable(naming) else target.name
    except Exception:
        declared = None
    if declared != target.name:
        raise BatchError("skill_batch_rename", f"{target.name!r}'s SKILL.md would name it {declared!r}: a batch "
                         "keeps each skill's name", index=index, op=op,
                         hints=[f"set name: {target.name} in the frontmatter",
                                "to rename, create the new skill and delete the old one in a separate call"],
                         preview=file_preview(target.name, _SKILL_FILE, text))


def _diffs(target: _Target) -> list[dict]:
    after = {} if target.deleted else _files_of(target.staged)
    out = []
    for rel in sorted(set(target.before_files) | set(after)):
        old, new = target.before_files.get(rel), after.get(rel)
        if old == new:
            continue
        try:
            a = (old or b"").decode("utf-8").splitlines(keepends=True)
            b = (new or b"").decode("utf-8").splitlines(keepends=True)
            text = "".join(difflib.unified_diff(a, b, fromfile=f"{rel} (now)", tofile=f"{rel} (after)"))
        except UnicodeDecodeError:
            text = "(binary)"
        change = "added" if old is None else "removed" if new is None else "changed"
        out.append({"file": rel, "change": change, "diff": text[:MAX_DIFF_CHARS],
                    **({"diff_truncated": True} if len(text) > MAX_DIFF_CHARS else {})})
    return out


def _lint(target: _Target) -> list[dict]:
    if target.deleted:
        return []
    from .validate import lint_skill_md

    try:
        return [p.as_dict() for p in lint_skill_md((target.staged / _SKILL_FILE).read_bytes(),
                                                   folder=target.live.name)]
    except Exception:
        return []


def _cleanup(targets: list[_Target]) -> None:
    for root in {t.stage_root for t in targets if t.stage_root is not None}:
        shutil.rmtree(root, ignore_errors=True)


# ── the swap ─────────────────────────────────────────────────────────────────────────

def _swap(target: _Target) -> None:
    target.old = target.stage_root / "old" / target.live.name
    if target.existing:
        _rename(target.live, target.old)
        if target.deleted:
            return
        try:
            _rename(target.staged, target.live)
        except BaseException:
            _rename(target.old, target.live)      # this skill is whole again before the undo
            target.old = None
            raise
    else:
        if target.live.exists():
            raise FileExistsError(str(target.live))
        _rename(target.staged, target.live)


def _unswap(target: _Target, loader: Any) -> None:
    if target.existing:
        if not target.deleted and target.live.exists():
            os.rename(target.live, target.stage_root / "new" / f"{target.live.name}.undone")
        os.rename(target.old, target.live)
        if target.renewed and target.standing.get("approved"):
            try:
                from .signing import source_snapshot

                loader.restore_standing(target.live, {"approved": True}, snapshot=source_snapshot(target.live))
            except Exception:
                logger.warning("skill batch: the approval of %s could not be put back", target.name, exc_info=True)
    else:
        os.rename(target.live, target.stage_root / "new" / f"{target.live.name}.undone")


def _renew(target: _Target, loader: Any, staged_fp: str) -> None:
    """Give the new bytes the standing the old ones had: the owner wrote or approved them."""
    if not target.existing or target.deleted or not (target.standing.get("signed") or target.standing.get("approved")):
        return
    from .signing import source_snapshot

    after = source_snapshot(target.live)
    if after.fingerprint != staged_fp:
        raise RuntimeError("changed during the swap")
    target.renewed = True
    loader.restore_standing(target.live, target.standing, snapshot=after)


def _reload(loader: Any, targets: list[_Target]) -> None:
    skills = getattr(loader, "skills", None)
    for target in targets:
        if target.deleted:
            if isinstance(skills, dict):
                for key, skill in list(skills.items()):
                    if Path(skill.path) == target.live:
                        del skills[key]
            store = getattr(loader, "_approval_store", None)
            try:
                if store is not None:
                    store.prune_missing()
            except Exception:
                logger.debug("skill batch: approval prune skipped", exc_info=True)
            continue
        try:
            loader._load_skill(target.live, discovery_root=target.live.parent)
        except Exception:
            logger.warning("skill batch: %s could not be reloaded", target.name, exc_info=True)


def fingerprints(operations: list[dict], loader: Any) -> dict[str, str | None]:
    """Each touched existing skill's tree fingerprint now (None for one a batch creates)."""
    out: dict[str, str | None] = {}
    skills = getattr(loader, "skills", {}) or {}
    for op in operations:
        name = op.get("name")
        if name in out or not isinstance(name, str):
            continue
        skill = skills.get(name) if op.get("action") != "create" else None
        try:
            out[name] = _fingerprint(Path(skill.path)) if skill is not None else None
        except Exception:
            out[name] = "unreadable"
    return out


def run_batch(operations: Any, loader: Any, *, create_root: Path | None = None, backup_dir: Path | None = None,
              dry_run: bool = False, expect: dict[str, str | None] | None = None,
              flagger: Callable[[str], bool] | None = None) -> dict:
    """Check, stage and (unless ``dry_run``) atomically apply ``operations``. Never raises.

    ``expect`` pins each touched skill to the tree fingerprint a reviewer saw (a governed
    batch): a skill that changed since makes the batch ``skill_batch_drifted``. ``flagger``
    refuses text that reads like an instruction to the model (the governed path)."""
    try:
        ops = normalize(operations)
    except BatchError as exc:
        return exc.payload()
    if flagger is not None:
        for index, op in enumerate(ops):
            for field in ("content", "new_string", "file_content"):
                value = op.get(field)
                if isinstance(value, str) and value and flagger(value):
                    return BatchError("skill_batch_flagged", f"operation {index}: {field} reads like an "
                                      "instruction to the model, so the batch is not recorded",
                                      index=index, op=op).payload()
    batch_id = uuid.uuid4().hex[:10]
    root = _skills_root(create_root)
    targets: dict[str, _Target] = {}
    keep = False
    with _BATCH_LOCK:
        try:
            try:
                last_index: dict[str, int] = {}
                for index, op in enumerate(ops):
                    target = _resolve(op["name"], index, op, loader, targets, root)
                    if target.stage_root is None:
                        _stage(target, batch_id)
                        if expect is not None and target.existing and expect.get(target.name) != target.before_fp:
                            raise BatchError("skill_batch_drifted", f"{target.name!r} changed after this batch was "
                                             "checked; nothing was applied", index=index, op=op,
                                             hints=["propose the batch again against the skill as it is now"])
                        if expect is not None and not target.existing and target.name not in expect:
                            raise BatchError("skill_batch_drifted", "the batch is not the one that was checked",
                                             index=index, op=op)
                    _apply_op(target, index, op)
                    last_index[op["name"]] = index
                for target in targets.values():
                    _final_check(target, loader, ops, last_index)
            except BatchError as exc:
                return exc.payload()
            except OSError as exc:
                logger.warning("skill batch: staging failed", exc_info=True)
                return BatchError("skill_batch_io", f"the batch could not be staged: {exc.strerror or exc}").payload()
            order = list(targets.values())
            summary = [{"name": t.name, "change": "deleted" if t.deleted else "changed" if t.existing else "created",
                        "files": _diffs(t), "lint": _lint(t)} for t in order]
            if dry_run:
                return {"ok": True, "applied": False, "dry_run": True, "operations": len(ops), "skills": summary}
            # Nothing live has changed yet: re-check no skill moved under the staging copy.
            for target in order:
                if target.existing and _fingerprint(target.live) != target.before_fp:
                    return BatchError("skill_batch_drifted", f"{target.name!r} changed while the batch was "
                                      "staged; nothing was applied", hints=["try again"]).payload()
            staged_fp = {t.name: _fingerprint(t.staged) for t in order if not t.deleted}
            swapped: list[_Target] = []
            failure = ""
            try:
                for target in order:
                    _swap(target)
                    swapped.append(target)
                for target in order:
                    _renew(target, loader, staged_fp.get(target.name, ""))
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                logger.warning("skill batch %s: swap failed; rolling back %d skill(s)", batch_id, len(swapped),
                               exc_info=True)
                undone, stuck = [], []
                for target in reversed(swapped):
                    try:
                        _unswap(target, loader)
                        undone.append(target.name)
                    except Exception:
                        logger.error("skill batch %s: %s could not be rolled back (old copy at %s)", batch_id,
                                     target.name, target.old, exc_info=True)
                        stuck.append(target.name)
                payload = BatchError("skill_batch_apply_failed", "the batch could not be applied, so every "
                                     f"touched skill was put back as it was ({failure})",
                                     hints=["nothing changed; the batch can be sent again"]).payload(
                                         rolled_back=list(reversed(undone)))
                if stuck:
                    keep = True
                    payload["not_rolled_back"] = stuck
                    payload["detail"] = f"the batch failed and {', '.join(stuck)} could not be put back ({failure})"
                    return payload        # the staging (with the old copies) is kept for the owner
                return payload
            backup = None
            if backup_dir is not None and any(t.existing for t in order):
                backup = Path(backup_dir) / f"{time.strftime('%Y%m%dT%H%M%S')}-{batch_id}"
                for target in order:
                    if target.existing and target.old is not None and target.old.exists():
                        try:
                            backup.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(target.old), str(backup / target.live.name))
                        except OSError:
                            logger.warning("skill batch: the old %s could not be archived", target.name,
                                           exc_info=True)
            _reload(loader, order)
            return {"ok": True, "applied": True, "dry_run": False, "batch_id": batch_id, "operations": len(ops),
                    "skills": summary, **({"backup": str(backup)} if backup else {})}
        finally:
            if not keep:
                _cleanup(list(targets.values()))


# ── the governed path: a batch the model proposes, the owner decides ─────────────────

STATUS_PENDING, STATUS_APPLIED, STATUS_REJECTED, STATUS_FAILED, STATUS_SUPERSEDED = (
    "pending", "applied", "rejected", "failed", "superseded")


class SkillBatchStore(JsonStore):
    """Durable ledger of batches the model proposed: their operations, the trees they were
    checked against, the dry run's diffs, and the one approval card that decides each."""

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path)
        self._apply_lock = threading.Lock()

    def _serialize(self):
        return {"batches": self._items}

    def _deserialize(self, raw) -> None:
        items = raw.get("batches", {}) if isinstance(raw, dict) else {}
        self._items = items if isinstance(items, dict) else {}

    def propose(self, operations: list[dict], *, expect: dict, preview: list[dict], origin: str) -> dict:
        with self._lock:
            for rec in self._items.values():
                if (rec.get("status") == STATUS_PENDING and rec.get("operations") == operations
                        and rec.get("expect") == expect):
                    return dict(rec)
            bid = f"sb-{uuid.uuid4().hex[:10]}"
            rec = {"id": bid, "origin": origin, "operations": operations, "expect": expect,
                   "skills": list(expect), "preview": preview, "status": STATUS_PENDING, "ts": time.time()}
            self._items[bid] = rec
            self._save()
            return dict(rec)

    def get(self, batch_id: str) -> dict | None:
        with self._lock:
            rec = self._items.get(batch_id)
            return dict(rec) if rec else None

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            out = [dict(r) for r in self._items.values() if status is None or r.get("status") == status]
        return sorted(out, key=lambda r: r.get("ts", 0.0))

    def mark(self, batch_id: str, status: str, **fields) -> dict | None:
        with self._lock:
            rec = self._items.get(batch_id)
            if rec is None:
                return None
            rec["status"] = status
            rec["decided_ts"] = time.time()
            rec.update(fields)
            self._save()
            return dict(rec)

    def queue_card(self, batch_id: str, queue, *, agent: str, summary: str) -> str | None:
        """Queue the batch's one approval card and bind it: only that card decides it."""
        rec = self.get(batch_id)
        if rec is None or rec.get("status") != STATUS_PENDING or queue is None:
            return None
        if rec.get("card"):
            return rec["card"]
        item = queue.request({"tool": CARD_TOOL, "agent": agent, "summary": summary,
                              "args": {"batch_id": batch_id, "skills": rec.get("skills", [])}})
        card = str((item or {}).get("id") or "")
        if card:
            with self._lock:
                live = self._items.get(batch_id)
                if live is not None:
                    live["card"] = card
                    self._save()
        return card or None

    def supersede_older(self, record: dict, queue=None) -> None:
        """One pending batch per origin: a newer one replaces the older, its card withdrawn."""
        for older in self.list(STATUS_PENDING):
            if older["id"] != record["id"] and older.get("origin") == record.get("origin"):
                self.mark(older["id"], STATUS_SUPERSEDED)
                if older.get("card") and queue is not None:
                    try:
                        queue.decide(older["card"], False, by="superseded")
                    except Exception:
                        logger.debug("superseded batch card %s not withdrawn", older["card"], exc_info=True)

    def decide(self, batch_id: str, card: str, approved: bool, loader: Any, *, create_root: Path | None = None,
               backup_dir: Path | None = None) -> dict:
        """The owner's decision on ``card``: an approval applies the batch now, against the
        trees it was checked on; a rejection closes it. Only the bound card decides."""
        with self._apply_lock:
            rec = self.get(batch_id)
            if rec is None or not card or rec.get("card") != card:
                return {"ok": False, "reason": "not_this_batch_card"}
            if rec.get("status") != STATUS_PENDING:
                return {"ok": False, "reason": f"not_pending:{rec.get('status')}"}
            if not approved:
                self.mark(batch_id, STATUS_REJECTED)
                return {"ok": True, "applied": False, "status": STATUS_REJECTED}
            out = run_batch(rec["operations"], loader, create_root=create_root, backup_dir=backup_dir,
                            expect=rec.get("expect") or {})
            if out.get("ok"):
                self.mark(batch_id, STATUS_APPLIED, backup=out.get("backup"))
            else:
                self.mark(batch_id, STATUS_FAILED, reason=out.get("reason"), detail=out.get("detail"))
            return out

    def sync_rejections(self, queue) -> None:
        """A card rejected by another path (a group reject, a reset) closes its batch."""
        lister = getattr(queue, "list", None)
        if not callable(lister):
            return
        try:
            rejected = {str(i.get("id")) for i in lister("rejected") if i.get("tool") == CARD_TOOL}
        except Exception:
            return
        for rec in self.list(STATUS_PENDING):
            if rec.get("card") in rejected:
                self.mark(rec["id"], STATUS_REJECTED)


__all__ = [
    "ACTIONS", "ALLOWED_SUBDIRS", "CARD_TOOL", "MAX_OPS", "BatchError", "SkillBatchStore", "file_preview",
    "fingerprints", "normalize", "run_batch",
]
