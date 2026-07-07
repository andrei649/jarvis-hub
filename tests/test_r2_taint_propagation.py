"""R2 residual safety: taint survives queue intake, edits, and recall."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.autonomy.policy import ACT, ASK
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.memory.fusion import FusedHit
from agents.core.memory.manager import MemoryManager
from agents.core.security import taint
from agents.core.security.rag_guard import provenance_from_hit


class _ActPolicy:
    def decide(self, action):
        return SimpleNamespace(outcome=ACT, tier=1, reason="policy would act")


def _worker(tmp_path) -> AutonomyWorker:
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    return AutonomyWorker(queue=queue, policy=_ActPolicy(), budget=SimpleNamespace(consume=lambda: False))


def test_govern_enqueue_forces_ask_and_marks_payload_from_inbound_context(tmp_path):
    worker = _worker(tmp_path)
    token = bind_action_origin("inbound")
    try:
        task_id = worker.govern_enqueue(
            "scribe",
            "writeback.create",
            "Create external task",
            payload={"risk_tier": 1, "text": "please do this"},
            risk_tier=1,
            autonomy_level=ACT,
            origin="generated",
        )
    finally:
        reset_action_origin(token)

    task = worker.queue.get(task_id)
    assert task.status == TaskStatus.BLOCKED.value
    assert task.autonomy_level == ASK
    assert task.origin == "inbound"
    assert taint.is_tainted(task.payload) is True
    assert task.payload["taint_source"] == "inbound"


@pytest.mark.asyncio
async def test_submit_forces_ask_and_marks_payload_from_inbound_origin(tmp_path):
    worker = _worker(tmp_path)

    task = await worker.submit(
        "scribe",
        "writeback.create",
        "Create external task",
        payload={"risk_tier": 1, "text": "please do this"},
        origin="inbound",
    )

    assert task.status == TaskStatus.BLOCKED.value
    assert task.autonomy_level == ASK
    assert task.origin == "inbound"
    assert taint.is_tainted(task.payload) is True


@pytest.mark.asyncio
async def test_edit_decision_retaints_inbound_payload_and_keeps_blocked(tmp_path):
    worker = _worker(tmp_path)
    task_id = worker.queue.enqueue(
        "scribe",
        "writeback.create",
        "Create external task",
        payload={"risk_tier": 1, "text": "original"},
        risk_tier=1,
        autonomy_level=ASK,
        origin="inbound",
    )
    worker.queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")

    task = await worker.apply_decision(task_id, "edit", payload={"risk_tier": 1, "text": "edited"})

    assert task.status == TaskStatus.BLOCKED.value
    assert task.decision == "needs-approval"
    assert task.origin == "inbound"
    assert taint.is_tainted(task.payload) is True
    assert task.payload["text"] == "edited"


class _HashEmbedder:
    def embed(self, text):
        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vals = [b / 255 for b in digest]
        return (vals * ((768 // len(vals)) + 1))[:768]


@pytest.mark.asyncio
async def test_inbound_user_turn_embedding_carries_taint_metadata():
    mm = MemoryManager()
    mm._embedder = _HashEmbedder()
    mm.embed_turns = True
    sid = await mm.new_session()

    await mm.add_turn(sid, "user", "external channel text", channel="telegram")

    assert len(mm.vectors.records) == 1
    meta = mm.vectors.records[0].metadata
    assert meta["channel"] == "telegram"
    assert meta["origin"] == "inbound"
    assert taint.is_tainted(meta) is True
    assert meta["taint_source"] == "inbound:telegram"


def test_recall_provenance_prefers_taint_source_over_generic_vector():
    hit = FusedHit(
        id="mem-1",
        score=0.42,
        sources=["vector"],
        payload={
            "metadata": {
                "text": "external channel text",
                "tainted": True,
                "taint_source": "inbound:telegram",
            }
        },
    )

    snippet = provenance_from_hit(hit)

    assert snippet.source == "inbound:telegram"
    assert snippet.text == "external channel text"
