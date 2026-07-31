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

from core.llm.model_manager import (
    ModelManager,
    LMStudioControllerAdapter,
    OllamaControllerAdapter,
)


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


# ── Ollama controller adapter (keep_alive load/evict) ─────────────

class FakeOllamaClient:
    """Records POSTs; never touches a network. Mimics httpx.AsyncClient.post:
    an awaitable returning an object with raise_for_status()."""

    class _Resp:
        def raise_for_status(self):
            return None

    def __init__(self, *, raise_on_post=False):
        self.posts: list[tuple[str, dict]] = []
        self._raise = raise_on_post

    async def post(self, url, json=None):
        self.posts.append((url, json))
        if self._raise:
            raise RuntimeError("boom-post")
        return self._Resp()


async def test_ollama_adapter_unload_issues_keep_alive_zero():
    client = FakeOllamaClient()
    adapter = OllamaControllerAdapter(client)
    await adapter.unload("llama3.1:8b")
    assert len(client.posts) == 1
    url, body = client.posts[0]
    assert url == "/api/generate"
    assert body == {
        "model": "llama3.1:8b",
        "prompt": "",
        "keep_alive": 0,
        "stream": False,
    }


async def test_ollama_adapter_load_warms_with_keep_alive_minus_one():
    # load() mirrors OllamaBackend.warm_up: empty prompt + keep_alive=-1.
    client = FakeOllamaClient()
    adapter = OllamaControllerAdapter(client)
    await adapter.load("qwen2.5:14b")
    assert len(client.posts) == 1
    url, body = client.posts[0]
    assert url == "/api/generate"
    assert body == {
        "model": "qwen2.5:14b",
        "prompt": "",
        "keep_alive": -1,
        "stream": False,
    }


async def test_ollama_adapter_post_failure_is_swallowed():
    # The adapter is best-effort: a failing HTTP client never raises into the
    # manager (which falls through to Ollama's own JIT load on its TTL).
    client = FakeOllamaClient(raise_on_post=True)
    adapter = OllamaControllerAdapter(client)
    assert await adapter.load("m") is None
    assert await adapter.unload("m") is None
    assert len(client.posts) == 2


async def test_ollama_adapter_drives_manager_eviction():
    # Wire the Ollama adapter into the manager and force an LRU eviction: the
    # evicted model must get a keep_alive:0 POST, the loaded ones keep_alive:-1.
    client = FakeOllamaClient()
    adapter = OllamaControllerAdapter(client)
    clock = FakeClock()
    mgr = _mgr(adapter, total=10_000, reserve=2_000,
               hints={"a": 5_000, "b": 5_000}, clock=clock)
    clock.tick(); await mgr.ensure_resident("a")   # load a (keep_alive=-1)
    clock.tick(); await mgr.ensure_resident("b")   # evict a (keep_alive=0), load b
    keep_alives = [(body["model"], body["keep_alive"]) for _, body in client.posts]
    assert keep_alives == [("a", -1), ("a", 0), ("b", -1)]
    assert mgr.is_resident("a") is False
    assert mgr.is_resident("b") is True


# ── synthesize() residency hook (mirror of process()) ─────────────

class _FakeBackend:
    """Records the model it was asked to generate with."""

    def __init__(self):
        self.calls: list[str] = []

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.calls.append(model)
        return "synthesized reply"


class _FakeRouter:
    """Minimal HybridRouter surface the Agent's synthesize() touches: a fixed
    route decision, the best-effort ensure_resident hook, and model_manager."""

    def __init__(self, backend, route_name, manager):
        self._backend = backend
        self._route_name = route_name
        self._manager = manager

    @property
    def model_manager(self):
        return self._manager

    def select_backend(self, agent_id, prompt):
        return (self._backend, "deep-local-model", self._route_name)

    async def ensure_resident(self, model, route):
        if self._manager is None or not route.startswith("local"):
            return
        await self._manager.ensure_resident(model)


def _agent(router):
    from core.agent import Agent
    # config only — _load_soul is best-effort and missing SOUL.md is fine offline.
    agent = Agent("jarvis", {"name": "Jarvis", "model": "deep-local-model"}, llm_router=router)
    return agent


# These three exercise the model-manager residency hook inside synthesize, which is
# orthogonal to routing policy. They used `howard` as the contributor — and howard is in
# LOCAL_ONLY_AGENTS, so under the SEC-B1 floor every one of them would now be pinned local
# and the "cloud route" case could not exist. `stark` is not strict-local, so the route
# under test is the one the router is configured to return, which is the point.


async def test_synthesize_hook_noop_when_killswitch_off():
    # Manager attached but disabled → ensure_resident is a no-op, using() doesn't
    # ref-count, and synthesize still produces a reply (today's behavior).
    ctrl = FakeController()
    mgr = _mgr(ctrl, enabled=False, hints={"deep-local-model": 1_000})
    backend = _FakeBackend()
    router = _FakeRouter(backend, "local-deep", mgr)
    agent = _agent(router)

    out = await agent.synthesize({"jarvis": "", "stark": "fact A"}, intent=None)
    assert out == "synthesized reply"
    assert backend.calls == ["deep-local-model"]
    # Disabled: nothing loaded, nothing tracked.
    assert ctrl.loads == []
    assert mgr.resident_models == []


async def test_synthesize_hook_refcounts_model_when_enabled():
    # Kill-switch on + local route → ensure_resident loads the model and using()
    # ref-counts it for the duration of the generate.
    ctrl = FakeController()
    mgr = _mgr(ctrl, enabled=True, hints={"deep-local-model": 1_000})

    seen_refs = {}

    class _AssertingBackend(_FakeBackend):
        async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
            # Inside generate the model must be pinned (refs > 0) so a concurrent
            # ensure_resident can't evict it mid-flight.
            seen_refs["refs"] = mgr._residents[model].refs
            return await super().generate(model, prompt, system, max_tokens, temperature)

    backend = _AssertingBackend()
    router = _FakeRouter(backend, "local-deep", mgr)
    agent = _agent(router)

    out = await agent.synthesize({"jarvis": "", "stark": "fact A"}, intent=None)
    assert out == "synthesized reply"
    assert ctrl.loads == ["deep-local-model"]
    assert seen_refs["refs"] == 1            # pinned during generate
    assert mgr.is_resident("deep-local-model") is True
    assert mgr._residents["deep-local-model"].refs == 0  # released after


async def test_synthesize_hook_noop_on_cloud_route_when_enabled():
    # Even with the kill-switch on, a non-local (cloud) route has nothing to swap:
    # ensure_resident must not load, and using() must not be wrapped.
    ctrl = FakeController()
    mgr = _mgr(ctrl, enabled=True, hints={"deep-local-model": 1_000})
    backend = _FakeBackend()
    router = _FakeRouter(backend, "cloud-flash", mgr)
    agent = _agent(router)

    out = await agent.synthesize({"jarvis": "", "stark": "fact A"}, intent=None)
    assert out == "synthesized reply"
    assert ctrl.loads == []
    assert mgr.resident_models == []
