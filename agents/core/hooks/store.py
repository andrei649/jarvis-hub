"""G17 — the owner's hook definitions and the card that activates one.

**Defining a hook is an owner action that widens what Nerva runs on this machine**, so it
takes the same road as a trusted skill source (``skills.tap_add``) or a voice command:

* only an admin may ask, from this origin (the routes use ``admin_guard`` +
  ``same_origin_write``). Asking validates the command and **only queues an approval
  card** at the approval queue's irreversible tier (:mod:`agents.core.autonomy.
  irreversible`), kind :data:`APPROVAL_KIND`. The card shows the exact command line, the
  event, the tool matcher, whether the hook is a *guard*, its timeout, and every file
  that runs (the program and, for an interpreter or a shell, its script) with its size and
  sha256;
* the hook is stored ``pending`` and runs nowhere. :func:`apply_approved` makes it
  ``active`` only when a *person* accepted the card (``irreversible.execute`` refuses a
  machine decider), with a plain accept (an ``edit`` replaces the payload and is refused),
  when the card's payload still equals the one recorded at request time
  (``payload_changed``), and when every bound file still has the content it had then
  (``changed_since_request``);
* turning a hook back on after it was switched off is the same card again
  (:func:`request_enable`). Switching one off and removing one only narrow what runs, so
  they apply at once (audited);
* changing a hook is a new definition with ``replaces``: the old one keeps running as it
  was approved until the new card is accepted, then it is replaced in the same write.

**The argv is fixed at definition time.** Nothing from an event is ever put on the command
line: there is no placeholder syntax, the argv runs verbatim with no shell, and the event
arrives as one JSON object on stdin. ``argv[0]`` is an absolute path to a regular file
nobody else can write (``voice.local_providers.trusted_program``); a launcher that runs
another program from its arguments (``env``, ``sudo``, ``xargs``, ``find``…) is refused; a
shell or an interpreter is allowed only to run a script named by absolute path right after
it (no ``-c`` / ``-e`` inline code), and that script is bound like the program. The
hardline denylist (``terminal_contract.hardline_match``) refuses at definition and again at
every run, and an argument that looks like a credential is refused (a command line is
visible to every process on the host).
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import logging
import os
import re
import secrets
import shlex
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.hooks.store")

APPROVAL_KIND = "hooks.define"
STORE_FORMAT = "nerva-hooks/1"
MAX_HOOKS = 32
MAX_ARGV_ITEMS = 32
MAX_ARG_CHARS = 1024
MAX_NAME_CHARS = 80
DEFAULT_TIMEOUT_S = 10
#: The highest per-hook timeout the owner may choose (``JARVIS_HOOKS_MAX_TIMEOUT_S`` may
#: lower it, never raise it).
TIMEOUT_CEILING_S = 120
DEFAULT_MAX_TIMEOUT_S = 30
MATCHER_RE = re.compile(r"^[A-Za-z0-9_.*?\[\]-]{1,100}$")
HOOK_ID_RE = re.compile(r"^hk-[0-9a-f]{10}$")

#: The event catalogue. ``blocking`` events are awaited and a hook's answer may block the
#: thing they precede; every other event is observed after the fact and nothing a hook
#: prints is read. ``hermes`` names the Hermes event the same scripts subscribe to there
#: (users copy hook scripts between agents). ``fields`` is exactly what the event carries
#: in ``extra`` (besides the top-level ``tool_name`` / ``tool_input`` / ``session_id``).
EVENTS: dict[str, dict[str, Any]] = {
    "tool.before": {
        "blocking": True, "hermes": "pre_tool_call", "matcher": True,
        "fields": ("tool_name", "tool_input", "agent_id", "session_id"),
        "doc": "Before a tool call runs, after the model asked for it and before approval or the "
               "kernel judge it. A hook may block the call (exit 2, or {\"action\": \"block\"}); "
               "it can never allow a call the policy, the approval queue or the kernel would refuse.",
    },
    "tool.after": {
        "blocking": False, "hermes": "post_tool_call", "matcher": True,
        "fields": ("tool_name", "status"),
        "doc": "After a tool call finished or failed: its name and status (never its arguments or result).",
    },
    "message.received": {
        "blocking": False, "hermes": "pre_llm_call", "matcher": False,
        "fields": ("channel", "session_id", "chars"),
        "doc": "A message arrived and a turn starts: the channel, the session and the message's length "
               "(never its text).",
    },
    "turn.completed": {
        "blocking": False, "hermes": "post_llm_call", "matcher": False,
        "fields": ("channel", "session_id", "status", "duration_ms"),
        "doc": "A turn ended: ok, refused or error, and how long it took.",
    },
    "session.started": {
        "blocking": False, "hermes": "on_session_start", "matcher": False,
        "fields": ("session_id",), "doc": "A conversation session started.",
    },
    "session.ended": {
        "blocking": False, "hermes": "on_session_end", "matcher": False,
        "fields": ("session_id",), "doc": "A conversation session ended (another one started).",
    },
    "command.completed": {
        "blocking": False, "hermes": "pre_command", "matcher": False,
        "fields": ("command", "status"), "doc": "A slash command finished: its name and status.",
    },
    "approval.requested": {
        "blocking": False, "hermes": "pre_approval_request", "matcher": False,
        "fields": ("request_id", "surface", "command", "description"),
        "doc": "An approval was asked for a command (secrets in the excerpt are masked).",
    },
    "approval.decided": {
        "blocking": False, "hermes": "post_approval_response", "matcher": False,
        "fields": ("request_id", "surface", "command", "description", "choice", "decided_by"),
        "doc": "That approval was decided.",
    },
}
BLOCKING_EVENTS = frozenset(name for name, spec in EVENTS.items() if spec["blocking"])

_LOCK = threading.RLock()


class HookRefused(Exception):
    """A request the store refuses, with a stable code (the route's error body)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


# ── limits read from the environment ────────────────────────────────────────────

def max_timeout() -> int:
    from agents.core.env_config import env_int

    return max(1, min(env_int("JARVIS_HOOKS_MAX_TIMEOUT_S", DEFAULT_MAX_TIMEOUT_S, minimum=1),
                      TIMEOUT_CEILING_S))


def hooks_switched_on() -> bool:
    """``JARVIS_HOOKS`` (default on): the owner's switch for every hook at once."""
    from agents.core.env_config import env_flag

    return env_flag("JARVIS_HOOKS", True)


# ── the command a hook runs ─────────────────────────────────────────────────────

def _name(token: str) -> str:
    from agents.core.voice.local_providers import _command_name

    return _command_name(token)


def inspect_argv(argv: Any) -> tuple[list[str], list[Path]]:
    """``(problems, bound files)``: every reason *argv* cannot be a hook command (``[]``
    when it can) and the files it runs, resolved (the program, then a script)."""
    from agents.core.environments.terminal_contract import hardline_match
    from agents.core.settings_db import _looks_like_credential
    from agents.core.voice import local_providers as lp

    if (not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV_ITEMS
            or any(type(item) is not str for item in argv)):
        return [f"argv: a list of 1 to {MAX_ARGV_ITEMS} strings"], []
    problems: list[str] = []
    for n, item in enumerate(argv):
        if not item or len(item) > MAX_ARG_CHARS or "\x00" in item or "\n" in item or "\r" in item:
            problems.append(f"argv[{n}]: empty, longer than {MAX_ARG_CHARS} characters or holds a "
                            "line break or NUL")
    if problems:
        return problems, []
    files: list[Path] = []
    exe, why = lp.trusted_program(argv[0])
    if exe is None:
        return [f"argv[0]: {why} (a hook's program is named by absolute path)"], []
    files.append(exe)
    script_index = 0
    names = {_name(argv[0]), _name(str(exe))}
    launchers = sorted({n for n in names if n in lp.LAUNCHERS and n not in lp.SHELLS}
                       | {n for n in names if lp._LAUNCHER_RE.match(n)})
    if launchers:
        problems.append(f"argv[0]: {launchers[0]} runs other programs or code from its arguments, "
                        "which would hide what the hook runs")
    elif names & lp.SHELLS or any(lp._INTERPRETER_RE.match(n) for n in names):
        script = argv[1] if len(argv) > 1 else ""
        if not script or script.startswith("-") or not os.path.isabs(script):
            problems.append("argv[1]: a shell or an interpreter runs only a script file named by "
                            "absolute path right after it (no -c / -e inline code)")
        else:
            path, why = lp.trusted_program(script, executable=False, what="the script")
            if path is None:
                problems.append(f"argv[1]: {why}")
            else:
                files.append(path)
                script_index = 1
    for n, item in enumerate(argv[1:], start=1):
        if ("/" in item or "\\" in item) and _name(item) in lp.SHELLS and n != script_index:
            problems.append(f"argv[{n}]: names a shell ({_name(item)}); a hook never hands its work "
                            "to one")
    hit = hardline_match(list(argv))
    if hit is not None:
        problems.append(f"hardline_denied:{hit}")
    if any(_looks_like_credential(item) for item in argv[1:]
           if not os.path.isabs(item)):   # a path is a path (a long one reads as entropy)
        problems.append("an argument looks like a credential; a command line is visible to every "
                        "process on this host (put the key in the script's own config)")
    return problems, ([] if problems else files)


def identities(files: list[Path]) -> list[dict] | None:
    """Each bound file's identity with its sha256, or None when one cannot be read."""
    from agents.core.voice.local_providers import bound_identities

    return bound_identities(files)


def shown(identity: dict) -> dict:
    return {"path": identity.get("path"), "size": identity.get("size"), "sha256": identity.get("sha256")}


# ── the store (``<data>/hooks/hooks.json``) ─────────────────────────────────────

def _store_path() -> Path:
    from agents.core.paths import data_path

    return Path(data_path("hooks", "hooks.json"))


def store_folder() -> Path:
    """``<data>/hooks``: no other writer may touch it (the file browser never shows it and a
    model file write refuses it), and it is kept 0700 with ``hooks.json`` 0600."""
    from agents.core.paths import data_path

    return Path(data_path("hooks"))


def is_store_path(path: object) -> bool:
    """Whether *path* is in ``<data>/hooks``, or is a ``hooks.json`` anywhere under the data
    root (resolved, so a link to it counts too)."""
    from agents.core.paths import data_root

    try:
        target = Path(os.path.realpath(os.fspath(path)))
        folder = Path(os.path.realpath(store_folder()))
        root = Path(os.path.realpath(data_root()))
    except (TypeError, ValueError, OSError):
        return False
    if target == folder or folder in target.parents:
        return True
    return target.name.lower() == "hooks.json" and (target == root or root in target.parents)


def run_dir() -> Path:
    """The private working directory every hook starts in (created 0700)."""
    from agents.core.paths import data_path

    path = Path(data_path("hooks", "run"))
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        # Owner-only private dir: 0o700 is stricter than the rule's suggested 0o644.
        os.chmod(path, 0o700)  # nosec B103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    return path


def _empty() -> dict:
    return {"format": STORE_FORMAT, "hooks": []}


def _row_ok(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    spec = EVENTS.get(row.get("event"))
    return (spec is not None and isinstance(row.get("id"), str) and bool(HOOK_ID_RE.fullmatch(row["id"]))
            and row.get("status") in ("pending", "active", "disabled")
            and isinstance(row.get("argv"), list) and all(type(a) is str for a in row["argv"])
            and isinstance(row.get("identities"), list) and bool(row["identities"])
            and type(row.get("guard")) is bool and (not row["guard"] or row["event"] in BLOCKING_EVENTS)
            and type(row.get("timeout_s")) is int and 1 <= row["timeout_s"] <= TIMEOUT_CEILING_S
            and (row.get("matcher") is None or (spec["matcher"] and isinstance(row["matcher"], str)
                                                 and bool(MATCHER_RE.fullmatch(row["matcher"])))))


_CACHE: dict[str, Any] = {"key": None, "data": None, "dropped": 0}


def store_key() -> tuple | None:
    """The store file's identity now (None when absent): anything cached about the
    store's rows is valid only for this key."""
    try:
        info = _store_path().stat()
    except OSError:
        return None
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read() -> dict:
    """The store, re-read whenever the file changed (a hot path asks on every tool call)."""
    path = _store_path()
    try:
        info = path.stat()
        key = (str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    except FileNotFoundError:
        return _empty()
    except OSError as exc:
        raise HookRefused("store_unavailable") from exc
    if _CACHE["key"] == key and _CACHE["data"] is not None:
        return json.loads(_CACHE["data"])
    data, dropped = _read_file(path)
    if dropped:
        logger.warning("the hook store held %d malformed row(s); they never run", dropped)
        _audit(None, "hooks", "hook.store_rows_dropped",
               f"{dropped} malformed row(s) in the hook store were dropped, never run", {"dropped": dropped})
    _CACHE.update(key=key, data=json.dumps(data), dropped=dropped)
    return data


def _read_file(path: Path) -> tuple[dict, int]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty(), 0
    except OSError as exc:
        raise HookRefused("store_unavailable") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HookRefused("store_unavailable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), list):
        raise HookRefused("store_unavailable")
    # A hand-edited row that does not hold up is dropped, never run (and audited).
    kept = [row for row in data["hooks"] if _row_ok(row)]
    dropped = len(data["hooks"]) - len(kept)
    data["hooks"] = kept[:MAX_HOOKS]
    return data, dropped


def _write(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        # Owner-only private dir: 0o700 is stricter than the rule's suggested 0o644.
        os.chmod(path.parent, 0o700)  # nosec B103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    fd, tmp = tempfile.mkstemp(prefix=".hooks-", dir=str(path.parent))   # created 0600
    try:
        with contextlib.suppress(OSError):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _find(data: dict, ident: str) -> dict | None:
    return next((row for row in data["hooks"] if row["id"] == ident), None)


def all_hooks() -> list[dict]:
    with _LOCK:
        return [dict(row) for row in _read()["hooks"]]


def get(ident: str) -> dict | None:
    with _LOCK:
        row = _find(_read(), ident)
        return dict(row) if row is not None else None


class StoreUnreadable(Exception):
    """The hook store exists but cannot be read: a ``tool.before`` caller fails closed."""


def active_for(event: str, tool: str | None = None, *, strict: bool = False) -> list[dict]:
    """The active hooks for *event* (and, for a tool event, whose matcher takes *tool*), in
    the order they were defined. A store that cannot be read holds no hook for an observer
    (logged); with ``strict`` (the blocking ``tool.before`` path) it raises
    :class:`StoreUnreadable`, so a guard the owner set up cannot be lost to a corrupt file."""
    try:
        rows = all_hooks()
    except HookRefused:
        logger.warning("the hook store could not be read; no hook runs")
        if strict:
            raise StoreUnreadable(str(_store_path())) from None
        return []
    found = []
    for row in rows:
        if row["status"] != "active" or row["event"] != event:
            continue
        matcher = row.get("matcher")
        if matcher and not fnmatch.fnmatchcase(str(tool or ""), matcher):
            continue
        found.append(row)
    return sorted(found, key=lambda r: (r.get("approved_at") or 0, r["id"]))


def command_line(argv: list[str]) -> str:
    return shlex.join(argv)


def public(row: dict) -> dict:
    return {
        "id": row["id"], "name": row.get("name") or "", "event": row["event"], "argv": list(row["argv"]),
        "command": command_line(row["argv"]), "matcher": row.get("matcher"), "guard": row["guard"],
        "timeout_s": row["timeout_s"], "status": row["status"], "task_id": row.get("task_id"),
        "files": [shown(i) for i in row["identities"]], "replaces": row.get("replaces"),
        "requested_at": row.get("requested_at"), "approved_at": row.get("approved_at"),
        "approved_by": row.get("approved_by"), "pending_card": bool(row.get("card_open")),
        "reapproval_pending": bool(row.get("card_open") and row.get("requested_identities")),
    }


def catalogue() -> list[dict]:
    return [{"event": name, "blocking": spec["blocking"], "hermes": spec["hermes"],
             "matcher": spec["matcher"], "fields": list(spec["fields"]), "doc": spec["doc"]}
            for name, spec in EVENTS.items()]


# ── define (an approval card), apply, enable, disable, remove ───────────────────

def _payload(row: dict) -> dict:
    return {"operation": APPROVAL_KIND, "hook_id": row["id"], "name": row.get("name") or "",
            "event": row["event"], "argv": list(row["argv"]), "matcher": row.get("matcher"),
            "guard": row["guard"], "timeout_s": row["timeout_s"],
            "files": [shown(i) for i in row["identities"]], "replaces": row.get("replaces")}


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def binding_digest(row: dict) -> str:
    """The digest of everything the owner approved (:func:`_payload`: the id, event, argv,
    matcher, guard flag, timeout, name and every file with its size and sha256). A run's
    receipt names it, and the approval queue's stored card must carry the same digest."""
    return payload_digest(_payload(row))


#: (task id, binding digest, store key) → verified. Cleared by any change of the store.
_VERIFIED: dict[tuple, bool] = {}


def _queue_of(orch: Any) -> Any:
    queue = getattr(orch, "autonomy_queue", None)
    if queue is None:
        queue = getattr(getattr(orch, "autonomy", None), "queue", None)
    return queue


def approval_verified(row: dict, orch: Any = None) -> bool:
    """Whether the durable approval queue holds the human acceptance of this exact hook:
    the row's ``approved_task_id`` is a ``hooks.define`` task, decided accept (plain) by a
    person (``irreversible.MACHINE_DECIDERS`` refused), approved or applied, and its stored
    card carries this hook's full binding. ``hooks.json`` alone proves nothing: a row that
    any other writer put there does not run. Cached per (task, binding, store state)."""
    from agents.core.autonomy.irreversible import MACHINE_DECIDERS

    if orch is None:
        from agents.core.app_state import get_orch

        orch = get_orch()
    task_id = row.get("approved_task_id")
    if type(task_id) is not int or task_id <= 0 or row.get("status") != "active":
        return False
    digest = binding_digest(row)
    key = (task_id, digest, store_key())
    if _VERIFIED.get(key):
        return True
    queue = _queue_of(orch)
    getter = getattr(queue, "get", None)
    if not callable(getter):
        return False
    try:
        task = getter(task_id)
    except Exception:  # noqa: BLE001 — an unreadable queue proves nothing
        logger.warning("the approval queue could not be read for hook %s", row.get("id"), exc_info=True)
        return False
    if task is None:
        return False
    payload = getattr(task, "payload", None)
    decided_by = str(getattr(task, "decided_by", "") or "").strip().lower()
    ok = (getattr(task, "kind", None) == APPROVAL_KIND
          and str(getattr(task, "decision", "") or "").strip().lower() in ("accept", "approve")
          and decided_by not in MACHINE_DECIDERS
          and str(getattr(task, "status", "") or "") in ("approved", "running", "done")
          and isinstance(payload, dict) and payload.get("hook_id") == row["id"]
          and payload_digest({k: payload.get(k) for k in _payload(row)}) == digest)
    if ok:
        if len(_VERIFIED) > 256:
            _VERIFIED.clear()
        _VERIFIED[key] = True
    return ok


_EFFECT = ("Runs on this machine as the hub's user, with that user's permissions: it can read what "
           "the hub's user can read. Nerva starts it with the argv shown (no shell), the event as JSON "
           "on stdin (secrets in a tool call's arguments masked), an environment without the hub's "
           "secrets, the timeout shown (it and anything it started are killed then) and capped output. "
           "Approving binds these exact files: changing any of them stops the hook until it is "
           "approved again. It does not bind what they load or start: a bound script can still import "
           "modules, read files or run programs that are not on this card.")


def _preview(row: dict, *, operation: str) -> dict:
    spec = EVENTS[row["event"]]
    effect = _EFFECT
    if row["event"] in BLOCKING_EVENTS:
        effect += (" It may block a tool call (exit 2 or {\"action\": \"block\"}); it can never allow "
                   "one that would otherwise be refused, and it cannot change a call's arguments.")
        effect += (" As a guard, a hook that fails (timeout, crash, unreadable answer) blocks the call."
                   if row["guard"] else " If it fails, the call goes ahead and the failure is audited.")
    else:
        effect += " It only observes: nothing it prints is read."
    return {"action": {"define": "Run a new owner hook", "enable": "Turn an owner hook back on",
                       "reapprove": "Approve an owner hook's changed files",
                       "replace": "Replace an owner hook"}[operation],
            "command": command_line(row["argv"]), "argv": list(row["argv"]),
            "event": row["event"], "event_doc": spec["doc"], "matcher": row.get("matcher") or "(every tool)"
            if spec["matcher"] else None, "guard": row["guard"], "timeout_s": row["timeout_s"],
            "files": [shown(i) for i in row["identities"]], "replaces": row.get("replaces"),
            "effect": effect}


def _queue(orch: Any, row: dict, operation: str) -> int:
    from agents.core.autonomy import irreversible

    payload = _payload(row)
    verb = {"enable": "Turn on", "reapprove": "Re-approve"}.get(operation, "Run")
    title = f"{verb} hook on {row['event']}: {command_line(row['argv'])[:120]}"
    queued = irreversible.enqueue(orch, APPROVAL_KIND, title=title, payload=payload,
                                  preview=_preview(row, operation=operation))
    if "pending" not in queued:
        raise HookRefused(str(queued.get("refused") or "approval_queue_unavailable"))
    row["task_id"] = queued["pending"]
    row["payload_sha256"] = payload_digest(payload)
    row["card_open"] = True
    return row["task_id"]


def validate_definition(*, event: Any, argv: Any, matcher: Any = None, guard: Any = False,
                        timeout_s: Any = None, name: Any = "") -> tuple[dict, list[Path]]:
    """The normalized definition and its bound files, or :class:`HookRefused`."""
    if event not in EVENTS:
        raise HookRefused("unknown_event", "one of " + ", ".join(EVENTS))
    spec = EVENTS[event]
    if type(guard) is not bool:
        raise HookRefused("invalid_guard")
    if guard and event not in BLOCKING_EVENTS:
        raise HookRefused("guard_not_blocking", "only a tool.before hook can be a guard")
    if matcher in ("", None):
        matcher = None
    elif not spec["matcher"]:
        raise HookRefused("matcher_not_supported", "a matcher applies to tool events only")
    elif not isinstance(matcher, str) or not MATCHER_RE.fullmatch(matcher):
        raise HookRefused("invalid_matcher", "a tool name or glob: letters, digits, _ . - * ? [ ]")
    if timeout_s is None:
        timeout_s = min(DEFAULT_TIMEOUT_S, max_timeout())
    if type(timeout_s) is not int or not 1 <= timeout_s <= max_timeout():
        raise HookRefused("invalid_timeout", f"1 to {max_timeout()} seconds")
    if not isinstance(name, str) or len(name) > MAX_NAME_CHARS or any(ord(c) < 32 for c in name):
        raise HookRefused("invalid_name")
    problems, files = inspect_argv(argv)
    if problems:
        raise HookRefused("invalid_command", "; ".join(problems))
    return {"event": event, "argv": list(argv), "matcher": matcher, "guard": guard,
            "timeout_s": timeout_s, "name": name.strip()}, files


def request_define(orch: Any, *, event: str, argv: list, matcher: str | None = None, guard: bool = False,
                   timeout_s: int | None = None, name: str = "", replaces: str | None = None,
                   requested_by: str = "owner") -> dict:
    """Validate and queue the card. ``{"pending": task_id, "hook": …}`` or :class:`HookRefused`."""
    definition, files = validate_definition(event=event, argv=argv, matcher=matcher, guard=guard,
                                            timeout_s=timeout_s, name=name)
    found = identities(files)
    if found is None:
        raise HookRefused("unreadable_file", "a bound file could not be read whole")
    with _LOCK:
        data = _read()
        if replaces is not None:
            old = _find(data, str(replaces))
            if old is None:
                raise HookRefused("not_found", "the hook to replace does not exist")
            if any(r.get("replaces") == old["id"] and r["status"] == "pending" for r in data["hooks"]):
                raise HookRefused("replacement_pending")
        if len(data["hooks"]) >= MAX_HOOKS:
            raise HookRefused("too_many_hooks")
        row = {"id": f"hk-{secrets.token_hex(5)}", **definition, "identities": found, "status": "pending",
               "replaces": replaces, "requested_by": requested_by, "requested_at": time.time()}
        _queue(orch, row, "replace" if replaces else "define")
        data["hooks"].append(row)
        _write(data)
    _audit(orch, requested_by, "hook.request",
           f"hook {row['id']} on {row['event']} asked for: {command_line(row['argv'])[:200]}",
           {"hook": row["id"], "event": row["event"], "task_id": row["task_id"], "guard": row["guard"]})
    return {"pending": row["task_id"], "hook": public(row)}


def _files_changed(row: dict) -> bool:
    problems, files = inspect_argv(row["argv"])
    now = identities(files) if not problems else None
    return now is None or [shown(i) for i in now] != [shown(i) for i in row["identities"]]


def request_enable(orch: Any, ident: str, *, actor: str = "owner") -> dict:
    """Turning a switched-off hook back on is the same card again, with the files as they
    are now (a changed file shows its new digest on the card). For an active hook whose
    files changed since its approval this is the one-step re-approval: the card shows the
    new digests, and the hook stays stopped until it is accepted."""
    with _LOCK:
        data = _read()
        row = _find(data, ident)
        if row is None:
            raise HookRefused("not_found")
        if row["status"] == "active":
            if not _files_changed(row):
                raise HookRefused("not_disabled", "the hook is on and its files are as approved")
            operation = "reapprove"
        elif row["status"] == "disabled":
            operation = "enable"
        else:
            raise HookRefused("not_disabled")
        problems, files = inspect_argv(row["argv"])
        if problems:
            raise HookRefused("invalid_command", "; ".join(problems))
        found = identities(files)
        if found is None:
            raise HookRefused("unreadable_file")
        current = dict(row, identities=found)
        _queue(orch, current, operation)
        # The row keeps its approved files until the card is accepted (so the approved
        # binding still proves only what was approved); the card's files wait on the side.
        row.update(task_id=current["task_id"], payload_sha256=current["payload_sha256"], card_open=True,
                   requested_identities=found)
        _write(data)
    _audit(orch, actor, "hook.request", f"hook {ident} asked to be {'re-approved' if operation == 'reapprove' else 'turned back on'}",
           {"hook": ident, "task_id": row["task_id"], "operation": operation})
    return {"pending": row["task_id"], "hook": public(row)}


async def apply_approved(task: Any, orch: Any) -> dict:
    """A person accepted the card (``irreversible.execute`` checked who): activate the
    hook the card names, only as it was asked and only while its files are unchanged."""
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decision not in ("accept", "approve"):
        return {"status": "refused", "reason": "edit_not_supported"}
    payload = dict(getattr(task, "payload", {}) or {})
    task_id = getattr(task, "id", None)
    with _LOCK:
        data = _read()
        row = _find(data, str(payload.get("hook_id") or ""))
        if row is None or row.get("task_id") != task_id or not row.get("card_open"):
            return {"status": "refused", "reason": "not_requested"}
        if row["status"] not in ("pending", "disabled", "active"):
            return {"status": "refused", "reason": "already_applied"}
        requested = row.get("requested_identities") or row["identities"]
        expected = _payload(dict(row, identities=requested))
        if (payload_digest({k: payload.get(k) for k in expected}) != row.get("payload_sha256")
                or any(payload.get(k) != v for k, v in expected.items())):
            return {"status": "refused", "reason": "payload_changed"}
        problems, files = inspect_argv(row["argv"])
        now = identities(files) if not problems else None
        if now is None or [shown(i) for i in now] != [shown(i) for i in requested]:
            row["card_open"] = False
            _write(data)
            return {"status": "refused", "reason": "changed_since_request"}
        replaced = row.get("replaces")
        if replaced:
            data["hooks"] = [r for r in data["hooks"] if r["id"] != replaced]
        row.pop("requested_identities", None)
        row["identities"] = now
        row["status"] = "active"
        row["card_open"] = False
        row["approved_task_id"] = task_id
        row["approved_by"] = str(getattr(task, "decided_by", "") or "owner")
        row["approved_at"] = time.time()
        _write(data)
    _audit(orch, row["approved_by"], "hook.activate",
           f"hook {row['id']} on {row['event']} approved (task {task_id}): {command_line(row['argv'])[:200]}",
           {"hook": row["id"], "event": row["event"], "task_id": task_id, "replaced": replaced,
            "guard": row["guard"], "binding": binding_digest(row)})
    return {"status": "ok", "hook": row["id"]}


def disable(orch: Any, ident: str, *, actor: str = "owner") -> dict:
    with _LOCK:
        data = _read()
        row = _find(data, ident)
        if row is None:
            raise HookRefused("not_found")
        row["status"] = "disabled" if row["status"] != "pending" else "pending"
        row["card_open"] = False   # an open card for it no longer applies
        row.pop("requested_identities", None)
        row["disabled_at"] = time.time()
        _write(data)
    _audit(orch, actor, "hook.disable", f"hook {ident} switched off", {"hook": ident})
    return {"disabled": ident, "hook": public(row)}


def remove(orch: Any, ident: str, *, actor: str = "owner") -> dict:
    with _LOCK:
        data = _read()
        row = _find(data, ident)
        if row is None:
            raise HookRefused("not_found")
        data["hooks"] = [r for r in data["hooks"] if r["id"] != ident]
        _write(data)
    _audit(orch, actor, "hook.remove", f"hook {ident} removed", {"hook": ident, "event": row["event"]})
    return {"removed": ident}


def receipt_matches(action: Any) -> bool:
    """The kernel's ``approval_check`` for ``hook.exec``: the receipt names an active hook,
    the task that activated it and the binding it was approved with, **and the durable
    approval queue holds a person's acceptance of exactly that binding**
    (:func:`approval_verified`) — the row in ``hooks.json`` is never its own proof."""
    payload = getattr(action, "payload", None)
    if getattr(action, "kind", None) != "hook.exec" or not isinstance(payload, dict):
        return False
    try:
        row = get(str(payload.get("hook_id") or ""))
    except HookRefused:
        return False
    return (row is not None and row["status"] == "active"
            and type(payload.get("approved_task_id")) is int
            and payload["approved_task_id"] == row.get("approved_task_id")
            and payload.get("binding_sha256") == binding_digest(row)
            and approval_verified(row))


def _audit(orch: Any, actor: str, action: str, why: str, metadata: dict) -> None:
    if orch is None:
        from agents.core.app_state import get_orch

        orch = get_orch()
    audit = getattr(orch, "intent_log", None)
    if callable(getattr(audit, "record", None)):
        try:
            audit.record(actor=actor, action=action, why=why, cause="hooks", metadata=metadata)
        except Exception:  # noqa: BLE001 — a projection
            logger.warning("hook intent projection failed", exc_info=True)


__all__ = [
    "APPROVAL_KIND", "BLOCKING_EVENTS", "EVENTS", "HookRefused", "active_for", "all_hooks",
    "apply_approved", "approval_verified", "binding_digest", "catalogue", "disable", "get", "inspect_argv",
    "is_store_path", "public", "StoreUnreadable",
    "receipt_matches", "remove", "request_define", "request_enable", "run_dir",
]
