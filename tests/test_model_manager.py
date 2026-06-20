"""Tests for ModelManager (H22.5) — LRU residency for the local fast↔deep swap.

Offline by design: load/unload go through an injected fake controller (no GPU /
LM Studio / network), and a fake monotonic clock makes LRU order deterministic.
Covers: kill-switch off = no-op, LRU eviction order, headroom reserve respected,
in-flight (ref'd) model never evicted, load/unload call accounting, the
`using()` ref-count context manager, and the router's best-effort hook.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.model_manager import ModelManager, LMStudioControllerAdapter


class FakeController:
    """Records load/unload calls; never touches a GPU. Optionally raises."""

    def __init__(self, *, raise_on_load=False, raise_on_unload=False):
        self.loads: list[str] = []
        self.unloads: list[str] = []
        self._raise_on_load = raise_on_load
        self._raise_on_unload = raise_on_unload

    async def load(self, model_id: str):
        self.loads.append(model_id)
        if self._raise_on_load:
            raise RuntimeError("boom-load")
        return {"status": "ok"}

    async def unload(self, model_id: str):
        self.unloads.append(model_id)
        if self._raise_on_unload:
            raise RuntimeError("boom-unload")
        return {"status": "ok"}


class FakeClock:
    """Monotonic-ish clock we tick by hand for deterministic LRU ordering."""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def tick(self, dt: float = 1.0) -> float:
        self.t += dt
        return self.t


def _mgr(controller=None, *, enabled=True, total=24_576, reserve=2_048,
         hints=None, default_size=8_192, clock=None):
    return ModelManager(
        controller,
        vram_total_mb=total,
        vram_reserve_mb=reserve,
        size_hints=hints,
        default_size_mb=default_size,
        enabled=enabled,
        clock=clock or FakeClock(),
    )


# ── kill-switch ───────────────────────────────────────────────────

async def test_killswitch_off_is_noop():
    ctrl = FakeController()
    mgr = _mgr(ctrl, enabled=False)
    await mgr.ensure_resident("model-a")
    assert ctrl.loads == [] and ctrl.unloads == []
    assert mgr.resident_models == []
    assert mgr.is_resident("model-a") is False


async def test_killswitch_off_using_is_noop():
    ctrl = FakeController()
    mgr = _mgr(ctrl, enabled=False)
    async with mgr.using("model-a"):
        pass
    assert mgr.resident_models == []


def test_killswitch_defaults_off_from_env(monkeypatch=None):
    # Without an explicit `enabled`, the env var decides. Unset → OFF.
    import os
    os.environ.pop("JARVIS_MODEL_MANAGER", None)
    mgr = ModelManager(FakeController())
    assert mgr.enabled is False


def test_killswitch_env_on():
    import os
    prev = os.environ.get("JARVIS_MODEL_MANAGER")
    os.environ["JARVIS_MODEL_MANAGER"] = "1"
    try:
        mgr = ModelManager(FakeController())
        assert mgr.enabled is True
    finally:
        if prev is None:
            os.environ.pop("JARVIS_MODEL_MANAGER", None)
        else:
            os.environ["JARVIS_MODEL_MANAGER"] = prev


# ── basic residency + touch ───────────────────────────────────────

async def test_ensure_resident_loads_once_then_touches():
    ctrl = FakeController()
    clock = FakeClock()
    mgr = _mgr(ctrl, hints={"a": 1_000}, clock=clock)
    await mgr.ensure_resident("a")
    assert ctrl.loads == ["a"]
    assert mgr.is_resident("a")
    # Second call: already resident → no reload, just a ts touch.
    clock.tick()
    await mgr.ensure_resident("a")
    assert ctrl.loads == ["a"]
    assert ctrl.unloads == []


# ── headroom reserve ──────────────────────────────────────────────

async def test_headroom_allows_models_that_fit_without_eviction():
    # total=10000, reserve=2000 → budget=8000. Two 3000MB models fit (6000).
    ctrl = FakeController()
    mgr = _mgr(ctrl, total=10_000, reserve=2_000, hints={"a": 3_000, "b": 3_000})
    await mgr.ensure_resident("a")
    await mgr.ensure_resident("b")
    assert ctrl.unloads == []  # both fit under budget, nothing evicted
    assert set(mgr.resident_models) == {"a", "b"}
    assert mgr.used_mb() == 6_000


async def test_headroom_reserve_forces_eviction():
    # budget=8000. a+b=6000 fits; adding c=4000 would be 10000 > 8000 → evict LRU.
    ctrl = FakeController()
    clock = FakeClock()
    mgr = _mgr(ctrl, total=10_000, reserve=2_000,
               hints={"a": 3_000, "b": 3_000, "c": 4_000}, clock=clock)
    clock.tick(); await mgr.ensure_resident("a")   # a oldest
    clock.tick(); await mgr.ensure_resident("b")
    clock.tick(); await mgr.ensure_resident("c")   # needs room → evict a (LRU)
    assert ctrl.unloads == ["a"]
    assert mgr.is_resident("a") is False
    assert set(mgr.resident_models) == {"b", "c"}
    assert mgr.used_mb() == 7_000  # b(3000)+c(4000), within budget 8000


# ── LRU eviction order ────────────────────────────────────────────

async def test_lru_eviction_order_respects_recent_use():
    # budget=8000, each model 4000 → only one fits at a time... use 3 of 3000.
    ctrl = FakeController()
    clock = FakeClock()
    mgr = _mgr(ctrl, total=10_000, reserve=2_000,
               hints={"a": 3_000, "b": 3_000, "c": 3_000, "d": 3_000}, clock=clock)
    clock.tick(); await mgr.ensure_resident("a")
    clock.tick(); await mgr.ensure_resident("b")
    # Touch a so b is now the LRU.
    clock.tick(); await mgr.ensure_resident("a")
    # Load c → must evict to fit (a+b+c=9000 > 8000). LRU is b.
    clock.tick(); await mgr.ensure_resident("c")
    assert ctrl.unloads == ["b"]
    assert set(mgr.resident_models) == {"a", "c"}


# ── in-flight (ref'd) model never evicted ─────────────────────────

async def test_inflight_model_never_evicted():
    ctrl = FakeController()
    clock = FakeClock()
    mgr = _mgr(ctrl, total=10_000, reserve=2_000,
               hints={"a": 3_000, "b": 3_000, "c": 4_000}, clock=clock)
    clock.tick(); await mgr.ensure_resident("a")   # a is LRU
    clock.tick(); await mgr.ensure_resident("b")
    # Pin a (in-flight). Now loading c must skip a and evict b instead.
    async with mgr.using("a"):
        clock.tick()
        await mgr.ensure_resident("c")
        assert ctrl.unloads == ["b"]          # b evicted, NOT the pinned LRU a
        assert mgr.is_resident("a") is True
    # After release, a is evictable again.
    assert "a" in mgr.resident_models


async def test_all_resident_pinned_loads_anyway_without_eviction():
    # If everything resident is in-flight, the manager can't free room; it loads
    # the new model anyway (best-effort) rather than blocking or evicting a ref.
    ctrl = FakeController()
    clock = FakeClock()
    mgr = _mgr(ctrl, total=10_000, reserve=2_000,
               hints={"a": 5_000, "b": 5_000}, clock=clock)
    clock.tick(); await mgr.ensure_resident("a")
    async with mgr.using("a"):
        clock.tick()
        await mgr.ensure_resident("b")  # a pinned, no room, can't evict → load b
    assert ctrl.unloads == []
    assert ctrl.loads == ["a", "b"]
    assert mgr.is_resident("b") is True


# ── ref-counting via using() ──────────────────────────────────────

async def test_using_refcount_nested_and_released():
    ctrl = FakeController()
    mgr = _mgr(ctrl, hints={"a": 1_000})
    await mgr.ensure_resident("a")
    async with mgr.using("a"):
        async with mgr.using("a"):
            # Two refs held; an internal eviction scan would skip a.
            assert mgr._pick_lru_evictable() is None
        # One ref still held.
        assert mgr._pick_lru_evictable() is None
    # All refs released → a is evictable again.
    assert mgr._pick_lru_evictable() is not None


# ── best-effort: controller errors are swallowed ──────────────────

async def test_load_failure_is_swallowed():
    ctrl = FakeController(raise_on_load=True)
    mgr = _mgr(ctrl, hints={"a": 1_000})
    # Must not raise; ensure_resident is best-effort.
    await mgr.ensure_resident("a")
    assert ctrl.loads == ["a"]


async def test_unload_failure_is_swallowed_and_load_continues():
    ctrl = FakeController(raise_on_unload=True)
    clock = FakeClock()
    mgr = _mgr(ctrl, total=10_000, reserve=2_000,
               hints={"a": 5_000, "b": 5_000}, clock=clock)
    clock.tick(); await mgr.ensure_resident("a")
    clock.tick(); await mgr.ensure_resident("b")   # evict a → unload raises, swallowed
    assert ctrl.unloads == ["a"]


# ── adapter wraps LMStudioController surface ──────────────────────

async def test_lmstudio_adapter_maps_load_unload():
    class FakeLMS:
        def __init__(self):
            self.calls = []

        async def load_model(self, model, agent="jarvis"):
            self.calls.append(("load", model, agent))
            return {"status": "ok"}

        async def unload_model(self, model, agent="jarvis"):
            self.calls.append(("unload", model, agent))
            return {"status": "ok"}

    lms = FakeLMS()
    adapter = LMStudioControllerAdapter(lms, agent="jarvis")
    await adapter.load("m/x")
    await adapter.unload("m/x")
    assert lms.calls == [("load", "m/x", "jarvis"), ("unload", "m/x", "jarvis")]


# ── router hook (HybridRouter.ensure_resident) ────────────────────

async def test_router_hook_only_acts_on_local_routes():
    from core.llm.hybrid_router import HybridRouter
    ctrl = FakeController()
    mgr = _mgr(ctrl, hints={"deep": 1_000})
    router = HybridRouter()
    router.attach_model_manager(mgr)

    # Cloud route: hook is a no-op (nothing to swap).
    await router.ensure_resident("gemini-2.5-flash", "cloud-flash")
    assert ctrl.loads == []

    # Local route: hook makes the model resident.
    await router.ensure_resident("deep", "local-deep")
    assert ctrl.loads == ["deep"]


async def test_router_hook_noop_without_manager():
    from core.llm.hybrid_router import HybridRouter
    router = HybridRouter()
    # No manager attached → silently no-op, never raises.
    await router.ensure_resident("anything", "local")
    assert router.model_manager is None
