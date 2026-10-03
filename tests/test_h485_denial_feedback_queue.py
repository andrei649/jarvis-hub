"""H485 queue-local feedback from committed guardian denials, never authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
    render_chat_outcomes,
    tool_approval_scope,
)
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.smart_approvals import SmartApprovalResult
from agents.core.commands import Principal


def _signer():
    key = b"h485-denial-feedback-test-key"
    return DetachedHMACSigner(lambda payload: hmac.new(key, payload, hashlib.sha256).hexdigest())


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SMART_DENIAL_BREAKER_THRESHOLD", raising=False)
    value = TaskQueue(str(tmp_path / "tasks.db"), mediation_signer=_signer()).initialize()
    yield value
    value.close()


def _turn(*, session="s", instance="i", principal=None):
    return open_approval_turn(
        session_id=session, session_instance=instance,
        principal=principal or Principal(channel="web", admin=True),
        session_is_live=lambda _session, _instance: True,
    )


def _propose(queue, *, context=None, command="printf hello"):
    def create():
        task_id = queue.enqueue(
            "jarvis", "toolrpc.terminal_run", "Run command",
            payload={"tool": "terminal_run", "target": "terminal_run",
                     "args": {"target": "dev", "command": command}},
            risk_tier=3, autonomy_level="ask",
        )
        queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
        return task_id

    if context is None:
        task_id = create()
    else:
        token = bind_approval_turn(context)
        try:
            with tool_approval_scope("terminal_run"):
                task_id = create()
        finally:
            close_approval_turn(context, token)
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    assert digest is not None
    return task_id, digest


def _judge(queue, task_id, digest, verdict="deny", *, check=lambda: True):
    result = SmartApprovalResult(
        verdict=verdict, policy_revision="a" * 64, judge_revision="b" * 64,
        judge={"model": "test-guardian"}, at=1_000_000.0,
    )
    return queue.store_smart_terminal_judgement(task_id, digest, result, check=check)


def _guardian(queue, context=None):
    observations = sorted(queue.chat_outcome_snapshot(context or _turn()),
                          key=lambda item: item["task_id"])
    return [item.get("guardian") for item in observations]


def _tallies(queue):
    return queue._conn.execute(
        "SELECT session_id, session_instance, principal_key, consecutive_denials "
        "FROM chat_guardian_denial_tallies ORDER BY session_id, session_instance, principal_key"
    ).fetchall()


def test_third_exact_denial_warns_with_event_count_only(queue):
    for expected in (1, 2, 3):
        task_id, digest = _propose(queue, context=_turn(), command=f"printf {expected}")
        assert _judge(queue, task_id, digest)[0]["decision"] == "deny"
    observations = sorted(queue.chat_outcome_snapshot(_turn()), key=lambda item: item["task_id"])
    assert [item["guardian"] for item in observations] == [
        {"decision": "deny", "consecutive_denials": 1, "breaker": False},
        {"decision": "deny", "consecutive_denials": 2, "breaker": False},
        {"decision": "deny", "consecutive_denials": 3, "breaker": True},
    ]
    assert all(set(item["guardian"]) == {"decision", "consecutive_denials", "breaker"}
               for item in observations)
    assert len(render_chat_outcomes(observations)[0].encode()) <= 4096
    assert len(_tallies(queue)) == 1


def test_duplicate_stale_escalate_and_missing_context_do_not_count(queue):
    unbound, unbound_digest = _propose(queue)
    assert _judge(queue, unbound, unbound_digest)[0]["decision"] == "deny"
    assert _tallies(queue) == []

    first, digest = _propose(queue, context=_turn())
    assert _judge(queue, first, "0" * 64) == (None, None)
    assert _judge(queue, first, digest, check=lambda: False) == (None, None)
    assert _judge(queue, first, digest, "escalate")[0]["decision"] == "escalate"
    assert _judge(queue, first, digest) == (None, None)
    assert _tallies(queue) == []
    second, second_digest = _propose(queue, context=_turn())
    assert _judge(queue, second, second_digest)[0]["decision"] == "deny"
    assert _judge(queue, second, second_digest) == (None, None)
    assert _guardian(queue)[-1] == {"decision": "deny", "consecutive_denials": 1,
                                  "breaker": False}


def test_changed_task_revision_hides_stale_event_then_counts_new_denial(queue):
    task_id, digest = _propose(queue, context=_turn())
    _judge(queue, task_id, digest)
    old, = queue.chat_outcome_snapshot(_turn())
    queue.update_payload(task_id, queue.get(task_id).payload)
    changed, = queue.chat_outcome_snapshot(_turn())
    assert changed["intent"] == "changed"
    assert "guardian" not in changed
    assert changed["revision"] != old["revision"]
    assert _judge(queue, task_id, digest) == (None, None)
    fresh = queue.approval_snapshot_digest(queue.get(task_id))
    assert fresh != digest
    assert _judge(queue, task_id, fresh)[0]["decision"] == "deny"
    renewed, = queue.chat_outcome_snapshot(_turn())
    assert renewed["guardian"] == {"decision": "deny", "consecutive_denials": 2,
                                   "breaker": False}


def test_signed_approve_resets_without_reviving_old_warning(queue):
    for index in range(3):
        task_id, digest = _propose(queue, context=_turn(), command=f"printf deny{index}")
        _judge(queue, task_id, digest)
    old = sorted(queue.chat_outcome_snapshot(_turn()), key=lambda item: item["task_id"])
    assert old[-1]["guardian"]["breaker"] is True
    approved, approved_digest = _propose(queue, context=_turn(), command="printf approve")
    assert _judge(queue, approved, approved_digest, "approve")[0]["decision"] == "approve"
    after = sorted(queue.chat_outcome_snapshot(_turn()), key=lambda item: item["task_id"])
    assert after[2]["guardian"] == {"decision": "deny", "consecutive_denials": 3,
                                    "breaker": False}
    assert _tallies(queue) == []
    assert after[2]["revision"] != old[2]["revision"]
    for index in range(3):
        fresh, fresh_digest = _propose(queue, context=_turn(), command=f"printf fresh{index}")
        _judge(queue, fresh, fresh_digest)
    renewed = sorted(queue.chat_outcome_snapshot(_turn()), key=lambda item: item["task_id"])
    assert renewed[2]["guardian"] == {"decision": "deny", "consecutive_denials": 3,
                                      "breaker": False}
    assert renewed[-1]["guardian"] == {"decision": "deny", "consecutive_denials": 3,
                                       "breaker": True}


@pytest.mark.parametrize("decision,edit", [("accept", False), ("edit", True)])
def test_recorded_human_approval_resets_but_reject_does_not(queue, decision, edit):
    denied, digest = _propose(queue, context=_turn())
    _judge(queue, denied, digest)
    rejected, rejected_digest = _propose(queue, context=_turn(), command="printf rejected")
    _judge(queue, rejected, rejected_digest)
    queue.transition(rejected, TaskStatus.REJECTED, decided_by="owner", decision="reject",
                     human_reason=None)
    assert _tallies(queue)[0][3] == 2
    approved, _ = _propose(queue, context=_turn(), command="printf accepted")
    if edit:
        task = queue.get(approved)
        queue.update_payload_policy(approved, task.payload, risk_tier=task.risk_tier,
                                    autonomy_level=task.autonomy_level, decided_by="owner",
                                    human_reason=None, approve=True)
    else:
        queue.transition(approved, TaskStatus.APPROVED, decided_by="owner",
                         decision=decision, human_reason=None)
    assert _tallies(queue) == []
    assert _guardian(queue)[0]["breaker"] is False


def test_identity_and_instance_isolation_and_restart(queue):
    telegram = Principal(channel="telegram", sender="owner", chat="room", admin=True)
    for _ in range(3):
        task_id, digest = _propose(queue, context=_turn(principal=telegram))
        _judge(queue, task_id, digest)
    assert _guardian(queue, _turn(principal=telegram))[-1]["breaker"] is True
    assert queue.chat_outcome_snapshot(_turn()) == []
    assert queue.chat_outcome_snapshot(_turn(instance="replacement", principal=telegram)) == []
    other = TaskQueue(queue.db_path, mediation_signer=_signer()).initialize()
    try:
        assert _guardian(other, _turn(principal=telegram))[-1]["consecutive_denials"] == 3
    finally:
        other.close()


def test_approval_resets_only_matching_consumer_identity(queue):
    telegram = Principal(channel="telegram", sender="owner", chat="room", admin=True)
    for index in range(3):
        task_id, digest = _propose(queue, context=_turn(principal=telegram),
                                   command=f"printf {index}")
        _judge(queue, task_id, digest)
    web_id, web_digest = _propose(queue, context=_turn(), command="printf web")
    _judge(queue, web_id, web_digest, "approve")
    replacement_id, replacement_digest = _propose(
        queue, context=_turn(instance="replacement", principal=telegram),
        command="printf replacement",
    )
    _judge(queue, replacement_id, replacement_digest, "approve")
    assert _guardian(queue, _turn(principal=telegram))[-1]["breaker"] is True
    own_id, own_digest = _propose(queue, context=_turn(principal=telegram),
                                  command="printf own")
    _judge(queue, own_id, own_digest, "approve")
    assert _guardian(queue, _turn(principal=telegram))[2]["breaker"] is False


@pytest.mark.parametrize("raw,breaker", [("0", False), ("-1", False), ("bad", True),
                                         ("1000001", False), ("1", True)])
def test_live_threshold_parsing(queue, monkeypatch, raw, breaker):
    task_id, digest = _propose(queue, context=_turn())
    _judge(queue, task_id, digest)
    for index in range(2):
        task_id, digest = _propose(queue, context=_turn(), command=f"printf {index}")
        _judge(queue, task_id, digest)
    monkeypatch.setenv("JARVIS_SMART_DENIAL_BREAKER_THRESHOLD", raw)
    assert _guardian(queue)[-1]["breaker"] is breaker


def test_ready_birth_checked_association_required(queue):
    context = _turn()
    token = bind_approval_turn(context)
    try:
        with tool_approval_scope("terminal_run"):
            task_id = queue.enqueue("jarvis", "toolrpc.terminal_run", "Unready",
                                    payload={"tool": "terminal_run", "target": "terminal_run",
                                             "args": {"target": "dev", "command": "pwd"}},
                                    autonomy_level="ask")
    finally:
        close_approval_turn(context, token)
    queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
    digest = queue.approval_snapshot_digest(queue.get(task_id))
    _judge(queue, task_id, digest)
    assert _tallies(queue) == []
    observations = queue.chat_outcome_snapshot(_turn())
    assert not observations or "guardian" not in observations[0]

    second, second_digest = _propose(queue, context=_turn())
    queue._conn.execute("UPDATE chat_approval_tasks SET task_birth=? WHERE task_id=?", ("wrong", second))
    queue._conn.commit()
    _judge(queue, second, second_digest)
    assert _tallies(queue) == []


def test_concurrent_duplicate_write_counts_once(queue):
    task_id, digest = _propose(queue, context=_turn())
    other = TaskQueue(queue.db_path, mediation_signer=_signer()).initialize()
    barrier = threading.Barrier(2)
    outcomes = []

    def write(q):
        barrier.wait()
        outcomes.append(_judge(q, task_id, digest)[0])

    threads = [threading.Thread(target=write, args=(q,)) for q in (queue, other)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(result is not None for result in outcomes) == 1
    assert _tallies(queue)[0][3] == 1
    other.close()


def test_denial_event_and_tally_roll_back_together(queue):
    task_id, digest = _propose(queue, context=_turn())
    queue._conn.execute("CREATE TRIGGER fail_guardian BEFORE INSERT ON chat_guardian_denial_tallies "
                        "BEGIN SELECT RAISE(ABORT, 'tally failed'); END")
    queue._conn.commit()
    assert _judge(queue, task_id, digest) == (None, None)
    assert queue.approval_judgement(task_id, digest) is None
    queue._conn.execute("DROP TRIGGER fail_guardian")
    queue._conn.commit()
    assert _judge(queue, task_id, digest)[0]["decision"] == "deny"
    assert _tallies(queue)[0][3] == 1


def test_purge_and_backup_include_only_observational_metadata(queue):
    task_id, digest = _propose(queue, context=_turn())
    _judge(queue, task_id, digest)
    backup = queue.chat_outcomes_for_backup("s", session_instance="i")
    assert backup["tasks"][0]["denial_count"] == 1
    assert backup["guardian_denials"][0]["consecutive_denials"] == 1
    assert "printf hello" not in json.dumps(backup)
    assert queue.purge_chat_outcomes("s", "other") == 0
    assert _tallies(queue)[0][3] == 1
    assert queue.purge_chat_outcomes("s", "i") == 1
    assert _tallies(queue) == []
    assert queue.chat_outcome_snapshot(_turn()) == []


def test_tally_capacity_evicts_old_epoch_without_reviving_warning(queue, monkeypatch):
    monkeypatch.setenv("JARVIS_SMART_DENIAL_BREAKER_THRESHOLD", "1")
    monkeypatch.setattr("agents.core.autonomy.queue._now", lambda: "2026-10-03T00:00:00+00:00")
    for index in range(257):
        task_id, digest = _propose(queue, context=_turn(session=f"s{index}"))
        _judge(queue, task_id, digest)
    assert len(_tallies(queue)) == 256
    old, = queue.chat_outcome_snapshot(_turn(session="s0"))
    assert old["guardian"] == {"decision": "deny", "consecutive_denials": 1,
                               "breaker": False}
    assert _guardian(queue, _turn(session="s1"))[0]["breaker"] is True
    refreshed_id, refreshed_digest = _propose(queue, context=_turn(session="s1"),
                                              command="printf refresh")
    _judge(queue, refreshed_id, refreshed_digest)
    task_id, digest = _propose(queue, context=_turn(session="s0"), command="printf again")
    _judge(queue, task_id, digest)
    refreshed = sorted(queue.chat_outcome_snapshot(_turn(session="s0")),
                       key=lambda item: item["task_id"])
    assert refreshed[0]["guardian"]["breaker"] is False
    assert refreshed[1]["guardian"]["breaker"] is True
    assert len(_tallies(queue)) == 256
    active_sessions = {row[0] for row in _tallies(queue)}
    assert "s1" in active_sessions and "s2" not in active_sessions


def test_denial_count_saturates_at_one_million(queue):
    task_id, digest = _propose(queue, context=_turn())
    _judge(queue, task_id, digest)
    queue._conn.execute("UPDATE chat_guardian_denial_tallies SET consecutive_denials=1000000")
    queue._conn.commit()
    next_id, next_digest = _propose(queue, context=_turn(), command="printf next")
    _judge(queue, next_id, next_digest)
    assert _tallies(queue)[0][3] == 1_000_000
    assert _guardian(queue)[-1]["consecutive_denials"] == 1_000_000


def test_terminal_retention_purges_orphan_denial_tally(queue):
    task_id, digest = _propose(queue, context=_turn())
    _judge(queue, task_id, digest)
    queue.transition(task_id, TaskStatus.REJECTED, decided_by="owner", decision="reject",
                     human_reason=None)
    context = _turn()
    assert queue.ack_chat_outcomes(context, queue.chat_outcome_snapshot(context)) == 1
    queue._conn.execute("UPDATE chat_approval_tasks SET acknowledged_at='2000-01-01T00:00:00+00:00'")
    queue._conn.commit()
    assert queue.prune_chat_outcomes() == 1
    assert _tallies(queue) == []
    assert queue.chat_outcomes_for_backup("s", session_instance="i").get("guardian_denials", []) == []


@pytest.mark.parametrize("table,column,value", [
    ("chat_approval_tasks", "denial_count", -1),
    ("chat_approval_tasks", "denial_count", 1_000_001),
    ("chat_approval_tasks", "denial_epoch", "broken"),
    ("chat_approval_tasks", "denial_epoch", "z" * 32),
    ("chat_approval_tasks", "denial_snapshot_sha256", "0" * 64),
    ("task_smart_approvals", "annotation", '{"decision":"approve"}'),
    ("task_smart_approvals", "annotation", '{'),
])
def test_malformed_stored_denial_event_omits_guardian(queue, table, column, value):
    task_id, digest = _propose(queue, context=_turn())
    _judge(queue, task_id, digest)
    assert _guardian(queue)[0]["decision"] == "deny"
    queue._conn.execute(f"UPDATE {table} SET {column}=? WHERE task_id=?", (value, task_id))
    queue._conn.commit()
    observation, = queue.chat_outcome_snapshot(_turn())
    assert "guardian" not in observation


@pytest.mark.parametrize("corruption", ["minimal", "extra", "nonfinite", "noncanonical"])
def test_incomplete_or_noncanonical_smart_hold_omits_guardian(queue, corruption):
    task_id, digest = _propose(queue, context=_turn())
    _judge(queue, task_id, digest)
    stored = queue._conn.execute(
        "SELECT annotation FROM task_smart_approvals WHERE task_id=?", (task_id,)
    ).fetchone()[0]
    annotation = json.loads(stored)
    if corruption == "minimal":
        changed = '{"advisory":false,"decision":"deny"}'
    elif corruption == "extra":
        annotation["extra"] = True
        changed = json.dumps(annotation, sort_keys=True, separators=(",", ":"))
    elif corruption == "nonfinite":
        annotation["at"] = float("nan")
        changed = json.dumps(annotation, sort_keys=True, separators=(",", ":"))
    else:
        changed = json.dumps(annotation, sort_keys=True)
    queue._conn.execute("UPDATE task_smart_approvals SET annotation=? WHERE task_id=?",
                        (changed, task_id))
    queue._conn.commit()
    observation, = queue.chat_outcome_snapshot(_turn())
    assert "guardian" not in observation


def test_latest_active_breaker_preempts_waiting_backlog_with_exact_ack(queue):
    waiting = [_propose(queue, context=_turn(), command=f"printf waiting{index}")[0]
               for index in range(8)]
    plain = queue.chat_outcome_snapshot(_turn())
    assert [item["task_id"] for item in plain] == waiting

    denied = []
    for index in range(4):
        task_id, digest = _propose(queue, context=_turn(), command=f"printf denied{index}")
        _judge(queue, task_id, digest)
        denied.append(task_id)
    consumer = _turn()
    prioritized = queue.chat_outcome_snapshot(consumer)
    assert len(prioritized) == 8
    assert prioritized[0]["task_id"] == denied[-1]
    assert prioritized[0]["guardian"] == {"decision": "deny", "consecutive_denials": 4,
                                          "breaker": True}
    assert [item["task_id"] for item in prioritized[1:]] == waiting[:7]
    assert queue.ack_chat_outcomes(consumer, prioritized) == 8
    remainder = queue.chat_outcome_snapshot(_turn())
    assert [item["task_id"] for item in remainder] == [denied[-2], waiting[-1], *denied[:2]]
    assert remainder[0]["guardian"]["breaker"] is True
    assert all(item["task_id"] != denied[-1] for item in remainder)
    assert queue.ack_chat_outcomes(_turn(), remainder) == 4
    assert queue.chat_outcome_snapshot(_turn()) == []
    other = _turn(principal=Principal(channel="telegram", sender="owner", chat="other",
                                     admin=True))
    assert queue.chat_outcome_snapshot(other) == []


def test_owner_reset_rolls_back_with_approval_if_tally_delete_fails(queue):
    denied, digest = _propose(queue, context=_turn())
    _judge(queue, denied, digest)
    approved, _ = _propose(queue, context=_turn(), command="printf approve")
    queue._conn.execute("CREATE TRIGGER fail_guardian_reset BEFORE DELETE ON chat_guardian_denial_tallies "
                        "BEGIN SELECT RAISE(ABORT, 'reset failed'); END")
    queue._conn.commit()
    with pytest.raises(Exception, match="reset failed"):
        queue.transition(approved, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                         human_reason=None)
    assert queue.get(approved).status == "blocked"
    assert _tallies(queue)[0][3] == 1
    queue._conn.execute("DROP TRIGGER fail_guardian_reset")
    queue._conn.commit()
    queue.transition(approved, TaskStatus.APPROVED, decided_by="owner", decision="accept",
                     human_reason=None)
    assert _tallies(queue) == []


def test_signed_approval_reset_rolls_back_with_receipt_if_tally_delete_fails(queue):
    denied, digest = _propose(queue, context=_turn())
    _judge(queue, denied, digest)
    approved, approved_digest = _propose(queue, context=_turn(), command="printf approve")
    queue._conn.execute("CREATE TRIGGER fail_guardian_reset BEFORE DELETE ON chat_guardian_denial_tallies "
                        "BEGIN SELECT RAISE(ABORT, 'reset failed'); END")
    queue._conn.commit()
    assert _judge(queue, approved, approved_digest, "approve") == (None, None)
    assert queue.get(approved).status == "blocked"
    assert queue.approval_judgement(approved, approved_digest) is None
    assert _tallies(queue)[0][3] == 1
    queue._conn.execute("DROP TRIGGER fail_guardian_reset")
    queue._conn.commit()
    assert _judge(queue, approved, approved_digest, "approve")[0]["decision"] == "approve"
    assert _tallies(queue) == []
