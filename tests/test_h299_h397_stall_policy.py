"""Result-aware, turn-local tool-loop stall policy."""

from __future__ import annotations

import asyncio
import json

import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_loop_guardrails import (
    StallObserver,
    classify_failure,
    is_poller,
    recovery_hint,
    safe_args_preview,
)
from agents.core.tool_rpc import ToolRPCServer


def _observe(observer, tool="lookup", args=None, result=None):
    return observer.observe(tool, args or {"q": "x"}, result or {"ok": True, "result": "same"})


def test_result_aware_streaks_and_default_advice():
    observer = StallObserver()
    first = _observe(observer)
    second = _observe(observer)
    third = _observe(observer)
    assert not first.notices
    assert "no_progress" in second.notices and second.halt is None
    assert "identical_call" in third.notices and third.halt is None
    assert all(_observe(observer).halt is None for _ in range(4))
    assert not _observe(observer, result={"ok": True, "result": "changed"}).notices


def test_exact_failure_and_same_tool_failure_are_separate_contiguous_tracks():
    observer = StallObserver(halt_enabled=True)
    failure = {"ok": False, "reason": "not_found"}
    assert not _observe(observer, result=failure).notices
    assert "exact_failure" in _observe(observer, result=failure).notices
    assert _observe(observer, result=failure).halt is None
    assert _observe(observer, result=failure).halt is None
    assert _observe(observer, result=failure).halt == "exact_failure"
    assert _observe(observer, tool="other", result=failure).halt is None
    assert _observe(observer, result=failure).halt is None

    observer = StallObserver(halt_enabled=True)
    for n in range(1, 9):
        decision = _observe(observer, args={"q": str(n)}, result=failure)
        assert ("same_tool_failure" in decision.notices) is (n >= 3)
        assert decision.halt == ("same_tool_failure" if n == 8 else None)


def test_no_progress_halt_and_poller_exemption():
    observer = StallObserver(halt_enabled=True)
    assert [_observe(observer).halt for _ in range(5)] == [None, None, None, None, "no_progress"]
    for name in ("process", "worker_poll", "worker_get_result"):
        assert is_poller(name)
        assert all(not _observe(observer, tool=name).notices for _ in range(8))
    assert not is_poller("worker_polling")


@pytest.mark.parametrize(("result", "failed"), [
    ({"ok": True, "result": {"ok": False, "reason": "bad_args"}}, True),
    ({"ok": False, "reason": "not_found"}, True),
    ({"error": "bad"}, True),
    ({"status": "refused"}, True),
    ({"status": 404}, True),
    ({"status": "503"}, True),
    ({"reason": "timeout"}, True),
    ({"result": {"page": "ok"}}, False),
    ({"error": "", "status": "ready"}, False),
    ({"result": {"reason": "because", "answer": "yes"}}, False),
    ({"reason": "not_found"}, True),
    ({}, False),
])
def test_missing_ok_fallback_and_explicit_status(result, failed):
    assert classify_failure(result) is failed


def test_args_preview_redacts_secret_values_and_is_bounded():
    preview = safe_args_preview({"q": "x" * 300})
    assert len(preview) <= 120
    assert safe_args_preview({"api_key": "SECRET", "q": "safe"}).find("SECRET") == -1


@pytest.mark.parametrize("args", [
    {"Cookie": "session=SECRET"},
    {"accessToken": "SECRET"},
    {"Authorization": "Bearer SECRET"},
    {"command": "curl -H 'Authorization: Bearer SECRET' example.com"},
    {"nested": {"command": "echo SECRET"}},
    {"url": "https://user:SECRET@example.com/path"},
])
def test_args_preview_withholds_embedded_credentials(args):
    assert "SECRET" not in safe_args_preview(args)


def test_stall_observer_does_not_retain_unbounded_arguments_or_results():
    observer = StallObserver()
    secret = "S" * 10_000
    _observe(observer, args={"q": secret}, result={"ok": True, "result": secret})
    assert observer._last is not None
    assert secret not in repr(observer._last)
    assert len(repr(observer._last)) < 250


@pytest.mark.asyncio
async def test_duplicate_reference_index_retains_digest_not_payload():
    runtime = AgentToolRuntime(ToolRPCServer(), enabled=lambda: True)
    call = ToolCall(id="c1", name="lookup", raw_arguments="{}", arguments={})
    content = json.dumps({"ok": True, "result": "S" * 10_000})
    seen = {}
    first = await runtime._dedupe_result(call, {"ok": True}, content, seen,
                                         agent_id="nerva", event_sink=None)
    assert first == content
    assert len(repr(seen)) < 200
    assert "S" * 100 not in repr(seen)


@pytest.mark.asyncio
async def test_duplicate_stub_uses_character_threshold_for_unicode():
    runtime = AgentToolRuntime(ToolRPCServer(), enabled=lambda: True)
    first = ToolCall(id="c1", name="lookup", raw_arguments="{}", arguments={})
    second = ToolCall(id="c2", name="lookup", raw_arguments="{}", arguments={})
    seen = {}
    short = json.dumps({"ok": True, "result": "é" * 300}, ensure_ascii=False)
    assert len(short) < 512 and len(short.encode()) > 512
    await runtime._dedupe_result(first, {"ok": True}, short, seen, agent_id="nerva", event_sink=None)
    again = await runtime._dedupe_result(second, {"ok": True}, short, seen,
                                         agent_id="nerva", event_sink=None)
    assert again == short
    long = json.dumps({"ok": True, "result": "é" * 512}, ensure_ascii=False)
    await runtime._dedupe_result(first, {"ok": True}, long, seen, agent_id="nerva", event_sink=None)
    again = await runtime._dedupe_result(second, {"ok": True}, long, seen,
                                         agent_id="nerva", event_sink=None)
    assert json.loads(again)["same_as"] == "c1"


def test_recovery_hints_are_reason_specific_and_do_not_echo_untrusted_detail():
    assert "arguments" in recovery_hint({"ok": False, "reason": "bad_args"})
    assert "path" in recovery_hint({"ok": False, "reason": "not_found"})
    assert "permission" in recovery_hint({"ok": False, "reason": "approval_required"})
    assert "EVIL" not in recovery_hint({"ok": False, "reason": "EVIL", "detail": "EVIL"})


class _Backend:
    supports_tools = True

    def __init__(self, script):
        self.script = list(script)
        self.messages = []

    async def generate_tool_turn(self, **kwargs):
        self.messages.append(kwargs["messages"])
        if self.script:
            tool, args = self.script.pop(0)
            n = len(self.messages)
            return ToolTurn(tool_calls=(ToolCall(id=f"c{n}", name=tool,
                                             raw_arguments=json.dumps(args), arguments=args),))
        return ToolTurn(content="done")


@pytest.mark.asyncio
async def test_runtime_advices_by_default_and_halts_only_when_enabled():
    server = ToolRPCServer()
    calls = []

    async def lookup(args):
        calls.append(args)
        return {"page": "same"}

    server.register_tool("lookup", lookup)
    backend = _Backend([("lookup", {"q": "x"})] * 5)
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_iterations=lambda: 8)
    reply = await runtime.run_result(agent_id="nerva", backend=backend, model="m", prompt="p",
                                     system="s", max_tokens=64, temperature=0)
    assert reply.reply == "done" and len(calls) == 5
    tool_rows = [json.loads(row["content"]) for row in backend.messages[-1] if row["role"] == "tool"]
    assert "no_progress" in tool_rows[1]["stall_notice"]["tracks"]

    calls.clear()
    backend = _Backend([("lookup", {"q": "x"})] * 6)
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_iterations=lambda: 8,
                               stall_halt_enabled=True)
    reply = await runtime.run_result(agent_id="nerva", backend=backend, model="m", prompt="p",
                                     system="s", max_tokens=64, temperature=0)
    assert reply.exit_reason == "repeated_call" and len(calls) == 5


@pytest.mark.asyncio
async def test_result_change_does_not_get_stopped_pre_dispatch():
    server = ToolRPCServer()
    sequence = []

    async def lookup(_args):
        sequence.append(len(sequence))
        return {"version": len(sequence)}

    server.register_tool("lookup", lookup)
    backend = _Backend([("lookup", {"q": "x"})] * 6)
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_iterations=lambda: 8,
                               stall_halt_enabled=True)
    reply = await runtime.run_result(agent_id="nerva", backend=backend, model="m", prompt="p",
                                     system="s", max_tokens=64, temperature=0)
    assert reply.reply == "done" and len(sequence) == 6


@pytest.mark.asyncio
async def test_missing_ok_inner_handler_error_is_classified_on_real_rpc_path():
    server = ToolRPCServer()

    async def lookup(_args):
        return {"error": "missing row"}

    server.register_tool("lookup", lookup)
    backend = _Backend([("lookup", {"q": "x"})] * 2)
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    events = []
    result = await runtime.run_result(agent_id="nerva", backend=backend, model="m", prompt="p",
                                      system="s", max_tokens=64, temperature=0,
                                      event_sink=events.append)
    assert result.reply == "done"
    tool_rows = [json.loads(row["content"]) for row in backend.messages[-1] if row["role"] == "tool"]
    assert tool_rows[1]["result"]["error"] == "missing row"
    assert "exact_failure" in tool_rows[1]["stall_notice"]["tracks"]
    assert "same_as" not in tool_rows[1]
    assert [e["event"] for e in events if e["call_id"] == "c2" and e["event"] in {"tool_result", "tool_failed"}] == ["tool_failed"]


@pytest.mark.asyncio
async def test_cap_refuses_one_call_but_settles_all_ids_before_controlled_exit():
    server = ToolRPCServer()
    ran = []

    async def lookup(args):
        ran.append(args["n"])
        return {"n": args["n"]}

    server.register_tool("lookup", lookup)

    class _BatchBackend(_Backend):
        async def generate_tool_turn(self, **kwargs):
            self.messages.append(kwargs["messages"])
            assert len(self.messages) == 1
            return ToolTurn(tool_calls=tuple(
                ToolCall(id=f"c{n}", name="lookup", raw_arguments=json.dumps({"n": n}),
                         arguments={"n": n}) for n in range(3)
            ))

    events = []
    runtime = AgentToolRuntime(server, enabled=lambda: True, per_tool_limit=2)
    result = await runtime.run_result(agent_id="nerva", backend=_BatchBackend([]), model="m",
                                      prompt="p", system="s", max_tokens=64, temperature=0,
                                      event_sink=events.append)
    assert result.exit_reason == "tool_call_limit"
    assert sorted(ran) == [0, 1]
    finished = [e for e in events if e["event"] in {"tool_result", "tool_failed"}]
    assert {e["call_id"] for e in finished} == {"c0", "c1", "c2"}


@pytest.mark.asyncio
async def test_concurrent_runs_do_not_share_stall_counts():
    server = ToolRPCServer()

    async def lookup(_args):
        return {"page": "same"}

    server.register_tool("lookup", lookup)
    runtime = AgentToolRuntime(server, enabled=lambda: True, stall_halt_enabled=True,
                               max_iterations=lambda: 8)

    async def one_turn():
        backend = _Backend([("lookup", {"q": "x"})] * 3)
        reply = await runtime.run_result(agent_id="nerva", backend=backend, model="m", prompt="p",
                                         system="s", max_tokens=64, temperature=0)
        return reply, backend

    runs = await asyncio.gather(one_turn(), one_turn())
    assert all(reply.reply == "done" for reply, _backend in runs)
    assert all(len([row for row in backend.messages[-1] if row["role"] == "tool"]) == 3
               for _reply, backend in runs)


@pytest.mark.asyncio
async def test_approval_wins_over_stall_halt_in_a_completed_batch(monkeypatch):
    server = ToolRPCServer()

    async def lookup(_args):
        return {"ok": False, "reason": "not_found"}

    server.register_tool("lookup", lookup)

    class _BatchBackend(_Backend):
        async def generate_tool_turn(self, **kwargs):
            self.messages.append(kwargs["messages"])
            return ToolTurn(tool_calls=tuple(
                ToolCall(id=f"c{n}", name="lookup", raw_arguments='{"q":"x"}',
                         arguments={"q": "x"}) for n in range(6)
            ))

    runtime = AgentToolRuntime(server, enabled=lambda: True, stall_halt_enabled=True)

    async def observations(*_args, **_kwargs):
        failed = {"ok": False, "reason": "not_found", "tool": "lookup"}
        approval = {"ok": False, "reason": "approval_required", "tool": "lookup"}
        return [(failed, json.dumps(failed)) for _ in range(5)] + [(approval, json.dumps(approval))]

    monkeypatch.setattr(runtime, "_execute_turn_calls", observations)
    result = await runtime.run_result(agent_id="nerva", backend=_BatchBackend([]), model="m",
                                      prompt="p", system="s", max_tokens=64, temperature=0)
    assert result.exit_reason == "approval_required"


@pytest.mark.asyncio
async def test_poller_is_exempt_from_stall_and_stub_but_obeys_owner_cap():
    server = ToolRPCServer()
    calls = []

    async def poll(_args):
        calls.append(1)
        return {"page": "x" * 700}

    server.register_tool("worker_poll", poll)
    backend = _Backend([("worker_poll", {})] * 6)
    runtime = AgentToolRuntime(server, enabled=lambda: True, stall_halt_enabled=True,
                               max_iterations=lambda: 8)
    result = await runtime.run_result(agent_id="nerva", backend=backend, model="m", prompt="p",
                                      system="s", max_tokens=64, temperature=0)
    assert result.reply == "done" and len(calls) == 6
    rows = [json.loads(row["content"]) for row in backend.messages[-1] if row["role"] == "tool"]
    assert all("same_as" not in row and "stall_notice" not in row for row in rows)

    capped = AgentToolRuntime(server, enabled=lambda: True, stall_halt_enabled=True,
                              per_tool_limit=2)
    result = await capped.run_result(agent_id="nerva", backend=_Backend([("worker_poll", {})] * 6),
                                     model="m", prompt="p", system="s", max_tokens=64,
                                     temperature=0)
    assert result.exit_reason == "tool_call_limit" and len(calls) == 8


def test_oversized_wrapped_handler_error_keeps_failure_status_in_preview():
    runtime = AgentToolRuntime(ToolRPCServer(), enabled=lambda: True, max_result_bytes=256)
    _result, content = runtime._prepare_result(
        {"ok": True, "tool": "lookup", "result": {"error": "x" * 4_000}}, "lookup",
    )
    assert json.loads(content)["ok"] is False
    folded = runtime._compacted_content(json.dumps(
        {"ok": True, "tool": "lookup", "result": {"error": "x" * 4_000}},
    ))
    assert json.loads(folded)["ok"] is False
