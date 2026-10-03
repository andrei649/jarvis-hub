"""H485 guardian observer events follow physical send and durable smart CAS."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from contextvars import ContextVar

import httpx
import pytest

from agents.core import settings_db
from agents.core.autonomy.approval_judge import ApprovalJudge
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.task_approval_judge import TaskApprovalJudge
from agents.core.extensions.events import EXTENSION_EVENTS, ExtensionEventBus
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.egress import llm_async_client


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "observer-settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "test-guardian")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER", "lm-studio")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL", "http://localhost:1234")
    monkeypatch.setenv("JARVIS_SMART_APPROVALS", "1")
    monkeypatch.delenv("JARVIS_SMART_APPROVAL_POLICY", raising=False)
    monkeypatch.delenv("JARVIS_SMART_APPROVAL_DENY", raising=False)


@pytest.fixture
def queue(tmp_path):
    key = b"h485-observer-fixture"
    signer = DetachedHMACSigner(lambda payload: hmac.new(key, payload, hashlib.sha256).hexdigest())
    value = TaskQueue(str(tmp_path / "queue.db"), mediation_signer=signer).initialize()
    yield value
    value.close()


def _blocked(queue, *, command="printf hello", title="Run command"):
    task_id = queue.enqueue(
        "jarvis", "toolrpc.terminal_run", title,
        payload={"tool": "terminal_run", "target": "terminal_run",
                 "args": {"target": "dev", "command": command}},
        risk_tier=3, autonomy_level="ask",
    )
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    return task_id


def _wire(queue, handler, *, on_close=None):
    def backend(status):
        instance = object.__new__(LMStudioBackend)
        instance.base_url = status.base_url
        instance.client = llm_async_client(
            "lm-studio", base_url=status.base_url, trust_env=False,
            transport=httpx.MockTransport(handler),
        )
        if on_close is not None:
            async def close():
                await on_close()
                await instance.client.aclose()

            instance.aclose = close
        return instance

    judge = ApprovalJudge(settings=lambda category, key, default=None: default,
                          backend_factory=backend)
    adapter = TaskApprovalJudge(queue)
    adapter.attach_judge(judge, loop=asyncio.get_running_loop())
    return judge, adapter


async def _drain(adapter):
    await asyncio.sleep(0)
    while adapter._judge_tasks:
        await asyncio.gather(*tuple(adapter._judge_tasks))
        await asyncio.sleep(0)


def _events(monkeypatch, on_emit=None):
    seen = []

    def emit(name, **fields):
        seen.append((name, dict(fields)))
        if on_emit is not None:
            on_emit(name, fields)
        return {"event": name, "delivered": ["fixture"], "dropped": 0}

    monkeypatch.setattr(EXTENSION_EVENTS, "emit", emit)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,choice,status", [
    ("APPROVE", "smart_approve", "approved"),
    ("DENY", "smart_deny", "blocked"),
])
async def test_native_request_precedes_http_and_decided_follows_durable_store(
    queue, monkeypatch, reply, choice, status,
):
    order = []
    task_id = _blocked(queue)

    def emitted(name, fields):
        order.append(name)
        if name == "approval.smart.decided":
            persisted = queue.get(task_id)
            assert persisted.status == status
            if status == "blocked":
                assert queue.approval_judgement(
                    task_id, queue.approval_snapshot_digest(persisted)
                )["decision"] == "deny"

    events = _events(monkeypatch, emitted)

    async def handler(_request):
        order.append("http")
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    _judge, adapter = _wire(queue, handler)
    adapter.schedule(task_id)
    await _drain(adapter)

    assert order == ["approval.smart.requested", "http", "approval.smart.decided"]
    assert [name for name, _ in events] == ["approval.smart.requested", "approval.smart.decided"]
    requested, decided = (fields for _, fields in events)
    assert set(requested) == {"request_id", "surface", "command", "description"}
    assert requested["surface"] == "smart"
    assert requested["command"] == "printf hello"
    assert requested["description"] == "Run command"
    assert uuid.UUID(requested["request_id"]).version == 4
    assert decided == {**requested, "choice": choice, "decided_by": "aux_llm"}


@pytest.mark.asyncio
async def test_static_policy_deny_and_escalate_never_emit_decided(queue, monkeypatch):
    events = _events(monkeypatch)
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ESCALATE"}}]})

    _judge, adapter = _wire(queue, handler)
    monkeypatch.setenv("JARVIS_SMART_APPROVAL_DENY", '["printf blocked"]')
    denied = _blocked(queue, command="printf blocked")
    adapter.schedule(denied)
    await _drain(adapter)
    assert requests == [] and events == []
    assert queue.approval_judgement(
        denied, queue.approval_snapshot_digest(queue.get(denied))
    )["decision"] == "deny"

    escalated = _blocked(queue, command="printf uncertain")
    adapter.schedule(escalated)
    await _drain(adapter)
    assert len(requests) == 1
    assert [name for name, _ in events] == ["approval.smart.requested"]
    assert queue.approval_judgement(
        escalated, queue.approval_snapshot_digest(queue.get(escalated))
    )["decision"] == "escalate"


@pytest.mark.asyncio
async def test_stale_or_revoked_request_has_pre_only_and_no_durable_decision(queue, monkeypatch):
    events = _events(monkeypatch)
    task_id = _blocked(queue)

    async def handler(_request):
        monkeypatch.setenv("JARVIS_SMART_APPROVAL_POLICY", "Changed while in flight")
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    _judge, adapter = _wire(queue, handler)
    adapter.schedule(task_id)
    await _drain(adapter)
    assert [name for name, _ in events] == ["approval.smart.requested"]
    assert queue.get(task_id).status == "blocked"
    assert queue.approval_judgement(
        task_id, queue.approval_snapshot_digest(queue.get(task_id))
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raise", "unbound"])
async def test_observation_failure_never_changes_guardian_result(queue, monkeypatch, failure):
    events = []

    def emit(name, **fields):
        events.append(name)
        if failure == "raise":
            raise RuntimeError("secret scanner or observer failed: private data")
        return None

    monkeypatch.setattr(EXTENSION_EVENTS, "emit", emit)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    adapter.schedule(task_id)
    await _drain(adapter)
    assert queue.get(task_id).decision == "smart-approve"
    assert events == ["approval.smart.requested"]


@pytest.mark.asyncio
async def test_concurrent_tasks_keep_distinct_request_identity(queue, monkeypatch):
    events = _events(monkeypatch)
    pending = asyncio.Event()
    arrived = asyncio.Event()
    seen_http = []

    async def handler(request):
        seen_http.append(request)
        if len(seen_http) == 2:
            arrived.set()
        await pending.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    ids = [_blocked(queue, command=f"printf {index}") for index in range(2)]
    for task_id in ids:
        adapter.schedule(task_id)
    await asyncio.wait_for(arrived.wait(), timeout=3)
    assert [name for name, _ in events] == ["approval.smart.requested"] * 2
    pending.set()
    await _drain(adapter)
    pairs = {}
    for name, fields in events:
        pairs.setdefault(fields["request_id"], {})[name] = fields
    assert len(pairs) == 2
    assert {pair["approval.smart.requested"]["command"] for pair in pairs.values()} == {
        "printf 0", "printf 1",
    }
    assert all(set(pair) == {"approval.smart.requested", "approval.smart.decided"}
               for pair in pairs.values())


@pytest.mark.asyncio
async def test_delivery_hang_is_async_and_does_not_delay_decision(queue, monkeypatch):
    delivery = asyncio.Event()
    deliveries = []

    def emit(name, **fields):
        deliveries.append(asyncio.create_task(delivery.wait()))
        return {"event": name, "delivered": ["fixture"], "dropped": 0}

    monkeypatch.setattr(EXTENSION_EVENTS, "emit", emit)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    adapter.schedule(task_id)
    await asyncio.wait_for(_drain(adapter), timeout=3)
    assert queue.approval_judgement(
        task_id, queue.approval_snapshot_digest(queue.get(task_id))
    )["decision"] == "deny"
    assert len(deliveries) == 2 and all(not item.done() for item in deliveries)
    delivery.set()
    await asyncio.gather(*deliveries)


@pytest.mark.asyncio
async def test_observation_identity_failure_does_not_abort_guardian_or_reservation(queue, monkeypatch):
    from agents.core.autonomy import smart_observers

    def fail_uuid():
        raise OSError("entropy unavailable: private detail")

    monkeypatch.setattr(smart_observers.uuid, "uuid4", fail_uuid)
    events = _events(monkeypatch)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    adapter.schedule(task_id)
    await _drain(adapter)
    assert queue.approval_judgement(
        task_id, queue.approval_snapshot_digest(queue.get(task_id))
    )["decision"] == "deny"
    assert adapter._judging == set()
    assert events == []


@pytest.mark.asyncio
async def test_parent_preparation_failure_is_not_retried_in_wait_for_child(queue, monkeypatch):
    from agents.core.autonomy import smart_observers

    original = uuid.uuid4
    attempts = 0

    def first_failure():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary entropy failure")
        return original()

    task_id = _blocked(queue)
    monkeypatch.setattr(smart_observers.uuid, "uuid4", first_failure)
    events = _events(monkeypatch)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    adapter.schedule(task_id)
    await _drain(adapter)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert queue.approval_judgement(task_id, digest)["decision"] == "deny"
    assert events == []
    assert adapter._judging == set()


@pytest.mark.asyncio
async def test_direct_score_emits_only_requested_without_a_durable_store(queue, monkeypatch):
    events = _events(monkeypatch)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    snapshot = adapter._snapshot(queue.get(task_id))
    result = await judge.score(snapshot, judge.status())
    assert result.verdict == "approve"
    assert [name for name, _ in events] == ["approval.smart.requested"]
    assert queue.get(task_id).status == "blocked"


@pytest.mark.asyncio
async def test_advisory_score_never_emits_smart_observation(queue, monkeypatch):
    events = _events(monkeypatch)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"risk": 17, "why": "Routine."}',
        }}]})

    judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    snapshot = adapter._snapshot(queue.get(task_id))
    snapshot["tool"] = "file_write"
    snapshot["args"]["kind"] = "toolrpc.file_write"
    result = await judge.score(snapshot, judge.status())
    assert result["advisory"] is True
    assert events == []


@pytest.mark.asyncio
async def test_native_retry_emits_one_request_and_one_decision(queue, monkeypatch):
    events = _events(monkeypatch)
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(400, json={"error": "Model unloaded by user or API request."})
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    adapter.schedule(task_id)
    await _drain(adapter)
    assert len(requests) == 2
    assert [name for name, _ in events] == [
        "approval.smart.requested", "approval.smart.decided",
    ]
    assert queue.approval_judgement(
        task_id, queue.approval_snapshot_digest(queue.get(task_id))
    )["decision"] == "deny"


@pytest.mark.asyncio
async def test_cleanup_revocation_keeps_pre_without_post(queue, monkeypatch):
    events = _events(monkeypatch)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "APPROVE"}}]})

    async def close():
        monkeypatch.setenv("JARVIS_SMART_APPROVAL_POLICY", "changed during close")

    _judge, adapter = _wire(queue, handler, on_close=close)
    task_id = _blocked(queue)
    adapter.schedule(task_id)
    await _drain(adapter)
    assert [name for name, _ in events] == ["approval.smart.requested"]
    assert queue.get(task_id).status == "blocked"


@pytest.mark.asyncio
async def test_failed_durable_store_has_no_decided_event(queue, monkeypatch):
    events = _events(monkeypatch)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    monkeypatch.setattr(adapter, "_store_judgement", lambda snapshot, annotation: None)
    task_id = _blocked(queue)
    adapter.schedule(task_id)
    await _drain(adapter)
    assert [name for name, _ in events] == ["approval.smart.requested"]
    assert queue.approval_judgement(
        task_id, queue.approval_snapshot_digest(queue.get(task_id))
    ) is None


@pytest.mark.asyncio
async def test_secret_preparation_failure_suppresses_pair_without_changing_result(queue, monkeypatch):
    from agents.core.security.scanner import SecretScanner

    events = _events(monkeypatch)

    def fail_redact(self, _value):
        raise ValueError("untrusted private secret")

    monkeypatch.setattr(SecretScanner, "redact", fail_redact)

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue)
    adapter.schedule(task_id)
    await _drain(adapter)
    assert events == []
    assert queue.approval_judgement(
        task_id, queue.approval_snapshot_digest(queue.get(task_id))
    )["decision"] == "deny"


@pytest.mark.asyncio
async def test_preparation_redacts_source_before_fake_observer_receives_it(queue, monkeypatch):
    events = _events(monkeypatch)
    secret = "Bearer abcdefghijklmnopqrstuvwxyz123456"

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue, command=f"printf '{secret}'", title=f"Do not log {secret}")
    adapter.schedule(task_id)
    await _drain(adapter)
    assert len(events) == 2
    for _name, fields in events:
        assert secret not in fields["command"]
        assert secret not in fields["description"]
        assert "[REDACTED:" in fields["command"]


@pytest.mark.asyncio
async def test_real_bound_bus_delivers_scanned_pair_without_grant_authority(queue, monkeypatch):
    class Runtime:
        def __init__(self):
            self.events = []

        def observers(self, _event):
            return ("observer",)

        async def observe(self, _extension_id, event, payload):
            self.events.append((event, payload))
            return {"decision": "approve", "grant": "fake"}

    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime)
    monkeypatch.setattr(EXTENSION_EVENTS, "bus", bus)
    secret = "Bearer abcdefghijklmnopqrstuvwxyz123456"

    async def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    _judge, adapter = _wire(queue, handler)
    task_id = _blocked(queue, command=f"printf '{secret}'")
    adapter.schedule(task_id)
    await _drain(adapter)
    await bus.drain(timeout=1)
    assert [event for event, _ in runtime.events] == [
        "approval.smart.requested", "approval.smart.decided",
    ]
    requested, decided = (payload for _, payload in runtime.events)
    assert requested["request_id"] == decided["request_id"]
    assert secret not in requested["command"] and secret not in decided["command"]
    assert decided["choice"] == "smart_deny"
    assert "decision" not in decided and "grant" not in decided
    assert queue.approval_judgement(
        task_id, queue.approval_snapshot_digest(queue.get(task_id))
    )["decision"] == "deny"
