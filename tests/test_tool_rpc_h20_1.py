"""H20.1 — Governed Tool-RPC surface (allowlist + gating + secret scrub)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.tool_rpc import ToolRPCServer
from agents.core.security.secret_broker import SecretBroker


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append(dict(kind=kind, payload=payload, autonomy_level=autonomy_level,
                               risk_tier=risk_tier))
        return len(self.calls)


class _Task:
    def __init__(self, payload):
        self.kind = "toolrpc.x"
        self.payload = payload


def _server(**kw):
    s = ToolRPCServer(**kw)

    async def echo(args):
        return {"echo": args}

    s.register_tool("echo", echo)            # read-only
    return s


@pytest.mark.asyncio
async def test_allowlist_blocks_unknown_tool():
    s = _server()
    out = await s.handle({"tool": "rm_rf", "args": {}})
    assert out["ok"] is False and out["reason"] == "tool_not_allowed"


@pytest.mark.asyncio
async def test_read_only_tool_runs_inline():
    s = _server()
    out = await s.handle({"tool": "echo", "args": {"a": 1}})
    assert out["ok"] is True and out["result"] == {"echo": {"a": 1}}


@pytest.mark.asyncio
async def test_bad_args_rejected():
    s = _server()
    out = await s.handle({"tool": "echo", "args": ["not", "a", "dict"]})
    assert out["ok"] is False and out["reason"] == "bad_args"


@pytest.mark.asyncio
async def test_gated_tool_requires_approval_and_enqueues():
    q = _FakeQueue()
    s = ToolRPCServer(enqueue=q.enqueue)

    async def send(args):
        return {"sent": True}

    s.register_tool("send_email", send, gated=True)
    out = await s.handle({"tool": "send_email", "args": {"to": "x"}})
    assert out["ok"] is False and out["reason"] == "approval_required" and out["task_id"] == 1
    # the gated tool did NOT run; it was enqueued ask-tier instead
    call = q.calls[0]
    assert call["kind"] == "toolrpc.send_email" and call["autonomy_level"] == "ask"


@pytest.mark.asyncio
async def test_gated_tool_without_queue_is_denied():
    s = ToolRPCServer(enqueue=None)
    s.register_tool("send", lambda a: None, gated=True)
    out = await s.handle({"tool": "send", "args": {}})
    assert out["ok"] is False and out["reason"] == "approval_required" and "task_id" not in out


@pytest.mark.asyncio
async def test_secrets_scrubbed_from_results():
    sb = SecretBroker()
    sb.put("api_key", "sk-SUPERSECRET")
    s = ToolRPCServer(secret_broker=sb)

    async def leaky(args):
        return {"data": "token is sk-SUPERSECRET", "nested": ["sk-SUPERSECRET"]}

    s.register_tool("leaky", leaky)
    out = await s.handle({"tool": "leaky", "args": {}})
    assert "sk-SUPERSECRET" not in str(out["result"])
    assert "[REDACTED:api_key]" in out["result"]["data"]


@pytest.mark.asyncio
async def test_handler_error_is_caught():
    s = ToolRPCServer()

    async def boom(args):
        raise RuntimeError("kaboom")

    s.register_tool("boom", boom)
    out = await s.handle({"tool": "boom", "args": {}})
    assert out["ok"] is False and out["reason"] == "tool_error"


@pytest.mark.asyncio
async def test_pipeline_runs_without_llm_roundtrip():
    s = _server()
    results = await s.run_pipeline([
        {"tool": "echo", "args": {"i": 1}},
        {"tool": "echo", "args": {"i": 2}},
        {"tool": "nope", "args": {}},
    ])
    assert [r.get("ok") for r in results] == [True, True, False]


def test_tools_lists_allowlist_with_gating():
    q = _FakeQueue()
    s = ToolRPCServer(enqueue=q.enqueue)
    s.register_tool("read", lambda a: None)
    s.register_tool("write", lambda a: None, gated=True)
    names = {t["name"]: t["gated"] for t in s.tools()}
    assert names == {"read": False, "write": True}


@pytest.mark.asyncio
async def test_approved_gated_tool_executes_via_executor():
    ran = {}

    async def send(args):
        ran["args"] = args
        return {"sent": True}

    s = ToolRPCServer()
    s.register_tool("send_email", send, gated=True)
    # After approval the worker dispatches the task to .execute → tool runs.
    out = await s.execute(_Task({"tool": "send_email", "args": {"to": "y"}}))
    assert out["status"] == "ok" and out["result"] == {"sent": True}
    assert ran["args"] == {"to": "y"}
