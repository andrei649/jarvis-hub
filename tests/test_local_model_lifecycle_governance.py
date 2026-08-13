"""Governed Jarvis lifecycle control for LM Studio and Ollama.

These are hostile-boundary tests: no host/model effect may happen unless the
permission, contract, kernel and durable audit preflight all succeed.  MCP is
an additional trust boundary and must carry a server-verified owner identity.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import llm_control
from agents.core.autonomy.remediation import ExecResult
from agents.core.kernel import Decision, Verdict
from agents.core.llm.lmstudio_control import LMStudioController
from agents.core.llm.ollama_control import OllamaController
from agents.core.mcp.server import JarvisMCPServer


class _Controller:
    def __init__(self, provider: str, order: list[str]):
        self.provider = provider
        self.order = order
        self.calls: list[tuple[str, str | None]] = []

    async def status(self):
        return {"online": True, "active_models": ["qwen2.5:7b"]}

    async def start_server(self, agent="jarvis"):
        self.order.append("effect")
        self.calls.append(("start", None))
        return {"status": "ok"}

    async def load_model(self, model, agent="jarvis"):
        self.order.append("effect")
        self.calls.append(("load", model))
        return {"status": "ok", "model": model}

    async def unload_model(self, model=None, agent="jarvis"):
        self.order.append("effect")
        self.calls.append(("unload", model))
        return {"status": "ok", "model": model}


class _PermissionGate:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    def check_call(self, plugin, agent):
        self.calls.append((plugin, agent))
        return self.allowed


class _Audit:
    def __init__(self, order: list[str], *, raises=False):
        self.order = order
        self.raises = raises
        self.events = []

    def log(self, event):
        self.order.append("audit")
        if self.raises:
            raise OSError("audit disk unavailable")
        self.events.append(event)


class _Kernel:
    def __init__(self, order: list[str], verdict=Verdict.GRANT):
        self.order = order
        self.verdict = verdict
        self.actions = []

    def __call__(self, action):
        self.order.append("kernel")
        self.actions.append(action)
        return Decision(self.verdict, reason="test policy", tier=1)


def _orch(order: list[str], *, allowed=True, audit_raises=False):
    router = SimpleNamespace(
        name="local",
        active_model="qwen2.5:7b",
        refresh_active_model=None,
    )
    return SimpleNamespace(
        lmstudio=_Controller("lmstudio", order),
        ollama=_Controller("ollama", order),
        llm_router=router,
        permission_gate=_PermissionGate(allowed),
        audit=_Audit(order, raises=audit_raises),
    )


def test_detect_explicit_ollama_lifecycle_commands():
    assert llm_control.detect_llm_control("ollama status") == ("ollama.status", None)
    assert llm_control.detect_llm_control("start Ollama") == ("ollama.start", None)
    assert llm_control.detect_llm_control("ollama load qwen2.5:7b") == (
        "ollama.load", "qwen2.5:7b"
    )
    assert llm_control.detect_llm_control("unload qwen2.5:7b from Ollama") == (
        "ollama.unload", "qwen2.5:7b"
    )


@pytest.mark.asyncio
async def test_lmstudio_effect_runs_only_after_kernel_and_durable_audit(monkeypatch):
    order: list[str] = []
    orch = _orch(order)
    kernel = _Kernel(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(orch, "load", "qwen2.5:7b", channel="web")

    assert "Loaded" in reply
    assert order == ["kernel", "audit", "effect"]
    assert orch.lmstudio.calls == [("load", "qwen2.5:7b")]
    action = kernel.actions[0]
    assert action.kind == "host.control"
    assert action.agent == "jarvis"
    assert action.payload["provider"] == "lmstudio"
    assert action.payload["action"] == "lmstudio.load"
    assert action.payload["risk_tier"] == 1
    assert action.payload["reversible"] is True
    assert orch.audit.events[0].action_taken == "lmstudio.load authorized before effect"


@pytest.mark.asyncio
async def test_ollama_effect_uses_same_governed_boundary(monkeypatch):
    order: list[str] = []
    orch = _orch(order)
    kernel = _Kernel(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(
        orch, "ollama.unload", "qwen2.5:7b", channel="voice"
    )

    assert "Unloaded" in reply
    assert order == ["kernel", "audit", "effect"]
    assert orch.ollama.calls == [("unload", "qwen2.5:7b")]
    assert kernel.actions[0].payload["action"] == "ollama.unload"


@pytest.mark.asyncio
async def test_permission_denial_blocks_before_kernel_audit_and_effect(monkeypatch):
    order: list[str] = []
    orch = _orch(order, allowed=False)
    kernel = _Kernel(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(orch, "start", None, channel="web")

    assert "not permitted" in reply
    assert order == []
    assert orch.lmstudio.calls == []
    assert kernel.actions == []


@pytest.mark.asyncio
async def test_invalid_model_is_rejected_before_any_authority_or_controller(monkeypatch):
    order: list[str] = []
    orch = _orch(order)
    kernel = _Kernel(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(
        orch, "ollama.load", "qwen; touch /tmp/pwned", channel="web"
    )

    assert "valid model id" in reply
    assert order == []
    assert kernel.actions == []
    assert orch.ollama.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", [Verdict.DENY, Verdict.QUEUE])
async def test_non_grant_kernel_verdict_never_reaches_effect(monkeypatch, verdict):
    order: list[str] = []
    orch = _orch(order)
    kernel = _Kernel(order, verdict=verdict)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(orch, "start", None, channel="web")

    assert ("approval required" if verdict is Verdict.QUEUE else "denied") in reply.lower()
    assert order == ["kernel"]
    assert orch.lmstudio.calls == []


@pytest.mark.asyncio
async def test_kernel_disabled_or_audit_failure_both_fail_closed(monkeypatch):
    order: list[str] = []
    orch = _orch(order)
    kernel = _Kernel(order)
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(orch, "start", None, channel="web")
    assert "kernel" in reply.lower()
    assert order == []
    assert orch.lmstudio.calls == []

    order.clear()
    orch = _orch(order, audit_raises=True)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    reply = await llm_control.run_llm_control(orch, "start", None, channel="web")
    assert "audit" in reply.lower()
    assert order == ["kernel", "audit"]
    assert orch.lmstudio.calls == []


@pytest.mark.asyncio
async def test_direct_mcp_channel_call_without_server_authority_fails_closed(monkeypatch):
    order: list[str] = []
    orch = _orch(order)
    kernel = _Kernel(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(orch, "start", None, channel="mcp")

    assert "authenticated MCP owner" in reply
    assert order == []
    assert orch.lmstudio.calls == []


@pytest.mark.asyncio
async def test_guarded_mcp_owner_call_reaches_governed_effect(monkeypatch):
    order: list[str] = []
    orch = _orch(order)
    kernel = _Kernel(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    async def runner(_agent_id, _text):
        return await llm_control.run_llm_control(
            orch, "start", None, channel="mcp"
        )

    def owner_guard(agent_id, _text, identity):
        if agent_id != "jarvis" or identity != "owner-token":
            return "owner identity required"
        return None

    server = JarvisMCPServer(
        runner,
        {"jarvis": "Prime orchestrator"},
        agent_request_guard=owner_guard,
    )
    response = await server.call_tool(
        "ask_jarvis", {"text": "start LM Studio"}, identity="owner-token"
    )

    assert response["isError"] is False
    assert "up" in response["content"][0]["text"].lower()
    assert order == ["kernel", "audit", "effect"]
    assert orch.lmstudio.calls == [("start", None)]


class _HTTPResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"models": []}


class _HTTPClient:
    def __init__(self, order):
        self.order = order

    async def get(self, _path):
        return _HTTPResponse()

    async def post(self, path, json):
        self.order.append(f"effect:http:{path}:{json['keep_alive']}")
        return _HTTPResponse()


def _production_controller_orch(provider, order):
    online = {"value": False}
    gate = _PermissionGate()
    router = SimpleNamespace(
        name="local",
        active_model="qwen2.5:7b",
        refresh_active_model=None,
        detect=None,
    )

    async def exec_fn(argv, _timeout, _detach):
        order.append(f"effect:subprocess:{' '.join(argv)}")
        if "start" in argv or "serve" in argv:
            online["value"] = True
        return ExecResult(exit_code=0)

    if provider == "lmstudio":
        ctrl = LMStudioController(
            permission_gate=gate,
            router=router,
            exec_fn=exec_fn,
            probe_fn=lambda _host, _port: online["value"],
            models_fn=lambda: _async_value(["qwen2.5:7b"]),
            verify_attempts=1,
            verify_delay=0,
        )
    else:
        ctrl = OllamaController(
            permission_gate=gate,
            router=router,
            exec_fn=exec_fn,
            probe_fn=lambda _host, _port: online["value"],
            client=_HTTPClient(order),
            verify_attempts=1,
            verify_delay=0,
        )
    return SimpleNamespace(
        **{provider: ctrl},
        llm_router=router,
        permission_gate=gate,
        audit=_Audit(order),
    )


async def _async_value(value):
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "action", "start_effect", "load_effect"),
    [
        ("lmstudio", "load", "effect:subprocess:lms server start", "effect:subprocess:lms load qwen2.5:7b -y"),
        ("ollama", "ollama.load", "effect:subprocess:ollama serve", "effect:http:/api/generate:-1"),
    ],
)
async def test_offline_load_authorizes_and_audits_start_and_load_separately(
    monkeypatch, provider, action, start_effect, load_effect
):
    order = []
    orch = _production_controller_orch(provider, order)

    class _PhaseKernel:
        def __call__(self, action):
            order.append(f"kernel:{action.payload['action']}")
            return Decision(Verdict.GRANT, reason="test", tier=1)

    class _PhaseAudit(_Audit):
        def log(self, event):
            order.append(f"audit:{event.action_taken.split()[0]}")
            self.events.append(event)

    orch.audit = _PhaseAudit(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: _PhaseKernel())

    reply = await llm_control.run_llm_control(
        orch, action, "qwen2.5:7b", channel="web"
    )

    assert "Loaded" in reply
    assert order == [
        f"kernel:{provider}.start",
        f"audit:{provider}.start",
        start_effect,
        f"kernel:{provider}.load",
        f"audit:{provider}.load",
        load_effect,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("second_phase", [Verdict.DENY, Verdict.QUEUE, "audit_failure"])
async def test_offline_load_second_phase_failure_never_loads_model(
    monkeypatch, second_phase
):
    order = []
    orch = _production_controller_orch("lmstudio", order)
    kernel_calls = 0

    def kernel(action):
        nonlocal kernel_calls
        kernel_calls += 1
        order.append(f"kernel:{action.payload['action']}")
        verdict = Verdict.GRANT if kernel_calls == 1 or second_phase == "audit_failure" else second_phase
        return Decision(verdict, reason="second phase blocked", tier=1)

    class _PhaseAudit(_Audit):
        def log(self, event):
            action = event.action_taken.split()[0]
            order.append(f"audit:{action}")
            if second_phase == "audit_failure" and action == "lmstudio.load":
                raise OSError("audit unavailable")
            self.events.append(event)

    orch.audit = _PhaseAudit(order)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(llm_control, "make_action_kernel", lambda _orch: kernel)

    reply = await llm_control.run_llm_control(
        orch, "load", "qwen2.5:7b", channel="web"
    )

    assert "could not load" in reply.lower()
    assert "effect:subprocess:lms server start" in order
    assert "effect:subprocess:lms load qwen2.5:7b -y" not in order


@pytest.mark.asyncio
async def test_ollama_status_does_not_claim_empty_residency_when_inventory_is_unknown():
    class _UnknownStatusController:
        async def status(self):
            return {
                "online": True,
                "status": "unknown",
                "active_models": None,
                "reason": "active model inventory is unavailable",
            }

    orch = SimpleNamespace(
        ollama=_UnknownStatusController(),
        llm_router=SimpleNamespace(name="local"),
    )

    reply = await llm_control.run_llm_control(
        orch, "ollama.status", None, channel="web"
    )

    assert "could not verify" in reply.lower()
    assert "no model currently resident" not in reply.lower()
