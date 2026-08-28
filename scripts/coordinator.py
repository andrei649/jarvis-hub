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
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

logger = logging.getLogger("jarvis.coordinator")


def _env_float(name: str, default: float, *, minimum: float) -> float:
    from agents.core.env_config import env_float

    return env_float(name, default, minimum=minimum)


async def _build_orchestrator():
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


async def run() -> None:
    import os

    from agents.core.observability.runtime_log import RuntimeRunLog, default_log_path

    log_path = default_log_path()
    state_path = Path(os.environ.get("JARVIS_RUNTIME_STATE", "logs/runtime_state.json"))
    cycle_seconds = _env_float("JARVIS_RUNTIME_CYCLE_SECONDS", 20.0, minimum=15.0)

    orch = await _build_orchestrator()
    orch.runtime_log = RuntimeRunLog(log_path=log_path, state_path=state_path)
    orch._runtime_settings["system.autonomy_tick"] = cycle_seconds

    stop = asyncio.Event()

    def _request_stop(*_args) -> None:
        logger.info("coordinator received shutdown signal")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_a: _request_stop())

    logger.info(
        "coordinator starting: cycle=%ss log=%s state=%s",
        cycle_seconds,
        log_path,
        state_path,
    )
    await orch.start_channels()
    try:
        await stop.wait()
    finally:
        logger.info("coordinator stopping")
        await orch.stop_channels()
        await orch.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
