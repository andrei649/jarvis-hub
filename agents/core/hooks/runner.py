"""G17 — running an owner hook, and the two entry points the hub calls.

**One run** (:func:`run_hook`) is governed end to end, and every refusal is a named reason:

1. **off states** — ``JARVIS_HOOKS`` (default on) is the owner's switch for every hook,
   safe mode runs none (the ``owner_hooks`` layer), the emergency stop runs none. In an off
   state *nothing runs and nothing is blocked*, not even by a guard (:data:`OFF_STATES`);
2. the hub must have an **admin credential**: on a box that never had one, the hub trusts
   any local process as the owner, so a hook could decide approval cards over loopback.
   Hooks refuse to run there (``admin_credential_required``), and defining one is refused;
3. the hook must still be ``active`` and its files must still have the content the owner
   approved (``changed_since_approval`` otherwise; re-hashed when a file's stat changed);
4. **the durable approval queue must hold a person's acceptance of this exact hook**
   (:func:`agents.core.hooks.store.approval_verified`): ``hooks.json`` is never its own
   proof, so a row any other writer put there is ``not_approved`` and does not run (and
   blocks nothing). This is checked whether or not the Action Kernel is on;
5. with the Action Kernel on (``JARVIS_ACTION_KERNEL``), the run also crosses it as
   ``hook.exec`` at risk tier 3, with a receipt naming the hook, the task that activated it
   and its binding digest. The kernel grants it only through that receipt, re-verified
   against the queue (:func:`agents.core.hooks.store.receipt_matches`), and its kill
   switch, plan mode and policy mode ``off`` refuse it. **With the kernel off (the default)
   a run does not cross the kernel**: checks 1-4 are made directly;
6. the program runs through the governed local host transport
   (:class:`agents.core.environments.local_transport.LocalHostTransport`) in its own
   process group: the argv verbatim (no shell, no interpolation), the hardline denylist
   again, a private working directory (``<data>/hooks/run``), an environment scrubbed of
   every secret-looking variable, the hook's timeout, and output capped at 8 KB. The whole
   group is killed at the timeout, and while it runs it is killed as soon as hooks are
   switched off, safe mode or the emergency stop comes on, or the hook is switched off or
   removed. **The event is one JSON object on stdin**; a tool call's arguments are cut to
   size and masked with the approval events' scanners first.

**The wire protocol** follows Hermes's shell hooks so scripts move between the two:
stdin carries ``hook_event_name`` (the Hermes name, e.g. ``pre_tool_call``), ``event`` (the
Nerva name), ``tool_name``, ``tool_input`` (``tool.before`` only), ``session_id``, ``cwd`` and
``extra``. For ``tool.before`` a hook blocks the call with exit code 2, or with
``{"action": "block", "message": …}`` / ``{"decision": "block", "reason": …}`` on stdout.
**Nothing else is honoured**: ``allow``/``approve`` and ``modify`` directives are recorded
as ignored, so a hook can never turn a refusal into a run or change a call's arguments, and
it runs *before* the approval queue and the kernel judge the call, which still decide
everything they decided before. For every other event, nothing a hook prints is read.

**Failure.** A hook that fails (refused for a reason that is not an off state, timed out,
crashed, exited with neither 0 nor 2, printed something that is not a JSON object, or ran out
of the per-call budget of :data:`TOOL_BEFORE_BUDGET_S`) **blocks the call when the owner
marked it a guard** (fail closed) and lets it through otherwise (fail open). A hook store
that cannot be read blocks every tool call, since its guards cannot run. Either way the run
is audited with its outcome. A block reason is masked, and the model sees it fenced as
untrusted text.

**Audit.** Every run lands in the intent log (``hook.run``, actor ``hook:<id>``) and in a
bounded in-memory list the HUD and ``nerva hooks list`` show.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import store

logger = logging.getLogger("jarvis.hooks.runner")

OUTPUT_CAP_BYTES = 8_000
MAX_STDIN_BYTES = 64 * 1024
MESSAGE_CHARS = 400
EXCERPT_CHARS = 300
MAX_CONCURRENT = 4
MAX_PENDING_OBSERVERS = 32
#: The most wall-clock time all ``tool.before`` hooks together may take for one tool call.
TOOL_BEFORE_BUDGET_S = 60
#: How often a running hook is checked against a switch-off, safe mode or the emergency stop.
STOP_POLL_S = 0.5
#: Characters of one string in ``tool_input`` kept (before masking), and of all of them.
INPUT_STRING_CHARS = 16_000
INPUT_TOTAL_CHARS = 48_000
#: Refusals that mean "hooks are off here": nothing runs and nothing is blocked, not even
#: by a guard. Every other refusal is a failure (a guard blocks on it).
OFF_STATES = frozenset({"hooks_switched_off", "safe_mode", "kill_switch_engaged", "not_approved",
                        "hook_switched_off"})
RUN_LOG_SIZE = 200
BLOCK_EXIT_CODE = 2
DEFAULT_BLOCK_MESSAGE = "Blocked by an owner hook."

_RUNS: collections.deque = collections.deque(maxlen=RUN_LOG_SIZE)
_RUNS_LOCK = threading.Lock()
_SLOTS: dict[int, asyncio.Semaphore] = {}
_PENDING: set[asyncio.Task] = set()
_STATE = {"loop": None, "dropped": 0}
_HASH_CACHE: dict[tuple, str] = {}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


# ── seams (tests and the action-auth matrix replace these) ──────────────────────

def admin_credential_configured() -> bool:
    """Whether the hub has an admin credential (``agents.web._admin_configured``). With no
    hub loaded (a CLI process, a bare test) the answer is no: hooks never run there."""
    web = sys.modules.get("agents.web")
    probe = getattr(web, "_admin_configured", None)
    try:
        return bool(probe()) if callable(probe) else False
    except Exception:  # noqa: BLE001 — cannot tell: refuse
        return False


def kernel_for(orch: Any):
    """The bound kernel (``make_action_kernel``), or None when no policy is reachable."""
    from agents.core.kernel.binding import make_action_kernel

    return make_action_kernel(orch)


def transport_for(timeout_s: int):
    from agents.core.environments.local_transport import LocalHostTransport

    return LocalHostTransport([store.run_dir()], default_timeout=timeout_s,
                              max_timeout=store.TIMEOUT_CEILING_S, max_output=OUTPUT_CAP_BYTES)


def _halted(orch: Any) -> bool:
    switch = getattr(orch, "kill_switch", None)
    halted = getattr(switch, "is_halted", None)
    try:
        return bool(callable(halted) and halted("global"))
    except Exception:  # noqa: BLE001 — a stop that cannot be read is treated as engaged
        return True


def _off_state(orch: Any) -> str | None:
    """Why no hook may run at all right now (nothing runs, nothing is blocked), or None."""
    from agents.core import safe_mode

    if not store.hooks_switched_on():
        return "hooks_switched_off"
    if safe_mode.enabled():
        safe_mode.note("owner_hooks")
        return "safe_mode"
    if _halted(orch):
        return "kill_switch_engaged"
    return None


def _stop_reason(row: dict, orch: Any) -> str | None:
    """Why a hook already running must be stopped now (its process group is killed)."""
    try:
        off = _off_state(orch)
        if off is not None:
            return off
        now = store.get(row["id"])
        if now is None or now.get("status") != "active":
            return "hook_switched_off"
    except Exception:  # noqa: BLE001 — cannot tell: keep running to its own timeout
        logger.debug("hook stop check failed", exc_info=True)
    return None


def _orch(orch: Any = None) -> Any:
    if orch is not None:
        return orch
    from agents.core.app_state import get_orch

    return get_orch()


# ── checks before a run ─────────────────────────────────────────────────────────

def _file_unchanged(identity: dict) -> bool:
    """Whether the bound file still has the approved content. The digest is recomputed
    whenever the file's stat (including ctime, which no one can set) changed."""
    from agents.core.voice.local_providers import file_identity

    path = str(identity.get("path") or "")
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    key = (path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    digest = _HASH_CACHE.get(key)
    if digest is None:
        now = file_identity(Path(path))
        if now is None:
            return False
        digest = now["sha256"]
        if len(_HASH_CACHE) > 256:
            _HASH_CACHE.clear()
        _HASH_CACHE[key] = digest
    return digest == identity.get("sha256")


def binding_current(row: dict) -> bool:
    """The argv still resolves to the bound files and each has its approved content."""
    problems, files = store.inspect_argv(row["argv"])
    if problems or [str(f) for f in files] != [i.get("path") for i in row["identities"]]:
        return False
    return all(_file_unchanged(identity) for identity in row["identities"])


def _gate(row: dict, orch: Any) -> str | None:
    """Why this run may not happen, or None. Never raises. A reason in :data:`OFF_STATES`
    means the hook is not running here at all; any other is a failure."""
    try:
        off = _off_state(orch)
        if off is not None:
            return off
        if not admin_credential_configured():
            return "admin_credential_required"
        if not binding_current(row):
            return "changed_since_approval"
        # Kernel on or off: the durable approval queue must hold a person's acceptance of
        # this exact binding. A row that only hooks.json vouches for is not an owner hook.
        if not store.approval_verified(row, orch):
            return "not_approved"
        return _kernel_gate(row, orch)
    except Exception:  # noqa: BLE001 — a gate that fails, fails closed
        logger.warning("hook gate failed", exc_info=True)
        return "gate_unavailable"


def _kernel_gate(row: dict, orch: Any) -> str | None:
    from agents.core.kernel.flags import kernel_enabled

    if not kernel_enabled():
        return None
    from agents.core.environments.terminal_contract import argv_fingerprint
    from agents.core.kernel import Action, Verdict

    kernel = kernel_for(orch)
    if kernel is None:
        return "governance_unavailable"
    # The origin is "generated" on purpose: what runs is fixed by the owner's approval; the
    # turn's (possibly untrusted) data only reaches the hook as JSON on stdin. A guard must
    # run on exactly the turns that read untrusted content.
    action = Action(kind="hook.exec", agent="owner", title=f"owner hook {row['id']} on {row['event']}",
                    payload={"hook_id": row["id"], "event": row["event"],
                             "argv_sha256": argv_fingerprint(row["argv"]),
                             "binding_sha256": store.binding_digest(row),
                             "approved_task_id": row.get("approved_task_id"),
                             "risk_tier": 3, "reversible": False},
                    origin="generated")
    decision = kernel(action, approval_check=store.receipt_matches)
    if decision.verdict is Verdict.GRANT:
        return None
    return "kernel_" + ("denied" if decision.verdict is Verdict.DENY else "queued")


# ── the payload ────────────────────────────────────────────────────────────────

def _jsonable(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return "…"
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in list(value.items())[:500]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, depth + 1) for v in list(value)[:500]]
    return str(value)


def _masked_input(value: Any) -> Any:
    """A tool call's arguments for a hook's stdin: bounded before it is serialised (strings
    cut to :data:`INPUT_STRING_CHARS`, :data:`INPUT_TOTAL_CHARS` in all) and every string
    masked with the scanners the approval events use (secrets and catalogue identifiers)."""
    from agents.core.log_catalogue import CatalogueScanner
    from agents.core.security.scanner import SecretScanner

    secret, catalogue = SecretScanner(), CatalogueScanner()
    budget = [INPUT_TOTAL_CHARS]

    def walk(item: Any, depth: int) -> Any:
        if depth > 12:
            return "…"
        if item is None or type(item) in (bool, int, float):
            return item
        if isinstance(item, str):
            if budget[0] <= 0:
                return "…"
            cut = item[:min(INPUT_STRING_CHARS, budget[0])]
            budget[0] -= len(cut)
            masked = catalogue.redact(secret.redact(cut))
            return masked + ("…" if len(cut) < len(item) else "")
        if isinstance(item, dict):
            return {str(k)[:200]: walk(v, depth + 1) for k, v in list(item.items())[:500]}
        if isinstance(item, (list, tuple)):
            return [walk(v, depth + 1) for v in list(item)[:500]]
        return walk(str(item), depth)

    return walk(value, 0)


def build_stdin(row: dict, event: str, fields: dict) -> bytes:
    """The one JSON object a hook reads on stdin (the production and the test path)."""
    spec = store.EVENTS[event]
    extra = {k: _jsonable(v) for k, v in fields.items()
             if k in spec["fields"] and k not in ("tool_name", "tool_input", "session_id")}
    body = {
        "hook_event_name": spec["hermes"], "event": event,
        "tool_name": fields.get("tool_name"),
        "tool_input": _masked_input(fields.get("tool_input")) if event == "tool.before" else None,
        "session_id": str(fields.get("session_id") or ""),
        "cwd": str(store.run_dir()), "extra": extra,
        "nerva": {"hook_id": row["id"], "occurred_at": round(time.time(), 3), "guard": row["guard"]},
    }
    data = json.dumps(body, ensure_ascii=False, default=str, allow_nan=False).encode("utf-8")
    if len(data) > MAX_STDIN_BYTES and body["tool_input"] is not None:
        import hashlib

        raw = json.dumps(body["tool_input"], sort_keys=True, default=str).encode("utf-8")
        body["tool_input"] = {"truncated": True, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        data = json.dumps(body, ensure_ascii=False, default=str, allow_nan=False).encode("utf-8")
    if len(data) > MAX_STDIN_BYTES:
        body["extra"] = {"truncated": True}
        data = json.dumps(body, ensure_ascii=False, default=str, allow_nan=False).encode("utf-8")
    return data


# ── the answer ─────────────────────────────────────────────────────────────────

def _clean(text: Any, limit: int) -> str:
    return _CONTROL.sub(" ", str(text or ""))[:limit].strip()


def _redacted(text: str, limit: int) -> str:
    try:
        from agents.core.security.scanner import SecretScanner

        return _clean(SecretScanner().redact(text[:4 * limit]), limit)
    except Exception:  # noqa: BLE001 — an excerpt we cannot mask is not kept
        return ""


def evaluate(event: str, result: dict) -> dict:
    """What a run's result means: ``{"block", "message", "error", "ignored", "exit_code"}``.
    ``error`` is a failure reason (fail closed for a guard, open otherwise)."""
    out = {"block": False, "message": None, "error": None, "ignored": None,
           "exit_code": result.get("exit_code")}
    if "exit_code" not in result:                      # refused before a process existed
        out["error"] = str(result.get("reason") or "spawn_failed")
        return out
    if result.get("reason") == "timeout":
        out["error"] = "timeout"
        return out
    code = result.get("exit_code")
    stdout = str(result.get("stdout") or "").strip()
    directive = None
    if stdout:
        if result.get("truncated"):
            out["error"] = "output_too_large"
        else:
            try:
                parsed = json.loads(stdout)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                directive = parsed
            else:
                out["error"] = "unparseable_stdout"
    if event not in store.BLOCKING_EVENTS:
        if directive:
            out["ignored"] = "observer_output"
        if code not in (0, None) and out["error"] is None:
            out["error"] = f"exit_{code}"
        return out
    verb = None
    if directive is not None:
        verb = str(directive.get("action") or directive.get("decision") or "").strip().lower() or None
    if code == BLOCK_EXIT_CODE or verb == "block":
        message = None
        if directive is not None:
            message = directive.get("message") or directive.get("reason")
        if not message and code == BLOCK_EXIT_CODE:
            message = _redacted(str(result.get("stderr") or ""), MESSAGE_CHARS)
        out["block"] = True
        out["error"] = None
        out["message"] = _redacted(str(message or ""), MESSAGE_CHARS) or DEFAULT_BLOCK_MESSAGE
        return out
    if verb is not None:
        # allow / approve / ask / modify / anything else: a hook only ever blocks.
        out["ignored"] = verb if verb in ("allow", "approve", "ask", "modify", "continue") else "unknown"
    if code not in (0, None) and out["error"] is None:
        out["error"] = f"exit_{code}"
    return out


# ── one run ────────────────────────────────────────────────────────────────────

def _slot(blocking: bool) -> asyncio.Semaphore:
    """``tool.before`` and observers each have their own slots, so observers never make a
    tool call wait."""
    loop = asyncio.get_running_loop()
    key = (id(loop), blocking)
    if key not in _SLOTS:
        for stale in [k for k in _SLOTS if k[0] != id(loop)]:
            del _SLOTS[stale]
        _SLOTS[key] = asyncio.Semaphore(MAX_CONCURRENT)
    return _SLOTS[key]


async def _spawn(row: dict, stdin: bytes, timeout_s: int, orch: Any) -> dict:
    """Run the program in its own process group, and kill that whole group when its
    timeout passes, or when hooks are switched off, safe mode or the emergency stop comes on,
    or the hook itself is switched off or removed, while it runs."""
    job = asyncio.ensure_future(transport_for(timeout_s).run(
        list(row["argv"]), cwd=str(store.run_dir()), timeout=timeout_s, stdin_data=stdin,
        process_group=True))
    try:
        while True:
            done, _ = await asyncio.wait({job}, timeout=STOP_POLL_S)
            if done:
                return job.result()
            reason = _stop_reason(row, orch)
            if reason is not None:
                job.cancel()
                await asyncio.wait({job})
                return {"ok": False, "reason": reason, "exit_code": -1, "stopped": True}
    except asyncio.CancelledError:
        job.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.wait({job})
        raise


def _record(orch: Any, row: dict, event: str, run: dict) -> None:
    entry = {"at": round(time.time(), 3), "hook": row["id"], "name": row.get("name") or "", "event": event,
             **{k: run.get(k) for k in ("outcome", "reason", "exit_code", "duration_ms", "blocked",
                                        "fail_open", "ignored", "tool", "test")}}
    with _RUNS_LOCK:
        _RUNS.append(entry)
    store._audit(orch, f"hook:{row['id']}", "hook.run",
                 f"hook {row['id']} on {event}: {run.get('outcome')}"
                 + (f" ({run.get('reason')})" if run.get("reason") else ""),
                 {k: v for k, v in entry.items() if k != "at"})


def recent_runs(limit: int = 50, hook: str | None = None) -> list[dict]:
    with _RUNS_LOCK:
        rows = [dict(r) for r in _RUNS if hook is None or r["hook"] == hook]
    return rows[-max(1, min(int(limit), RUN_LOG_SIZE)):]


async def run_hook(row: dict, event: str, fields: dict, *, orch: Any = None, test: bool = False,
                   timeout_s: int | None = None) -> dict:
    """Run one hook once and say what it meant. Never raises; always audited."""
    orch = _orch(orch)
    started = time.monotonic()
    run: dict = {"outcome": "ok", "reason": None, "exit_code": None, "blocked": False, "fail_open": False,
                 "ignored": None, "tool": fields.get("tool_name") if event.startswith("tool.") else None,
                 "test": test, "message": None}
    result: dict = {}
    try:
        refusal = _gate(row, orch)
        if refusal is not None:
            result = {"ok": False, "reason": refusal}
        else:
            stdin = build_stdin(row, event, fields)
            limit = row["timeout_s"] if timeout_s is None else max(1, min(int(timeout_s), row["timeout_s"]))
            async with _slot(event in store.BLOCKING_EVENTS):
                result = await _spawn(row, stdin, limit, orch)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — a crash in here is a failed run, never the turn's
        logger.warning("hook run failed", exc_info=True)
        result = {"ok": False, "reason": "runner_error"}
    off = result.get("reason") if result.get("reason") in OFF_STATES else None
    meaning = evaluate(event, result) if off is None else {"block": False, "error": None, "ignored": None,
                                                           "exit_code": result.get("exit_code")}
    run["exit_code"] = meaning["exit_code"]
    run["ignored"] = meaning["ignored"]
    if off is not None:
        # Hooks are off here (or this row is not an approved hook): nothing ran to the end
        # and nothing is blocked, not even by a guard.
        run.update(outcome="stopped" if result.get("stopped") else "skipped", reason=off)
    elif meaning["block"]:
        run.update(outcome="blocked", blocked=True, message=meaning["message"])
    elif meaning["error"] is not None:
        refused = "exit_code" not in result
        run.update(outcome="refused" if refused else ("timeout" if meaning["error"] == "timeout" else "failed"),
                   reason=meaning["error"])
        if event in store.BLOCKING_EVENTS:
            if row["guard"]:
                run.update(blocked=True, message=f"Owner hook {row.get('name') or row['id']} failed closed: "
                                                 f"{meaning['error']}")
            else:
                run["fail_open"] = True
    run["duration_ms"] = int((time.monotonic() - started) * 1000)
    if test:
        run["stdout"] = _redacted(str(result.get("stdout") or ""), EXCERPT_CHARS * 4)
        run["stderr"] = _redacted(str(result.get("stderr") or ""), EXCERPT_CHARS * 4)
        run["stdin"] = json.loads(build_stdin(row, event, fields).decode("utf-8"))
    _record(orch, row, event, run)
    return run


# ── the entry points ───────────────────────────────────────────────────────────

def _remember_loop() -> None:
    with contextlib.suppress(RuntimeError):
        _STATE["loop"] = asyncio.get_running_loop()


async def before_tool(tool: str, args: Any, *, agent_id: str = "", session_id: str = "",
                      orch: Any = None) -> dict:
    """Run the active ``tool.before`` hooks for *tool*, in order, until one blocks.

    Returns ``{"blocked": bool, "message": str | None, "hook": id | None}``. This can only
    ever *add* a refusal: the call goes on to the approval queue and the kernel exactly as
    before when nothing blocked it."""
    _remember_loop()
    verdict = {"blocked": False, "message": None, "hook": None}
    try:
        rows = store.active_for("tool.before", tool, strict=True)
    except store.StoreUnreadable:
        # A guard the owner set up must not be lost to a corrupt file: fail closed.
        store._audit(_orch(orch), "hooks", "hook.store_unreadable",
                     f"the hook store cannot be read; tool call {tool} blocked", {"tool": str(tool)[:100]})
        return {"blocked": True, "hook": None,
                "message": "The owner hook store cannot be read, so its guards cannot run; "
                           "fix or remove <data>/hooks/hooks.json."}
    if not rows:
        return verdict
    fields = {"tool_name": str(tool), "tool_input": args if isinstance(args, dict) else {},
              "agent_id": str(agent_id or ""), "session_id": str(session_id or "")}
    started = time.monotonic()
    for row in rows:
        remaining = TOOL_BEFORE_BUDGET_S - (time.monotonic() - started)
        if remaining < 1:
            if row["guard"]:
                return {"blocked": True, "hook": row["id"],
                        "message": f"Owner hook {row.get('name') or row['id']} failed closed: hook_budget_exceeded"}
            _record(_orch(orch), row, "tool.before", {"outcome": "skipped", "reason": "hook_budget_exceeded",
                                                       "tool": str(tool), "blocked": False})
            continue
        run = await run_hook(row, "tool.before", fields, orch=orch, timeout_s=int(remaining))
        if run["blocked"]:
            return {"blocked": True, "message": run["message"], "hook": row["id"]}
    return verdict


def observe(event: str, **fields: Any) -> int:
    """Hand an event to the active hooks that watch it, without waiting. Safe from any
    thread; never raises. Returns how many runs were scheduled."""
    try:
        if event not in store.EVENTS or event in store.BLOCKING_EVENTS:
            return 0
        _remember_loop()
        rows = store.active_for(event, fields.get("tool_name"))
        if not rows:
            return 0
        clean = {k: v for k, v in fields.items() if k in store.EVENTS[event]["fields"]}
        for key, value in list(clean.items()):
            if isinstance(value, str):
                clean[key] = value[:200]
        loop = _STATE["loop"]
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is None or loop.is_closed():
            _STATE["dropped"] += len(rows)
            return 0
        scheduled = 0
        for row in rows:
            if len(_PENDING) >= MAX_PENDING_OBSERVERS:
                _STATE["dropped"] += 1
                continue

            def spawn(row=row) -> None:
                task = asyncio.get_running_loop().create_task(run_hook(row, event, dict(clean)))
                _PENDING.add(task)
                task.add_done_callback(_PENDING.discard)

            if running is loop:
                spawn()
            else:
                loop.call_soon_threadsafe(spawn)
            scheduled += 1
        return scheduled
    except Exception:  # noqa: BLE001 — observation never breaks what it observes
        logger.debug("hook observation failed", exc_info=True)
        return 0


async def drain(timeout: float | None = None) -> int:
    """Await observer runs in flight (shutdown and tests)."""
    pending = tuple(_PENDING)
    if pending:
        await asyncio.wait(pending, timeout=timeout)
    return len(pending)


def status() -> dict:
    from agents.core import safe_mode
    from agents.core.kernel.flags import kernel_enabled

    blockers = []
    if not store.hooks_switched_on():
        blockers.append("hooks_switched_off")
    if safe_mode.enabled():
        blockers.append("safe_mode")
    if not admin_credential_configured():
        blockers.append("admin_credential_required")
    return {"switched_on": store.hooks_switched_on(), "safe_mode": safe_mode.enabled(),
            "admin_credential": admin_credential_configured(), "kernel": kernel_enabled(),
            "ready": not blockers, "blockers": blockers, "max_timeout_s": store.max_timeout(),
            "dropped_observations": _STATE["dropped"]}


__all__ = ["BLOCK_EXIT_CODE", "before_tool", "build_stdin", "drain", "evaluate", "observe",
           "recent_runs", "run_hook", "status"]
