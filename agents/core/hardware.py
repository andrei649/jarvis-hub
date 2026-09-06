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

GPU PROBES (model-setup slice) — `detect_gpu` is no longer NVIDIA-only. It walks an
ordered tuple of probes, each a zero-arg callable returning a GPU dict or ``None``
("not applicable on this box"): nvidia-smi, then Apple Silicon (unified memory via
``sysctl -n hw.memsize``, argv only), then AMD (``rocm-smi --showmeminfo vram --csv``).
Every probe runs a fixed argv through `_run_argv` (no shell) and is injectable — a
test passes ``probes=(...)`` or patches `_run_argv`; nothing here fabricates a card.
The returned dict now carries ``kind`` (``nvidia|apple|amd|none|unknown``) so the
model recommender can say *why* it counted unified memory as VRAM.
"""

from __future__ import annotations

import contextlib
import logging
import platform
import shutil
from collections.abc import Callable, Sequence

logger = logging.getLogger("jarvis.hardware")

# Apple Silicon has no discrete VRAM: the GPU draws on unified memory, and Metal's
# default working-set ceiling is roughly three quarters of RAM. This is an ASSUMED
# fraction (it is reported as such in the probe's ``note``), not a measurement.
APPLE_UNIFIED_GPU_FRACTION = 0.75

# Reference points for the 0..100 spec score. Reaching a reference maxes that
# component's weight; they are coarse rungs, not measured limits.
_VRAM_REF_MB = 24_576
_THREADS_REF = 32
_RAM_REF_GB = 64.0

_W_VRAM, _W_THREADS, _W_RAM = 50, 25, 25

_gpu_cache: dict | None = None


def _unprobed_gpu(name: str = "none") -> dict:
    return {"name": name, "kind": name if name in ("none", "unknown") else "unknown",
            "vram_total_mb": None, "vram_used_mb": None, "load_pct": None, "measured": False}


def _run_argv(argv: list[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run a fixed argv (never a shell) and return ``(returncode, stdout)``.

    The single subprocess seam for every probe below — tests patch this one
    name instead of faking ``subprocess`` itself.
    """
    import subprocess  # nosec B404 - fixed argv, no shell

    r = subprocess.run(  # nosec B603 - fixed argv, no shell
        list(argv), capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, r.stdout or ""


def _probe_nvidia() -> dict | None:
    """nvidia-smi → MB. ``None`` when the binary is absent; ``unknown`` when it errors."""
    if shutil.which("nvidia-smi") is None:
        return None
    out = _unprobed_gpu("unknown")
    with contextlib.suppress(Exception):
        code, stdout = _run_argv(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"])
        if code == 0 and stdout.strip():
            parts = [p.strip() for p in stdout.strip().splitlines()[0].split(",")]
            if len(parts) == 4:
                out = {
                    "name": parts[0] or "unknown",
                    "kind": "nvidia",
                    "vram_used_mb": int(float(parts[1])),
                    "vram_total_mb": int(float(parts[2])),
                    "load_pct": int(float(parts[3])),
                    "measured": True,
                }
        else:
            return None
    return out


def _probe_apple() -> dict | None:
    """Apple Silicon: unified memory via ``sysctl -n hw.memsize`` (argv, no shell).

    Only applicable on Darwin/arm64 with ``sysctl`` on PATH. The usable GPU budget
    is ``APPLE_UNIFIED_GPU_FRACTION`` of RAM — an assumption, named in ``note``.
    """
    if platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64"):
        return None
    if shutil.which("sysctl") is None:
        return None
    out = _unprobed_gpu("unknown")
    with contextlib.suppress(Exception):
        code, stdout = _run_argv(["sysctl", "-n", "hw.memsize"])
        if code == 0 and stdout.strip():
            total_mb = int(int(stdout.strip().split()[0]) / (1024 * 1024))
            if total_mb > 0:
                out = {
                    "name": "Apple Silicon (unified memory)",
                    "kind": "apple",
                    "vram_used_mb": None,
                    "vram_total_mb": int(total_mb * APPLE_UNIFIED_GPU_FRACTION),
                    "unified_memory_total_mb": total_mb,
                    "load_pct": None,
                    "measured": True,
                    "note": (f"unified memory: GPU budget assumed at "
                             f"{int(APPLE_UNIFIED_GPU_FRACTION * 100)}% of {total_mb} MB RAM"),
                }
    return out


def _probe_amd() -> dict | None:
    """AMD via ``rocm-smi --showmeminfo vram --csv`` (argv, no shell). Bytes → MB."""
    if shutil.which("rocm-smi") is None:
        return None
    out = _unprobed_gpu("unknown")
    with contextlib.suppress(Exception):
        code, stdout = _run_argv(["rocm-smi", "--showmeminfo", "vram", "--csv"])
        if code == 0 and stdout.strip():
            parsed = _parse_rocm_csv(stdout)
            if parsed is not None:
                total_b, used_b = parsed
                out = {
                    "name": "AMD GPU (rocm-smi)",
                    "kind": "amd",
                    "vram_used_mb": None if used_b is None else int(used_b / (1024 * 1024)),
                    "vram_total_mb": int(total_b / (1024 * 1024)),
                    "load_pct": None,
                    "measured": True,
                }
    return out


def _parse_rocm_csv(text: str) -> tuple[int, int | None] | None:
    """First device row of rocm-smi's CSV: ``(total_bytes, used_bytes|None)``."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    header = [h.strip().lower() for h in lines[0].split(",")]
    total_idx = next((i for i, h in enumerate(header)
                      if "total" in h and "used" not in h and "vram" in h), None)
    used_idx = next((i for i, h in enumerate(header) if "used" in h and "vram" in h), None)
    if total_idx is None:
        return None
    row = [c.strip() for c in lines[1].split(",")]
    if total_idx >= len(row):
        return None
    total = int(float(row[total_idx]))
    if total <= 0:
        return None
    used = None
    if used_idx is not None and used_idx < len(row):
        with contextlib.suppress(ValueError):
            used = int(float(row[used_idx]))
    return total, used


DEFAULT_GPU_PROBES: tuple[Callable[[], dict | None], ...] = (
    _probe_nvidia, _probe_apple, _probe_amd,
)


def detect_gpu(force: bool = False,
               probes: Sequence[Callable[[], dict | None]] | None = None) -> dict:
    """Probe the GPU (NVIDIA → Apple Silicon → AMD). Values in **MB**; never fabricates.

    ``name`` is ``"none"`` when no probe applies to this box (no binary, wrong OS)
    and ``"unknown"`` when a probe's binary is present but the probe errors — the
    same honest degradation `_sys_info()` has always used. Cached after the first
    call so the boot path pays the subprocess cost at most once per process;
    ``force=True`` refreshes (the readiness screen wants live used/load numbers).
    ``probes`` injects the probe order (tests); an injected probe list is never
    cached, so a fake card cannot outlive its test.
    """
    global _gpu_cache
    if probes is None and _gpu_cache is not None and not force:
        return dict(_gpu_cache)
    out = _unprobed_gpu("none")
    for probe in (DEFAULT_GPU_PROBES if probes is None else probes):
        try:
            found = probe()
        except Exception:
            logger.debug("gpu probe %r failed", probe, exc_info=True)
            found = None
        if found is not None:
            out = dict(found)
            break
    if probes is None:
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
