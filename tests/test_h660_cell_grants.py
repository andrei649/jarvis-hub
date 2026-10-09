"""Actual resident worker: only a current explicit cell grant permits effects."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core import code_tools
from agents.core.kernel import Decision, Verdict
from tests.test_code_tools import _run, _session_tool


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [Decision(Verdict.QUEUE), None,
                                    SimpleNamespace(verdict="grant")])
async def test_non_grant_cell_cannot_change_existing_variables(tmp_path, decision):
    live = {"decision": Decision(Verdict.GRANT)}
    _server, tool = _session_tool(tmp_path, authorizer=lambda _action: live["decision"])
    try:
        assert (await _run(tool, "kept = 'original'"))["ok"]
        live["decision"] = decision
        refused = await _run(tool, "kept = 'changed'")
        assert refused["ok"] is False, "A non-GRANT cell executed"
        assert refused["reason"] == code_tools.SESSION_DENIED
        live["decision"] = Decision(Verdict.GRANT)
        assert "original" in (await _run(tool, "print(kept)"))["stdout"]
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_missing_authorizer_cannot_start_a_worker(tmp_path):
    _server, tool = _session_tool(tmp_path)
    tool._authorizer = None
    try:
        refused = await _run(tool, "print('unapproved')")
        assert refused["ok"] is False, "Missing cell mediation started a worker"
        assert refused["reason"] == code_tools.SESSION_DENIED
        assert tool._kernels.status() == []
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("non_consuming", [False, True])
async def test_policy_changed_while_waiting_for_kernel_lock_is_rechecked(tmp_path, non_consuming):
    live = {"decision": Decision(Verdict.GRANT)}
    authorized = asyncio.Event()

    def authorizer(_action):
        authorized.set()
        return live["decision"]

    if non_consuming:
        authorizer.revalidate = lambda _action: live["decision"]

    _server, tool = _session_tool(tmp_path, authorizer=authorizer)
    pending = None
    record = None
    try:
        assert (await _run(tool, "kept = 'original'"))["ok"]
        record = next(iter(tool._kernels._records.values()))
        await record.lock.acquire()
        authorized.clear()
        pending = asyncio.create_task(_run(tool, "kept = 'changed'"))
        await asyncio.wait_for(authorized.wait(), 2)
        assert not pending.done()
        live["decision"] = Decision(Verdict.DENY)
        record.lock.release()
        refused = await asyncio.wait_for(pending, 2)
        assert refused["ok"] is False, "A queued cell used its stale pre-lock grant"
        live["decision"] = Decision(Verdict.GRANT)
        assert "original" in (await _run(tool, "print(kept)"))["stdout"]
    finally:
        if record is not None and record.lock.locked():
            record.lock.release()
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_unapproved_reset_preserves_existing_interpreter(tmp_path):
    live = {"decision": Decision(Verdict.GRANT)}
    _server, tool = _session_tool(tmp_path, authorizer=lambda _action: live["decision"])
    try:
        assert (await _run(tool, "kept = 'original'"))["ok"]
        live["decision"] = Decision(Verdict.DENY)
        refused = await tool.execute({"code": "kept = 'changed'", "reset": True})
        assert refused["ok"] is False
        live["decision"] = Decision(Verdict.GRANT)
        result = await _run(tool, "print(kept)")
        assert result["ok"] and "original" in result["stdout"], "Denied reset discarded the interpreter"
        assert result["continuity"] == "continued"
    finally:
        await tool._kernels.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("reset", [False, True])
async def test_live_dispatch_checks_do_not_consume_the_cell_budget_twice(tmp_path, reset):
    _server, tool = _session_tool(tmp_path, authorizer=lambda _action: Decision(Verdict.GRANT))
    consumed = []

    def authorize(action):
        consumed.append(action)
        return Decision(Verdict.GRANT if len(consumed) == 1 else Verdict.DENY, reason="one cell budget")

    # Production make_action_kernel exposes this same non-consuming check.
    authorize.revalidate = lambda _action: Decision(Verdict.GRANT)
    try:
        assert (await _run(tool, "kept = 'original'"))["ok"]
        tool._authorizer = authorize
        result = await tool.execute({"code": "print('one approved cell')", "reset": reset})
        assert result["ok"], "Duplicate authorization exhausted the cell budget"
        assert "one approved cell" in result["stdout"]
        assert len(consumed) == 1
    finally:
        await tool._kernels.shutdown()
