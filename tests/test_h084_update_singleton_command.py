"""A durable hub.update singleton refuses without reusing another signed card."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.core import hub_update_apply
from agents.core.autonomy import irreversible
from agents.core.autonomy.queue import HubUpdateActive, TaskQueue, TaskQueueError
from agents.core.commands import CommandContext, Principal
from agents.core.update_commands import update_command


def _plan():
    return {"can_apply": True, "from": "a" * 40, "to": "b" * 40,
            "target_ref": "@{u}", "tag": None, "dirty_policy": "refuse",
            "from_version": "1", "to_version": "2",
            "dependencies": {"changed": False, "command": None},
            "migrations": [], "migrations_uncertain": False, "frontend_changed": False,
            "dirty": False, "verdict": {"how": "pinned", "signer": None},
            "commit_count": 1, "commits": [], "file_count": 0}


def _orch(govern, queue):
    return SimpleNamespace(autonomy=SimpleNamespace(govern_enqueue=govern, queue=queue))


def _context(orch):
    return CommandContext(orch, Principal(channel="web", admin=True), "update", "")


def test_only_typed_singleton_refusal_maps_to_in_progress():
    queue = SimpleNamespace()

    def typed(**_kwargs):
        raise HubUpdateActive()

    def generic(**_kwargs):
        raise TaskQueueError("unknown private queue detail")

    request = {"kind": "hub.update", "title": "update", "payload": {"to": "b" * 40}, "preview": {}}
    assert irreversible.enqueue(_orch(typed, queue), **request) == {"refused": "update_in_progress"}
    assert irreversible.enqueue(_orch(generic, queue), **request) == {"refused": "approval_queue_refused"}


@pytest.mark.parametrize("active", ["approved", "running", "deferred"])
async def test_real_queue_busy_after_precheck_miss_never_rebinds_card_or_audits(
        tmp_path, monkeypatch, active):
    queue = TaskQueue(str(tmp_path / "tasks.db"), mediation_mode="off").initialize()
    try:
        existing = queue.enqueue(agent="owner", kind="hub.update", title="older target",
                                 payload={"to": "a" * 40})
        queue._conn.execute("UPDATE tasks SET status=? WHERE id=?", (active, existing))
        queue._conn.commit()
        # /update's process-local UX precheck cannot see approved/running/deferred;
        # force the missed read so the durable queue guard is the authority.
        monkeypatch.setattr(queue, "pending_decisions", lambda **_kwargs: [])
        orch = _orch(queue.enqueue, queue)
        remembered, audited = [], []
        monkeypatch.setattr(hub_update_apply, "plan",
                            lambda ref=None, dirty_policy="refuse": _plan())
        monkeypatch.setattr(hub_update_apply, "_remember_card",
                            lambda *args: remembered.append(args))
        monkeypatch.setattr(hub_update_apply, "_audit",
                            lambda *args: audited.append(args))
        monkeypatch.setattr(hub_update_apply, "apply_approved",
                            lambda *_args: pytest.fail("update effect ran"))
        reply = await update_command(_context(orch))
        assert "pending or running" in reply.lower()
        assert "#" not in reply and "b" * 40 not in reply
        assert remembered == audited == []
        rows = queue._conn.execute("SELECT id, payload FROM tasks WHERE kind='hub.update'").fetchall()
        assert len(rows) == 1 and rows[0]["id"] == existing
        assert json.loads(rows[0]["payload"])["to"] == "a" * 40
    finally:
        queue.close()
