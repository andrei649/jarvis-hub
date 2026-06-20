"""
model_manager.py — H22.5 LRU-evicting residency manager for local model slots.

The hybrid router decides *which* local model a request wants (fast VRAM slot vs.
deep DDR5 slot); the backends (LM Studio / Ollama) load on demand and evict on
their own TTL. Under back-to-back fast→deep→fast traffic on a single GPU this can
thrash (load deep while fast is still resident → near-OOM → slow reload). This
manager mirrors ComfyUI's `model_management.free_memory()` + an LRU policy: it
tracks resident local models with last-used timestamps and **explicitly evicts
the LRU model before loading another**, keeping a VRAM headroom reserve — and it
never evicts the model serving an in-flight request (ref-counting).

Design constraints (H22.5):
  - **Kill-switch.** `JARVIS_MODEL_MANAGER` defaults OFF (GPU-unvalidated). When
    off, `ensure_resident()` is an immediate no-op. The manager is *best-effort*:
    it never raises into the caller — on any failure it falls through to today's
    behavior (the backend's own JIT load).
  - **Injectable controller.** load/unload go through a small controller protocol
    so the logic is unit-tested offline with fakes (no GPU / LM Studio / network).
    The default adapter wraps `LMStudioController`; for Ollama, eviction is a
    `keep_alive: 0` request and load is the H22.2 warm-up.
  - **Coarse headroom.** Headroom + per-model size hints are static for now
    (env `JARVIS_VRAM_RESERVE_MB`, `JARVIS_VRAM_TOTAL_MB`, per-model size hints).
    Refine after measuring on the real card.

All public state mutation is guarded by an asyncio lock so concurrent
`ensure_resident()` / `using()` calls can't race the resident set.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable, Optional, Protocol

logger = logging.getLogger("jarvis.llm.model_manager")

# Coarse, static defaults (MB). The real card is a 24GB GPU; reserve ~2GB of
# headroom so a load never tips into OOM. Both are env-overridable.
DEFAULT_VRAM_TOTAL_MB = 24_576
DEFAULT_VRAM_RESERVE_MB = 2_048
# Fallback size hint for a model we have no estimate for. Deliberately large so
# an unknown model is treated as "needs room" rather than "fits for free".
DEFAULT_MODEL_SIZE_MB = 8_192


def _env_int(name: str, default: int) -> int:
    """Read a non-negative int from the environment, falling back on junk."""
    try:
        v = int(os.environ.get(name, "").strip())
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


def _manager_enabled() -> bool:
    """`JARVIS_MODEL_MANAGER` kill-switch. Default OFF (unset / 0 / false)."""
    return os.environ.get("JARVIS_MODEL_MANAGER", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


class ModelController(Protocol):
    """Minimal load/unload surface the manager drives. Async, best-effort.

    Implementations must never need a real GPU to be *callable* — the default
    adapter delegates to LMStudioController, but tests inject a fake. Return
    value is ignored by the manager; raising is tolerated (logged, swallowed).
    """

    async def load(self, model_id: str) -> object: ...
    async def unload(self, model_id: str) -> object: ...


class LMStudioControllerAdapter:
    """Adapts an `LMStudioController` to the `ModelController` protocol.

    `load` → `controller.load_model(model_id)`; `unload` →
    `controller.unload_model(model_id)`. The controller already carries its own
    kill-switch and never raises, so this is a thin shim. For an Ollama backend,
    pass an adapter whose `unload` issues a `keep_alive: 0` request instead.
    """

    def __init__(self, controller, *, agent: str = "jarvis"):
        self._controller = controller
        self._agent = agent

    async def load(self, model_id: str):
        return await self._controller.load_model(model_id, agent=self._agent)

    async def unload(self, model_id: str):
        return await self._controller.unload_model(model_id, agent=self._agent)


class OllamaControllerAdapter:
    """Adapts an Ollama server to the `ModelController` protocol.

    Ollama has no explicit "unload" verb; instead residency is controlled per
    request via `keep_alive`:

      - **load** mirrors `OllamaBackend.warm_up`: POST `/api/generate` with an
        empty prompt (loads the weights without generating) and `keep_alive: -1`
        so the model is pinned resident and doesn't unload between turns.
      - **unload (evict)** is the same endpoint with `keep_alive: 0`, which tells
        Ollama to drop the model from memory immediately after the (no-op) call.

    The HTTP client is **injectable** so the adapter is unit-tested offline with a
    fake that records calls — no Ollama server, no network. Any client whose
    `post(url, json=...)` is awaitable works (httpx.AsyncClient is the default in
    production, constructed by the caller). Best-effort: a failing request is
    logged and swallowed so the manager falls through to today's JIT behavior.
    """

    def __init__(self, client, *, generate_path: str = "/api/generate"):
        self._client = client
        self._generate_path = generate_path

    async def load(self, model_id: str):
        # Warm-up: empty prompt loads weights without generating; keep_alive=-1
        # pins it resident. Identical contract to OllamaBackend.warm_up.
        return await self._post(model_id, keep_alive=-1)

    async def unload(self, model_id: str):
        # keep_alive=0 → Ollama evicts the model from memory right away.
        return await self._post(model_id, keep_alive=0)

    async def _post(self, model_id: str, *, keep_alive: int):
        try:
            return await self._client.post(
                self._generate_path,
                json={
                    "model": model_id,
                    "prompt": "",
                    "keep_alive": keep_alive,
                    "stream": False,
                },
            )
        except Exception:
            logger.warning(
                "ollama_control: keep_alive=%d request for %s failed",
                keep_alive, model_id, exc_info=True,
            )
            return None


class _Resident:
    """Bookkeeping for one resident model: last-used ts, ref-count, size hint."""

    __slots__ = ("model_id", "last_used", "refs", "size_mb")

    def __init__(self, model_id: str, size_mb: int, now: float):
        self.model_id = model_id
        self.last_used = now
        self.refs = 0
        self.size_mb = size_mb


class ModelManager:
    """LRU-evicting residency tracker for the local model slots.

    Typical use (best-effort, default-off via the kill-switch):

        await manager.ensure_resident("deepseek-r1-distill-qwen-32b")
        async with manager.using(model_id):
            await backend.generate(model=model_id, ...)

    `using()` ref-counts the model for the duration of a generation so it can't
    be evicted mid-flight by a concurrent `ensure_resident()`.
    """

    def __init__(
        self,
        controller: Optional[ModelController] = None,
        *,
        vram_total_mb: Optional[int] = None,
        vram_reserve_mb: Optional[int] = None,
        size_hints: Optional[dict[str, int]] = None,
        default_size_mb: int = DEFAULT_MODEL_SIZE_MB,
        enabled: Optional[bool] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._controller = controller
        self.vram_total_mb = (
            vram_total_mb if vram_total_mb is not None
            else _env_int("JARVIS_VRAM_TOTAL_MB", DEFAULT_VRAM_TOTAL_MB)
        )
        self.vram_reserve_mb = (
            vram_reserve_mb if vram_reserve_mb is not None
            else _env_int("JARVIS_VRAM_RESERVE_MB", DEFAULT_VRAM_RESERVE_MB)
        )
        self._size_hints = dict(size_hints or {})
        self._default_size_mb = default_size_mb
        # Resolve the kill-switch once at construction unless overridden. The
        # caller may pass enabled=True/False explicitly (tests); otherwise the
        # env var decides, default OFF.
        self._enabled = _manager_enabled() if enabled is None else bool(enabled)
        self._clock = clock
        self._residents: dict[str, _Resident] = {}
        self._lock = asyncio.Lock()

    # ── introspection ───────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def resident_models(self) -> list[str]:
        """Resident model ids, LRU-first (oldest last_used at index 0)."""
        return [r.model_id for r in sorted(self._residents.values(), key=lambda r: r.last_used)]

    def is_resident(self, model_id: str) -> bool:
        return model_id in self._residents

    def used_mb(self) -> int:
        """Sum of size hints for all resident models."""
        return sum(r.size_mb for r in self._residents.values())

    def _size_of(self, model_id: str) -> int:
        return self._size_hints.get(model_id, self._default_size_mb)

    def _headroom_ok(self, incoming_mb: int) -> bool:
        """True if loading `incoming_mb` keeps us within total − reserve."""
        budget = self.vram_total_mb - self.vram_reserve_mb
        return self.used_mb() + incoming_mb <= budget

    # ── core API ────────────────────────────────────────────────────
    async def ensure_resident(self, model_id: str) -> None:
        """Make `model_id` resident, evicting LRU models for headroom first.

        No-op (returns immediately) when the kill-switch is off or `model_id`
        is falsy. Best-effort: any controller failure is logged and swallowed so
        the caller falls through to the backend's own JIT load. Never raises.
        """
        if not self._enabled or not model_id:
            return
        try:
            async with self._lock:
                now = self._clock()
                resident = self._residents.get(model_id)
                if resident is not None:
                    resident.last_used = now  # touch: already hot
                    return

                incoming = self._size_of(model_id)
                # Evict LRU models (never ref'd / in-flight) until there's room.
                while not self._headroom_ok(incoming):
                    victim = self._pick_lru_evictable()
                    if victim is None:
                        # Everything resident is pinned in-flight (or nothing is
                        # resident yet but the model is simply too big for the
                        # budget). Stop trying to free; attempt the load anyway —
                        # the backend may overcommit or fail on its own.
                        logger.warning(
                            "model_manager: no evictable model to make room for %s "
                            "(used=%dMB, incoming=%dMB, budget=%dMB) — loading anyway",
                            model_id, self.used_mb(), incoming,
                            self.vram_total_mb - self.vram_reserve_mb,
                        )
                        break
                    await self._evict(victim)

                await self._load(model_id, incoming, now)
        except Exception:
            # Best-effort: never let residency management break a request.
            logger.warning("model_manager: ensure_resident(%s) failed", model_id, exc_info=True)

    def using(self, model_id: str) -> "_ResidencyRef":
        """Async context manager that pins `model_id` for an in-flight request.

        While held, the model's ref-count is > 0 so `ensure_resident()` will
        never evict it. A no-op when the kill-switch is off. Entering does NOT
        load the model — call `ensure_resident()` first if you need it resident;
        `using()` only protects whatever is (or becomes) resident under that id.
        """
        return _ResidencyRef(self, model_id)

    async def acquire(self, model_id: str) -> None:
        """Increment the in-flight ref-count for `model_id` (no-op when off)."""
        if not self._enabled or not model_id:
            return
        async with self._lock:
            resident = self._residents.get(model_id)
            if resident is None:
                # Pin it even if we never explicitly loaded it (the backend may
                # have JIT-loaded it): create a placeholder so it's protected and
                # tracked for LRU once released.
                resident = _Resident(model_id, self._size_of(model_id), self._clock())
                self._residents[model_id] = resident
            resident.refs += 1
            resident.last_used = self._clock()

    async def release(self, model_id: str) -> None:
        """Decrement the in-flight ref-count for `model_id` (no-op when off)."""
        if not self._enabled or not model_id:
            return
        async with self._lock:
            resident = self._residents.get(model_id)
            if resident is None:
                return
            if resident.refs > 0:
                resident.refs -= 1
            resident.last_used = self._clock()

    # ── helpers ─────────────────────────────────────────────────────
    def _pick_lru_evictable(self) -> Optional[_Resident]:
        """Least-recently-used resident with no in-flight refs, or None."""
        candidates = [r for r in self._residents.values() if r.refs == 0]
        if not candidates:
            return None
        return min(candidates, key=lambda r: r.last_used)

    async def _evict(self, resident: _Resident) -> None:
        """Drop a resident from tracking and ask the controller to unload it."""
        self._residents.pop(resident.model_id, None)
        logger.info("model_manager: evicting LRU model %s (%dMB)", resident.model_id, resident.size_mb)
        if self._controller is not None:
            await self._controller.unload(resident.model_id)

    async def _load(self, model_id: str, size_mb: int, now: float) -> None:
        """Ask the controller to load a model and start tracking it as resident."""
        logger.info("model_manager: loading model %s (%dMB)", model_id, size_mb)
        if self._controller is not None:
            await self._controller.load(model_id)
        # Track as resident even if the controller is a no-op stub, so the LRU
        # bookkeeping stays consistent with what the manager believes is hot.
        self._residents[model_id] = _Resident(model_id, size_mb, now)


class _ResidencyRef:
    """Async context manager returned by `ModelManager.using()`."""

    def __init__(self, manager: ModelManager, model_id: str):
        self._manager = manager
        self._model_id = model_id

    async def __aenter__(self) -> "_ResidencyRef":
        await self._manager.acquire(self._model_id)
        return self

    async def __aexit__(self, *exc) -> bool:
        await self._manager.release(self._model_id)
        return False
