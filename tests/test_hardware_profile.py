"""DRA-44 — hardware detection feeds the VRAM budget, and is scored honestly.

Two defects this pins:
  1. `ModelManager` assumed a 24GB card via a static constant, so on an 8GB box
     `_headroom_ok()` cheerfully said an 8GB model fits for free.
  2. There was no hardware score at all, and no surface for one.

The score is a **spec-based** score (VRAM / threads / RAM the machine already
reports), not a throughput benchmark — every component reports whether it was
measured, and an unmeasured component is never silently credited.
"""
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core import hardware, system_profiles
from agents.core.llm.model_manager import DEFAULT_VRAM_TOTAL_MB, ModelManager


class _FakeController:
    async def load(self, model_id):  # pragma: no cover - never driven here
        return None

    async def unload(self, model_id):  # pragma: no cover - never driven here
        return None


def _gpu(vram=None, measured=False, name="none"):
    return {"name": name, "vram_total_mb": vram, "vram_used_mb": None,
            "load_pct": None, "measured": measured}


def test_model_manager_uses_detected_vram_when_env_unset(monkeypatch):
    monkeypatch.delenv("JARVIS_VRAM_TOTAL_MB", raising=False)
    monkeypatch.setattr(hardware, "detected_vram_total_mb", lambda: 8192)
    mgr = ModelManager(_FakeController())
    assert mgr.vram_total_mb == 8192
    # 8192 - 2048 reserve = 6144 budget: an 8GB model does NOT fit for free.
    assert mgr._headroom_ok(8192) is False


def test_env_and_explicit_arg_still_win_over_detection(monkeypatch):
    monkeypatch.setattr(hardware, "detected_vram_total_mb", lambda: 8192)
    monkeypatch.setenv("JARVIS_VRAM_TOTAL_MB", "12000")
    assert ModelManager(_FakeController()).vram_total_mb == 12000
    assert ModelManager(_FakeController(), vram_total_mb=4096).vram_total_mb == 4096


def test_detection_failure_never_raises_and_falls_back(monkeypatch):
    monkeypatch.delenv("JARVIS_VRAM_TOTAL_MB", raising=False)

    def boom():
        raise OSError("probe unavailable")

    monkeypatch.setattr(hardware, "detected_vram_total_mb", boom)
    assert ModelManager(_FakeController()).vram_total_mb == DEFAULT_VRAM_TOTAL_MB


def test_detect_gpu_is_honest_when_nvidia_smi_absent(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    gpu = hardware.detect_gpu(force=True)
    assert gpu["name"] == "none"
    assert gpu["vram_total_mb"] is None
    assert gpu["measured"] is False
    blob = repr(gpu)
    assert "RTX" not in blob and "24576" not in blob


def test_score_never_credits_an_unmeasured_component():
    without_gpu = hardware.score_hardware(
        {"gpu": _gpu(), "cpu_threads": 32, "ram_total_gb": 192.0})
    with_gpu = hardware.score_hardware(
        {"gpu": _gpu(24576, True, "big card"), "cpu_threads": 32, "ram_total_gb": 192.0})
    assert without_gpu["score"] < with_gpu["score"]
    assert without_gpu["components"]["gpu"] == "not_measured"
    assert with_gpu["components"]["gpu"] == "measured"

    blind = hardware.score_hardware({"gpu": _gpu(), "cpu_threads": None, "ram_total_gb": None})
    assert blind["tier"] == "unknown"          # not "low" — we measured nothing
    assert blind["score"] == 0


def test_recommended_profile_is_always_a_real_profile():
    cases = [
        ({"gpu": _gpu(8192, True), "cpu_threads": 8, "ram_total_gb": 32.0}, "headless"),
        ({"gpu": _gpu(16384, True), "cpu_threads": 16, "ram_total_gb": 64.0}, "balanced"),
        ({"gpu": _gpu(24576, True), "cpu_threads": 32, "ram_total_gb": 128.0}, "ai"),
    ]
    for hw, expected in cases:
        got = hardware.recommended_profile(hw)
        assert got in system_profiles.PROFILES
        assert got == expected
    no_gpu = {"gpu": _gpu(), "cpu_threads": 8, "ram_total_gb": 32.0}
    assert hardware.recommended_profile(no_gpu) in system_profiles.PROFILES
    blind = {"gpu": _gpu(), "cpu_threads": None, "ram_total_gb": None}
    assert hardware.recommended_profile(blind) == system_profiles.DEFAULT


def test_detect_hardware_accepts_an_injected_probe():
    hw = hardware.detect_hardware(probe=lambda: _gpu(24576, True, "injected"))
    assert hw["gpu"]["name"] == "injected"
    assert "cpu_threads" in hw and "ram_total_gb" in hw


def test_hardware_route_shape():
    from agents import web
    old = web.USER_TOKEN
    web.USER_TOKEN = "user-secret"
    try:
        with TestClient(web.app) as c:
            # same guard posture as its 0.62 sibling, whatever the harness resolves to
            assert (c.get("/api/system/hardware").status_code
                    == c.get("/api/system/profiles").status_code)
            r = c.get("/api/system/hardware", headers={"X-User-Token": "user-secret"})
            assert r.status_code == 200
            body = r.json()
            for key in ("detected", "score", "recommended_profile", "active_profile"):
                assert key in body
            assert body["recommended_profile"] in system_profiles.PROFILES
            assert body["active_profile"] in system_profiles.PROFILES
            assert body["score"]["components"]["gpu"] in ("measured", "not_measured")
    finally:
        web.USER_TOKEN = old
