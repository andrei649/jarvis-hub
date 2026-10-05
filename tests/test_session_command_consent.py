"""A session command opt-out becomes durable only after governed owner approval."""

from __future__ import annotations

import hashlib
import json

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.channels.session_command_consent import (
    SessionCommandConsent,
    session_command_digest,
)
from agents.core.permission_ledger import PermissionLedger, PermissionRequestError

OWNER = ("telegram", "tg:123:topic:7", "42")


@pytest.fixture
def governed(tmp_path):
    ledger = PermissionLedger(tmp_path / "permissions.db", enabled=False)
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register("permission.grant", ledger.apply_grant)
    worker.executor = executor.execute
    consent = SessionCommandConsent(ledger, worker.govern_enqueue)
    yield consent, ledger, queue, worker, tmp_path / "permissions.db"
    queue.close()
    ledger.close()


def test_digest_canonicalizes_only_recognized_operations():
    canonical = json.dumps(
        ["session_command", "telegram", "tg:123:topic:7", "42", "reset"],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert session_command_digest(OWNER, "/new") == expected
    assert session_command_digest(OWNER, "/reset") == expected
    assert session_command_digest(OWNER, "reset") == expected
    assert session_command_digest(OWNER, "/undo") != expected
    assert session_command_digest(("telegram", "tg:123:topic:7", "43"), "/reset") != expected
    assert session_command_digest(("telegram", "tg:123:topic:8", "42"), "/reset") != expected
    assert session_command_digest(("web", "tg:123:topic:7", "42"), "/reset") != expected


@pytest.mark.parametrize("command", ["/delete", "reset --hard", "", "/undo all", "/new@otherbot"])
def test_unrelated_command_cannot_acquire_session_command_selector(command):
    with pytest.raises(PermissionRequestError):
        session_command_digest(OWNER, command)


@pytest.mark.parametrize("key", [(), ("telegram", "route"), ("", "route", "42"),
                                 ("telegram", "", "42"), ("telegram", "route", ""),
                                 ("telegram", "route", None),
                                 ("telegram", "route", "42", "extra")])
def test_unverified_or_incomplete_identity_is_rejected(key):
    with pytest.raises(PermissionRequestError):
        session_command_digest(key, "/reset")


def test_missing_ledger_asks_but_cannot_request_permanence():
    consent = SessionCommandConsent(None, None)
    assert consent.check(OWNER, "/reset") == "ask"
    with pytest.raises((PermissionRequestError, RuntimeError)):
        consent.request_always(OWNER, "/reset", "owner")


def test_missing_governed_intake_cannot_request_permanence(tmp_path):
    ledger = PermissionLedger(tmp_path / "permissions.db", enabled=False)
    try:
        consent = SessionCommandConsent(ledger, None)
        assert consent.check(OWNER, "/reset") == "ask"
        with pytest.raises((PermissionRequestError, RuntimeError)):
            consent.request_always(OWNER, "/reset", "owner")
        assert ledger.list_grants(include_inactive=True) == []
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_real_worker_request_remains_pending_until_owner_approval_and_execution(governed):
    consent, ledger, queue, worker, _ = governed
    assert consent.check(OWNER, "/reset") == "ask"  # required even with legacy flag off
    task_id = consent.request_always(OWNER, "/new", "owner-42")
    pending = queue.get(task_id)
    assert pending.kind == "permission.grant"
    assert pending.status == "blocked"
    assert pending.human_decision is None
    assert pending.payload["key"] == session_command_digest(OWNER, "/reset")
    assert pending.payload["scope"] == "always"
    assert ledger.list_grants(include_inactive=True) == []
    assert consent.check(OWNER, "/reset") == "ask"
    assert (await worker.tick(task_id=task_id))["done"] == 0
    assert consent.check(OWNER, "/reset") == "ask"

    approved = await worker.apply_decision(task_id, "accept", decided_by="owner-42")
    assert approved.status == "approved"
    assert approved.human_decision is not None
    assert consent.check(OWNER, "/reset") == "ask"
    assert (await worker.tick(task_id=task_id))["done"] == 1
    assert consent.check(OWNER, "/reset") == "allow"
    assert consent.check(OWNER, "/new") == "allow"
    assert consent.check(OWNER, "/undo") == "ask"
    assert consent.check(("telegram", "tg:123:topic:7", "43"), "/reset") == "ask"
    assert consent.check(("telegram", "tg:123:topic:8", "42"), "/reset") == "ask"


@pytest.mark.asyncio
async def test_policy_decision_cannot_mint_grant_through_registered_executor(governed):
    consent, ledger, queue, worker, _ = governed
    task_id = consent.request_always(OWNER, "reset", "owner-42")
    approved = await worker.apply_decision(task_id, "accept", decided_by="policy")
    assert approved.status == "approved"
    await worker.tick(task_id=task_id)
    assert queue.get(task_id).result["reason"] == "human_decision_required"
    assert ledger.list_grants(include_inactive=True) == []
    assert consent.check(OWNER, "reset") == "ask"


@pytest.mark.asyncio
async def test_grant_survives_restart_then_revoke_restores_ask(governed):
    consent, ledger, queue, worker, path = governed
    task_id = consent.request_always(OWNER, "/undo", "owner-42")
    await worker.apply_decision(task_id, "accept", decided_by="owner-42")
    assert (await worker.tick(task_id=task_id))["done"] == 1
    grants = ledger.list_grants()
    assert len(grants) == 1
    restarted = PermissionLedger(path, enabled=False)
    try:
        restored = SessionCommandConsent(restarted, worker.govern_enqueue)
        assert restored.check(OWNER, "/undo") == "allow"
        assert restarted.revoke(grants[0].id).status == "revoked"
        assert restored.check(OWNER, "/undo") == "ask"
    finally:
        restarted.close()


def test_never_row_denies_and_request_cannot_override(governed):
    consent, ledger, queue, _worker, _ = governed
    digest = session_command_digest(OWNER, "/undo")
    ledger.deny("session_command", digest)
    assert consent.check(OWNER, "/undo") == "deny"
    with pytest.raises(PermissionRequestError, match="never_entry"):
        consent.request_always(OWNER, "/undo", "owner-42")
    assert queue.list() == []
