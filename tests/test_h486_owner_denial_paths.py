"""H486 — every settled owner "no" on a chat terminal call feeds the denial breaker.

The single-card reject is covered in test_h485_denial_feedback_queue.py. The other two
places the owner says no go through their own queue writes: the grouped reject of a model
that retried one command, and the reusable-consent deny. Both count on the same tally, and
a consent session/always grant is an owner approval that resets it.
"""
from __future__ import annotations

import pytest

from agents.core.approval_outcomes import open_approval_turn, render_chat_outcomes
from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.commands import Principal
from tests.test_h487_consent_queue_runtime import _ask, _turn, world  # noqa: F401


async def _retry(server, times):
    """One model turn that retries the identical command: one registered group."""
    ids = []
    with _turn():
        for _ in range(times):
            reply = await server.handle({"tool": "terminal_run",
                                         "args": {"command": "printf synthetic"}})
            ids.append(reply["task_id"])
    return ids


def _owner_turn():
    return open_approval_turn(
        session_id="session", session_instance="instance",
        principal=Principal(channel="web", admin=True), session_is_live=lambda *_: True,
    )


def _tally(queue):
    row = queue._conn.execute(
        "SELECT consecutive_denials FROM chat_guardian_denial_tallies").fetchall()
    return [r[0] for r in row]


def _guardians(queue):
    items = sorted(queue.chat_outcome_snapshot(_owner_turn()), key=lambda item: item["task_id"])
    return items, [item.get("guardian") for item in items]


def _deny(queue, task_id):
    offer = queue.pending_consent_offer(task_id)
    assert offer is not None
    actor = OwnerConsentActor("admin", "admin", lambda: True)
    return queue.decide_reusable_consent(task_id, offer.revision, choice="deny", actor=actor,
                                         reason="not this")


@pytest.mark.asyncio
@pytest.mark.parametrize("world", ["enforce"], indirect=True)
async def test_grouped_owner_reject_counts_every_member_and_trips_the_breaker(world):  # noqa: F811
    queue, server, _policy, _external, _captured = world
    ids = await _retry(server, 3)
    group = queue.pending_group(ids[0])
    assert group is not None and group["member_ids"] == ids
    assert _tally(queue) == []
    rejected = queue.reject_pending_group(group["id"], snapshot=group["snapshot"],
                                          member_ids=group["member_ids"], decided_by="admin",
                                          reason="stop retrying")
    assert [task.status for task in rejected] == ["rejected"] * 3
    assert _tally(queue) == [3]
    items, guardians = _guardians(queue)
    assert [g["consecutive_denials"] for g in guardians] == [1, 2, 3]
    assert [g["breaker"] for g in guardians] == [False, False, True]
    assert "STOP attempting variations" in render_chat_outcomes(items)[0]


@pytest.mark.asyncio
async def test_consent_deny_counts_and_trips_the_breaker(world):  # noqa: F811
    queue, server, _policy, _external, _captured = world
    for expected in (1, 2, 3):
        task_id = await _ask(server)
        result = _deny(queue, task_id)
        assert result is not None and [t.status for t in result.tasks] == ["rejected"]
        assert queue.get(task_id).decision == "consent-deny"
        assert _tally(queue) == [expected]
    items, guardians = _guardians(queue)
    assert [g["consecutive_denials"] for g in guardians] == [1, 2, 3]
    assert [g["breaker"] for g in guardians] == [False, False, True]
    assert all(item["decision"]["action"] == "deny" for item in items)
    assert "STOP attempting variations" in render_chat_outcomes(items)[0]


@pytest.mark.asyncio
async def test_a_grouped_consent_deny_counts_every_member(world):  # noqa: F811
    queue, server, _policy, _external, _captured = world
    ids = await _retry(server, 3)
    result = _deny(queue, ids[0])
    assert result is not None and [t.id for t in result.tasks] == ids
    assert _tally(queue) == [3]
    _items, guardians = _guardians(queue)
    assert [g["breaker"] for g in guardians] == [False, False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["session", "always"])
async def test_a_consent_grant_resets_the_tally(world, choice):  # noqa: F811
    queue, server, _policy, _external, _captured = world
    for _ in range(2):
        assert _deny(queue, await _ask(server)) is not None
    assert _tally(queue) == [2]
    task_id = await _ask(server)
    offer = queue.pending_consent_offer(task_id)
    actor = OwnerConsentActor("admin", "admin", lambda: True)
    assert queue.decide_reusable_consent(task_id, offer.revision, choice=choice, actor=actor)
    assert _tally(queue) == []
    _items, guardians = _guardians(queue)
    assert guardians[:2] == [
        {"decision": "deny", "consecutive_denials": 1, "breaker": False},
        {"decision": "deny", "consecutive_denials": 2, "breaker": False},
    ]
    assert _deny(queue, await _ask(server)) is not None
    assert _tally(queue) == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("world", ["enforce"], indirect=True)
async def test_a_group_reject_and_single_reject_share_one_tally_without_double_counting(world):  # noqa: F811
    from agents.core.autonomy.queue import TaskQueueError, TaskStatus

    queue, server, _policy, _external, _captured = world
    first, second = await _retry(server, 2)
    group = queue.pending_group(first)
    queue.reject_pending_group(group["id"], snapshot=group["snapshot"],
                               member_ids=group["member_ids"], decided_by="admin")
    assert _tally(queue) == [2]
    # A settled task cannot be rejected again, so the tally cannot be counted twice.
    with pytest.raises(TaskQueueError):
        queue.transition(first, TaskStatus.REJECTED, decided_by="owner", decision="reject",
                         human_reason=None)
    assert _tally(queue) == [2]
    assert second != first
