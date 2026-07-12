import pytest

from agents.core.capability_actions import (
    CapabilityActionAPI,
    PerformContext,
)
from agents.core.capability_manifests import CapabilityManifest
from agents.core.kernel import Action, Decision, Verdict
from agents.core.tool_rpc import ToolRPCServer


class KernelSpy:
    def __init__(self, verdict=Verdict.GRANT):
        self.verdict = verdict
        self.calls = []

    def __call__(self, action, capability=None, budget=None):
        self.calls.append((action, capability, budget))
        return Decision(self.verdict, reason=f"kernel-{self.verdict.value}", tier=2,
                        card={"title": action.title} if self.verdict is Verdict.QUEUE else None)


def _valid_payment():
    return {"mandate_id": "m1", "payee": "acme", "amount": 10, "currency": "EUR"}


@pytest.mark.asyncio
async def test_perform_is_default_off_and_invokes_nothing(monkeypatch):
    monkeypatch.delenv("JARVIS_UNIFIED_ACTION_API", raising=False)
    kernel = KernelSpy()
    calls = []
    api = CapabilityActionAPI(authorizer=kernel)
    api.register("action:payment", lambda params, ctx: calls.append(params))

    result = await api.perform("action:payment", _valid_payment())

    assert result.status == "disabled"
    assert not kernel.calls
    assert not calls


@pytest.mark.asyncio
async def test_unknown_malformed_missing_input_and_unbound_fail_closed(monkeypatch):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    api = CapabilityActionAPI(authorizer=KernelSpy())

    assert (await api.perform("action:nope", {})).reason == "unknown_capability"
    assert (await api.perform("action:payment", ["not", "a", "mapping"])).reason == "invalid_params"
    assert (await api.perform("action:payment", {})).reason == "missing_inputs:amount,currency,mandate_id,payee"
    assert (await api.perform("action:payment", _valid_payment())).reason == "implementation_unbound"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "status", "executed"),
    [
        (Verdict.DENY, "refused", False),
        (Verdict.QUEUE, "queued", False),
        (Verdict.GRANT, "completed", True),
    ],
)
async def test_facade_mediation_authorizes_once_and_only_grant_executes(
    monkeypatch, verdict, status, executed
):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    kernel = KernelSpy(verdict)
    calls = []

    async def handler(params, context):
        calls.append((params, context))
        return {"receipt": "ok"}

    api = CapabilityActionAPI(authorizer=kernel)
    api.register("action:payment", handler)
    context = PerformContext(
        agent="stark",
        title="Pay invoice",
        origin="operator",
        scope="global",
        capability_token="token-1",
        capability_name="payment",
    )

    result = await api.perform("action:payment", _valid_payment(), context)

    assert result.status == status
    assert len(kernel.calls) == 1
    action, capability, _budget = kernel.calls[0]
    assert action.kind == "payment"
    assert action.agent == "stark"
    assert action.origin == "operator"
    assert capability.token_id == "token-1"
    assert bool(calls) is executed
    if executed:
        assert result.output == {"receipt": "ok"}
    if verdict is Verdict.QUEUE:
        assert result.card == {"title": "Pay invoice"}


@pytest.mark.asyncio
async def test_missing_kernel_and_handler_exception_are_stable_and_redacted(monkeypatch):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")

    api = CapabilityActionAPI(authorizer=None)
    api.register("action:kg.write", lambda params, ctx: {"ok": True})
    missing = await api.perform("action:kg.write", {"operation": "upsert"})
    assert missing.status == "refused"
    assert missing.reason == "kernel_unavailable"

    def explode(params, ctx):
        raise RuntimeError("secret-host-path C:/private")

    api = CapabilityActionAPI(authorizer=KernelSpy())
    api.register("action:kg.write", explode)
    failed = await api.perform("action:kg.write", {"operation": "upsert"})
    assert failed.status == "failed"
    assert failed.reason == "implementation_error"
    assert "secret" not in repr(failed)
    assert "private" not in repr(failed)


def test_delegated_registration_refuses_non_kernel_action_kind():
    manifest = CapabilityManifest(
        id="action:read.only",
        description="Read a harmless value.",
        inputs={"type": "object"},
        risk="read_only",
        requires=("action-kernel",),
        supports=("read",),
        verification="action-auth:read.only",
        rollback="no mutation to roll back",
        confidence=0.5,
        implementation="example.reader:read",
        action_kind="read.only",
    )
    api = CapabilityActionAPI(manifests=[manifest])
    with pytest.raises(ValueError, match="kernel-mediated"):
        api.register_broker("action:read.only", lambda params, ctx: None)


@pytest.mark.asyncio
async def test_broker_adapter_delegates_without_double_authorization(monkeypatch):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    facade_kernel = KernelSpy()
    broker_kernel = KernelSpy()

    def broker(params, context):
        broker_kernel(Action(kind="kg.write", payload=params))
        return {"accepted": True}

    api = CapabilityActionAPI(authorizer=facade_kernel)
    api.register_broker("action:kg.write", broker)
    result = await api.perform("action:kg.write", {"operation": "upsert"})

    assert result.status == "completed"
    assert result.output == {"accepted": True}
    assert not facade_kernel.calls
    assert len(broker_kernel.calls) == 1


@pytest.mark.asyncio
async def test_tool_rpc_adapter_uses_server_owned_kernel_once(monkeypatch):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    facade_kernel = KernelSpy()
    rpc_kernel = KernelSpy()
    queued = []

    async def danger(args):
        return {"should_not": "run_before_approval"}

    server = ToolRPCServer(
        kernel=rpc_kernel,
        enqueue=lambda *args, **kwargs: queued.append((args, kwargs)) or 42,
    )
    server.register_tool("danger", danger, gated=True)

    api = CapabilityActionAPI(authorizer=facade_kernel)
    api.register_tool_rpc("action:tool.rpc", server)
    result = await api.perform(
        "action:tool.rpc",
        {"tool": "danger", "args": {"target": "x"}},
        PerformContext(agent="stark"),
    )

    assert result.status == "queued"
    assert result.reason == "approval_required"
    assert not facade_kernel.calls
    assert len(rpc_kernel.calls) == 1
    assert len(queued) == 1
