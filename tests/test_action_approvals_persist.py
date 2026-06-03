"""A7: ActionApprovalQueue opt-in persistence + JsonStore in-memory mode."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.persistence import JsonStore


# ── JsonStore in-memory (path=None) ───────────────────────────────────────────

def test_jsonstore_in_memory_mode():
    class S(JsonStore):
        def _serialize(self): return self._d
        def _deserialize(self, raw): self._d = raw if isinstance(raw, dict) else {}
    s = S(None)
    assert s.path is None
    s._d = {"x": 1}
    s._save()                         # no-op, must not raise


# ── persistence ───────────────────────────────────────────────────────────────

def test_queue_persists_when_path_given(tmp_path):
    p = tmp_path / "aa.json"
    q = ActionApprovalQueue(path=p)
    item = q.request({"tool": "deploy", "args": {"x": 1}})
    q2 = ActionApprovalQueue(path=p)        # reload from disk
    reloaded = q2.get(item["id"])
    assert reloaded is not None and reloaded["status"] == "pending"
    assert q2.stats()["pending"] == 1


def test_decision_survives_reload(tmp_path):
    p = tmp_path / "aa.json"
    q = ActionApprovalQueue(path=p)
    item = q.request({"tool": "x"})
    q.decide(item["id"], True)
    assert ActionApprovalQueue(path=p).get(item["id"])["status"] == "approved"


def test_in_memory_default_does_not_persist(tmp_path, monkeypatch):
    # default (no path) stays in-memory → isolated, writes nothing
    q = ActionApprovalQueue()
    assert q.path is None
    q.request({"tool": "x"})
    assert q.stats()["pending"] == 1


@pytest.mark.asyncio
async def test_await_decision_recreates_event_for_reloaded_item(tmp_path):
    p = tmp_path / "aa.json"
    q = ActionApprovalQueue(path=p)
    item = q.request({"tool": "x"})
    # fresh instance reloaded from disk has no in-memory event yet
    q2 = ActionApprovalQueue(path=p)

    async def approve():
        await asyncio.sleep(0.01)
        q2.decide(item["id"], True)

    asyncio.create_task(approve())
    status = await q2.await_decision(item["id"], timeout=0.5)   # must lazily create the event
    assert status == "approved"
