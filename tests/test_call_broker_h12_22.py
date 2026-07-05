"""H12.22 — Governed outbound voice / call-back. All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.automation_contracts import ContractDecision
from agents.core.autonomy.call_broker import (
    CallBroker, NullCallClient, HttpCallClient, build_call_request,
)
from agents.core.autonomy.worker import InterruptBudget
from agents.core.security.secret_broker import SecretBroker


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append(dict(agent=agent, kind=kind, title=title, payload=payload,
                               risk_tier=risk_tier, autonomy_level=autonomy_level,
                               origin=origin))
        return len(self.calls)


class _Task:
    def __init__(self, payload):
        self.kind = "call.outbound"
        self.payload = payload


def test_providers_and_supports():
    assert {p["provider"] for p in CallBroker().providers()} == {"twilio", "telnyx"}
    assert CallBroker.supports("twilio") and CallBroker.supports("Telnyx")
    assert not CallBroker.supports("skype")


def test_request_unknown_provider():
    out = CallBroker().request("+1", "hi", provider="skype")
    assert out["ok"] is False and out["reason"] == "unknown_provider"


def test_request_missing_fields():
    out = CallBroker().request("", "", provider="twilio")
    assert out["ok"] is False and set(out["missing"]) == {"to", "message"}


def test_request_budget_exhausted():
    cb = CallBroker(enqueue=_FakeQueue().enqueue, budget=InterruptBudget(per_day=0))
    out = cb.request("+1", "hi")
    assert out["ok"] is False and out["reason"] == "interrupt_budget_exhausted"


def test_request_preview_mode():
    out = CallBroker().request("+15551234", "Your build is done")
    assert out["ok"] is True and out["queued"] is False
    assert out["preview"]["requires_approval"] is True
    assert out["preview"]["would_execute"] is False


def test_request_enqueues_governed_task():
    q = _FakeQueue()
    out = CallBroker(enqueue=q.enqueue).request("+15551234", "deploy finished",
                                                provider="twilio", reason="deploy")
    assert out["ok"] is True and out["queued"] is True
    call = q.calls[0]
    assert call["kind"] == "call.outbound"
    assert call["autonomy_level"] == "ask" and call["risk_tier"] == 2
    p = call["payload"]
    assert p["provider"] == "twilio" and p["to"] == "+15551234"
    assert p["credential_ref"] == "{{secret:twilio_auth_token}}"


def test_request_obeys_live_call_request_contract(monkeypatch):
    import agents.core.autonomy.call_broker as call_broker

    class _FakeCallRequestContract:
        def __init__(self):
            self.calls = []

        def evaluate(self, payload=None, **kwargs):
            payload = payload or {}
            self.calls.append((payload, kwargs))
            return ContractDecision(
                kind="call_request",
                admissible=False,
                requires_approval=True,
                reason="contract_denied",
                checked=("fake",),
            )

    q = _FakeQueue()
    contract = _FakeCallRequestContract()
    monkeypatch.setattr(call_broker, "CALL_REQUEST_CONTRACT", contract, raising=False)

    out = call_broker.CallBroker(enqueue=q.enqueue).request(
        "+15551234",
        "deploy finished",
        provider="twilio",
        reason="night-shift",
        agent="jarvis",
    )

    assert out == {"ok": False, "reason": "contract_denied", "kind": "call.outbound"}
    assert q.calls == []
    assert len(contract.calls) == 1
    payload, kwargs = contract.calls[0]
    assert payload["kind"] == "call.outbound"
    assert payload["provider"] == "twilio"
    assert payload["action"] == "call"
    assert payload["to"] == "+15551234"
    assert payload["message"] == "deploy finished"
    assert payload["reason"] == "night-shift"
    assert payload["agent"] == "jarvis"
    assert "now" in kwargs


def test_build_call_request_twilio():
    spec = build_call_request("twilio", "+1", "say <hi>", {"token": "tok"},
                              {"account_sid": "AC1", "from": "+9"})
    assert spec["url"].endswith("/Accounts/AC1/Calls.json")
    assert spec["auth"] == ("AC1", "tok")
    assert spec["data"]["To"] == "+1" and spec["data"]["From"] == "+9"
    assert "&lt;hi&gt;" in spec["data"]["Twiml"]  # xml-escaped


def test_build_call_request_telnyx():
    spec = build_call_request("telnyx", "+1", "hi", {"token": "T"},
                              {"connection_id": "C", "from": "+9"})
    assert spec["url"] == "https://api.telnyx.com/v2/calls"
    assert spec["headers"]["Authorization"] == "Bearer T"
    assert spec["json"]["connection_id"] == "C" and spec["json"]["to"] == "+1"


def test_build_call_request_unsupported():
    with pytest.raises(ValueError):
        build_call_request("skype", "+1", "hi", {}, {})


@pytest.mark.asyncio
async def test_execute_null_client_consumes_budget():
    budget = InterruptBudget(per_day=4)
    null = NullCallClient()
    cb = CallBroker(client=null, budget=budget)
    task = _Task({"provider": "twilio", "to": "+1", "message": "hi",
                  "credential_ref": "{{secret:twilio_auth_token}}"})
    out = await cb.execute(task)
    assert out["status"] == "ok" and out["call"]["status"] == "deferred"
    assert null.calls[0]["to"] == "+1"
    assert budget.remaining() == 3  # consumed one slot


@pytest.mark.asyncio
async def test_execute_resolves_credentials_behind_approval():
    sb = SecretBroker()
    sb.put("twilio_auth_token", "tok_secret")

    class _Rec:
        last = None
        async def call(self, provider, to, message, credentials, config):
            _Rec.last = credentials
            return {"status": "ok"}

    cb = CallBroker(secret_broker=sb, client=_Rec())
    task = _Task({"provider": "twilio", "to": "+1", "message": "hi",
                  "credential_ref": "{{secret:twilio_auth_token}}"})
    await cb.execute(task)
    assert _Rec.last["token"] == "tok_secret"


@pytest.mark.asyncio
async def test_execute_budget_exhausted_at_call_time():
    cb = CallBroker(client=NullCallClient(), budget=InterruptBudget(per_day=0))
    task = _Task({"provider": "twilio", "to": "+1", "message": "hi"})
    out = await cb.execute(task)
    assert out["status"] == "failed" and out["reason"] == "interrupt_budget_exhausted"


@pytest.mark.asyncio
async def test_execute_invalid_payload():
    cb = CallBroker(client=NullCallClient())
    out = await cb.execute(_Task({"provider": "skype", "to": "+1"}))
    assert out["status"] == "failed" and out["reason"] == "invalid_call"


@pytest.mark.asyncio
async def test_http_call_client_twilio():
    class _Resp:
        status_code = 201
        def raise_for_status(self): pass

    class _Http:
        def __init__(self): self.calls = []
        async def request(self, method, url, headers=None, json=None, data=None, auth=None):
            self.calls.append({"url": url, "data": data, "auth": auth, "json": json})
            return _Resp()

    http = _Http()
    out = await HttpCallClient(http=http).call(
        "twilio", "+1", "hi", {"token": "tok"}, {"account_sid": "AC1", "from": "+9"})
    assert out["status"] == "ok" and out["http_status"] == 201
    assert http.calls[0]["auth"] == ("AC1", "tok")
    assert http.calls[0]["data"]["To"] == "+1"


@pytest.mark.asyncio
async def test_end_to_end_governed_execution(tmp_path):
    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.executor import TaskExecutor

    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    try:
        sb = SecretBroker()
        sb.put("twilio_auth_token", "tok_e2e")
        null = NullCallClient()
        cb = CallBroker(enqueue=q.enqueue, secret_broker=sb, client=null,
                        budget=InterruptBudget(per_day=4))

        out = cb.request("+15551234", "your nightly job finished")
        tid = out["task_id"]
        assert q.get(tid).status == "proposed" and null.calls == []

        q.transition(tid, TaskStatus.APPROVED, decided_by="andrei", decision="accept")
        executor = TaskExecutor()
        executor.register("call", cb.execute)
        worker = AutonomyWorker(q, policy=AutonomyPolicy(), executor=executor.execute)
        summary = await worker.tick()

        assert summary["done"] == 1 and q.get(tid).status == "done"
        assert len(null.calls) == 1 and null.calls[0]["has_credential"] is True
    finally:
        q.close()
