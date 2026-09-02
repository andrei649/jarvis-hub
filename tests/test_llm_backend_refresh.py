"""A model server started after Jarvis must not stay invisible for the session.

`LLMRouter.detect()` runs once, from `Orchestrator` startup. In a real session
Ollama was refused at boot ("Ollama not available — Howard will fall back to
default backend") and was answering on :11434 from 11:38; nothing ever looked
again, so Howard ran degraded for the remaining two hours against a server that
was up the whole time.

`refresh_availability()` closes that: a cheap periodic probe that escalates to a
full `detect()` only on an actual transition, registered by
`SchedulerService.schedule_llm_backend_refresh` on a 5-minute interval.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.router import LLMRouter  # noqa: E402


class _Router(LLMRouter):
    """A router whose probe answers from a dict instead of the network."""

    def __init__(self, up: dict[str, bool]):
        super().__init__()
        self.up = up
        self.detect_calls = 0
        self.backend_type = "auto"
        self.lm_studio_url = "http://localhost:1234"
        self.ollama_url = "http://localhost:11434"
        self._backend_name = "none"

    async def _check(self, url: str) -> bool:
        return self.up["lm" if "/v1/models" in url else "ol"]

    async def detect(self):
        self.detect_calls += 1
        if self.up["lm"] and self.backend_type in ("auto", "lm-studio"):
            self._backend_name = "lm-studio"
        elif self.up["ol"] and self.backend_type in ("auto", "ollama"):
            self._backend_name = "ollama"
        else:
            self._backend_name = "none"


@pytest.mark.asyncio
async def test_a_backend_that_appears_after_boot_is_picked_up():
    router = _Router({"lm": False, "ol": False})
    await router.detect()
    assert router._backend_name == "none"

    router.up["lm"] = True  # the owner starts LM Studio
    assert await router.refresh_availability() is True
    assert router._backend_name == "lm-studio"


@pytest.mark.asyncio
async def test_a_steady_picture_costs_nothing_beyond_the_probe():
    """The 5-minute cadence must not rebuild the connection pool every pass."""
    router = _Router({"lm": True, "ol": True})
    await router.detect()
    before = router.detect_calls

    for _ in range(12):  # an hour of passes
        assert await router.refresh_availability() is False

    assert router.detect_calls == before


@pytest.mark.asyncio
async def test_a_backend_that_disappears_is_noticed_too():
    router = _Router({"lm": True, "ol": False})
    await router.detect()
    assert router._backend_name == "lm-studio"

    router.up["lm"] = False
    assert await router.refresh_availability() is True
    assert router._backend_name == "none"


@pytest.mark.asyncio
async def test_a_pinned_backend_ignores_the_other_one_coming_up():
    """`backend_type` is an operator pin; the refresh must respect it."""
    router = _Router({"lm": False, "ol": False})
    router.backend_type = "lm-studio"
    await router.detect()

    router.up["ol"] = True
    assert await router.refresh_availability() is False
    assert router._backend_name == "none"

    router.up["lm"] = True
    assert await router.refresh_availability() is True
    assert router._backend_name == "lm-studio"


@pytest.mark.asyncio
async def test_hybrid_sees_ollama_arrive_while_lm_studio_keeps_serving():
    """The exact logged case, on the class that actually runs in production.

    LM Studio was up throughout, so `_backend_name` never changed — a check that
    only watched the primary backend would have reported "nothing changed" and
    left Howard on the fallback model forever.
    """
    from agents.core.llm.hybrid_router import HybridRouter

    router = HybridRouter.__new__(HybridRouter)  # no network, no admin DB
    router.backend_type = "auto"
    router.lm_studio_url = "http://localhost:1234"
    router.ollama_url = "http://localhost:11434"
    router._backend_name = "lm-studio"
    router._ollama_available = False

    assert router._availability_changed(lm_up=True, ol_up=False) is False
    assert router._availability_changed(lm_up=True, ol_up=True) is True


@pytest.mark.asyncio
async def test_the_scheduled_job_never_raises():
    """A failing probe must not take down the scheduler thread."""
    from agents.core.scheduler_service import SchedulerService

    class _Boom:
        async def refresh_availability(self):
            raise RuntimeError("probe exploded")

    class _Orch:
        llm_router = _Boom()

    assert await SchedulerService(_Orch()).run_llm_backend_refresh() == {
        "skipped": True,
        "reason": "probe_failed",
    }


@pytest.mark.asyncio
async def test_the_scheduled_job_degrades_without_a_router():
    from agents.core.scheduler_service import SchedulerService

    class _Orch:
        llm_router = None

    assert await SchedulerService(_Orch()).run_llm_backend_refresh() == {
        "skipped": True,
        "reason": "unavailable",
    }


def test_the_refresh_is_registered_with_every_other_scheduled_job():
    """A job body nothing registers is a job that never runs."""
    from agents.core.scheduler_service import SchedulerService

    registered: list[tuple] = []

    class _Sched:
        def add_job(self, fn, kind, **kw):
            registered.append((kw.get("id"), kind, kw.get("seconds")))

    class _HB:
        scheduler = _Sched()

    class _Orch:
        heartbeat_scheduler = _HB()

    SchedulerService(_Orch()).schedule_llm_backend_refresh()

    assert registered == [("llm-backend-refresh", "interval", 300)]
    assert "schedule_llm_backend_refresh" in SchedulerService.schedule_all.__code__.co_names
