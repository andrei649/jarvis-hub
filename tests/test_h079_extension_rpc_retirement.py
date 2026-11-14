"""Exercise extension retirement through the real ToolRPCServer surface."""
from __future__ import annotations

import asyncio

import pytest

from agents.core.tool_rpc import ToolRPCServer
from tests import test_extension_runtime as runtime_tests

rig = runtime_tests.rig


class _PausingRunner(runtime_tests._Runner):
    """Pause a real locally executed extension dispatch at the runner await."""

    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.pause_next = True

    async def run(self, command, *, container_name):
        if self.pause_next:
            self.pause_next = False
            self.started.set()
            await self.release.wait()
        return await super().run(command, container_name=container_name)


@pytest.mark.asyncio
async def test_deactivation_cancels_real_rpc_call_and_later_activation_rebinds(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    rpc = rig.runtime.rpc = ToolRPCServer()
    await rig.runtime.activate(manifest)

    assert any(row["name"] == "boats.summarize" for row in rpc.tools())
    runner = _PausingRunner()
    rig.runtime.runner = runner
    call = asyncio.create_task(rpc.handle({
        "tool": "boats.summarize", "args": {"text": "must not escape cancellation"},
    }))

    await asyncio.wait_for(runner.started.wait(), timeout=5)
    assert not call.done()
    try:
        await asyncio.wait_for(rig.runtime.deactivate(manifest.id), timeout=5)
    finally:
        runner.release.set()

    assert call.cancelled()
    assert not any(row["name"] == "boats.summarize" for row in rpc.tools())
    # This adapter reaches an absent binding after deactivation, without touching
    # the old handler or waiting on its already-cancelled invocation.
    refused = await rpc.handle({"tool": "boats.summarize", "args": {}})
    assert refused == {"ok": False, "reason": "tool_not_allowed", "tool": "boats.summarize"}

    await asyncio.wait_for(rig.runtime.activate(manifest), timeout=5)
    assert any(row["name"] == "boats.summarize" for row in rpc.tools())
    result = await asyncio.wait_for(rpc.handle({
        "tool": "boats.summarize", "args": {"text": "new activation"},
    }), timeout=5)
    assert result["ok"] is True
    assert result["result"] == {"tool": "boats.summarize", "seen": {"text": "new activation"}}
