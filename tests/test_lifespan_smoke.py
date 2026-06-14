"""Lifespan startup/shutdown smoke test — the CLN-2 wiring guard.

Most of the orchestrator's scheduler/autonomy/watcher/channel wiring only runs
inside `web.py`'s `lifespan`, so unit tests never exercise it. The CLN-2
decomposition relocates exactly that code (SchedulerService, AutonomyCoordinator,
…). This test enters the real app lifespan via the TestClient context manager and
asserts the wiring actually fired — so a mis-wired scheduler call or a broken
`start_channels`/`stop_channels`/`aclose` fails here even when every other unit
test stays green.

Attribute paths verified against the live app on 2026-06-13:
  - `orch.channels` is a dict keyed by channel name → {"web", "voice"}.
  - the APScheduler instance lives at `orch.heartbeat_scheduler.scheduler`
    (NOT `orch.scheduler`); ~20 jobs are registered during startup.
  - `/api/status` → 200 with keys {version, agents, status}.
"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def test_lifespan_starts_and_stops_clean():
    from agents import web

    assert web.orch is None, "orchestrator should not exist before startup"
    with TestClient(web.app) as c:
        orch = web.orch
        assert orch is not None, "lifespan startup did not construct the orchestrator"

        # start_channels ran
        assert set(orch.channels) >= {"web", "voice"}, (
            f"expected web+voice channels, got {list(orch.channels)}"
        )

        # the scheduler/digest/log-scan/learning-loop/budget-reset jobs registered
        # (this is the CLN-2 SchedulerService surface; worldview-kg-sync is skipped
        # under JARVIS_TESTING). Locks the exact job wiring the service owns.
        job_ids = {j.id for j in orch.heartbeat_scheduler.scheduler.get_jobs()}
        assert {
            "autonomy-morning-brief", "autonomy-evening-retro",
            "log-scan-quick", "log-scan-hourly", "log-scan-daily",
            "learning-loop-promotions", "autonomy-daily-budget-reset",
        } <= job_ids, f"SchedulerService did not wire its jobs: {sorted(job_ids)}"

        # the app actually serves
        r = c.get("/api/status")
        assert r.status_code == 200
        assert set(r.json()) >= {"version", "agents", "status"}

    # stop_channels + aclose ran and released the singleton
    assert web.orch is None, "lifespan shutdown did not release the orchestrator"
