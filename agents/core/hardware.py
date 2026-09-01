"""
hardware.py — DRA-44: what card/CPU/RAM this box actually has, and what that
implies for the local-model budget and the usage-mode profile.

Two things were missing before this module existed:
  * `ModelManager` assumed a 24GB card via a static constant, so on an 8GB box
    the headroom arithmetic said an 8GB model fits for free.
  * Nothing scored the host at all, so `system_profiles` (0.62) could only ever
    report which posture is *selected*, never which one the hardware suggests.

HONESTY BOUNDARY — this is a **spec-based** score, not a benchmark. It reads the
numbers the machine already reports (nvidia-smi + psutil): VRAM, logical threads,
RAM. It does NOT measure tokens/sec, load latency or thermal headroom; that needs
a run on the real card with models loaded, which is a benchmark, not code. So the
score reports each component as ``measured``/``not_measured`` rather than
collapsing to one opaque number, and an unmeasured component contributes **zero**
— it is never silently credited. When nothing at all was measured the tier is
``unknown``, not ``low``: "we could not look" and "the box is weak" are different
claims (the same discipline as observability/benchmark.py's MeasurementStatus).

`recommended_profile()` is advisory only. It never writes JARVIS_SYSTEM_PROFILE —
profile selection stays env-driven and read-only, per routers/system_profiles.py.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
from collections.abc import Callable

logger = logging.getLogger("jarvis.hardware")

# Reference points for the 0..100 spec score. Reaching a reference maxes that
# component's weight; they are coarse rungs, not measured limits.
_VRAM_REF_MB = 24_576
_THREADS_REF = 32
_RAM_REF_GB = 64.0

_W_VRAM, _W_THREADS, _W_RAM = 50, 25, 25

_gpu_cache: dict | None = None


def _unprobed_gpu(name: str = "none") -> dict:
    return {"name": name, "vram_total_mb": None, "vram_used_mb": None,
            "load_pct": None, "measured": False}


def detect_gpu(force: bool = False) -> dict:
    """Probe the NVIDIA GPU via nvidia-smi. Values in **MB**; never fabricates.

    ``name`` is ``"none"`` when the binary is absent (or reports nothing) and
    ``"unknown"`` when it is present but the probe errors — the same honest
    degradation `_sys_info()` has always used. Cached after the first call so the
    boot path pays the subprocess cost at most once per process; ``force=True``
    refreshes (the readiness screen wants live used/load numbers).
    """
    global _gpu_cache
    if _gpu_cache is not None and not force:
        return dict(_gpu_cache)
    if shutil.which("nvidia-smi") is None:
        out = _unprobed_gpu("none")
    else:
        out = _unprobed_gpu("unknown")
        with contextlib.suppress(Exception):
            import subprocess  # nosec B404 - fixed argv, no shell
            r = subprocess.run(  # nosec B603 - fixed argv, no shell
                ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
                if len(parts) == 4:
                    out = {
                        "name": parts[0] or "unknown",
                        "vram_used_mb": int(float(parts[1])),
                        "vram_total_mb": int(float(parts[2])),
                        "load_pct": int(float(parts[3])),
                        "measured": True,
                    }
            else:
                out = _unprobed_gpu("none")
    _gpu_cache = dict(out)
    return dict(out)


def detect_hardware(probe: Callable[[], dict] | None = None) -> dict:
    """GPU + CPU threads + RAM, each carrying its own truth (None = not probed).

    `probe` injects the GPU reader so the scoring path is testable with no GPU.
    """
    gpu = (probe or detect_gpu)()
    threads = None
    ram_gb = None
    with contextlib.suppress(Exception):
        import psutil
        threads = psutil.cpu_count(logical=True) or None
        vm = psutil.virtual_memory()
        ram_gb = round(vm.total / 1e9, 1) or None
    return {"gpu": gpu, "cpu_threads": threads, "ram_total_gb": ram_gb}


def score_hardware(hw: dict) -> dict:
    """Deterministic 0..100 spec score + tier + per-component measurement truth."""
    hw = hw or {}
    gpu = hw.get("gpu") or {}
    vram = gpu.get("vram_total_mb") if gpu.get("measured") else None
    threads = hw.get("cpu_threads")
    ram_gb = hw.get("ram_total_gb")

    reasons: list[str] = []
    score = 0.0
    components = {}

    if vram:
        score += _W_VRAM * min(float(vram) / _VRAM_REF_MB, 1.0)
        components["gpu"] = "measured"
        reasons.append(f"{gpu.get('name') or 'GPU'} · {vram} MB VRAM")
    else:
        components["gpu"] = "not_measured"
        reasons.append("no GPU measured — VRAM contributes 0, never assumed")

    if threads:
        score += _W_THREADS * min(float(threads) / _THREADS_REF, 1.0)
        components["cpu"] = "measured"
        reasons.append(f"{threads} logical threads")
    else:
        components["cpu"] = "not_measured"
        reasons.append("cpu threads not measured — contributes 0")

    if ram_gb:
        score += _W_RAM * min(float(ram_gb) / _RAM_REF_GB, 1.0)
        components["ram"] = "measured"
        reasons.append(f"{ram_gb} GB RAM")
    else:
        components["ram"] = "not_measured"
        reasons.append("ram not measured — contributes 0")

    if all(v == "not_measured" for v in components.values()):
        tier = "unknown"
    elif score >= 60:
        tier = "high"
    elif score >= 30:
        tier = "mid"
    else:
        tier = "low"
    return {"score": int(round(score)), "tier": tier, "components": components,
            "reasons": reasons, "basis": "spec-based (VRAM/threads/RAM) — not a throughput benchmark"}


def recommended_profile(hw: dict) -> str:
    """Advisory system-profile suggestion. Always a real `system_profiles` key."""
    from agents.core import system_profiles as sp

    scored = score_hardware(hw)
    if scored["tier"] == "unknown":
        return sp.DEFAULT
    gpu = (hw or {}).get("gpu") or {}
    vram = gpu.get("vram_total_mb") if gpu.get("measured") else None
    threads = (hw or {}).get("cpu_threads") or 0
    if not vram or vram < 10_240:
        name = "headless"
    elif vram >= 20_480 and threads >= 16:
        name = "ai"
    else:
        name = "balanced"
    return name if name in sp.PROFILES else sp.DEFAULT


def detected_vram_total_mb() -> int | None:
    """Total VRAM in MB when actually measured, else None. Never raises."""
    try:
        gpu = detect_gpu()
    except Exception:
        logger.debug("gpu probe failed", exc_info=True)
        return None
    return gpu.get("vram_total_mb") if gpu.get("measured") else None
