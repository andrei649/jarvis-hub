import pytest

from agents.core.capability_actions import (
    CapabilityActionAPI,
    PerformContext,
)
from agents.core.kernel import Decision, Verdict


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
