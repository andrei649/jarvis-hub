"""H133 — the live status chrome: ``/status`` reports the gateway (which channels run),
the active-session count and the version, so the HUD's top bar and rail can show them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def _inventory():
    return {"providers": [], "configured_model": None, "backend": "none",
            "resident_models": [], "residency_state": "offline", "models": []}


def _orch(**extra):
    base = {"llm_router": None, "lmstudio": None, "model_info": None, "channel_manager": None,
            "channels": {}, "running_channels": []}
    base.update(extra)
    return SimpleNamespace(**base)


def _status(orch):
    import agents.web as web

    # The lifespan installs the real orchestrator, so the fake one goes in after it.
    with (
        TestClient(web.app) as client,
        patch.object(web, "orch", orch),
        patch.object(web, "_list_local_models", AsyncMock(return_value=_inventory())),
        patch.object(web, "_enrich_agents", return_value=[]),
        patch.object(web, "_sys_info", return_value={}),
        patch("agents.core.routers.status.get_gateway", return_value=None),
    ):
        return client.get("/status").json()


def _checkpoints(tmp_path):
    from agents.core.checkpoint import CheckpointManager

    cp = CheckpointManager(db_path=str(tmp_path / "cp.db"))
    cp.initialize()
    return cp


def test_status_reports_gateway_running_channels():
    channels = {"web": SimpleNamespace(), "telegram": SimpleNamespace(_running=True),
                "discord": SimpleNamespace(), "slack": SimpleNamespace(running=True)}
    body = _status(_orch(channels=channels, running_channels=["discord"]))
    gateway = body["gateway"]
    assert gateway["state"] == "running"
    assert gateway["running"] == ["discord", "slack", "telegram"]
    assert gateway["running_count"] == 3
    assert gateway["total"] == 4


def test_status_gateway_stopped_and_none():
    stopped = _status(_orch(channels={"telegram": SimpleNamespace()}))["gateway"]
    assert stopped == {"state": "stopped", "running": [], "running_count": 0, "total": 1}
    none = _status(_orch())["gateway"]
    assert none == {"state": "none", "running": [], "running_count": 0, "total": 0}


def test_status_reports_version():
    from agents import __version__

    assert _status(_orch())["version"] == __version__


def test_active_session_count_counts_recent_unarchived(tmp_path):
    cp = _checkpoints(tmp_path)
    try:
        now = datetime.now(UTC)
        for sid in ("a", "b", "old", "arch"):
            cp.create_session_record(sid)
        cp.update_session("b", turn_count=3)
        old = (now - timedelta(hours=3)).isoformat()
        with cp._lock:
            cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id='old'", (old, old))
            cp._conn.commit()
        assert cp.set_archived("arch", True)
        since = (now - timedelta(minutes=15)).isoformat()
        assert cp.active_session_count(since) == 2
        assert cp.active_session_count((now + timedelta(minutes=1)).isoformat()) == 0
    finally:
        cp.close()


def test_active_session_count_unavailable_store():
    from agents.core.checkpoint import CheckpointManager

    assert CheckpointManager(db_path=":memory:").active_session_count("2026-01-01") is None


def test_status_reports_active_sessions(tmp_path):
    cp = _checkpoints(tmp_path)
    try:
        cp.create_session_record("live-1")
        cp.create_session_record("live-2")
        sessions = _status(_orch(checkpoints=cp))["sessions"]
    finally:
        cp.close()
    assert sessions == {"active": 2, "window_s": 900, "state": "known"}


def test_status_sessions_unknown_without_store():
    assert _status(_orch())["sessions"] == {"active": None, "window_s": 900, "state": "unknown"}


def test_status_sessions_unknown_when_store_raises():
    broken = SimpleNamespace(active_session_count=lambda since: (_ for _ in ()).throw(RuntimeError("db")))
    assert _status(_orch(checkpoints=broken))["sessions"]["state"] == "unknown"
