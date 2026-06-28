"""0.62 — System Profiles: usage-mode posture presets (env-driven, default 'balanced')."""

import pytest

from agents.core import system_profiles as sp


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("JARVIS_SYSTEM_PROFILE", raising=False)


def test_default_is_balanced_and_keeps_autonomy_on():
    assert sp.active_name() == "balanced"
    post = sp.active_posture()
    assert post["background_autonomy"] is True       # default path: heartbeats run
    assert post["heavy_features"] is True


def test_unknown_profile_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "no-such-mode")
    assert sp.active_name() == "balanced"


@pytest.mark.parametrize("name,bg", [
    ("gaming", False), ("multimedia", False), ("ai", True), ("admin", True),
])
def test_profiles_select_and_expose_autonomy_knob(monkeypatch, name, bg):
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", name.upper())   # case-insensitive
    assert sp.active_name() == name
    assert sp.active_posture()["background_autonomy"] is bg


def test_active_posture_is_a_copy():
    sp.active_posture()["background_autonomy"] = "mutated"
    assert sp.PROFILES["balanced"]["background_autonomy"] is True   # source unchanged


def test_list_profiles_shape():
    out = sp.list_profiles()
    assert out["active"] == "balanced" and out["default"] == "balanced"
    assert set(out["profiles"]) == {"balanced", "gaming", "ai", "multimedia", "admin"}


# ── the live consumer: run_heartbeat is paused under a no-autonomy profile ──────
@pytest.mark.asyncio
async def test_run_heartbeat_paused_when_profile_disables_autonomy(monkeypatch):
    from agents.core.orchestrator import Orchestrator

    o = Orchestrator.__new__(Orchestrator)   # bypass heavy __init__

    class _Agent:
        has_heartbeat = True
        _heartbeat_config = {}
        async def run_heartbeat(self, orchestrator=None):
            return "ran"
    o.agents = {"jarvis": _Agent()}

    # balanced (default) → heartbeat runs
    assert await o.run_heartbeat("jarvis") == "ran"
    # gaming → background autonomy off → heartbeat is skipped
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "gaming")
    assert await o.run_heartbeat("jarvis") is None
