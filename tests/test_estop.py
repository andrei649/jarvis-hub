"""
Tests for the global emergency stop (agents/core/estop.py) — the resumable
pause for NEW autonomous work (heartbeats + autonomy ticks), ported from
hermes-agent agent/estop.py (Nous Research, MIT, v2026.8.27).
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import json
import logging
import os

import pytest

from agents.core import estop


@pytest.fixture
def estop_home(tmp_path, monkeypatch):
    """Point the sentinel at a temp dir and reset the log-once bookkeeping."""
    monkeypatch.setattr(estop, "install_root", lambda: tmp_path)
    estop._reset_log_state_for_tests()
    return tmp_path


def test_disengaged_by_default(estop_home):
    assert estop.is_engaged() is False
    assert estop.get_state() is None


def test_engage_writes_reason_and_timestamp(estop_home):
    path = estop.engage("smoke in the server room")
    assert path == estop_home / "ESTOP"
    assert estop.is_engaged() is True
    state = estop.get_state()
    assert state["reason"] == "smoke in the server room"
    assert state["engaged_at"]
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["reason"] == "smoke in the server room"


def test_engage_is_idempotent_and_updates_reason(estop_home):
    estop.engage("first")
    estop.engage("second")
    assert estop.get_state()["reason"] == "second"


def test_disengage_lifts_pause_and_reports(estop_home):
    estop.engage()
    assert estop.disengage() is True
    assert estop.is_engaged() is False
    assert estop.disengage() is False  # already lifted


def test_corrupt_sentinel_still_counts_engaged(estop_home):
    # `touch data/ESTOP` (empty / non-JSON body) must still pause — fail safe.
    (estop_home / "ESTOP").write_text("not json", encoding="utf-8")
    assert estop.is_engaged() is True
    state = estop.get_state()
    assert state == {"reason": None, "engaged_at": None}


def test_check_paused_logs_once_per_engagement(estop_home, caplog):
    logger = logging.getLogger("test.estop")
    with caplog.at_level(logging.INFO, logger="test.estop"):
        assert estop.check_paused("autonomy", logger) is False
        estop.engage("drill")
        assert estop.check_paused("autonomy", logger) is True
        assert estop.check_paused("autonomy", logger) is True
        # one log line for the engaged transition, not one per tick
        paused_lines = [r for r in caplog.records if "paused" in r.getMessage()]
        assert len(paused_lines) == 1
        # a resume re-arms the log for the next engagement
        estop.disengage()
        assert estop.check_paused("autonomy", logger) is False
        estop.engage("second drill")
        assert estop.check_paused("autonomy", logger) is True
        paused_lines = [r for r in caplog.records if "paused" in r.getMessage()]
        assert len(paused_lines) == 2


def test_components_log_independently(estop_home, caplog):
    logger = logging.getLogger("test.estop")
    estop.engage()
    with caplog.at_level(logging.INFO, logger="test.estop"):
        assert estop.check_paused("autonomy", logger) is True
        assert estop.check_paused("heartbeat:friday", logger) is True
        paused_lines = [r for r in caplog.records if "paused" in r.getMessage()]
        assert len(paused_lines) == 2


async def test_heartbeat_dispatch_skipped_while_engaged(estop_home):
    from agents.core.heartbeat import HeartbeatScheduler

    calls = []

    class FakeOrchestrator:
        async def run_heartbeat(self, agent_id):
            calls.append(agent_id)
            return "ran"

    scheduler = HeartbeatScheduler.__new__(HeartbeatScheduler)
    estop.engage("test pause")
    await scheduler._run_heartbeat("friday", FakeOrchestrator())
    assert calls == []

    estop.disengage()
    await scheduler._run_heartbeat("friday", FakeOrchestrator())
    assert calls == ["friday"]


# --- H694: one canonical kill switch every profile honors ---------------------------


@pytest.fixture
def profiled_install(tmp_path, monkeypatch):
    """A real install root (``$JARVIS_HOME``) with profile hubs beside it (H689)."""
    home = tmp_path / "home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    estop._reset_log_state_for_tests()
    return home


def test_install_root_is_shared_by_every_profile(profiled_install, monkeypatch):
    from agents.core import paths

    assert paths.install_root() == profiled_install
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    # the profile's data root moves beside the install root; the install root does not
    assert paths.data_root() == profiled_install.parent / "home-profiles" / "work"
    assert paths.install_root() == profiled_install
    assert paths.install_root({"JARVIS_HOME": str(profiled_install), "JARVIS_PROFILE": "x"}) == profiled_install


def test_sentinel_lives_at_install_root_for_a_profiled_hub(profiled_install, monkeypatch):
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert estop.sentinel_path() == profiled_install / "ESTOP"


def test_profiled_hub_pauses_on_the_canonical_estop(profiled_install, monkeypatch):
    # the default hub engages the kill switch ...
    estop.engage("canonical drill")
    assert (profiled_install / "ESTOP").exists()
    # ... and a hub running under another profile pauses on that same sentinel
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    logger = logging.getLogger("test.estop")
    assert estop.is_engaged() is True
    assert estop.check_paused("heartbeat:friday", logger) is True
    assert estop.get_state()["reason"] == "canonical drill"


def test_engage_from_a_profile_stops_every_scope(profiled_install, monkeypatch):
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    path = estop.engage("from work")
    assert path == profiled_install / "ESTOP"
    monkeypatch.setenv("JARVIS_PROFILE", "personal")
    assert estop.is_engaged() is True
    monkeypatch.delenv("JARVIS_PROFILE")
    assert estop.is_engaged() is True
    # and resuming from any scope lifts it everywhere
    assert estop.disengage() is True
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert estop.is_engaged() is False


def _legacy_sentinel(profile: str, body: dict) -> Path:
    """Plant a pre-H694 sentinel inside a profile's own data root."""
    from agents.core.paths import data_root

    local = data_root({"JARVIS_HOME": os.environ["JARVIS_HOME"], "JARVIS_PROFILE": profile}) / "ESTOP"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(body), encoding="utf-8")
    return local


def test_legacy_profile_local_sentinel_is_folded_into_the_canonical_switch(profiled_install, monkeypatch):
    # review-H694 #2: a pre-H694 sentinel in one profile's root used to pause only that
    # profile, invisible to (and not liftable from) every other scope. It is now one switch.
    local = _legacy_sentinel("work", {"reason": "old drill", "engaged_at": "2026-01-02T03:04:05+00:00"})
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert estop.is_engaged() is True
    # the legacy body moved to the canonical sentinel, reason and timestamp kept
    assert not local.exists()
    body = json.loads((profiled_install / "ESTOP").read_text(encoding="utf-8"))
    assert body == {"reason": "old drill", "engaged_at": "2026-01-02T03:04:05+00:00"}
    monkeypatch.setenv("JARVIS_PROFILE", "personal")
    assert estop.is_engaged() is True
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert estop.disengage() is True
    assert estop.is_engaged() is False


def test_legacy_sentinel_is_visible_and_liftable_from_the_default_hub(profiled_install, monkeypatch):
    # the profile that owns the legacy sentinel never ran: status and resume from the
    # default hub (and any other profile) must still see and lift it
    local = _legacy_sentinel("work", {"reason": "old drill"})
    assert estop.is_engaged() is True
    assert estop.get_state()["reason"] == "old drill"
    monkeypatch.setenv("JARVIS_PROFILE", "personal")
    assert estop.check_paused("autonomy", logging.getLogger("test.estop")) is True
    monkeypatch.delenv("JARVIS_PROFILE")
    assert estop.disengage() is True
    assert not local.exists()
    for profile in ("work", "personal"):
        monkeypatch.setenv("JARVIS_PROFILE", profile)
        assert estop.is_engaged() is False
        assert estop.get_state() is None


def test_resume_lifts_legacy_sentinels_even_when_the_canonical_one_is_engaged(profiled_install, monkeypatch):
    estop.engage("canonical")
    a = _legacy_sentinel("work", {"reason": "a"})
    b = _legacy_sentinel("personal", {"reason": "b"})
    # the canonical sentinel wins the status read
    assert estop.get_state()["reason"] == "canonical"
    assert estop.disengage() is True
    assert not a.exists() and not b.exists()
    assert not (profiled_install / "ESTOP").exists()
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert estop.is_engaged() is False


def test_forget_on_the_default_hub_keeps_the_shared_estop(profiled_install, monkeypatch):
    # review-H694 #1: the canonical sentinel lives in the default hub's data root, so the
    # default hub's "forget" sweep used to unlink it and silently resume every profile.
    from agents.core import data_purge

    profiled_install.mkdir(parents=True)
    (profiled_install / "scratch.txt").write_text("user content", encoding="utf-8")
    estop.engage("forget drill")
    report = data_purge.purge_data(str(profiled_install), backup_first=False)
    assert not (profiled_install / "scratch.txt").exists()   # the sweep did run
    assert report["ok"] is True
    assert (profiled_install / "ESTOP").exists()
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert estop.is_engaged() is True
    assert estop.get_state()["reason"] == "forget drill"


def test_backup_never_carries_the_kill_switch(profiled_install, tmp_path):
    # review-H694 #1: a backup taken while engaged must not reinstate a stale pause for
    # every profile when restored later, and a restore never removes a live pause.
    import tarfile

    from agents.core import backup

    profiled_install.mkdir(parents=True)
    (profiled_install / "notes.json").write_text("{}", encoding="utf-8")
    estop.engage("during backup")
    snap = backup.create_backup(source_root=str(profiled_install), out_dir=str(tmp_path / "bk"))
    with tarfile.open(snap["archive"]) as tar:
        assert "ESTOP" not in {Path(m.name).name for m in tar.getmembers()}
    assert backup.verify_backup(snap["archive"])["ok"] is True
    # restoring the snapshot after a resume does not bring the pause back ...
    estop.disengage()
    result = backup.restore_backup(snap["archive"], str(profiled_install), force=True)
    assert result["ok"] is True
    assert estop.is_engaged() is False
    # ... and restoring over an engaged root leaves the live pause in place
    estop.engage("live pause")
    backup.restore_backup(snap["archive"], str(profiled_install), force=True)
    assert estop.get_state()["reason"] == "live pause"


async def test_profiled_hub_dispatch_and_status_honor_the_canonical_estop(profiled_install, monkeypatch):
    # review-H694 #3: a real consumer under $JARVIS_PROFILE, nothing patched in estop/paths
    from agents.core.heartbeat import HeartbeatScheduler
    from agents.core.routers import ops

    estop.engage("integration drill")   # engaged from the default hub's environment
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    calls = []

    class FakeOrchestrator:
        async def run_heartbeat(self, agent_id):
            calls.append(agent_id)
            return "ran"

    scheduler = HeartbeatScheduler.__new__(HeartbeatScheduler)
    assert await scheduler._run_heartbeat("friday", FakeOrchestrator()) == {"_scheduler_status": "skipped"}
    assert calls == []
    status = json.loads((await ops.estop_state()).body)
    assert status["engaged"] is True
    assert status["state"]["reason"] == "integration drill"
    resumed = json.loads((await ops.estop_resume()).body)   # resume from the profiled hub
    assert resumed == {"engaged": False, "lifted": True}
    await scheduler._run_heartbeat("friday", FakeOrchestrator())
    assert calls == ["friday"]
