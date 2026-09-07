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

import pytest
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


# A card this box does not have. Exactly one test below forces a *fabricated*
# probe (`test_detect_gpu_is_honest_when_nvidia_smi_absent`) — the rest use
# `_gpu(...)` literals or patch `detected_vram_total_mb` — but that one is enough
# to have leaked. On a runner with no nvidia-smi a leaked probe and a restored one
# both read {"name": "none"}, indistinguishable; pinning the module global to a
# card for the file's duration makes the difference observable.
_A_REAL_CARD = {"name": "a real card", "vram_total_mb": 24576, "vram_used_mb": 0,
                "load_pct": 3, "measured": True}


# Set by the forced-probe test below, read by the leak test after it. Without
# this, every way of losing the ordering — running the leak test alone, `-k`,
# `--dist load`/`worksteal` instead of CI's `loadfile`, or renaming the prober —
# makes the leak test pass vacuously instead of failing loudly.
_forced_a_probe = False


@pytest.fixture(autouse=True, scope="module")
def _pretend_this_box_has_a_card():
    saved = hardware._gpu_cache
    hardware._gpu_cache = dict(_A_REAL_CARD)
    yield
    hardware._gpu_cache = saved


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
    global _forced_a_probe
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    gpu = hardware.detect_gpu(force=True)
    _forced_a_probe = True
    assert gpu["name"] == "none"
    assert gpu["vram_total_mb"] is None
    assert gpu["measured"] is False
    blob = repr(gpu)
    assert "RTX" not in blob and "24576" not in blob


def test_the_forced_probe_above_did_not_outlive_its_test():
    """`detect_gpu()` memoises into a module global and `force=True` overwrites
    it. Nothing put it back, so a pytest worker — which runs many files in one
    process — carried that fabricated "this box has no GPU" into every later
    test, including on the owner's RTX box where it is false.

    `conftest._isolate_gpu_probe_cache` snapshots and restores it per test.
    Without that fixture this reads {"name": "none"} and fails; the module pin
    above is what makes the two cases distinguishable off a GPU box.
    """
    if not _forced_a_probe:
        # Not a quarantine: without the prober having run there is nothing for
        # the fixture to have restored, so the assertion below would PASS while
        # proving nothing. Skipping makes that visible in the report instead.
        # CI runs `-n auto --dist loadfile`, which keeps a file on one worker in
        # definition order, so this never skips there; `--dist load`,
        # `--dist worksteal`, `-k` and running this test alone do.
        pytest.skip("needs test_detect_gpu_is_honest_when_nvidia_smi_absent to run first")
    assert hardware._gpu_cache == _A_REAL_CARD


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


def test_hardware_route_shape(monkeypatch):
    # This route reads detect_gpu() *unforced*, so the module pin above would
    # feed it the fabricated card and flip its score component from
    # "not_measured" to "measured" — silently changing which branch a no-GPU
    # runner covers. Clear the cache for this test so it probes the real box.
    monkeypatch.setattr(hardware, "_gpu_cache", None)
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


# ── model-setup slice: the probe is no longer NVIDIA-only ────────────────────
# Each probe runs a fixed argv through `hardware._run_argv` (no shell); tests
# swap that one seam and `shutil.which`/`platform` — nothing here spawns anything.

def _argv_fake(table):
    """`_run_argv` stand-in: argv[0] → (returncode, stdout); records every call."""
    calls = []

    def run(argv, timeout=5.0):
        calls.append(list(argv))
        code, out = table[argv[0]]
        return code, out
    run.calls = calls
    return run


def test_apple_silicon_probe_counts_unified_memory_as_a_gpu_budget(monkeypatch):
    monkeypatch.setattr(hardware.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/sbin/sysctl" if n == "sysctl" else None)
    run = _argv_fake({"sysctl": (0, "34359738368\n")})          # 32 GiB
    monkeypatch.setattr(hardware, "_run_argv", run)
    gpu = hardware.detect_gpu(probes=hardware.DEFAULT_GPU_PROBES)
    assert run.calls == [["sysctl", "-n", "hw.memsize"]]         # argv, no shell
    assert gpu["kind"] == "apple" and gpu["measured"] is True
    assert gpu["unified_memory_total_mb"] == 32768
    assert gpu["vram_total_mb"] == int(32768 * hardware.APPLE_UNIFIED_GPU_FRACTION)
    assert "assumed" in gpu["note"]
    # an injected probe run never touches the process-wide cache
    assert hardware._gpu_cache == _A_REAL_CARD


def test_apple_probe_is_not_applicable_off_darwin_arm64(monkeypatch):
    monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/sbin/sysctl")
    run = _argv_fake({"sysctl": (0, "34359738368\n")})
    monkeypatch.setattr(hardware, "_run_argv", run)
    assert hardware._probe_apple() is None
    assert run.calls == []
    monkeypatch.setattr(hardware.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "x86_64")
    assert hardware._probe_apple() is None


def test_amd_probe_parses_rocm_smi_csv_bytes_to_mb(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda n: "/opt/rocm/bin/rocm-smi" if n == "rocm-smi" else None)
    csv = ("device,VRAM Total Memory (B),VRAM Total Used Memory (B)\n"
           "card0,17163091968,536870912\n")
    run = _argv_fake({"rocm-smi": (0, csv)})
    monkeypatch.setattr(hardware, "_run_argv", run)
    gpu = hardware.detect_gpu(probes=hardware.DEFAULT_GPU_PROBES)
    assert run.calls == [["rocm-smi", "--showmeminfo", "vram", "--csv"]]
    assert gpu["kind"] == "amd" and gpu["measured"] is True
    assert gpu["vram_total_mb"] == 16368 and gpu["vram_used_mb"] == 512
    assert hardware._parse_rocm_csv("garbage") is None
    assert hardware._parse_rocm_csv("device,VRAM Total Memory (B)\ncard0,0\n") is None


def test_probe_order_is_nvidia_then_apple_then_amd_and_errors_are_unknown(monkeypatch):
    monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
    monkeypatch.setattr(shutil, "which", lambda n: f"/usr/bin/{n}" if n in ("nvidia-smi", "rocm-smi") else None)
    run = _argv_fake({
        "nvidia-smi": (0, "RTX 4090, 1024, 24564, 3\n"),
        "rocm-smi": (0, "device,VRAM Total Memory (B),VRAM Total Used Memory (B)\ncard0,17163091968,0\n"),
    })
    monkeypatch.setattr(hardware, "_run_argv", run)
    gpu = hardware.detect_gpu(probes=hardware.DEFAULT_GPU_PROBES)
    assert gpu["kind"] == "nvidia" and gpu["name"] == "RTX 4090" and gpu["vram_total_mb"] == 24564
    assert [c[0] for c in run.calls] == ["nvidia-smi"]        # first applicable probe wins

    # a present-but-broken binary is "unknown", never "none" and never a number
    def boom(argv, timeout=5.0):
        raise OSError("driver wedged")
    monkeypatch.setattr(hardware, "_run_argv", boom)
    gpu = hardware.detect_gpu(probes=(hardware._probe_amd,))
    assert gpu["name"] == "unknown" and gpu["kind"] == "unknown"
    assert gpu["measured"] is False and gpu["vram_total_mb"] is None

    # no applicable probe at all → "none", and a probe that raises is skipped
    def raises():
        raise RuntimeError("probe bug")
    gpu = hardware.detect_gpu(probes=(raises, lambda: None))
    assert gpu == hardware._unprobed_gpu("none")
    assert gpu["kind"] == "none"


def test_amd_and_apple_cards_feed_the_score_like_nvidia():
    amd = {"name": "AMD GPU (rocm-smi)", "kind": "amd", "vram_total_mb": 16368,
           "vram_used_mb": 512, "load_pct": None, "measured": True}
    scored = hardware.score_hardware({"gpu": amd, "cpu_threads": 16, "ram_total_gb": 64.0})
    assert scored["components"]["gpu"] == "measured"
    assert hardware.recommended_profile({"gpu": amd, "cpu_threads": 16, "ram_total_gb": 64.0}) == "balanced"
