"""Registrar-owned review can settle one gated intake before a manual footer."""

from __future__ import annotations

import asyncio

import pytest

from agents.core.tool_rpc import ToolRPCServer
from agents.core.turn_approvals import open_turn_approvals, reset_turn_approvals


async def _handler(_args):
    pytest.fail("gated handlers must not run during intake or review")


def _server(intake, review=None):
    server = ToolRPCServer(agent="default")
    server.register_tool(
        "terminal_run", _handler, gated=True, trusted_execution=True,
        gated_intake=intake, gated_review=review,
    )
    return server


@pytest.mark.asyncio
async def test_existing_positional_registration_still_labels_classified_calls():
    queued = []
    server = ToolRPCServer(enqueue=lambda *args, **kwargs: queued.append(kwargs['payload']) or 71)
    server.register_tool('file_write', _handler, True, 'Write a file', None, None,
                         None, False, False, None,
                         lambda args: {'class': 'persistent_policy'}, 4096, None)
    result = await server.handle({'tool': 'file_write', 'args': {'path': 'AGENTS.md'}})
    assert result['reason'] == 'approval_required' and result['task_id'] == 71
    assert queued[0]['class'] == 'persistent_policy'


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    {"ok": True, "tool": "terminal_run", "result": {"status": "ok"}},
    {"ok": False, "tool": "terminal_run", "reason": "smart_denied"},
])
async def test_review_answer_precedes_collector_and_returns_verbatim(answer):
    order = []
    entered, release = asyncio.Event(), asyncio.Event()

    def intake(actor, args):
        order.append(("intake", actor, args["command"]))
        return 17

    async def review(actor, args, task_id):
        order.append(("review", actor, args["command"], task_id))
        entered.set()
        await release.wait()
        return answer

    server = _server(intake, review)
    approvals, token = open_turn_approvals()
    try:
        call = asyncio.create_task(server.handle(
            {"tool": "terminal_run", "args": {"command": "printf one"}}, actor="owner",
        ))
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert approvals == []
        assert order == [("intake", "owner", "printf one"),
                         ("review", "owner", "printf one", 17)]
        release.set()
        assert await call == answer
        assert approvals == []
    finally:
        release.set()
        reset_turn_approvals(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "raise", "invalid"])
async def test_unavailable_review_keeps_manual_pending_fallback(failure):
    async def review(_actor, _args, _task_id):
        if failure == "raise":
            raise RuntimeError("private provider detail")
        return None if failure == "none" else ["not a server result"]

    server = _server(lambda _actor, _args: 19, review)
    approvals, token = open_turn_approvals()
    try:
        assert await server.handle({"tool": "terminal_run", "args": {"command": "x"}}) == {
            "ok": False, "reason": "approval_required", "tool": "terminal_run", "task_id": 19,
        }
        assert approvals == [19]
    finally:
        reset_turn_approvals(token)


@pytest.mark.asyncio
async def test_cancellation_propagates_without_completed_result_or_pending_footer():
    entered = asyncio.Event()

    async def review(_actor, _args, _task_id):
        entered.set()
        await asyncio.Event().wait()

    server = _server(lambda _actor, _args: 23, review)
    approvals, token = open_turn_approvals()
    try:
        call = asyncio.create_task(server.handle({"tool": "terminal_run", "args": {}}))
        await asyncio.wait_for(entered.wait(), timeout=2)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert approvals == []
    finally:
        reset_turn_approvals(token)


def test_review_registration_requires_trusted_custom_gated_async_callback():
    async def review(_actor, _args, _task_id):
        return None

    invalid = [
        {"gated": False, "trusted_execution": True, "gated_intake": lambda *_: 1},
        {"gated": True, "trusted_execution": False, "gated_intake": lambda *_: 1},
        {"gated": True, "trusted_execution": True},
    ]
    for options in invalid:
        server = ToolRPCServer()
        with pytest.raises(ValueError):
            server.register_tool("terminal_run", _handler, gated_review=review, **options)
    with pytest.raises(ValueError):
        ToolRPCServer().register_tool(
            "terminal_run", _handler, gated=True, trusted_execution=True,
            gated_intake=lambda *_: 1, gated_review=lambda *_: {},
        )


@pytest.mark.asyncio
async def test_intake_and_review_get_detached_finalized_arguments():
    request = {"tool": "terminal_run", "args": {"nested": {"command": "original"}}}
    observed = []

    def preflight(args):
        args["nested"]["command"] = "finalized"
        return args

    def intake(_actor, args):
        args["nested"]["command"] = "intake-mutated"
        return 31

    async def review(_actor, args, _task_id):
        observed.append(args["nested"]["command"])
        args["nested"]["command"] = "review-mutated"
        return {"ok": False, "reason": "smart_denied"}

    server = ToolRPCServer()
    server.register_tool(
        "terminal_run", _handler, gated=True, trusted_execution=True,
        preflight=preflight, gated_intake=intake, gated_review=review,
    )
    assert (await server.handle(request))["reason"] == "smart_denied"
    assert observed == ["finalized"]
    assert request["args"]["nested"]["command"] == "original"


@pytest.mark.asyncio
async def test_replacement_registration_discards_stale_success_without_pending_footer():
    entered, release = asyncio.Event(), asyncio.Event()

    async def review(_actor, _args, _task_id):
        entered.set()
        await release.wait()
        return {"ok": True, "result": "stale success"}

    server = _server(lambda _actor, _args: 37, review)
    approvals, token = open_turn_approvals()
    try:
        call = asyncio.create_task(server.handle({"tool": "terminal_run", "args": {}}))
        await asyncio.wait_for(entered.wait(), timeout=2)
        server.register_tool("terminal_run", _handler, gated=True, trusted_execution=True,
                             gated_intake=lambda _actor, _args: 38)
        release.set()
        assert await call == {"ok": False, "reason": "registration_changed",
                              "tool": "terminal_run", "task_id": 37}
        assert approvals == []
    finally:
        release.set()
        reset_turn_approvals(token)


@pytest.mark.asyncio
async def test_unrelated_gated_tool_and_model_metadata_cannot_select_review():
    called = []

    async def review(_actor, args, _task_id):
        called.append(args["gated_review"])
        return {"ok": False, "reason": "smart_denied"}

    server = _server(lambda _actor, _args: 41, review)
    server.register_tool("file_write", _handler, gated=True)
    approvals, token = open_turn_approvals()
    try:
        assert await server.handle({"tool": "terminal_run", "args": {
            "gated_review": "model-chosen", "trusted_execution": False,
        }, "gated_review": "outside-args"}) == {"ok": False, "reason": "smart_denied"}
        assert called == ["model-chosen"]
        assert await server.handle({"tool": "file_write", "args": {}}) == {
            "ok": False, "reason": "approval_required", "tool": "file_write",
        }
        assert approvals == []
    finally:
        reset_turn_approvals(token)
