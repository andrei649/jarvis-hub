"""CDX-10 — `_sys_info()` is honest: probed values, or "unknown"/"none", never fabricated.

The /status readiness screen must not imply a host/CPU/GPU (or a loaded model) that isn't
actually there. This pins that the old plausible-but-fake defaults are gone and that a
failed probe degrades to an honest placeholder.
"""

import socket

from agents import web

# The fabricated constants the old _sys_info() returned when probes failed.
_FABRICATIONS = (
    "BONOBO-WS",
    "RTX 5090",
    "Intel Core Ultra 9",
    "google/gemma-4-31b-a4b",
    "LM Studio · 1234",
)


def test_shape_is_stable():
    info = web._sys_info()
    for k in (
        "host",
        "cpu",
        "ram_used",
        "ram_total",
        "gpu",
        "vram_used",
        "vram_total",
        "gpu_load",
        "backend",
        "model",
        "uptime",
    ):
        assert k in info, f"missing readiness key {k}"


def test_no_fabricated_hardware_or_model(monkeypatch):
    """Failed probes must not fall back to the old demo constants.

    The assertion is intentionally hermetic: an owner may genuinely run hardware whose
    name matches an old demo value (for example an RTX 5090).
    """
    import platform
    import shutil

    import psutil

    monkeypatch.setattr(socket, "gethostname", lambda: "")
    monkeypatch.setattr(platform, "processor", lambda: "")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: None)

    def unavailable_memory():
        raise OSError("hardware probe unavailable")

    monkeypatch.setattr(psutil, "virtual_memory", unavailable_memory)
    blob = repr(web._sys_info())
    for fake in _FABRICATIONS:
        assert fake not in blob, f"_sys_info still fabricates {fake!r}"


def test_host_is_real_or_unknown():
    info = web._sys_info()
    assert info["host"] in (socket.gethostname(), "unknown")


def test_unprobed_backend_and_model_are_unknown_not_faked():
    info = web._sys_info()
    # sys_info does not probe the LLM — so it must say so, not name a model that isn't loaded.
    assert info["backend"] == "unknown" and info["model"] == "unknown"


def test_gpu_is_honest_when_absent():
    """On a host with no NVIDIA GPU (the CI runner), gpu degrades to none/unknown and VRAM
    reads 0 — never a fabricated card."""
    info = web._sys_info()
    assert info["gpu"] in ("none", "unknown") or info["vram_total"] > 0
    if info["gpu"] in ("none", "unknown"):
        assert info["vram_total"] == 0 and info["vram_used"] == 0 and info["gpu_load"] == 0
