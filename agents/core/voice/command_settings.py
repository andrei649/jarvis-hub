"""command_settings.py — the one writer of ``voice.tts_command`` / ``voice.stt_command`` (H613).

A command provider makes the hub run a program the owner names, so its setting is a
host-exec capability and is written only here:

* the two rows are ROUTE_ONLY (``settings_db.ROUTE_ONLY``): a generic settings write, an
  import, ``nerva config set``, an export, a reset and an undo leave them alone;
* ``POST /api/admin/voice/commands`` (admin-only, same-origin JSON) is the only entry.
  **Setting or changing** a command is a request to the approval queue's irreversible
  tier (H262, kind ``settings.voice_command``): the card names every file that runs (the
  program and, for an interpreter, its script — each with its size and sha256), the full
  argv, the side and who it runs as, and nothing is written until a *human* accepts it
  (``irreversible.execute`` refuses a machine decider). **Clearing** one only takes a
  capability away, so it applies at once and is audited — only on an explicit
  ``{"clear": true}``;
* :func:`request` records what the card shows, server-side, keyed by the task id
  (``<data>/voice/command_requests.json``). :func:`apply_approved` writes only that: it
  refuses a task whose payload differs from the record (an ``edit`` that swapped the
  program), a task with no record (one submitted straight to the queue), and any
  decision but a plain accept. It validates the command again, requires the arming flag,
  refuses in safe mode, and refuses when a bound file or the stored value changed since
  the request (``changed_since_request``) — the owner asks again;
* every spawn re-checks it all (``local_providers.command_ready``), once more after the
  concurrency slot is held.

Not closed here: ``settings.voice_command`` is not a registered Action Kernel kind
(``agents/core/kernel/registry.py`` is protected). With ``JARVIS_TASK_MEDIATION`` at
``enforce`` or ``hold`` the queue refuses it, so setting a command answers 503 until the
owner adds the registry entry; clearing still works.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import local_providers as lp

logger = logging.getLogger("jarvis.voice.commands")

APPROVAL_KIND = "settings.voice_command"
KEYS = {"tts": "tts_command", "stt": "stt_command"}
NOTE = ("Runs on this machine as the hub's user, with that user's permissions; what it does cannot be "
        "undone by the hub. Nerva reads back only the audio (or the transcript) it produces in a private "
        "run directory. Approving binds these exact files (the program and, for an interpreter, its "
        "script): changing, replacing or upgrading any of them needs approving again. What they load "
        "is not bound: libraries, and the modules a script imports (a Python script never imports from "
        "its own folder or the user's site-packages).")
#: The decisions that apply a card: a plain accept. An edit replaces the payload, so it
#: never applies one (the owner asks again from the settings block).
PLAIN_ACCEPT = frozenset({"accept", "approve"})
#: The payload keys a card's record pins: everything the card shows or the write uses.
RECORDED_KEYS = ("side", "argv", "fingerprint", "exe_identity", "bound", "before_fingerprint", "preview")
#: The most requests kept on record (the oldest go first).
MAX_RECORDS = 64
_records_lock = threading.Lock()


def _records_path() -> Path:
    from agents.core.paths import data_path

    return data_path("voice", "command_requests.json")


def _load_records() -> dict[str, dict]:
    try:
        raw = json.loads(_records_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}


def _save_records(records: dict[str, dict]) -> None:
    path = _records_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _record_request(task_id: int, payload: dict) -> bool:
    """Keep what the card for *task_id* shows (the one thing :func:`apply_approved` writes)."""
    try:
        with _records_lock:
            records = _load_records()
            records[str(int(task_id))] = {**{key: payload.get(key) for key in RECORDED_KEYS}, "at": time.time()}
            for old in sorted(records, key=lambda k: records[k].get("at") or 0)[:-MAX_RECORDS]:
                records.pop(old, None)
            _save_records(records)
        return True
    except (OSError, TypeError, ValueError):
        logger.warning("could not record a voice command request (task %s); its card cannot be applied", task_id)
        return False


def _recorded_request(task_id: Any) -> dict | None:
    try:
        key = str(int(task_id))
    except (TypeError, ValueError):
        return None
    with _records_lock:
        return _load_records().get(key)


def _forget_request(task_id: Any) -> None:
    try:
        with _records_lock:
            records = _load_records()
            if records.pop(str(int(task_id)), None) is not None:
                _save_records(records)
    except (OSError, TypeError, ValueError):
        logger.warning("could not drop the record of voice command request %s", task_id)


def _refused(reason: str, **extra: Any) -> dict:
    return {"status": "refused", "reason": reason, **extra}


def _runs_as() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no name for this uid
        return "the hub's user"


def _fingerprint(argv: list[str]) -> str:
    from agents.core.environments.terminal_contract import argv_fingerprint

    return argv_fingerprint(argv)


def _shown(exe: Any, fingerprint: str) -> str:
    """The program and the argv fingerprint as an audit row carries them: the full digest
    reads as a secret to the row's redaction, so its first 16 hex digits name it."""
    name = getattr(exe, "name", str(exe))
    return f"program {name} (exe={exe}) · argv sha256 {str(fingerprint)[:16]}"


def _pending_for(orch: Any, side: str) -> list[Any]:
    from agents.core.autonomy import irreversible

    return [task for task in irreversible.pending(orch, APPROVAL_KIND)
            if isinstance(getattr(task, "payload", None), dict) and task.payload.get("side") == side]


def status(orch: Any) -> dict[str, Any]:
    """Per side: configured, armed, safe mode, ready (and why not), the approved program
    and fingerprint, and the request waiting for a decision."""
    from agents.core import safe_mode

    sides = {}
    for side in lp.SIDES:
        value = lp.stored_command(side)
        ready = lp.command_ready(side)
        waiting = _pending_for(orch, side)
        exe = value.get("exe") if isinstance(value.get("exe"), dict) else {}
        sides[side] = {
            "configured": bool(value.get("argv")), "armed": lp.armed(), "safe_mode": safe_mode.enabled(),
            "ready": ready.ok, "reason": ready.reason, "problems": list(ready.problems),
            "argv": value.get("argv") or None, "exe": exe.get("path"), "fingerprint": value.get("fingerprint"),
            "files": [lp.shown_file(b) for b in (value.get("bound") or []) if isinstance(b, dict)],
            "approved_task": value.get("approved_task"),
            "pending_task": int(waiting[0].id) if waiting else None,
        }
    return {"sides": sides, "arm_env": lp.ARM_ENV, "kind": APPROVAL_KIND}


async def _audit(orch: Any, preview: str, action: str) -> None:
    from agents.core.security.types import SecurityEvent, SecurityEventType

    audit = getattr(orch, "audit", None) if orch is not None else None
    if audit is None:
        return
    try:
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
            content_preview=preview, action_taken=action))
    except Exception:  # noqa: BLE001 — the write stands; a lost audit row is logged
        logger.warning("failed to audit a voice command change (%s)", action)


def _intent(orch: Any, action: str, why: str, metadata: dict) -> None:
    log = getattr(orch, "intent_log", None) if orch is not None else None
    if log is None or not callable(getattr(log, "record", None)):
        return
    try:
        log.record(actor="owner", action=action, why=why, cause="voice.commands", metadata=metadata)
    except Exception:  # noqa: BLE001 — best effort; the audit row is the record
        logger.warning("voice command change not recorded in the intent log", exc_info=True)


async def clear(orch: Any, side: str) -> tuple[int, dict]:
    """Forget the *side* command now (narrowing never waits); audited."""
    from agents.core.settings_db import put_category

    before = lp.stored_command(side)
    await asyncio.to_thread(put_category, "voice", {KEYS[side]: {}})
    await _audit(orch, f"voice.{KEYS[side]} cleared (was argv sha256 {str(before.get('fingerprint') or 'none')[:16]})",
                 "voice_command_cleared")
    _intent(orch, "voice.command.clear", f"the owner cleared the {side} command provider",
            {"side": side, "fingerprint": before.get("fingerprint")})
    return 200, {"ok": True, "side": side, "cleared": True}


def _marked_argv(argv: list[str]) -> list[dict]:
    """The argv as the card lists it: each element, placeholders marked."""
    return [{"value": item, "placeholder": item in lp.PLACEHOLDERS} for item in argv]


async def request(orch: Any, side: str, argv: list[str], *, dry_run: bool = False) -> tuple[int, dict]:
    """Ask for *argv* as the *side* command: 422 invalid, 409 unarmed / safe mode / another
    request waiting, 200 on a dry run, 202 with the waiting task, 503 when the approval
    queue cannot take it. Nothing is written here."""
    from agents.core import safe_mode
    from agents.core.autonomy import irreversible

    problems, exe = lp.validate_command(argv, side)
    files = lp.bound_files(argv, side) if not problems else None
    if problems or exe is None or not files:
        return 422, {"error": "invalid_command", "problems": problems or ["the program cannot be resolved"]}
    if not lp.armed():
        return 409, {"error": "not_armed", "detail": f"set {lp.ARM_ENV}=1 in the hub's environment and restart"}
    if safe_mode.enabled():
        safe_mode.note("voice_commands")
        return 409, {"error": "safe_mode", "detail": "command providers are off in safe mode"}
    bound = await asyncio.to_thread(lp.bound_identities, files)
    if bound is None:
        return 422, {"error": "invalid_command",
                     "problems": ["a bound file cannot be read whole (missing, over 64 MiB, or changing)"]}
    identity = bound[0]
    fingerprint = _fingerprint(argv)
    timeout = lp.timeout_for(lp.TTS_TIMEOUT_S if side == "tts" else lp.STT_TIMEOUT_S)
    if dry_run:
        return 200, {"ok": True, "dry_run": True, "side": side, "exe": str(exe), "fingerprint": fingerprint,
                     "files": [lp.shown_file(b) for b in bound], "timeout_s": timeout}
    for task in await asyncio.to_thread(_pending_for, orch, side):
        if task.payload.get("fingerprint") == fingerprint:
            if task.payload.get("bound") != bound:     # verify round, N2: that card cannot apply
                return 409, {"error": "request_stale", "pending": int(task.id),
                             "detail": "the waiting request was made before the program or its script "
                                       "changed: decline it in the Decision Inbox, then ask again"}
            return 202, {"pending": int(task.id), "existing": True, "side": side}
        return 409, {"error": "request_waiting", "pending": int(task.id),
                     "detail": "another request for this command is waiting in the Decision Inbox: "
                               "decide it first"}
    before = lp.stored_command(side).get("fingerprint")
    preview = {"kind": side, "program": str(exe), "files": [lp.shown_file(b) for b in bound],
               "argv": list(argv), "argv_marked": _marked_argv(list(argv)), "side": side,
               "runs_as": _runs_as(), "timeout_s": timeout, "note": NOTE}
    payload = {"side": side, "argv": list(argv), "fingerprint": fingerprint, "exe_identity": identity,
               "bound": bound, "before_fingerprint": before}
    queued = irreversible.enqueue(
        orch, APPROVAL_KIND,
        title=f"Run {exe} as the {side.upper()} voice provider",
        payload=payload,
        preview=preview,
    )
    if "refused" in queued:
        return 503, {"error": "approval_unavailable", "reason": queued["refused"],
                     "detail": "setting a command provider needs the approval queue (with "
                               "JARVIS_TASK_MEDIATION at enforce or hold it refuses this kind until the "
                               "owner registers it); nothing was written"}
    await asyncio.to_thread(_record_request, queued["pending"], {**payload, "preview": preview})
    await _audit(orch, f"voice.{KEYS[side]} change sent to approval (task {queued['pending']}): "
                       f"{_shown(exe, fingerprint)}", "voice_command_requested")
    return 202, {"pending": queued["pending"], "side": side, "exe": str(exe), "fingerprint": fingerprint}


def _canonical(value: Any) -> str:
    """A value as JSON (a record read back from disk compares equal to the live payload)."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


async def apply_approved(task: Any, orch: Any) -> dict:
    """Write a ``settings.voice_command`` task a human accepted (``irreversible.execute``
    checked who decided): only as asked, only when nothing changed since."""
    from agents.core import safe_mode
    from agents.core.settings_db import put_category

    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decision == "edit":                   # an edit replaces the payload: ask again instead
        return _refused("edit_not_supported")
    if decision not in PLAIN_ACCEPT:
        return _refused("decision_not_accept")
    payload = task.payload
    task_id = getattr(task, "id", None)
    record = await asyncio.to_thread(_recorded_request, task_id)
    if record is None:                       # not a card request() queued (POST /autonomy/tasks)
        return _refused("not_requested", detail="request the command from Settings → Voice → Command providers")
    if any(_canonical(payload.get(key)) != _canonical(record.get(key)) for key in RECORDED_KEYS):
        return _refused("payload_changed", detail="the task no longer matches the card that was requested: ask again")
    side, argv = payload.get("side"), payload.get("argv")
    if side not in KEYS or not isinstance(argv, list):
        return _refused("payload_invalid")
    problems, exe = lp.validate_command(argv, side)
    files = lp.bound_files(argv, side) if not problems else None
    if problems or exe is None or not files:
        return _refused("invalid_command", problems=problems)
    if not lp.armed():
        return _refused("not_armed")
    if safe_mode.enabled():
        safe_mode.note("voice_commands")
        return _refused("safe_mode")
    fingerprint = _fingerprint(argv)
    bound = await asyncio.to_thread(lp.bound_identities, files)
    if (fingerprint != payload.get("fingerprint") or bound is None or bound != payload.get("bound")
            or bound[0] != payload.get("exe_identity")):
        return _refused("changed_since_request", detail="a file the command runs changed since the request: ask again")
    if lp.stored_command(side).get("fingerprint") != payload.get("before_fingerprint"):
        return _refused("changed_since_request", detail="the command changed since the request: ask again")
    identity = bound[0]
    decided_by = str(getattr(task, "decided_by", "") or "")
    await asyncio.to_thread(put_category, "voice", {KEYS[side]: {
        "argv": list(argv), "exe": identity, "bound": bound, "fingerprint": fingerprint,
        "approved_task": task_id, "approved_at": time.time()}})
    await asyncio.to_thread(_forget_request, task_id)
    await _audit(orch, f"voice.{KEYS[side]} approved (task {task_id} by {decided_by}): "
                       f"{_shown(exe, fingerprint)}", "voice_command_approved")
    _intent(orch, "voice.command.set", f"the owner approved {exe} as the {side} command provider",
            {"side": side, "exe": str(exe), "fingerprint": fingerprint, "task": task_id})
    return {"status": "ok", "kind": APPROVAL_KIND, "side": side, "fingerprint": fingerprint}


__all__ = ["APPROVAL_KIND", "KEYS", "apply_approved", "clear", "request", "status"]
