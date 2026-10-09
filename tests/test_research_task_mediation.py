"""The exact research task uses task-persisted kernel authority before web search."""

from __future__ import annotations

import hashlib
import hmac
from threading import Lock
from types import SimpleNamespace

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.kernel import Decision, Verdict
from agents.core.kernel.binding import MediationKernelBridge
from agents.core.kernel.registry import Mediation, classify

_KEY = b"research-mediation-test-key-with-enough-bytes"


class _HeadStore:
    def __init__(self):
        self._head = None
        self._lock = Lock()

    def read(self):
        with self._lock:
            return self._head

    def compare_and_swap(self, expected, replacement):
        with self._lock:
            if self._head != expected:
                return False
            self._head = replacement
            return True


@pytest.fixture
def make_queue(tmp_path):
    queues = []

    def create(mode="enforce"):
        path = tmp_path / f"{mode}-{len(queues)}.db"
        store = _HeadStore()
        signer = DetachedHMACSigner(
            lambda body: hmac.new(_KEY, body, hashlib.sha256).hexdigest()
        )
        queue = TaskQueue(
            str(path),
            mediation_mode=mode,
            mediation_signer=signer,
            mediation_head_anchor=MonotonicHeadAnchor(store.read, store.compare_and_swap),
            mediation_scope="global",
        ).initialize()
        queues.append(queue)
        return queue, signer

    yield create
    for queue in queues:
        queue.close()


def _worker(queue, signer, verdict, *, outcome="act"):
    calls = []

    def decide(action):
        calls.append(action)
        return Decision(verdict, reason="test decision", tier=0)

    worker = AutonomyWorker(
        queue,
        policy=SimpleNamespace(decide=lambda _action: SimpleNamespace(
            outcome=outcome, tier=0, reason="read only"
        )),
        kernel=MediationKernelBridge(decide) if verdict is not None else None,
        mediation_signer=signer,
    )
    return worker, calls


def _search_executor(worker, calls):
    async def fake_websearch(task):
        calls.append(task.payload["query"])
        return {"status": "ok", "results": ["fake local result"]}

    executor = TaskExecutor(execution_guard=worker.execution_allowed).register(
        "research", fake_websearch
    )
    worker.executor = executor.execute
    return executor


def test_exact_research_classifies_as_kernel_and_unknown_stays_unknown(make_queue):
    queue, _signer = make_queue()
    assert classify("research") is Mediation.KERNEL
    assert queue.classify_mediation("research") is True
    assert classify("research.extra") is None
    assert queue.classify_mediation("research.extra") is None
    for kind in ("research", "research.extra"):
        with pytest.raises(TaskQueueError, match="requires mediation"):
            queue.enqueue("jarvis", kind, "Research", {"query": "probe"})
    assert queue.list() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "expected_status"),
    [(Verdict.GRANT, TaskStatus.APPROVED), (Verdict.QUEUE, TaskStatus.BLOCKED)],
)
async def test_governed_research_receipt_and_private_execution_permit(
    make_queue, monkeypatch, verdict, expected_status
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    queue, signer = make_queue()
    worker, kernel_calls = _worker(queue, signer, verdict)
    searches = []
    executor = _search_executor(worker, searches)

    task = await worker.submit(
        "jarvis", "research", "Research local probe", {"query": "harbor"},
        attention_mode="none",
    )
    assert len(kernel_calls) == 1
    assert kernel_calls[0].kind == "research"
    assert kernel_calls[0].payload == {"query": "harbor"}
    assert task.status == expected_status.value
    assert task.mediation_receipt["verdict"] == verdict.value
    assert task.mediation_receipt["kind"] == "research"
    assert queue.verified_mediation_stats()["authorized_enqueue"] == 1

    # A valid persisted task still cannot call the adapter outside the worker's
    # private, single-use permit. QUEUE additionally needs an owner acceptance.
    assert await executor.execute(task) == {
        "status": "refused", "reason": "mediation_execution_context_required"
    }
    assert searches == []
    if verdict is Verdict.QUEUE:
        await worker.apply_decision(task.id, "accept", decided_by="owner")
    summary = await worker.tick()
    assert summary["done"] == 1
    assert queue.get(task.id).status == TaskStatus.DONE.value
    assert searches == ["harbor"]
    assert queue.verified_mediation_stats()["governed"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", [Verdict.DENY, None])
async def test_research_deny_or_missing_kernel_refuses_before_persistence(
    make_queue, monkeypatch, verdict
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    queue, signer = make_queue()
    worker, calls = _worker(queue, signer, verdict)
    searches = []
    _search_executor(worker, searches)
    with pytest.raises(TaskQueueError, match="denied|unavailable"):
        await worker.submit(
            "jarvis", "research", "Research local probe", {"query": "harbor"},
            attention_mode="none",
        )
    assert len(calls) == (0 if verdict is None else 1)
    assert queue.list() == []
    assert searches == []


@pytest.mark.asyncio
async def test_research_persisted_tuple_tamper_never_reaches_search(make_queue, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    queue, signer = make_queue()
    worker, _calls = _worker(queue, signer, Verdict.GRANT)
    searches = []
    _search_executor(worker, searches)
    task = await worker.submit(
        "jarvis", "research", "Research local probe", {"query": "harbor"},
        attention_mode="none",
    )
    queue._conn.execute("UPDATE tasks SET payload=? WHERE id=?", ('{"query":"changed"}', task.id))
    queue._conn.commit()
    summary = await worker.tick()
    assert summary["done"] == 0
    assert searches == []
    assert queue.get(task.id).status == TaskStatus.QUARANTINED.value


def test_off_compatibility_and_hold_refusal(make_queue):
    off, _ = make_queue("off")
    assert off.enqueue("jarvis", "research", "Research", {"query": "harbor"}) == 1
    hold, _ = make_queue("hold")
    with pytest.raises(TaskQueueError, match="mediation hold"):
        hold.enqueue("jarvis", "research", "Research", {"query": "harbor"})
    assert hold.list() == []
