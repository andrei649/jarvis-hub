"""H414 — the plugin LLM facade: a trusted in-tree plugin's own model call, on the rail.

Hermes hands a plugin ``ctx.llm`` for its own completions. Nerva's third-party
extensions get no ``ctx`` at all (the sandbox never sees a host object), so the
supported lane is for the in-tree plugins the hub builds itself: ``PluginManager``
hands a plugin whose manifest declares ``llm_access`` a small facade whose
``complete()`` and ``stream()`` go through ``run_oneshot`` — strict-local, the auxiliary
consent boundary, job pins excluded — labelled ``plugin:<id>`` in the usage ledger. A
plugin without the declaration, or one the gate has switched off (the load set, safe
mode), gets a clear error and no call. Hermetic: a loopback backend double, no model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import plugin_manager as pm
from agents.core.llm import auxiliary_text
from agents.core.llm.providers import get_profile
from agents.core.plugin_gate import (
    BUILTIN_PLUGINS,
    DataScope,
    NetworkAccess,
    PermissionGate,
    PluginManifest,
)


def _manifest(plugin_id="probe", **overrides):
    fields = {"id": plugin_id, "name": "Probe", "version": "0.1.0", "description": "a test plugin",
              "network_access": NetworkAccess.NONE, "data_scope": DataScope.LOCAL_ONLY,
              "agents_served": ["all"], "llm_access": True}
    fields.update(overrides)
    return PluginManifest(**fields)


@pytest.fixture
def rail(monkeypatch):
    monkeypatch.delenv("JARVIS_AUX_ONESHOT_MODEL", raising=False)
    monkeypatch.setattr(auxiliary_text, "_ONESHOT_USAGE", {})
    calls = []

    async def generate(**kwargs):
        calls.append(("generate", kwargs))
        return "local answer"

    async def generate_stream(**kwargs):
        calls.append(("stream", kwargs))
        await kwargs["on_token"]("local ")
        await kwargs["on_token"]("answer")
        return "local answer"

    backend = SimpleNamespace(profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
                              generate=generate, generate_stream=generate_stream)
    router = SimpleNamespace(local_backend=backend, active_model="active-local",
                             _backend=backend, _local_model="active-local")
    return SimpleNamespace(router=router, backend=backend, calls=calls)


@pytest.fixture
def manager(rail, monkeypatch):
    gate = PermissionGate(least_privilege=False)
    gate.register(_manifest())
    gate.register(_manifest("mute", llm_access=False))
    orch = SimpleNamespace(permission_gate=gate, llm_router=rail.router)
    manager = pm.PluginManager()
    manager.bind_llm(orch)
    return SimpleNamespace(manager=manager, gate=gate, orch=orch)


def test_no_shipped_plugin_declares_model_access_yet():
    assert PluginManifest.__dataclass_fields__["llm_access"].default is False
    assert not any(manifest.llm_access for manifest in BUILTIN_PLUGINS.values())


async def test_a_declared_plugin_completes_on_the_rail_under_its_own_purpose(manager, rail):
    llm = manager.manager.llm_for("probe")
    answer = await llm.complete("private prompt", system="plugin system", max_tokens=32, temperature=0.3)
    assert answer == "local answer"
    assert rail.calls == [("generate", {
        "model": "active-local", "system": "plugin system", "prompt": "private prompt",
        "max_tokens": 32, "temperature": 0.3,
    })]
    assert auxiliary_text.oneshot_usage()["plugin:probe"]["answered"] == 1


async def test_a_declared_plugin_streams_to_its_own_hook_on_the_rail(manager, rail):
    seen = []

    async def on_token(text):
        seen.append(text)

    llm = manager.manager.llm_for("probe")
    assert await llm.stream("private prompt", on_token=on_token, max_tokens=16) == "local answer"
    assert seen == ["local ", "answer"]
    assert rail.calls[0][0] == "stream"
    assert auxiliary_text.oneshot_usage()["plugin:probe"]["calls"] == 1


async def test_a_plugin_without_the_declaration_gets_a_clear_error_and_no_call(manager, rail):
    llm = manager.manager.llm_for("mute")
    with pytest.raises(pm.PluginLLMRefused, match="mute does not declare llm_access"):
        await llm.complete("private prompt")
    with pytest.raises(pm.PluginLLMRefused, match="does not declare llm_access"):
        await llm.stream("private prompt", on_token=lambda text: None)
    assert rail.calls == [] and auxiliary_text.oneshot_usage() == {}


async def test_an_unknown_or_switched_off_plugin_is_refused(manager, rail):
    with pytest.raises(pm.PluginLLMRefused, match="unknown plugin"):
        await manager.manager.llm_for("ghost").complete("p")
    manager.gate.plugins["probe"].enabled = False
    with pytest.raises(pm.PluginLLMRefused, match="probe is switched off"):
        await manager.manager.llm_for("probe").complete("p")
    assert rail.calls == []


async def test_safe_mode_switches_the_facade_off_with_the_plugins(rail, monkeypatch):
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    gate = PermissionGate(least_privilege=False)
    gate.register(_manifest())
    gate.apply_load_set()
    manager = pm.PluginManager()
    manager.bind_llm(SimpleNamespace(permission_gate=gate, llm_router=rail.router))
    with pytest.raises(pm.PluginLLMRefused, match="switched off"):
        await manager.llm_for("probe").complete("p")
    assert rail.calls == []


async def test_the_facade_checks_the_gate_at_every_call_not_at_construction(manager, rail):
    llm = manager.manager.llm_for("probe")
    await llm.complete("p")
    manager.gate.plugins["probe"].llm_access = False
    with pytest.raises(pm.PluginLLMRefused):
        await llm.complete("p")
    assert len(rail.calls) == 1


async def test_the_facade_inherits_the_rail_bounds_and_the_strict_local_contract(manager, rail):
    from agents.core.llm.auxiliary_text import MAX_ONESHOT_TOKENS, AuxiliaryConfigError

    llm = manager.manager.llm_for("probe")
    with pytest.raises(AuxiliaryConfigError):
        await llm.complete("p", max_tokens=MAX_ONESHOT_TOKENS + 1)

    class Router:
        active_model = None

        @property
        def local_backend(self):
            raise RuntimeError("No local LLM backend available (strict-local path).")

    manager.orch.llm_router = Router()
    with pytest.raises(RuntimeError, match="strict-local"):
        await llm.complete("p")
    assert rail.calls == []


async def test_an_unbound_manager_refuses_instead_of_inventing_a_route(rail):
    manager = pm.PluginManager()
    with pytest.raises(pm.PluginLLMRefused, match="not bound"):
        await manager.llm_for("probe").complete("p")
    manager.bind_llm(SimpleNamespace(llm_router=rail.router))
    with pytest.raises(pm.PluginLLMRefused, match="no permission gate"):
        await manager.llm_for("probe").complete("p")
    assert rail.calls == []


def test_build_hands_the_facade_to_plugins_that_ask_for_it(rail, monkeypatch):
    """A plugin receives the facade through ``attach_llm`` — never by import."""
    monkeypatch.setattr(pm, "load_hub_env", lambda: None)
    monkeypatch.setattr(pm, "_oauth_init", lambda: None)
    monkeypatch.setattr(pm, "_load_token", lambda provider: None)
    gate = PermissionGate(least_privilege=False)
    orch = SimpleNamespace(get_setting=lambda key, default=None: default, permission_gate=gate,
                           llm_router=rail.router)
    manager = pm.PluginManager()
    manager.build(orch)
    attached = []

    class Asking:
        def attach_llm(self, llm):
            attached.append(llm)

    manager.plugins["asking"] = Asking()
    manager.plugins["silent"] = object()
    manager.attach_llm()
    assert len(attached) == 1 and isinstance(attached[0], pm.PluginLLM)
    assert attached[0].plugin_id == "asking"
    assert manager.llm_for("weather").plugin_id == "weather"


# ── a stalled callback cannot stall generation ────────────────────────────────────


async def test_a_stalled_stream_callback_cannot_block_the_token_loop(manager, rail, monkeypatch):
    """The callback runs on its own worker behind a bounded queue: tokens keep flowing,
    the oldest queued pieces are dropped and counted, and the answer is still whole."""
    import asyncio

    monkeypatch.setattr(pm, "STREAM_DRAIN_SECONDS", 0.05)
    release = asyncio.Event()
    delivered = []

    async def stalled(text):
        await release.wait()
        delivered.append(text)

    async def generate_stream(**kwargs):
        for index in range(pm.STREAM_QUEUE_LIMIT * 3):
            await kwargs["on_token"](f"t{index} ")
        return "whole answer"

    rail.backend.generate_stream = generate_stream
    llm = manager.manager.llm_for("probe")
    answer = await asyncio.wait_for(llm.stream("p", on_token=stalled), timeout=5)
    assert answer == "whole answer"
    assert llm.dropped_tokens >= pm.STREAM_QUEUE_LIMIT
    assert delivered == []          # the worker was cancelled while stalled, never awaited inline


async def test_a_failing_stream_callback_is_skipped_not_propagated(manager, rail):
    seen = []

    def flaky(text):
        seen.append(text)
        if text == "local ":
            raise ValueError("callback bug")

    llm = manager.manager.llm_for("probe")
    assert await llm.stream("p", on_token=flaky) == "local answer"
    assert seen == ["local ", "answer"] and llm.dropped_tokens == 0


# ── reachable through PluginManager.build with a real manifest ────────────────────


async def test_build_attaches_a_working_facade_to_a_plugin_whose_manifest_declares_it(rail, monkeypatch):
    monkeypatch.setattr(pm, "load_hub_env", lambda: None)
    monkeypatch.setattr(pm, "_oauth_init", lambda: None)
    monkeypatch.setattr(pm, "_load_token", lambda provider: None)
    gate = PermissionGate(least_privilege=False)
    gate.register(_manifest("digest"))
    orch = SimpleNamespace(get_setting=lambda key, default=None: default, permission_gate=gate,
                           llm_router=rail.router)
    manager = pm.PluginManager()

    class Digest:
        llm = None

        def attach_llm(self, llm):
            self.llm = llm

    # Built through the real build(); the plugin joins the registry the way a shipped
    # one would, and attach_llm hands it the facade bound to its own gate id.
    original = pm.PluginManager._drop_switched_off

    def add_then_drop(self):
        self.plugins["digest"] = Digest()
        original(self)

    monkeypatch.setattr(pm.PluginManager, "_drop_switched_off", add_then_drop)
    manager.build(orch)
    plugin = manager.plugins["digest"]
    assert plugin.llm.plugin_id == "digest"
    assert await plugin.llm.complete("summarise this") == "local answer"
    assert auxiliary_text.oneshot_usage()["plugin:digest"]["answered"] == 1
    gate.plugins["digest"].llm_access = False       # the manifest is asked at every call
    with pytest.raises(pm.PluginLLMRefused, match="does not declare llm_access"):
        await plugin.llm.complete("again")


async def test_a_backend_failure_text_is_a_refusal_for_a_plugin_too(manager, rail):
    async def degraded(**kwargs):
        return "⚠️ I can't reach the local LM Studio model right now."

    rail.backend.generate = degraded
    with pytest.raises(auxiliary_text.AuxiliaryBackendFailure):
        await manager.manager.llm_for("probe").complete("p")
    assert auxiliary_text.oneshot_usage()["plugin:probe"]["refused"] == 1
