"""H20.1 — Governed Tool-RPC surface (allowlist + gating + secret scrub)."""
import sys, os
from types import MappingProxyType
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.automation_contracts import ContractDecision
from agents.core.kernel import Decision, Verdict
import agents.core.tool_rpc as tool_rpc
from agents.core.tool_rpc import ToolRPCServer
from agents.core.security.secret_broker import SecretBroker


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append(dict(agent=agent, kind=kind, payload=payload,
                               autonomy_level=autonomy_level, risk_tier=risk_tier))
        return len(self.calls)


class _Task:
    def __init__(self, payload, agent=None):
        self.kind = "toolrpc.x"
        self.payload = payload
        if agent is not None:
            self.agent = agent


class _SpyKernel:
    def __init__(self, verdict=Verdict.GRANT, reason="spy"):
        self.calls = []
        self.verdict = verdict
        self.reason = reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self.verdict, reason=self.reason)


class _Audit:
    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)


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
async def test_gated_preflight_sanitizes_before_kernel_and_durable_enqueue(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    q = _FakeQueue()
    kernel = _SpyKernel()
    s = ToolRPCServer(enqueue=q.enqueue, kernel=kernel)

    def preflight(args):
        return {"value": args["value"].strip().lower()}

    s.register_tool(
        "normalize",
        lambda _args: None,
        gated=True,
        preflight=preflight,
    )

    out = await s.handle({"tool": "normalize", "args": {"value": "  SAFE  "}})

    assert out["reason"] == "approval_required"
    assert q.calls[0]["payload"]["args"] == {"value": "safe"}
    assert kernel.calls[-1].payload["args_keys"] == ["value"]


@pytest.mark.asyncio
async def test_gated_preflight_rejection_never_reaches_kernel_or_enqueue(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    error_cls = getattr(tool_rpc, "ToolRPCValidationError", None)
    assert error_cls is not None, "ToolRPCValidationError must carry bounded denial reasons"
    q = _FakeQueue()
    kernel = _SpyKernel()
    s = ToolRPCServer(enqueue=q.enqueue, kernel=kernel)

    def reject(_args):
        raise error_cls("payload_too_large")

    s.register_tool("bounded", lambda _args: None, gated=True, preflight=reject)

    out = await s.handle({"tool": "bounded", "args": {"value": "x"}})

    assert out == {"ok": False, "reason": "payload_too_large", "tool": "bounded"}
    assert kernel.calls == []
    assert q.calls == []


@pytest.mark.asyncio
async def test_gated_tool_obeys_live_tool_rpc_contract(monkeypatch):
    q = _FakeQueue()

    class _Contract:
        def __init__(self):
            self.calls = []

        def evaluate(self, payload=None, **kwargs):
            self.calls.append((payload, kwargs))
            return ContractDecision(
                kind="tool_rpc_call",
                admissible=False,
                requires_approval=True,
                reason="contract_blocked",
            )

    contract = _Contract()
    monkeypatch.setattr(tool_rpc, "TOOL_RPC_CALL_CONTRACT", contract, raising=False)
    s = ToolRPCServer(enqueue=q.enqueue)

    async def send(args):
        return {"sent": True}

    s.register_tool("send_email", send, gated=True)
    out = await s.handle({"tool": "send_email", "args": {"to": "x"}})

    assert out == {"ok": False, "reason": "contract_blocked", "tool": "send_email"}
    assert q.calls == []
    assert contract.calls
    payload, kwargs = contract.calls[-1]
    assert payload["kind"] == "toolrpc.send_email"
    assert payload["tool"] == "send_email"
    assert payload["args_keys"] == ["to"]
    assert kwargs.get("now") is not None


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
async def test_secrets_scrubbed_from_tuple_set_and_frozenset_results():
    secret = "sk-NESTED-SECRET"
    sb = SecretBroker()
    sb.put("nested", secret)
    s = ToolRPCServer(secret_broker=sb)

    async def leaky(args):
        return (secret, {secret}, frozenset({secret}))

    s.register_tool("leaky", leaky)
    out = await s.handle({"tool": "leaky", "args": {}})

    result = out["result"]
    assert isinstance(result, tuple)
    assert isinstance(result[1], set)
    assert isinstance(result[2], frozenset)
    assert secret not in str(result)
    assert result == (
        "[REDACTED:nested]",
        {"[REDACTED:nested]"},
        frozenset({"[REDACTED:nested]"}),
    )


@pytest.mark.asyncio
async def test_secrets_scrubbed_from_dictionary_keys_and_values():
    secret = "sk-KEY-SECRET"
    sb = SecretBroker()
    sb.put("dict_key", secret)
    s = ToolRPCServer(secret_broker=sb)

    async def leaky(args):
        return {f"header-{secret}": f"value-{secret}"}

    s.register_tool("leaky", leaky)
    out = await s.handle({"tool": "leaky", "args": {}})

    assert out["result"] == {
        "header-[REDACTED:dict_key]": "value-[REDACTED:dict_key]"
    }


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


def test_tools_expose_sorted_descriptions_and_input_schemas():
    s = ToolRPCServer()
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    s.register_tool(
        "echo",
        lambda a: None,
        description="Return the provided values.",
        input_schema=schema,
    )
    s.register_tool("alpha", lambda a: None, gated=True)

    assert s.tools() == [
        {
            "name": "alpha",
            "gated": True,
            "description": "",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "echo",
            "gated": False,
            "description": "Return the provided values.",
            "input_schema": schema,
        },
    ]


def test_tool_input_schema_is_copied_on_registration_and_projection():
    s = ToolRPCServer()
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    s.register_tool("echo", lambda a: None, input_schema=schema)

    schema["properties"]["value"]["type"] = "integer"
    first_projection = s.tools()
    first_projection[0]["input_schema"]["properties"]["value"]["type"] = "boolean"

    assert s.tools()[0]["input_schema"] == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }


@pytest.mark.asyncio
async def test_trusted_actor_controls_contract_kernel_enqueue_and_audit(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    q = _FakeQueue()
    kernel = _SpyKernel()
    audit = _Audit()

    class _Contract:
        def __init__(self):
            self.payloads = []

        def evaluate(self, payload=None, **kwargs):
            self.payloads.append(payload)
            return ContractDecision(
                kind="tool_rpc_call",
                admissible=True,
                requires_approval=True,
            )

    contract = _Contract()
    monkeypatch.setattr(tool_rpc, "TOOL_RPC_CALL_CONTRACT", contract)
    s = ToolRPCServer(
        enqueue=q.enqueue,
        audit=audit,
        agent="server-default",
        kernel=kernel,
    )
    s.register_tool("send_email", lambda a: None, gated=True)

    out = await s.handle(
        {
            "tool": "send_email",
            "args": {"token": "secret-value"},
            "agent": "model-spoof",
            "actor": "model-spoof",
        },
        actor="trusted-agent",
    )

    assert out["reason"] == "approval_required"
    assert contract.payloads[-1]["agent"] == "trusted-agent"
    assert contract.payloads[-1]["args_keys"] == ["token"]
    assert q.calls[-1]["agent"] == "trusted-agent"
    assert kernel.calls[-1].agent == "trusted-agent"
    assert kernel.calls[-1].payload["args_keys"] == ["token"]
    assert "secret-value" not in str(kernel.calls[-1].payload)
    assert audit.calls[-1]["metadata"]["agent"] == "trusted-agent"
    assert "model-spoof" not in str(contract.payloads + kernel.calls + audit.calls)


@pytest.mark.asyncio
async def test_request_actor_fields_cannot_override_server_actor():
    q = _FakeQueue()
    s = ToolRPCServer(enqueue=q.enqueue, agent="server-default")
    s.register_tool("send_email", lambda a: None, gated=True)

    out = await s.handle(
        {"tool": "send_email", "args": {}, "agent": "spoof", "actor": "spoof"}
    )

    assert out["reason"] == "approval_required"
    assert q.calls[-1]["agent"] == "server-default"


@pytest.mark.asyncio
async def test_inline_and_approved_execute_audits_use_trusted_actor():
    audit = _Audit()
    s = ToolRPCServer(audit=audit, agent="server-default")

    async def echo(args):
        return {"echo": args}

    s.register_tool("echo", echo)
    s.register_tool("send_email", echo, gated=True)

    await s.handle({"tool": "echo", "args": {}}, actor="inline-agent")
    await s.execute(_Task({"tool": "send_email", "args": {}}, agent="approved-agent"))

    assert [call["metadata"]["agent"] for call in audit.calls] == [
        "inline-agent",
        "approved-agent",
    ]


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


@pytest.mark.asyncio
async def test_trusted_tool_refuses_direct_execute_without_explicit_context():
    token = object()
    ran = []
    s = ToolRPCServer(execution_context_check=lambda context, _task: context is token)

    async def mutate(args):
        ran.append(args)
        return {"ok": True}

    s.register_tool("mutate", mutate, gated=True, trusted_execution=True)
    task = _Task({"tool": "mutate", "args": {"value": "x"}})

    direct = await s.execute(task)
    trusted = await s.execute(task, execution_context=token)

    assert direct == {
        "status": "failed",
        "reason": "trusted_execution_required",
        "tool": "mutate",
    }
    assert trusted["status"] == "ok"
    assert ran == [{"value": "x"}]


@pytest.mark.asyncio
async def test_trusted_tool_fails_closed_on_non_mapping_handler_result():
    token = object()
    server = ToolRPCServer(
        execution_context_check=lambda context, _task: context is token
    )

    async def malformed(_args):
        return ["not", "a", "desktop", "result"]

    server.register_tool(
        "mutate",
        malformed,
        gated=True,
        trusted_execution=True,
    )

    result = await server.execute(
        _Task({"tool": "mutate", "args": {}}),
        execution_context=token,
    )

    assert result == {
        "status": "failed",
        "reason": "invalid_result",
        "tool": "mutate",
    }


@pytest.mark.asyncio
async def test_approved_execute_revalidates_persisted_args_before_handler():
    error_cls = tool_rpc.ToolRPCValidationError
    ran = []

    def preflight(args):
        if args.get("value") != "safe":
            raise error_cls("tampered_args")
        return args

    async def mutate(args):
        ran.append(args)
        return {"ok": True}

    s = ToolRPCServer()
    s.register_tool("mutate", mutate, gated=True, preflight=preflight)

    out = await s.execute(_Task({"tool": "mutate", "args": {"value": "unsafe"}}))

    assert out == {"status": "failed", "reason": "tampered_args", "tool": "mutate"}
    assert ran == []


@pytest.mark.asyncio
async def test_approved_execute_rechecks_kernel_with_task_actor(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    ran = []
    kernel = _SpyKernel(verdict=Verdict.DENY, reason="approval revoked")

    async def send(args):
        ran.append(args)
        return {"sent": True}

    s = ToolRPCServer(agent="server-default", kernel=kernel)
    s.register_tool("send_email", send, gated=True)
    task = _Task(
        {"tool": "send_email", "args": {"token": "secret-value"}},
        agent="approved-agent",
    )

    out = await s.execute(task)

    assert out == {
        "status": "failed",
        "reason": "kernel_denied",
        "tool": "send_email",
        "detail": "approval revoked",
    }
    assert ran == []
    assert kernel.calls[-1].agent == "approved-agent"
    assert kernel.calls[-1].payload["args_keys"] == ["token"]
    assert "secret-value" not in str(kernel.calls[-1].payload)


@pytest.mark.parametrize(
    "payload",
    [None, [], ["bad"], "bad", 7],
    ids=["none", "empty-list", "nonempty-list", "string", "scalar"],
)
@pytest.mark.asyncio
async def test_approved_execute_rejects_non_mapping_payload_before_side_effects(
    payload, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = _SpyKernel()
    ran = []

    async def send(args):
        ran.append(args)
        return {"sent": True}

    s = ToolRPCServer(kernel=kernel)
    s.register_tool("send_email", send, gated=True)

    out = await s.execute(_Task(payload, agent="approved-agent"))

    assert out == {"status": "failed", "reason": "bad_args", "tool": ""}
    assert kernel.calls == []
    assert ran == []


@pytest.mark.parametrize(
    "tool",
    [None, [], {"bad": True}, 7],
    ids=["none", "list", "mapping", "scalar"],
)
@pytest.mark.asyncio
async def test_approved_execute_rejects_unsafe_tool_identifier_before_lookup(
    tool, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = _SpyKernel()
    ran = []

    async def send(args):
        ran.append(args)
        return {"sent": True}

    s = ToolRPCServer(kernel=kernel)
    s.register_tool("send_email", send, gated=True)

    out = await s.execute(
        _Task({"tool": tool, "args": {}}, agent="approved-agent")
    )

    assert out == {"status": "failed", "reason": "bad_args", "tool": ""}
    assert kernel.calls == []
    assert ran == []


@pytest.mark.parametrize(
    "args",
    [None, [], ["bad"], "bad", 7],
    ids=["none", "empty-list", "nonempty-list", "string", "scalar"],
)
@pytest.mark.asyncio
async def test_approved_execute_rejects_explicit_non_mapping_args_before_side_effects(
    args, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = _SpyKernel()
    ran = []

    async def send(handler_args):
        ran.append(handler_args)
        return {"sent": True}

    s = ToolRPCServer(kernel=kernel)
    s.register_tool("send_email", send, gated=True)

    out = await s.execute(
        _Task({"tool": "send_email", "args": args}, agent="approved-agent")
    )

    assert out == {
        "status": "failed",
        "reason": "bad_args",
        "tool": "send_email",
    }
    assert kernel.calls == []
    assert ran == []


@pytest.mark.asyncio
async def test_approved_execute_normalizes_mapping_args_to_real_dict():
    seen = []

    async def send(args):
        seen.append(args)
        return {"sent": True}

    s = ToolRPCServer()
    s.register_tool("send_email", send, gated=True)
    task = _Task(
        MappingProxyType(
            {
                "tool": "send_email",
                "args": MappingProxyType({"to": "y"}),
            }
        )
    )

    out = await s.execute(task)

    assert out["status"] == "ok"
    assert seen == [{"to": "y"}]
    assert type(seen[0]) is dict


@pytest.mark.asyncio
async def test_approved_execute_kernel_grant_uses_server_actor_and_omitted_args(
    monkeypatch,
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    kernel = _SpyKernel(verdict=Verdict.GRANT)
    seen = []

    async def send(args):
        seen.append(args)
        return {"sent": True}

    s = ToolRPCServer(agent="server-default", kernel=kernel)
    s.register_tool("send_email", send, gated=True)

    out = await s.execute(_Task({"tool": "send_email"}))

    assert out["status"] == "ok"
    assert seen == [{}]
    assert kernel.calls[-1].agent == "server-default"
