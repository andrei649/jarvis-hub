"""O26-P2.2 — LivingMemory gets a real turn seam and nightly maintenance."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(repo_root / "tests"))

from golden_harness import make_golden_orchestrator  # noqa: E402

from agents.core.scheduler_service import SchedulerService  # noqa: E402

TURN = "Andrei Popescu lives in Bucharest and works at Innoveo."


def _enable_living_memory(orch) -> None:
    orch._runtime_settings.update({
        "cognition.enabled": True,
        "cognition.memory_enabled": True,
    })


def _tier_total(living_memory) -> int:
    return sum(living_memory.status()["tiers"].values())


async def test_living_memory_turn_seam_is_default_off(monkeypatch, tmp_path):
    orch, _fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    sid = await orch.memory.new_session("o26_p2_default_off")
    living_memory = orch.cognition.module("memory")

    await orch.handle_input(TURN, channel="web", session_id=sid)

    assert _tier_total(living_memory) == 0
    assert not any(r["id"].startswith(f"turn:{sid}:") for r in orch.decay.ranking(limit=1000))


async def test_enabled_living_memory_records_turns_and_nightly_tick(monkeypatch, tmp_path):
    orch, _fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    _enable_living_memory(orch)
    sid = await orch.memory.new_session("o26_p2_live_memory")
    living_memory = orch.cognition.module("memory")

    for idx in range(3):
        await orch.handle_input(f"{TURN} Turn marker {idx}.", channel="web", session_id=sid)

    records = living_memory.records(prefix=f"turn:{sid}:")
    recorded_ids = [record["id"] for record in records]
    assert len(records) == 3
    assert records[0]["content"]["session"] == sid
    assert records[0]["content"]["turn_ref"] == records[0]["id"]
    assert "text_sha256" in records[0]["content"]
    assert "user" not in records[0]["content"]
    assert "assistant" not in records[0]["content"]
    assert sum(1 for r in orch.decay.ranking(limit=1000) if r["id"].startswith(f"turn:{sid}:")) == 3

    result = await orch._scheduler.run_memory_maintenance()

    assert result["skipped"] is False
    assert result["living_memory"]["nrem"]["total"] >= 3
    assert result["living_memory"]["rem"]["phase"] == "rem"
    assert result["decay"]["ranked"] >= 3
    assert living_memory.records(prefix=recorded_ids[0])[0]["content"]["session"] == sid


async def test_orchestrator_living_core_uses_runtime_data_root(monkeypatch, tmp_path):
    orch, _fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    living_memory = orch.cognition.module("memory")
    living_memory.core.put("Andrei wants durable core facts.")

    core_path = tmp_path / "cognition" / "core_memory.json"
    assert core_path.exists()

    from agents.core.cognition.memory import LivingMemory
    reloaded = LivingMemory(core_path=core_path)
    assert reloaded.core.list() == ["Andrei wants durable core facts."]


async def test_orchestrator_living_tiers_use_runtime_data_root(monkeypatch, tmp_path):
    orch, _fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    _enable_living_memory(orch)
    sid = await orch.memory.new_session("o26_p2_tier_persist")

    await orch.handle_input(TURN, channel="web", session_id=sid)

    tiers_path = tmp_path / "cognition" / "living_tiers.json"
    assert tiers_path.exists()

    from agents.core.cognition.memory import LivingMemory
    reloaded = LivingMemory(tiers_path=tiers_path)
    records = reloaded.records(prefix=f"turn:{sid}:")
    assert len(records) == 1
    assert records[0]["content"]["turn_ref"] == records[0]["id"]


def test_scheduler_registers_memory_maintenance_job():
    calls = []

    class _Scheduler:
        def add_job(self, *args, **kwargs):
            calls.append((args, kwargs))

    class _Heartbeat:
        scheduler = _Scheduler()

    class _Orch:
        heartbeat_scheduler = _Heartbeat()

    SchedulerService(_Orch()).schedule_memory_maintenance()

    kwargs = calls[0][1]
    assert kwargs["id"] == "memory-consolidation-decay"
    assert kwargs["replace_existing"] is True
    assert calls[0][0][1] == "cron"


def test_memory_maintenance_logs_do_not_interpolate_exceptions():
    source = (repo_root / "agents/core/scheduler_service.py").read_text(encoding="utf-8")

    assert "Failed to schedule memory maintenance: {e}" not in source
    assert "LivingMemory consolidation failed: {e}" not in source
    assert "Decay inspection failed: {e}" not in source


def test_memory_maintenance_does_not_log_whole_result_payload():
    source = (repo_root / "agents/core/scheduler_service.py").read_text(encoding="utf-8")

    assert 'logger.info("Memory maintenance complete: %s", result)' not in source


def test_living_memory_turn_records_do_not_duplicate_raw_transcript_text():
    source = (repo_root / "agents/core/orchestrator.py").read_text(encoding="utf-8")

    assert '"user": user_text' not in source
    assert '"assistant": assistant_text' not in source
    assert "label = (user_text or assistant_text" not in source
    assert "text_sha256" in source


@pytest.mark.asyncio
async def test_memory_maintenance_noops_when_cognition_memory_disabled():
    class _Cognition:
        def sub_enabled(self, name):
            assert name == "memory_enabled"
            return False

        def module(self, name):
            raise AssertionError("disabled memory must not touch the module")

    class _Orch:
        cognition = _Cognition()
        decay = None

        def get_setting(self, _key, default=None):
            return default

    result = await SchedulerService(_Orch()).run_memory_maintenance()

    assert result == {"skipped": True, "reason": "cognition_memory_disabled"}


@pytest.mark.asyncio
async def test_memory_maintenance_runs_reprojection_hook():
    class _Living:
        def __init__(self):
            self.reprojected = False

        async def consolidate(self, phase):
            return {"phase": phase, "total": 1} if phase == "nrem" else {"phase": phase}

        async def reproject_stale(self):
            self.reprojected = True
            return {"available": True, "checked": 1, "reprojected": 1, "version": 2}

    class _Cognition:
        def __init__(self, living):
            self.living = living

        def sub_enabled(self, name):
            assert name == "memory_enabled"
            return True

        def module(self, name):
            assert name == "memory"
            return self.living

    class _Orch:
        def __init__(self, living):
            self.cognition = _Cognition(living)
            self.decay = None

        def get_setting(self, _key, default=None):
            return default

    living = _Living()
    result = await SchedulerService(_Orch(living)).run_memory_maintenance()

    assert living.reprojected is True
    assert result["reprojection"] == {
        "available": True,
        "checked": 1,
        "reprojected": 1,
        "version": 2,
    }
