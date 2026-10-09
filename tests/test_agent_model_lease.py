"""Agent local generation protects a model before route-aware loading."""

import asyncio

import pytest

from agents.core.agent import Agent
from agents.core.llm.model_manager import ControllerAck, ModelManager


class Controller:
    def __init__(self, *, load_ack=True):
        self.loads = []
        self.unloads = []
        self.load_ack = load_ack
        self.load_started = None
        self.release_load = None

    async def load(self, model):
        self.loads.append(model)
        if self.load_started is not None:
            self.load_started.set()
            await self.release_load.wait()
        return ControllerAck("load", model) if self.load_ack else None

    async def unload(self, model):
        self.unloads.append(model)
        return ControllerAck("unload", model)


def manager(controller, *, enabled=True):
    return ModelManager(controller, enabled=enabled, vram_total_mb=10,
                        vram_reserve_mb=0, size_hints={"a": 10, "b": 10})


class Backend:
    def __init__(self, manager, controller, *, fail=False, hold=None, started=None):
        self.manager = manager
        self.controller = controller
        self.fail = fail
        self.hold = hold
        self.started = started
        self.seen = []

    async def generate(self, *, model, **_kwargs):
        self.seen.append((model, self.manager.is_resident(model) if self.manager else None,
                          self.manager._active_refs.get(model, 0) if self.manager else None,
                          tuple(self.controller.unloads) if self.controller else ()))
        if self.started is not None:
            self.started.set()
        if self.hold is not None:
            await self.hold.wait()
        if self.fail:
            raise ValueError("generation failed")
        return "answer:" + model


class Router:
    def __init__(self, manager, backend, model, *, route="local-deep", pause_after_load=None,
                 loaded=None, guard_error=None, after_load=None):
        self.model_manager = manager
        self.backend = backend
        self.model = model
        self.route = route
        self.pause_after_load = pause_after_load
        self.loaded = loaded
        self.guard_error = guard_error
        self.after_load = after_load
        self.ensure_calls = []

    def select_backend(self, _agent, _prompt):
        return self.backend, self.model, self.route

    async def ensure_resident(self, model, route):
        self.ensure_calls.append((model, route))
        if self.model_manager is not None and route.startswith("local"):
            await self.model_manager.ensure_resident(model)
        if self.after_load is not None:
            self.after_load()
        if self.loaded is not None:
            self.loaded.set()
        if self.pause_after_load is not None:
            await self.pause_after_load.wait()

    def check_data_handling(self, *_args):
        if self.guard_error is not None:
            raise self.guard_error


def agent(router, model="a"):
    return Agent("jarvis", {"name": "Jarvis", "model": model}, llm_router=router)


async def run_path(which, subject):
    if which == "process":
        return await subject.process("hello", {"session_id": "lease"})
    return await subject.synthesize({"jarvis": "", "stark": "fact"}, intent=None)


@pytest.mark.parametrize("which", ["process", "synthesize"])
@pytest.mark.asyncio
async def test_local_model_is_pinned_through_post_load_route_gap(which):
    controller = Controller()
    mgr = manager(controller)
    loaded_a = asyncio.Event()
    resume_a = asyncio.Event()
    backend_a = Backend(mgr, controller)
    backend_b = Backend(mgr, controller)
    a = agent(Router(mgr, backend_a, "a", loaded=loaded_a, pause_after_load=resume_a))
    b = agent(Router(mgr, backend_b, "b"), "b")

    running_a = asyncio.create_task(run_path(which, a))
    try:
        await asyncio.wait_for(loaded_a.wait(), 2)
        assert mgr.is_resident("a")
        assert await asyncio.wait_for(run_path(which, b), 2) == "answer:b"
    finally:
        resume_a.set()
    assert await asyncio.wait_for(running_a, 2) == "answer:a"
    assert "a" not in controller.unloads
    assert backend_a.seen == [("a", True, 1, tuple(controller.unloads))]
    assert mgr._active_refs == {}


@pytest.mark.parametrize("which", ["process", "synthesize"])
@pytest.mark.asyncio
async def test_generation_settings_are_read_after_residency_hook(which):
    controller = Controller()
    mgr = manager(controller)
    settings = {"tokens": 100, "temperature": 0.2}

    class RecordingBackend(Backend):
        async def generate(self, *, max_tokens, temperature, **kwargs):
            self.parameters = (max_tokens, temperature)
            return await super().generate(**kwargs)

    backend = RecordingBackend(mgr, controller)
    router = Router(mgr, backend, "a", after_load=lambda: settings.update(tokens=300, temperature=0.8))
    subject = agent(router)
    subject._gen_params = lambda _route: (settings["tokens"], settings["temperature"])

    assert await run_path(which, subject) == "answer:a"
    assert backend.parameters == (300, 0.8)


@pytest.mark.parametrize("which", ["process", "synthesize"])
@pytest.mark.asyncio
async def test_cancel_during_controller_load_releases_unconfirmed_reference(which):
    controller = Controller()
    controller.load_started = asyncio.Event()
    controller.release_load = asyncio.Event()
    mgr = manager(controller)
    backend = Backend(mgr, controller)
    subject = agent(Router(mgr, backend, "a"))

    running = asyncio.create_task(run_path(which, subject))
    await asyncio.wait_for(controller.load_started.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert mgr._active_refs == {}
    assert mgr.resident_models == []
    assert backend.seen == []
    assert not mgr._lock.locked()


@pytest.mark.parametrize("which", ["process", "synthesize"])
@pytest.mark.parametrize("failure", ["generation", "guard"])
@pytest.mark.asyncio
async def test_generation_or_guard_failure_releases_lease(which, failure):
    controller = Controller()
    mgr = manager(controller)
    backend = Backend(mgr, controller, fail=failure == "generation")
    router = Router(mgr, backend, "a", guard_error=ValueError("guard failed") if failure == "guard" else None)
    subject = agent(router)

    with pytest.raises(ValueError):
        await run_path(which, subject)
    assert mgr._active_refs == {}
    assert mgr._residents["a"].refs == 0
    if failure == "guard":
        assert backend.seen == []


@pytest.mark.parametrize("which", ["process", "synthesize"])
@pytest.mark.parametrize("mode", ["refused", "no_controller"])
@pytest.mark.asyncio
async def test_unconfirmed_load_tracks_only_inflight_reference(which, mode):
    controller = Controller(load_ack=False) if mode == "refused" else None
    mgr = manager(controller)
    backend = Backend(mgr, controller)
    subject = agent(Router(mgr, backend, "a"))

    assert await run_path(which, subject) == "answer:a"
    assert backend.seen == [("a", False, 1, ())]
    assert mgr.resident_models == []
    assert mgr._active_refs == {}
    if controller is not None:
        assert controller.loads == ["a"]


@pytest.mark.parametrize("which", ["process", "synthesize"])
@pytest.mark.asyncio
async def test_two_calls_for_one_model_own_separate_references(which):
    controller = Controller()
    mgr = manager(controller)
    holding = asyncio.Event()
    first_generated = asyncio.Event()
    backend_a = Backend(mgr, controller, hold=holding, started=first_generated)
    backend_b = Backend(mgr, controller)
    first = agent(Router(mgr, backend_a, "a"))
    second = agent(Router(mgr, backend_b, "a"))

    running = asyncio.create_task(run_path(which, first))
    try:
        await asyncio.wait_for(first_generated.wait(), 2)
        assert await run_path(which, second) == "answer:a"
        assert backend_b.seen == [("a", True, 2, ())]
        assert mgr._active_refs == {"a": 1}
        assert controller.loads == ["a"]
    finally:
        holding.set()
    assert await asyncio.wait_for(running, 2) == "answer:a"
    assert mgr._active_refs == {}


@pytest.mark.parametrize("which", ["process", "synthesize"])
@pytest.mark.parametrize("mode", ["cloud", "no_manager", "off"])
@pytest.mark.asyncio
async def test_nonmanaged_paths_keep_generation_without_residency(which, mode):
    controller = Controller()
    mgr = None if mode == "no_manager" else manager(controller, enabled=mode != "off")
    backend = Backend(mgr, controller)
    subject = agent(Router(mgr, backend, "a", route="cloud-flash" if mode == "cloud" else "local"))

    assert await run_path(which, subject) == "answer:a"
    assert controller.loads == []
    assert controller.unloads == []
    assert mgr is None or mgr._active_refs == {}
