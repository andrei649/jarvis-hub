#!/usr/bin/env python3
"""coordinator.py — headless supervisor process: coordinator + heartbeat + night
shift, wired for real, no HTTP layer.

``Orchestrator.start_channels()`` already wires the three subsystems the mission
names for the interactive app: ``HeartbeatScheduler.start()``, the autonomy
coordinator's ``loop()`` (which gates a night-window ``max_tier`` — H6.6 — every
tick), and ``SchedulerService.schedule_all()``. This script boots the same real
Orchestrator headlessly (no uvicorn/FastAPI) so those loops can run as their own
OS process, separate from the HTTP app, and attaches a ``RuntimeRunLog`` so each
autonomy-coordinator cycle appends one bounded JSON line an operator or the
morning brief can tail.

Process name deliberately contains "coordinator" (``python scripts/coordinator.py``)
so an external supervisor can find it with ``pgrep -f coordinator``; recovering
from a killed coordinator is ``scripts/runtime_supervisor.py``'s job, not this
script's — a process cannot un-kill itself.

Env:
  JARVIS_RUNTIME_CYCLE_SECONDS  autonomy-coordinator tick interval (default 20,
                                 floor 15 — AutonomyCoordinator.loop() enforces
                                 the floor itself)
  JARVIS_RUNTIME_LOG            run-log path (default logs/runtime.jsonl)
  JARVIS_RUNTIME_STATE          cycle-state path (default logs/runtime_state.json)
  JARVIS_RUNTIME_FAKE_LLM       1 = boot with a deterministic in-process fake LLM
                                 backend instead of detecting a real one (dev/CI
                                 use, same pattern as scripts/install_smoke.py)
  JARVIS_SAFE_MODE              1 = safe mode (H275), as for the hub; ``--safe-mode``
                                 sets it
  JARVIS_RUNTIME_RESTORE_POLL   seconds between looks for a staged restore (default 2):
                                 when one is staged the coordinator stops its
                                 orchestrator and EXITS with RESTORE_YIELD_EXIT; the
                                 supervisor starts a fresh process at once, which waits
                                 without opening a store until the restore is applied,
                                 cancelled or expired, then builds on the restored files
                                 (H010)
  JARVIS_RUNTIME_RESTORE_GRACE_SECONDS  how long a stage nobody applies keeps it waiting
                                 (default 600); it then runs again and yields when the
                                 hub begins the apply (agents.core.backup)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

logger = logging.getLogger("jarvis.coordinator")

SAFE_MODE_SWITCH = "--safe-mode"


def apply_safe_mode_switch(argv=None) -> bool:
    """H275: ``--safe-mode`` sets ``JARVIS_SAFE_MODE=1`` before the orchestrator is built,
    as ``serve.py --safe-mode`` does for the hub. This process runs the heartbeats, the
    owner jobs and the agents on the hub's data root, so a safe hub beside a normal
    coordinator would still run them (review-H275 F3)."""
    if SAFE_MODE_SWITCH in (sys.argv[1:] if argv is None else argv):
        os.environ.update({"JARVIS_SAFE_MODE": "1"})   # a write, not a read of the environment
        return True
    return False


def _env_float(name: str, default: float, *, minimum: float) -> float:
    from agents.core.env_config import env_float

    return env_float(name, default, minimum=minimum)


async def _build_orchestrator():
    # The coordinator (systemd jarvis-runtime) shares the hub's data root: it loads the
    # same .env files before anything it builds reads config, or its audit rows go
    # unkeyed beside the hub's keyed ones and the shared chain reads as tampered
    # (review-H273e M2). Idempotent: run() has usually loaded already.
    from agents.core.env_provenance import load_hub_env

    load_hub_env()
    from agents.core.config import JarvisConfig
    from agents.core.env_config import env_flag
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator(JarvisConfig())
    if env_flag("JARVIS_RUNTIME_FAKE_LLM"):
        from agents.core.llm.base import LLMBackend
        from scripts.install_smoke import FAKE_BACKEND_NAME, FAKE_MODEL

        class _FakeBackend(LLMBackend):
            async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
                return "ok"

        async def _fake_detect() -> None:
            router = orch.llm_router
            router._backend = _FakeBackend()
            router._backend_name = FAKE_BACKEND_NAME
            router._detected_model = FAKE_MODEL
            router._local_model = FAKE_MODEL
            router._local_available = True
            router._ollama_available = False
            router._cloud_available = False
            router._claude_available = False

        orch.llm_router.detect = _fake_detect
    await orch.load_agents()
    return orch


def _restore_poll_seconds() -> float:
    """How often the coordinator looks for a staged restore (``JARVIS_RUNTIME_RESTORE_POLL``)."""
    return _env_float("JARVIS_RUNTIME_RESTORE_POLL", 2.0, minimum=0.05)


def _install_stop_handlers(stop: asyncio.Event) -> None:
    def _request_stop(*_args) -> None:
        logger.info("coordinator received shutdown signal")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_a: _request_stop())


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


# The exit status of a coordinator that left so a restore can run (EX_TEMPFAIL). The
# supervisor (scripts/runtime_supervisor.py) respawns it at once, without backoff; under a
# bare `Restart=on-failure` it is a failure status, so systemd restarts it too.
RESTORE_YIELD_EXIT = 75


def _open_root_files() -> list[str] | None:
    """The SQLite files (DBs and their -wal/-shm/-journal) under the data root this process
    has open (Linux: ``/proc/self/fd``); None where that cannot be read. The orchestrator's
    stores keep WAL connections that ``Orchestrator.aclose`` does not close (missions,
    permissions, work_runs, jobs, analytics, ambient attention …), several of them
    module-global. Other files (a log the operator pointed under the root) are not what a
    restore corrupts and must not make a fresh process exit forever. The check itself is
    ``backup.open_root_db_files``, which the hub's apply runs too."""
    from agents.core import backup

    return backup.open_root_db_files()


def _exit_process(code: int) -> None:
    """Leave now, without the interpreter's shutdown: threads the orchestrator started are
    not joined, and every file it has open is closed by the kernel. The runtime mark is
    left behind on purpose — its pid is dead once this returns, which is what releases
    the root (``backup.runtime_running_elsewhere``)."""
    for handler in logging.getLogger().handlers:
        with contextlib.suppress(Exception):
            handler.flush()
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(code)


async def run() -> None:
    from agents.core.env_provenance import load_hub_env

    load_hub_env()                    # before the paths and knobs below are read
    from agents.core import backup

    # H010: this process opens the hub's DBs too. It marks the root while it may open
    # them, and gives the root up whenever a restore is staged or being applied
    # (backup.runtime_should_yield). A process that has built an orchestrator never
    # drops its mark (not on a stop, an error or a yield) and never builds a second one: its stores keep SQLite handles that
    # aclose() leaves open, so it stops the channels and EXITS (RESTORE_YIELD_EXIT); the
    # restore waits for its pid to be gone (H010 review r3). The supervisor's fresh process
    # finds the stage before it opens anything, drops its mark (only with no file under
    # the root open — otherwise it exits too), waits, and builds once on the restored
    # files. Marking BEFORE the check: a restore that journals at the same moment either
    # sees this mark (and waits for it to clear) or is seen here.
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    poll = _restore_poll_seconds()
    exiting = False
    # Set before the first store opens (a build that raises halfway may have opened some):
    # from then on the mark is never cleared by this process, whatever way it leaves — a
    # SIGTERM stop, an exception from aclose(), a yield. Its dead (or zombie) pid is what
    # releases the root; clearing it first would let a waiting apply start while this
    # process's SQLite handles are still open (H010 review r4).
    built = False
    try:
        while not stop.is_set():
            backup.mark_runtime()
            if backup.runtime_should_yield():
                held = _open_root_files()
                if held:
                    logger.warning("a restore is staged, and this process still holds %d file(s) "
                                   "under the data root: it exits instead of releasing it",
                                   len(held))
                    exiting = True
                    _exit_process(RESTORE_YIELD_EXIT)
                backup.clear_runtime_mark()
                logger.info("a restore is staged or being applied: the coordinator waits for it")
                while not stop.is_set() and backup.runtime_should_yield():
                    await _sleep_or_stop(stop, poll)
                continue
            if backup.restore_wanted() and backup.note_runtime_resumed():
                logger.warning("a staged restore was not applied within %gs: the coordinator "
                               "runs again and stops when the hub applies it",
                               backup.runtime_restore_grace_seconds())
            built = True
            if not await _run_marked(stop, backup, poll):
                break
            logger.info("coordinator exits to release the data root for the restore; "
                        "the supervisor starts a fresh one")
            exiting = True
            _exit_process(RESTORE_YIELD_EXIT)
    finally:
        if not exiting and not built:
            backup.clear_runtime_mark()


async def _run_marked(stop: asyncio.Event, backup, poll: float) -> bool:
    """Run the orchestrator until *stop* (False) or until a restore wants the root (True).
    After True the caller must exit: this process's stores are not all closed."""
    from agents.core.observability.runtime_log import RuntimeRunLog, default_log_path

    log_path = default_log_path()
    state_path = Path(os.environ.get("JARVIS_RUNTIME_STATE", "logs/runtime_state.json"))
    cycle_seconds = _env_float("JARVIS_RUNTIME_CYCLE_SECONDS", 20.0, minimum=15.0)

    orch = await _build_orchestrator()
    orch.runtime_log = RuntimeRunLog(log_path=log_path, state_path=state_path)
    orch._runtime_settings["system.autonomy_tick"] = cycle_seconds

    logger.info(
        "coordinator starting: cycle=%ss log=%s state=%s",
        cycle_seconds,
        log_path,
        state_path,
    )
    yielded = False
    await orch.start_channels()
    try:
        while not stop.is_set():
            await _sleep_or_stop(stop, poll)
            if not stop.is_set() and await asyncio.to_thread(backup.runtime_should_yield):
                logger.info("a restore is staged: the coordinator stops to release the data root")
                yielded = True
                break
    finally:
        logger.info("coordinator stopping")
        await orch.stop_channels()
        await orch.aclose()
    return yielded


def configure_logging() -> None:
    """stderr logging, through both log redactors (H410): this process runs the
    orchestrator, its channels and its jobs, and wrote every record unredacted."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from agents.core.log import install_redaction

    install_redaction()


def main() -> None:
    apply_safe_mode_switch()
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
