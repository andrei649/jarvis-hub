"""model_setup.py — hardware-tiered local-model recommendation + governed Ollama pull.

Zero-key first value needs a *resident* local model within minutes of install.
Before this module nothing mapped the box to a model, nothing pulled one, and the
GPU probe was NVIDIA-only (see hardware.py's Apple/AMD probes, same slice).

Three honesty boundaries, stated once here and echoed in every payload:

* **Spec-based, not benchmarked.** `recommend_model` reads the VRAM/RAM numbers
  the machine reports and picks a rung from `TIERS`. It never claims tokens/sec;
  the ``basis`` string travels with the recommendation so no surface can drop it.
* **Loopback only.** A pull is a host-side download of gigabytes onto *this* disk.
  `ollama_present` / `ollama_pull` refuse any Ollama URL that is not loopback with
  ``ollama_url_not_loopback`` — there is no LAN mode for this path.
* **Every pull crosses the Action Kernel.** `MODEL_PULL_KIND` + `MODEL_PULL_CONTRACT`
  are defined here; the capability manifest lives with every other action kind in
  `capability_manifests.ACTION_CAPABILITY_MANIFESTS`, and the router binds
  `ModelSetupService.handle_pull` on a `CapabilityActionAPI` whose authorizer is the
  injected kernel hook (`make_action_kernel(orch)`). Nothing in this file self-authorizes: the
  handler is only reachable through the facade, and the facade refuses when the
  kernel/unified-action flags are off. Rollback is honest ``compensate`` — the
  pulled blobs are deleted through `ollama_delete` (``ollama rm`` over HTTP).

Runtime posture is default-off: the HTTP route refuses ``model_pull_disabled``
unless ``JARVIS_MODEL_PULL`` is set (see routers/model_setup.py). The size cap
(``llm.model_pull_max_gb``, default 20) is enforced from the pull stream's own
layer totals — Ollama exposes no size for a model that is not yet local, so the
first layer whose cumulative total exceeds the cap aborts the pull.

No new hard dependency: ``httpx`` (already pinned) is imported lazily where the
network call happens, and every I/O seam is injectable for hermetic tests.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    predicate,
)

logger = logging.getLogger("jarvis.llm.model_setup")

MODEL_PULL_KIND = "model.pull"
MODEL_PULL_CAPABILITY_ID = f"action:{MODEL_PULL_KIND}"
MODEL_PULL_ENV = "JARVIS_MODEL_PULL"
MODEL_PULL_MAX_GB_DEFAULT = 20
DEFAULT_OLLAMA_URL = "http://localhost:11434"
RECOMMENDATION_BASIS = "spec-based, not benchmarked"

# Same alphabet ollama_control accepts — an Ollama tag, never a path or a flag.
_MODEL_RE = re.compile(r"^[A-Za-z0-9._/:@\-]{1,200}$")
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})
_GB = 1024 ** 3


# ── the tier table ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelTier:
    """One rung: the smallest measured VRAM (MB) that earns it, and what it pulls.

    ``approx_gb`` is the published Q4 download size — a catalogue number used for
    the size-cap preview, not a measurement of this box.
    """

    name: str
    min_vram_mb: int
    model: str
    approx_gb: float
    note: str

    def __post_init__(self) -> None:
        if not self.name or not _MODEL_RE.fullmatch(self.model):
            raise ValueError("tier needs a name and a valid model tag")
        if self.min_vram_mb < 0 or self.approx_gb <= 0:
            raise ValueError("tier thresholds must be non-negative / positive")


# Ordered smallest → largest. The recommender walks it from the top and keeps
# the largest rung whose threshold the measured VRAM clears.
TIERS: tuple[ModelTier, ...] = (
    ModelTier("cpu-only", 0, "qwen2.5:3b", 1.9,
              "no usable GPU measured — a small model resident on CPU/RAM"),
    ModelTier("8gb", 6_144, "qwen2.5:7b", 4.7, "fits an 8 GB card at Q4 with KV-cache headroom"),
    ModelTier("12-16gb", 11_264, "qwen2.5:14b", 9.0, "fits a 12–16 GB card at Q4"),
    ModelTier("24gb+", 22_528, "gemma-4-31b-a4b", 19.0,
              "a 24 GB+ card: sparse 31B (4B active) at Q4"),
)


def recommend_model(hw: Mapping[str, Any] | None) -> dict:
    """Map a `hardware.detect_hardware()` dict to a tier. Pure; never probes.

    Unmeasured VRAM lands on ``cpu-only`` — "we could not look" must not be
    upgraded into a card we never saw. Apple unified memory is already reduced
    to a GPU budget by the probe, so it is treated like measured VRAM here and
    the reason says so.
    """
    hw = dict(hw or {})
    gpu = dict(hw.get("gpu") or {})
    measured = bool(gpu.get("measured")) and isinstance(gpu.get("vram_total_mb"), int)
    vram = int(gpu["vram_total_mb"]) if measured else 0
    kind = str(gpu.get("kind") or ("none" if not measured else "unknown"))
    ram_gb = hw.get("ram_total_gb")

    tier = TIERS[0]
    for candidate in TIERS:
        if measured and vram >= candidate.min_vram_mb:
            tier = candidate
    reasons: list[str] = []
    if measured:
        reasons.append(f"{gpu.get('name') or 'GPU'} · {vram} MB usable VRAM ({kind})")
        if kind == "apple":
            reasons.append(str(gpu.get("note") or "unified memory counted as GPU budget"))
    else:
        reasons.append("no GPU measured — VRAM treated as 0, never assumed")
    if isinstance(ram_gb, (int, float)) and not isinstance(ram_gb, bool) and ram_gb:
        reasons.append(f"{ram_gb} GB RAM")
        if tier.name == "cpu-only" and ram_gb < 8:
            reasons.append("under 8 GB RAM: even the 3B model will page — expect slow replies")
    else:
        reasons.append("RAM not measured")
    reasons.append(tier.note)
    return {
        "tier": tier.name,
        "model": tier.model,
        "approx_gb": tier.approx_gb,
        "gpu_kind": kind,
        "vram_mb": vram if measured else None,
        "basis": RECOMMENDATION_BASIS,
        "reasons": reasons,
    }


def tier_table() -> list[dict]:
    """The rungs as plain dicts (the HUD shows the whole ladder, not just the pick)."""
    return [
        {"tier": t.name, "min_vram_mb": t.min_vram_mb, "model": t.model,
         "approx_gb": t.approx_gb, "note": t.note}
        for t in TIERS
    ]


# ── loopback + model-id validation ───────────────────────────────────────────

def is_loopback_url(url: str) -> bool:
    """True only for ``http(s)://`` URLs whose host is a loopback name or address."""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def valid_model_tag(model: Any) -> bool:
    """An Ollama tag (``name[:tag]``, optional ``namespace/``) — never a path or a flag.

    Stricter than ollama_control's alphabet: no ``..`` segments, no leading
    ``/``/``.``/``-``, no empty segment between slashes or around the colon.
    """
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
        return False
    if model[0] in "/.-:@" or ".." in model or model.count(":") > 1:
        return False
    name, _, tag = model.partition(":")
    segments_ok = all(name.split("/"))
    return segments_ok and (":" not in model or bool(tag))


def _max_bytes_ok(view: Mapping[str, Any], now: float) -> bool:
    v = view.get("max_bytes")
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


MODEL_PULL_CONTRACT = ContractTemplate(
    kind=MODEL_PULL_KIND,
    description="Pull a local model into the loopback Ollama store, under a size cap.",
    constraints=(
        field_present("model", "url"),
        predicate("model_tag_valid", lambda v, now: valid_model_tag(v.get("model")),
                  reason="invalid_model_tag"),
        predicate("ollama_url_loopback", lambda v, now: is_loopback_url(v.get("url")),
                  reason="ollama_url_not_loopback"),
        predicate("max_bytes_positive", _max_bytes_ok, reason="invalid_max_bytes"),
    ),
)

# ── Ollama HTTP (loopback only, injectable client) ───────────────────────────

def _client(url: str, client: Any, timeout: float):
    if client is not None:
        return client, False
    import httpx  # lazy: only the network path needs it

    return httpx.AsyncClient(base_url=url.rstrip("/"), timeout=timeout, trust_env=False), True


def _model_names(payload: Any) -> list[str]:
    rows = payload.get("models") if isinstance(payload, dict) else None
    names: list[str] = []
    for row in rows or []:
        if isinstance(row, dict):
            name = str(row.get("name") or row.get("model") or "").strip()
            if name and valid_model_tag(name):
                names.append(name)
    return sorted(set(names))


async def ollama_present(url: str = DEFAULT_OLLAMA_URL, *, client: Any = None,
                         timeout: float = 3.0) -> dict:
    """``GET /api/tags`` on a loopback Ollama. Never raises; ``present`` is a fact."""
    url = str(url or "").strip() or DEFAULT_OLLAMA_URL
    if not is_loopback_url(url):
        return {"present": False, "url": url, "models": [], "reason": "ollama_url_not_loopback"}
    http, owned = _client(url, client, timeout)
    try:
        response = await http.get("/api/tags")
        if response.status_code != 200:
            return {"present": False, "url": url, "models": [],
                    "reason": f"ollama_http_{response.status_code}"}
        return {"present": True, "url": url, "models": _model_names(response.json()),
                "reason": ""}
    except Exception:
        logger.debug("ollama presence probe failed", exc_info=True)
        return {"present": False, "url": url, "models": [], "reason": "ollama_unreachable"}
    finally:
        if owned:
            await http.aclose()


ProgressCb = Callable[[dict], None]


async def ollama_pull(url: str, model: str, *, progress_cb: ProgressCb | None = None,
                      max_bytes: int | None = None, client: Any = None,
                      timeout: float = 600.0) -> dict:
    """Stream ``POST /api/pull`` and enforce the size cap from the stream's own totals.

    Ollama publishes no size for a model that is not yet local, so the cap is
    applied to the cumulative ``total`` of distinct layer digests as they appear;
    the first layer that pushes the sum over ``max_bytes`` aborts the pull with
    ``model_too_large`` (closing the stream cancels Ollama's download). Returns a
    dict, never raises; ``progress_cb`` receives each parsed status line.
    """
    url = str(url or "").strip() or DEFAULT_OLLAMA_URL
    if not valid_model_tag(model):
        return {"ok": False, "model": model, "reason": "invalid_model_tag"}
    if not is_loopback_url(url):
        return {"ok": False, "model": model, "reason": "ollama_url_not_loopback"}
    if max_bytes is not None and (isinstance(max_bytes, bool) or not isinstance(max_bytes, int)
                                  or max_bytes <= 0):
        return {"ok": False, "model": model, "reason": "invalid_max_bytes"}

    http, owned = _client(url, client, timeout)
    layers: dict[str, int] = {}
    completed: dict[str, int] = {}
    last_status = ""
    try:
        async with http.stream("POST", "/api/pull",
                               json={"model": model, "stream": True}) as response:
            if response.status_code != 200:
                return {"ok": False, "model": model,
                        "reason": f"ollama_http_{response.status_code}"}
            async for line in response.aiter_lines():
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    return {"ok": False, "model": model, "reason": "ollama_error",
                            "detail": str(event.get("error"))[:200]}
                last_status = str(event.get("status") or "")
                digest = str(event.get("digest") or "")
                total = event.get("total")
                if digest and isinstance(total, int) and not isinstance(total, bool) and total > 0:
                    layers[digest] = total
                    done = event.get("completed")
                    if isinstance(done, int) and not isinstance(done, bool):
                        completed[digest] = max(0, min(done, total))
                bytes_total = sum(layers.values())
                bytes_done = sum(completed.values())
                if progress_cb is not None:
                    progress_cb({"status": last_status, "bytes_total": bytes_total,
                                 "bytes_completed": bytes_done})
                if max_bytes is not None and bytes_total > max_bytes:
                    return {"ok": False, "model": model, "reason": "model_too_large",
                            "bytes_total": bytes_total, "max_bytes": max_bytes}
                if last_status == "success":
                    return {"ok": True, "model": model, "status": "success",
                            "bytes_total": bytes_total, "bytes_completed": bytes_done}
        return {"ok": False, "model": model, "reason": "ollama_stream_ended",
                "status": last_status, "bytes_total": sum(layers.values())}
    except Exception:
        logger.debug("ollama pull failed", exc_info=True)
        return {"ok": False, "model": model, "reason": "ollama_unreachable"}
    finally:
        if owned:
            await http.aclose()


async def ollama_delete(url: str, model: str, *, client: Any = None,
                        timeout: float = 30.0) -> dict:
    """The compensate rollback: ``DELETE /api/delete`` on the loopback store."""
    url = str(url or "").strip() or DEFAULT_OLLAMA_URL
    if not valid_model_tag(model):
        return {"ok": False, "model": model, "reason": "invalid_model_tag"}
    if not is_loopback_url(url):
        return {"ok": False, "model": model, "reason": "ollama_url_not_loopback"}
    http, owned = _client(url, client, timeout)
    try:
        response = await http.request("DELETE", "/api/delete", json={"model": model})
        if response.status_code not in (200, 404):
            return {"ok": False, "model": model, "reason": f"ollama_http_{response.status_code}"}
        return {"ok": True, "model": model, "deleted": response.status_code == 200}
    except Exception:
        logger.debug("ollama delete failed", exc_info=True)
        return {"ok": False, "model": model, "reason": "ollama_unreachable"}
    finally:
        if owned:
            await http.aclose()


# ── the pull job (one at a time, in-process) ─────────────────────────────────

PULL_STATES = ("running", "done", "failed")
_TERMINAL = frozenset({"done", "failed"})


@dataclass
class PullJob:
    id: str
    model: str
    started_at: float
    status: str = "running"
    bytes_total: int = 0
    bytes_completed: int = 0
    stage: str = ""
    reason: str = ""
    finished_at: float | None = None
    task: Any = field(default=None, repr=False, compare=False)

    def snapshot(self) -> dict:
        return {
            "id": self.id, "model": self.model, "status": self.status,
            "bytes_total": self.bytes_total, "bytes_completed": self.bytes_completed,
            "stage": self.stage, "reason": self.reason,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }


SpawnFn = Callable[[Awaitable[Any]], Awaitable[Any]]


async def _default_spawn(coro: Awaitable[Any]) -> Any:
    return asyncio.create_task(coro)


class ModelSetupService:
    """Plan + governed pull. Every I/O seam is injected; the kernel is NOT.

    The service never authorizes anything: `handle_pull` is the implementation
    the router binds on a `CapabilityActionAPI`, and only a kernel GRANT reaches
    it. It still re-checks the contract (defence in depth, like ollama_control).
    """

    def __init__(
        self,
        *,
        ollama_url: Callable[[], str] | str = DEFAULT_OLLAMA_URL,
        max_gb: Callable[[], float] | float = MODEL_PULL_MAX_GB_DEFAULT,
        hardware_fn: Callable[[], dict] | None = None,
        present_fn: Callable[..., Awaitable[dict]] = ollama_present,
        pull_fn: Callable[..., Awaitable[dict]] = ollama_pull,
        spawn: SpawnFn = _default_spawn,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ollama_url = ollama_url
        self._max_gb = max_gb
        self._hardware_fn = hardware_fn
        self._present_fn = present_fn
        self._pull_fn = pull_fn
        self._spawn = spawn
        self._clock = clock
        self._lock = threading.Lock()
        self._job: PullJob | None = None

    # ── configuration reads (live, never cached) ──
    def ollama_url(self) -> str:
        value = self._ollama_url() if callable(self._ollama_url) else self._ollama_url
        return str(value or "").strip() or DEFAULT_OLLAMA_URL

    def max_bytes(self) -> int:
        value = self._max_gb() if callable(self._max_gb) else self._max_gb
        try:
            gb = float(value)
        except (TypeError, ValueError):
            gb = float(MODEL_PULL_MAX_GB_DEFAULT)
        if gb <= 0:
            gb = float(MODEL_PULL_MAX_GB_DEFAULT)
        return int(gb * _GB)

    def hardware(self) -> dict:
        if self._hardware_fn is not None:
            return self._hardware_fn()
        from agents.core import hardware

        return hardware.detect_hardware()

    # ── the plan (read-only) ──
    async def plan(self, *, enabled: bool) -> dict:
        hw = self.hardware()
        rec = recommend_model(hw)
        presence = await self._present_fn(self.ollama_url())
        installed = list(presence.get("models") or [])
        return {
            "hardware": hw,
            "recommendation": rec,
            "tiers": tier_table(),
            "ollama": presence,
            "recommended_installed": _installed(rec["model"], installed),
            "pull": {
                "enabled": bool(enabled),
                "max_gb": round(self.max_bytes() / _GB, 2),
                "job": self.job_snapshot(),
                "hint": None if enabled else f"set {MODEL_PULL_ENV}=1 to allow governed pulls",
            },
            "basis": RECOMMENDATION_BASIS,
        }

    def job_snapshot(self) -> dict | None:
        with self._lock:
            return self._job.snapshot() if self._job is not None else None

    def pull_in_progress(self) -> bool:
        with self._lock:
            return self._job is not None and self._job.status not in _TERMINAL

    # ── the bound implementation (reached only through the facade) ──
    async def handle_pull(self, params: Mapping[str, Any], context: Any = None) -> dict:
        payload = dict(params or {})
        model = payload.get("model")
        url = str(payload.get("url") or self.ollama_url())
        max_bytes = payload.get("max_bytes", self.max_bytes())
        decision = MODEL_PULL_CONTRACT.evaluate(
            {"model": model, "url": url, "max_bytes": max_bytes})
        reason = contract_denial(decision)
        if reason:
            return {"ok": False, "reason": reason, "model": model}
        if self.pull_in_progress():
            return {"ok": False, "reason": "pull_in_progress", "job": self.job_snapshot()}
        presence = await self._present_fn(url)
        if not presence.get("present"):
            return {"ok": False, "reason": presence.get("reason") or "ollama_unreachable",
                    "model": model}
        if _installed(model, presence.get("models") or []):
            return {"ok": True, "already_installed": True, "model": model, "started": False}
        job = PullJob(id=uuid.uuid4().hex[:12], model=model, started_at=self._clock())
        with self._lock:
            self._job = job
        job.task = await self._spawn(self._run(job, url, int(max_bytes)))
        return {"ok": True, "started": True, "model": model, "job": job.snapshot()}

    async def _run(self, job: PullJob, url: str, max_bytes: int) -> None:
        def _progress(event: dict) -> None:
            with self._lock:
                job.stage = str(event.get("status") or "")
                job.bytes_total = int(event.get("bytes_total") or 0)
                job.bytes_completed = int(event.get("bytes_completed") or 0)

        try:
            result = await self._pull_fn(url, job.model, progress_cb=_progress,
                                         max_bytes=max_bytes)
        except Exception:
            logger.exception("model pull crashed: %s", job.model)
            result = {"ok": False, "reason": "pull_crashed"}
        with self._lock:
            job.finished_at = self._clock()
            if result.get("ok"):
                job.status = "done"
                job.stage = "success"
                job.bytes_total = int(result.get("bytes_total") or job.bytes_total)
                job.bytes_completed = int(result.get("bytes_completed") or job.bytes_total)
            else:
                job.status = "failed"
                job.reason = str(result.get("reason") or "pull_failed")


def _installed(model: Any, installed: list[str]) -> bool:
    if not isinstance(model, str) or not model:
        return False
    want = model if ":" in model else f"{model}:latest"
    have = {m if ":" in m else f"{m}:latest" for m in installed}
    return want in have
