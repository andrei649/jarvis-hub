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


# ── new consumers (0.62): heavy_features + model_tier actually bite ─────────────
def test_heavy_features_enabled(monkeypatch):
    assert sp.heavy_features_enabled() is True            # balanced default
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "gaming")
    assert sp.heavy_features_enabled() is False           # gaming frees the GPU


def test_preferred_model_tier(monkeypatch):
    assert sp.preferred_model_tier() == "auto"            # balanced default
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "gaming")
    assert sp.preferred_model_tier() == "local-light"
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "multimedia")
    assert sp.preferred_model_tier() == "local"


@pytest.mark.asyncio
async def test_media_generate_paused_under_gaming_profile(monkeypatch):
    """The media-gen entry point is gated on heavy_features — gaming pauses it
    before any backend/orch work (so the GPU stays free)."""
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "gaming")
    import json

    from agents.core.routers.multimodal import MediaGenBody, media_generate
    resp = await media_generate(MediaGenBody(kind="image", prompt="a cat"))
    body = json.loads(bytes(resp.body))
    assert body["ok"] is False and body["paused"] is True and body["profile"] == "gaming"


def test_constrained_model_tier_forces_cloud_fallback_never(monkeypatch):
    """A constrained model_tier (gaming/multimedia) forces cloud escalation OFF in
    load_runtime_settings, regardless of the llm.cloud_fallback setting; 'auto'
    (balanced) honors the setting."""
    import agents.core.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "_get_settings",
                        lambda: {"llm": [{"key": "cloud_fallback", "value": "always"}]})
    o = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    captured = {}

    class _Router:
        def set_cloud_fallback_mode(self, m):
            captured["mode"] = m

        def set_local_max(self, v):
            pass

        def set_flash_max(self, v):
            pass

    o.llm_router = _Router()
    o.load_runtime_settings()                       # balanced → honors the setting
    assert captured["mode"] == "always"
    monkeypatch.setenv("JARVIS_SYSTEM_PROFILE", "gaming")
    o.load_runtime_settings()                       # gaming → forced local-only
    assert captured["mode"] == "never"
