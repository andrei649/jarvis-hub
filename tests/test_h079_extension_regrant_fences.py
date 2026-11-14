"""H079: a revoked grant must not regain authority over suspended work.

These tests reuse the existing offline extension rig. The pause is at the runner
await boundary; after release, the existing runner still executes the generated
invocation script with the real local interpreter.
"""
from __future__ import annotations

import asyncio

import pytest

from agents.core.commands import build_default_registry
from agents.core.extensions.runtime import ExtensionRuntimeError
from tests import test_extension_runtime as runtime_tests
from tests.test_h079_extension_command_inspection import _acquisition, _activate_mixed, _row

rig = runtime_tests.rig


class _PausedRunner:
    """Pause one real sandbox invocation before delegating it to the offline rig."""

    def __init__(self):
        self.delegate = runtime_tests._Runner()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.pause_next = True

    @property
    def calls(self):
        return self.delegate.calls

    async def run(self, command, *, container_name):
        if self.pause_next:
            self.pause_next = False
            self.started.set()
            await self.release.wait()
        return await self.delegate.run(command, container_name=container_name)


class _NotifyingRunner(runtime_tests._Runner):
    """Signal after the real offline runner has completed sandbox registration."""

    def __init__(self):
        super().__init__()
        self.completed = asyncio.Event()

    async def run(self, command, *, container_name):
        result = await super().run(command, container_name=container_name)
        self.completed.set()
        return result


class _DelayedUnregisterRPC(runtime_tests._ToolRPC):
    def __init__(self):
        super().__init__()
        self.unregister_started = asyncio.Event()
        self.release_unregister = asyncio.Event()

    async def unregister_tool(self, name, *, cancel_inflight=False):
        self.unregister_started.set()
        await self.release_unregister.wait()
        await super().unregister_tool(name, cancel_inflight=cancel_inflight)


async def _wait_for_runner(runner: _PausedRunner, task: asyncio.Task):
    await asyncio.wait_for(runner.started.wait(), timeout=5)
    assert not task.done(), "the call must still be suspended at the runner boundary"


async def _revoke_and_regrant(consent, manifest):
    assert consent.revoke(manifest.id)
    consent.grant(manifest)
    # The declaration digest is intentionally identical; only the grant occurrence changed.
    assert consent.check(manifest).allowed


async def _activate_mixed_with_observer(rig):
    source = '''
def register():
    return {"tools": ["boats.summarize"], "commands": ["boat_report"], "events": ["session.started"]}
def call(tool, payload):
    return {"tool": tool, "seen": payload}
def command(name, args):
    return "Report: " + args
def on_event(event, payload):
    return None
'''
    rig.runtime.commands = build_default_registry()
    record = rig.packages.write(source)
    record.manifest.update(name=record.name, version=record.version, entrypoint="run")
    record.active = True
    record.status = "active"
    rig.packages.list_records = lambda *, include_retained: [record]
    manifest = runtime_tests.descriptor(tools=["summarize"], commands=["boat_report"],
        events=["session.started"], command_requires_args=["boat_report"])
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    return _acquisition(rig)


@pytest.mark.asyncio
async def test_regrant_during_registration_does_not_publish_the_old_activation(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    rpc = rig.runtime.rpc = runtime_tests._ToolRPC()
    runner = _PausedRunner()
    rig.runtime.runner = runner

    task = asyncio.create_task(rig.runtime.activate(manifest))
    try:
        await _wait_for_runner(runner, task)
        await _revoke_and_regrant(rig.consent, manifest)
    finally:
        runner.release.set()

    with pytest.raises(ExtensionRuntimeError):
        await task
    assert rig.runtime.active() == ()
    assert rig.runtime.callable_tools() == ()
    assert rpc.tools == {}


@pytest.mark.asyncio
async def test_public_deactivation_supersedes_a_pending_registration_without_consent_change(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    rpc = rig.runtime.rpc = runtime_tests._ToolRPC()
    runner = _PausedRunner()
    rig.runtime.runner = runner

    task = asyncio.create_task(rig.runtime.activate(manifest))
    try:
        await _wait_for_runner(runner, task)
        # Public deactivation advances the lifecycle fence even before anything
        # has been installed in the active map.
        assert await rig.runtime.deactivate(manifest.id) is False
    finally:
        runner.release.set()

    with pytest.raises(ExtensionRuntimeError):
        await task
    assert rig.runtime.active() == ()
    assert rig.runtime.callable_tools() == ()
    assert rpc.tools == {}


@pytest.mark.asyncio
async def test_regrant_during_tool_dispatch_drops_the_late_payload(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    runner = _PausedRunner()
    rig.runtime.runner = runner

    task = asyncio.create_task(rig.runtime.dispatch("boats.summarize", {"text": "old grant"}))
    try:
        await _wait_for_runner(runner, task)
        await _revoke_and_regrant(rig.consent, manifest)
    finally:
        runner.release.set()

    with pytest.raises(ExtensionRuntimeError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("interference", ["deactivate", "package change", "disable"],
                         ids=["deactivate", "package-change", "disable"])
async def test_tool_dispatch_discards_result_when_authority_changes_while_runner_waits(rig, interference):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    runner = _PausedRunner()
    rig.runtime.runner = runner

    task = asyncio.create_task(rig.runtime.dispatch("boats.summarize", {"text": "must be discarded"}))
    try:
        await _wait_for_runner(runner, task)
        if interference == "deactivate":
            assert await rig.runtime.deactivate(manifest.id) is True
        elif interference == "package change":
            rig.packages.record.package_hash = "d" * 64
        else:
            rig.runtime.enabled = lambda: False
    finally:
        runner.release.set()

    with pytest.raises(ExtensionRuntimeError):
        await task


@pytest.mark.asyncio
async def test_regrant_during_command_dispatch_drops_the_late_reply(rig):
    manifest = runtime_tests.descriptor(tools=[], commands=["boat_report"])
    rig.runtime.commands = build_default_registry()
    rig.packages.write(runtime_tests.COMMAND_EXTENSION)
    rig.consent.grant(manifest)
    await rig.runtime.activate(manifest)
    runner = _PausedRunner()
    rig.runtime.runner = runner

    task = asyncio.create_task(rig.runtime.dispatch_command("boat_report", "old grant"))
    try:
        await _wait_for_runner(runner, task)
        await _revoke_and_regrant(rig.consent, manifest)
    finally:
        runner.release.set()

    with pytest.raises(ExtensionRuntimeError):
        await task


@pytest.mark.asyncio
async def test_retirement_waiting_on_rpc_unregister_cannot_remove_a_new_activation(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    rpc = rig.runtime.rpc = _DelayedUnregisterRPC()
    await rig.runtime.activate(manifest)
    assert list(rpc.tools) == ["boats.summarize"]

    retiring = asyncio.create_task(rig.runtime.deactivate(manifest.id))
    await asyncio.wait_for(rpc.unregister_started.wait(), timeout=5)
    runner = _NotifyingRunner()
    rig.runtime.runner = runner
    activating = asyncio.create_task(rig.runtime.activate(manifest))
    try:
        # Registration has returned from the actual local invocation script. An
        # implementation with a per-extension mutation lock waits here until the
        # delayed retirement finishes; the unfenced baseline publishes too early.
        await asyncio.wait_for(runner.completed.wait(), timeout=5)
    finally:
        rpc.release_unregister.set()

    retired, activated = await asyncio.gather(retiring, activating)
    assert retired is True
    assert activated.manifest.id == manifest.id
    assert rig.runtime.active() == (activated,)
    assert list(rpc.tools) == ["boats.summarize"]
    assert rpc.tools["boats.summarize"]["handler"] is not None


@pytest.mark.asyncio
async def test_inspection_hides_callables_after_same_digest_regrant_until_explicit_activation(rig):
    acquisition = await _activate_mixed(rig)
    manifest = rig.runtime.active()[0].manifest
    await _revoke_and_regrant(rig.consent, manifest)

    before_inspection = len(rig.runner.calls)
    stale = _row(acquisition)
    assert stale["declared_tools"] == ["boats.summarize"]
    assert stale["declared_commands"] == ["boat_report"]
    assert stale["callable_tools"] == []
    assert stale["callable_commands"] == []
    assert stale["execution_available"] is False
    assert len(rig.runner.calls) == before_inspection

    # Consent on the same declaration set does not refresh the old activation.
    # A new, explicit registration is required before inspection calls it current.
    await rig.runtime.activate(manifest)
    after_activation = len(rig.runner.calls)
    current = _row(acquisition)
    assert current["callable_tools"] == ["boats.summarize"]
    assert current["callable_commands"] == ["boat_report"]
    assert current["execution_available"] is True
    assert len(rig.runner.calls) == after_activation


@pytest.mark.asyncio
async def test_observer_from_old_grant_refuses_delivery_after_same_digest_regrant(rig):
    await _activate_mixed_with_observer(rig)
    manifest = rig.runtime.active()[0].manifest
    await _revoke_and_regrant(rig.consent, manifest)
    before = len(rig.runner.calls)

    with pytest.raises(ExtensionRuntimeError, match="consent_changed"):
        await rig.runtime.observe("boats", "session.started", {"kind": "old grant"})
    assert len(rig.runner.calls) == before
