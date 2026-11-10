"""The verification evidence ledger: what a check actually proved, per session and project.

Hermes keeps a passive ledger (``agent/verification_evidence.py``) of the verify commands
the agent ran in a code workspace and their result, and marks it stale when code is
edited. This is Nerva's ledger, written for Nerva's execution model, where a command and
an edit both run *after* an approval and outside the turn that asked:

* **Passive.** It runs nothing and blocks nothing. A row is written when an approved
  ``terminal_run`` finished (``autonomy_coordinator._rpc_terminal_run`` calls
  :func:`record_terminal` with the redacted result) and its command is one of the
  project's verify commands (:func:`.project.verify_commands`); an approved
  ``file_write``/``file_delete`` marks the project edited (:func:`mark_edited`).
* **Attributed.** The session is the one whose turn queued the call (:func:`note_task`,
  called at intake). A call queued before a restart has no session and counts for the
  project only.
* **Classified like Hermes.** The command is matched against the canonical commands
  with the same equivalences (``npm test`` = ``npm run test``, ``python3 -m pytest`` =
  ``pytest``, ``./scripts/x.sh`` = ``bash scripts/x.sh``); trailing arguments that name
  a file or test make it ``targeted``, otherwise ``full``. Kind: test, lint, typecheck,
  build, format or check, from the command's words.
* **Not back-dated.** Each row carries the hash of the row before it (``row_hash`` over
  ``prev_hash`` and its fields) and, when the hub's signed intent log is available, the
  hash of the intent-log entry that anchored it (``audit_hash``, action
  ``verify.evidence``). :func:`verify_chain` re-checks both.
* **Bounded.** At most :data:`MAX_EVENTS` rows (oldest pruned), 200 changed paths per
  project and session, 1 200 characters of output tail, already redacted by the runner.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shlex
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.verify.evidence")

MAX_EVENTS = 5_000
MAX_CHANGED_PATHS = 200
MAX_OUTPUT_CHARS = 1_200
MAX_TASKS = 512
#: Turn-end nudges for one generation of edits (a new edit starts a new generation).
MAX_NUDGES = 2

_lock = threading.Lock()
_tasks: OrderedDict[int, str] = OrderedDict()
_db_override: Path | None = None

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        session_id TEXT NOT NULL,
        task_id INTEGER,
        root TEXT NOT NULL,
        cwd TEXT NOT NULL,
        command TEXT NOT NULL,
        canonical TEXT NOT NULL,
        kind TEXT NOT NULL,
        scope TEXT NOT NULL,
        status TEXT NOT NULL,
        exit_code INTEGER NOT NULL,
        output_tail TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL,
        audit_hash TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_events_root ON events(root, id DESC)",
    """CREATE TABLE IF NOT EXISTS state (
        session_id TEXT NOT NULL,
        root TEXT NOT NULL,
        last_edit_at REAL,
        changed_paths TEXT NOT NULL DEFAULT '[]',
        nudges INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (session_id, root)
    )""",
)

# Prose/data with nothing to verify (Hermes ``_NON_CODE_VERIFY_*``).
NON_CODE_EXTENSIONS = frozenset({".md", ".markdown", ".mdx", ".rst", ".txt", ".text", ".adoc", ".asciidoc",
                                 ".org", ".log", ".csv", ".tsv"})
NON_CODE_NAMES = frozenset({"license", "licence", "notice", "authors", "contributors", "changelog", "codeowners"})
_INTERPRETER_RE = re.compile(r"^(python|python3|py|node|bash|sh|ruby|perl)(?:[0-9]+(?:\.[0-9]+)*)?(?:\.exe)?$",
                             re.IGNORECASE)
_PY_FLAG_RE = re.compile(r"^-(?:[IBuEsSOd]+|3(?:\.\d+)?)$")
_PYTEST_SPELLINGS = (["python", "-m", "pytest"], ["uv", "run", "pytest"], ["poetry", "run", "pytest"],
                     ["pipenv", "run", "pytest"])
_TARGET_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java")
_TARGET_PREFIXES = ("test_", "tests", "spec", "__tests__")
_KIND_WORDS = (
    (frozenset({"lint", "eslint", "ruff", "flake8", "pylint"}), "lint"),
    (frozenset({"typecheck", "tsc", "mypy", "pyright"}), "typecheck"),
    (frozenset({"build", "compile", "package"}), "build"),
    (frozenset({"fmt", "format"}), "format"),
)


# ── storage ─────────────────────────────────────────────────────────────────

def db_path() -> Path:
    if _db_override is not None:
        return _db_override
    from agents.core.paths import data_path

    return data_path("verify", "evidence.db")


def set_db_path(path: Path | None) -> None:
    """Point the ledger at another file (tests)."""
    global _db_override
    _db_override = Path(path) if path is not None else None


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    for ddl in _SCHEMA:
        conn.execute(ddl)
    return conn


# ── task → session ──────────────────────────────────────────────────────────

def _current_session() -> str:
    try:
        from agents.core.llm.request_context import current_session

        return str(current_session() or "")
    except Exception:  # noqa: BLE001
        return ""


def note_task(task_id: object, session: str | None = None) -> None:
    """A gated call (terminal_run, file_write, file_delete) was queued in this turn: what it
    does once approved counts for the turn's session."""
    if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
        return
    sid = str(session if session is not None else _current_session())
    if not sid:
        return
    with _lock:
        _tasks[task_id] = sid
        _tasks.move_to_end(task_id)
        while len(_tasks) > MAX_TASKS:
            _tasks.popitem(last=False)


def task_session(task_id: object) -> str:
    with _lock:
        return _tasks.get(task_id, "") if isinstance(task_id, int) else ""


# ── classification ──────────────────────────────────────────────────────────

def _tokens(command: str) -> list[str]:
    try:
        return [t for t in shlex.split(command) if t]
    except ValueError:
        return []


def _strip_prefix(tokens: list[str]) -> list[str]:
    """Drop ``env``, ``VAR=value`` assignments, ``command``/``time`` and ``timeout <n>``."""
    i = 1 if tokens and tokens[0] == "env" else 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        i += 1
    while i < len(tokens):
        if tokens[i] in {"command", "time", "noglob"}:
            i += 1
        elif tokens[i] == "timeout" and i + 1 < len(tokens) and re.fullmatch(r"\d+(?:\.\d+)?[smhd]?", tokens[i + 1]):
            i += 2
        else:
            break
    return tokens[i:]


def _normalize(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = re.sub(r"^(?:\./)+", "", tokens[i])
        name = token.replace("\\", "/").rsplit("/", 1)[-1]
        match = _INTERPRETER_RE.match(name)
        family = None
        if match:
            family = re.sub(r"[0-9.]+$", "", match.group(1).lower())
            family = "python" if family == "py" else family
        out.append(family or token)
        i += 1
        if family == "python":
            while i < len(tokens) and _PY_FLAG_RE.match(tokens[i]):
                i += 1
    return out


def _needles(canonical: list[str]) -> list[list[str]]:
    found = [canonical]
    if len(canonical) >= 3 and canonical[1] == "run" and canonical[0] in {"npm", "pnpm", "yarn", "bun"}:
        found.append([canonical[0], canonical[2]])
    if len(canonical) == 1 and "/" in canonical[0]:
        found += [["bash", canonical[0]], ["sh", canonical[0]]]
    if canonical == ["pytest"]:
        found += [list(s) for s in _PYTEST_SPELLINGS]
    return found


def _looks_like_target(arg: str) -> bool:
    return bool(arg) and not arg.startswith("-") and "=" not in arg and (
        any(m in arg for m in ("/", "\\", "::")) or arg.endswith(_TARGET_EXTENSIONS)
        or arg.startswith(_TARGET_PREFIXES))


def kind_for(canonical: str) -> str:
    words = set(re.split(r"[\s:/._-]+", canonical.lower()))
    kind = next((k for group, k in _KIND_WORDS if words & group), None)
    return kind or ("check" if "check" in words and "test" not in words else "test")


def classify(command: str, canonical_commands: list[str]) -> tuple[str, str, str] | None:
    """``(canonical, kind, scope)`` when *command* runs one of *canonical_commands*."""
    candidate = _normalize(_strip_prefix(_tokens(command)))
    if not candidate:
        return None
    for canonical in canonical_commands:
        needle = [re.sub(r"^(?:\./)+", "", t) for t in _tokens(canonical)]
        if not needle:
            continue
        for spelling in _needles(needle):
            spelled = _normalize(spelling)
            if candidate[: len(spelled)] == spelled:
                trailing = candidate[len(spelled):]
                scope = "targeted" if any(map(_looks_like_target, trailing)) else "full"
                return canonical, kind_for(canonical), scope
    return None


def is_code_path(raw: object) -> bool:
    path = Path(str(raw or ""))
    if not path.name:
        return False
    suffix = path.suffix.lower()
    return not (suffix in NON_CODE_EXTENSIONS or (not suffix and path.name.lower() in NON_CODE_NAMES))


# ── writing ─────────────────────────────────────────────────────────────────

_FIELDS = ("created_at", "session_id", "task_id", "root", "cwd", "command", "canonical", "kind", "scope",
           "status", "exit_code", "output_tail")


def _row_hash(prev_hash: str, row: dict[str, Any]) -> str:
    body = json.dumps({k: row[k] for k in _FIELDS}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{prev_hash}|{body}".encode()).hexdigest()


def _tail(result: dict) -> str:
    text = "\n".join(str(result.get(k) or "") for k in ("stdout", "stderr") if result.get(k))
    text = text.strip()
    return text[-MAX_OUTPUT_CHARS:]


def _insert(row: dict[str, Any], audit=None) -> dict[str, Any]:
    with _lock, closing(_connect()) as conn:
        last = conn.execute("SELECT row_hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["row_hash"] if last is not None else ""
        row = {**row, "prev_hash": prev}
        row["row_hash"] = _row_hash(prev, row)
        audit_hash = ""
        if audit is not None:
            try:
                entry = audit.record(
                    actor="verify", action="verify.evidence",
                    why=f"{row['status']}: {row['canonical']}"[:200],
                    metadata={"root": row["root"], "session_id": row["session_id"], "kind": row["kind"],
                              "scope": row["scope"], "exit_code": row["exit_code"], "row_hash": row["row_hash"]})
                audit_hash = str((entry or {}).get("entry_hash") or "")
            except Exception:  # noqa: BLE001 — an anchor that fails leaves the row unanchored
                logger.warning("verify evidence: intent-log anchor failed", exc_info=True)
        row["audit_hash"] = audit_hash
        cols = (*_FIELDS, "prev_hash", "row_hash", "audit_hash")
        cur = conn.execute(f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",  # nosec B608 - fixed column names
                           tuple(row[c] for c in cols))
        row["id"] = int(cur.lastrowid or 0)
        if row["status"] == "passed" and row["scope"] == "full":
            # A full passing check proves the project for every session that edited it.
            conn.execute("UPDATE state SET changed_paths = '[]', nudges = 0, last_edit_at = NULL "
                         "WHERE root = ? AND (last_edit_at IS NULL OR last_edit_at <= ?)",
                         (row["root"], row["created_at"]))
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count > MAX_EVENTS:
            conn.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id LIMIT ?)",
                         (count - MAX_EVENTS,))
        conn.commit()
    return row


def record_terminal(task_id: object, args: dict, result: dict, *, audit=None, now: float | None = None,
                    scope=None) -> dict[str, Any] | None:
    """Record an approved ``terminal_run`` that finished, when its command is one of the
    project's verify commands. Returns the row, or None (not evidence / not run)."""
    from .project import facts_for, load_recipe, verify_commands

    if not isinstance(args, dict) or not isinstance(result, dict):
        return None
    command = args.get("command")
    exit_code = result.get("exit_code")
    cwd = args.get("cwd") or result.get("cwd")
    if (not isinstance(command, str) or not command.strip() or isinstance(exit_code, bool)
            or not isinstance(exit_code, int) or not cwd):
        return None
    facts = facts_for(cwd, scope)
    if facts is None:
        return None
    try:
        recipe, _source = load_recipe(Path(facts.root))
    except Exception:  # noqa: BLE001 — a recipe that cannot be read only narrows the match
        recipe = None
    match = classify(command, verify_commands(facts, recipe))
    if match is None:
        return None
    canonical, kind, scope_name = match
    with _lock:
        session = _tasks.pop(task_id, "") if isinstance(task_id, int) else ""
    row = {
        "created_at": float(now if now is not None else time.time()), "session_id": session,
        "task_id": task_id if isinstance(task_id, int) and not isinstance(task_id, bool) else None,
        "root": facts.root, "cwd": str(cwd), "command": command[:1000], "canonical": canonical,
        "kind": kind, "scope": scope_name, "status": "passed" if exit_code == 0 else "failed",
        "exit_code": exit_code, "output_tail": _tail(result),
    }
    return _insert(row, audit)


def mark_edited(task_id: object, path: object, *, now: float | None = None, scope=None) -> dict[str, Any] | None:
    """An approved write or delete changed *path*: the project's evidence is stale for the
    session whose turn queued it."""
    from .project import workspace_root

    if not path:
        return None
    found = workspace_root(str(path), scope)
    if found is None:
        return None
    root = str(found[0])
    with _lock:
        session = _tasks.pop(task_id, "") if isinstance(task_id, int) else ""
    edited_at = float(now if now is not None else time.time())
    with _lock, closing(_connect()) as conn:
        row = conn.execute("SELECT changed_paths FROM state WHERE session_id = ? AND root = ?",
                           (session, root)).fetchone()
        try:
            existing = json.loads(row["changed_paths"]) if row is not None else []
        except ValueError:
            existing = []
        merged = sorted(set(existing) | {str(path)})[-MAX_CHANGED_PATHS:]
        conn.execute(
            "INSERT INTO state (session_id, root, last_edit_at, changed_paths, nudges) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(session_id, root) DO UPDATE SET last_edit_at = excluded.last_edit_at, "
            "changed_paths = excluded.changed_paths, nudges = 0",
            (session, root, edited_at, json.dumps(merged)))
        conn.commit()
    return {"session_id": session, "root": root, "last_edit_at": edited_at, "changed_paths": merged}


# ── reading ─────────────────────────────────────────────────────────────────

def _fresh_pass(conn, root: str, since: float | None) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM events WHERE root = ? AND status = 'passed' AND scope = 'full' AND created_at >= ? "
        "ORDER BY id DESC LIMIT 1", (root, since or 0.0)).fetchone()


def status(root: str, session: str | None = None) -> dict[str, Any]:
    """The project's verification state: ``passed`` (a full passing check newer than the
    last edit), ``stale`` (evidence older than an edit), ``failed`` or ``unverified``."""
    with _lock, closing(_connect()) as conn:
        params: tuple = (root, session) if session is not None else (root,)
        where = "root = ? AND session_id = ?" if session is not None else "root = ?"
        edits = conn.execute(f"SELECT MAX(last_edit_at) AS at FROM state WHERE {where}", params).fetchone()  # nosec B608 - fixed clauses
        last_edit = edits["at"] if edits is not None else None
        latest = conn.execute("SELECT * FROM events WHERE root = ? ORDER BY id DESC LIMIT 1", (root,)).fetchone()
        fresh = _fresh_pass(conn, root, last_edit)
    if fresh is not None:
        return {"status": "passed", "root": root, "last_edit_at": last_edit, "evidence": dict(fresh)}
    if latest is None:
        return {"status": "unverified", "root": root, "last_edit_at": last_edit, "evidence": None}
    evidence = dict(latest)
    state = "stale" if last_edit is not None and last_edit > evidence["created_at"] else evidence["status"]
    if state == "passed" and evidence["scope"] != "full":
        state = "targeted"
    return {"status": state, "root": root, "last_edit_at": last_edit, "evidence": evidence}


def for_task(task_id: object) -> dict[str, Any] | None:
    """The ledger row an approved command wrote, by its task id (the newest), or None."""
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        return None
    with _lock, closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM events WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    return dict(row) if row is not None else None


def passed_since_edit(root: str, command: str) -> bool:
    """Whether *command* (exactly, or as the canonical command it ran) passed in *root* after
    the project's last edit by any session (``/verify run`` resumes after an approval)."""
    with _lock, closing(_connect()) as conn:
        edits = conn.execute("SELECT MAX(last_edit_at) AS at FROM state WHERE root = ?", (root,)).fetchone()
        since = edits["at"] if edits is not None and edits["at"] is not None else 0.0
        row = conn.execute(
            "SELECT id FROM events WHERE root = ? AND status = 'passed' AND (command = ? OR canonical = ?) "
            "AND created_at >= ? LIMIT 1", (root, command, command, since)).fetchone()
    return row is not None


def pending(session: str) -> list[dict[str, Any]]:
    """Projects this session edited (code, not prose) with no full passing check since,
    and nudges left in this generation of edits."""
    if not session:
        return []
    with _lock, closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM state WHERE session_id = ? AND last_edit_at IS NOT NULL",
                            (session,)).fetchall()
        out = []
        for row in rows:
            try:
                paths = [p for p in json.loads(row["changed_paths"]) if is_code_path(p)]
            except ValueError:
                paths = []
            if not paths or row["nudges"] >= MAX_NUDGES:
                continue
            if _fresh_pass(conn, row["root"], row["last_edit_at"]) is not None:
                continue
            out.append({"root": row["root"], "changed_paths": paths, "nudges": row["nudges"],
                        "last_edit_at": row["last_edit_at"]})
    return out


def note_nudged(session: str, root: str) -> None:
    with _lock, closing(_connect()) as conn:
        conn.execute("UPDATE state SET nudges = nudges + 1 WHERE session_id = ? AND root = ?", (session, root))
        conn.commit()


def recent(root: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with _lock, closing(_connect()) as conn:
        if root is None:
            rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM events WHERE root = ? ORDER BY id DESC LIMIT ?",
                                (root, limit)).fetchall()
    return [dict(r) for r in rows]


def verify_chain(audit=None) -> dict[str, Any]:
    """Re-check every row's hash and its link to the row before it, and, with the intent
    log, that each anchored row's hash is the one the log recorded."""
    with _lock, closing(_connect()) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY id").fetchall()]
    anchored: dict[str, str] = {}
    if audit is not None:
        try:
            for entry in audit.list(limit=100_000):
                if entry.get("action") == "verify.evidence":
                    anchored[str(entry.get("entry_hash"))] = str((entry.get("metadata") or {}).get("row_hash"))
        except Exception:  # noqa: BLE001
            anchored = {}
    prev: str | None = None
    for row in rows:
        if prev is not None and row["prev_hash"] != prev:
            return {"ok": False, "bad_id": row["id"], "reason": "link", "n": len(rows)}
        if _row_hash(row["prev_hash"], row) != row["row_hash"]:
            return {"ok": False, "bad_id": row["id"], "reason": "hash", "n": len(rows)}
        if audit is not None and row["audit_hash"] and anchored.get(row["audit_hash"]) != row["row_hash"]:
            return {"ok": False, "bad_id": row["id"], "reason": "anchor", "n": len(rows)}
        prev = row["row_hash"]
    return {"ok": True, "bad_id": None, "reason": "", "n": len(rows)}


def reset_for_tests() -> None:
    with _lock:
        _tasks.clear()


__all__ = [
    "MAX_NUDGES", "classify", "db_path", "is_code_path", "kind_for", "mark_edited", "note_nudged", "note_task",
    "pending", "recent", "record_terminal", "reset_for_tests", "set_db_path", "status", "task_session",
    "verify_chain",
]
