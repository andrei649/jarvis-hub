"""H512: bearer guard decisions and managed credential lifecycle audit."""

import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
from contextlib import redirect_stdout

import pytest
from fastapi import HTTPException

from agents.core.security import auth_audit
from agents.core.security import token_store as token_store_mod
from agents.core.security.audit import AuditLogger
from agents.core.security.token_store import TokenStore
from agents.core.security.types import SecurityEvent, SecurityEventType


class Request:
    def __init__(self, headers=None, host="10.0.0.9"):
        self.headers = headers or {}
        self.client = type("Client", (), {"host": host})()


@pytest.fixture
def context(tmp_path, monkeypatch):
    from agents import web

    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    store = TokenStore(db_path=str(tmp_path / "tokens.db"), audit_sink=audit)
    monkeypatch.setattr(token_store_mod, "_store", store)
    monkeypatch.setattr(auth_audit, "_resolve_sink", lambda: audit)
    monkeypatch.setattr(auth_audit, "_active_sink", lambda: audit)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    monkeypatch.setattr(web, "USER_TOKEN", "")
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    web._CONFIGURED_SCOPES.clear()
    yield web, store, audit
    auth_audit.flush_pending()
    store.close()


async def test_guard_rows_cover_success_failure_and_local_bypass(context):
    web, store, audit = context
    with pytest.raises(HTTPException) as denial:
        await web._admin_guard(Request())
    assert denial.value.status_code == 403
    await web._admin_guard(Request(host="127.0.0.1"))
    token = store.issue("admin")
    await web._admin_guard(Request({"x-admin-token": token}))
    with pytest.raises(HTTPException) as denial:
        await web._admin_guard(Request({"x-admin-token": "wrong"}))
    assert denial.value.status_code == 401
    auth_audit.flush_pending()
    rows = audit.query(limit=20)
    guards = [r for r in rows if r.event_type.value.startswith("auth_")]
    assert {(r.event_type.value, r.action_taken) for r in guards} == {
        ("auth_failure", "admin:network_disabled"),
        ("auth_success", "admin:local_bypass"),
        ("auth_success", "admin:credential"),
        ("auth_failure", "admin:invalid"),
    }
    assert audit.verify_chain() == (True, None)


async def test_user_admin_superset_and_missing_failure(context):
    web, store, audit = context
    admin = store.issue("admin")
    store.issue("user")
    await web._user_guard(Request({"x-admin-token": admin}))
    with pytest.raises(HTTPException) as denial:
        await web._user_guard(Request())
    assert denial.value.status_code == 401
    auth_audit.flush_pending()
    rows = [r for r in audit.query(limit=20) if r.event_type.value.startswith("auth_")]
    assert {(r.event_type.value, r.action_taken) for r in rows} == {
        ("auth_success", "user:admin_credential"),
        ("auth_failure", "user:missing"),
    }


async def test_user_guard_credential_invalid_and_local_network_paths(context):
    web, store, audit = context
    with pytest.raises(HTTPException) as denial:
        await web._user_guard(Request())
    assert denial.value.status_code == 403
    await web._user_guard(Request(host="127.0.0.1"))
    token = store.issue("user")
    await web._user_guard(Request({"x-user-token": token}))
    with pytest.raises(HTTPException) as denial:
        await web._user_guard(Request({"x-user-token": "invalid-user-secret"}))
    assert denial.value.status_code == 401
    auth_audit.flush_pending()
    rows = [r for r in audit.query(limit=20) if r.event_type.value.startswith("auth_")]
    assert {(r.event_type.value, r.action_taken) for r in rows} == {
        ("auth_failure", "user:network_disabled"),
        ("auth_success", "user:local_bypass"),
        ("auth_success", "user:credential"),
        ("auth_failure", "user:invalid"),
    }
    assert b"invalid-user-secret" not in audit._db_path.read_bytes()


async def test_sink_failure_does_not_change_guard_result_or_log_secret(context, monkeypatch, caplog):
    web, store, _ = context
    secret = "sensitive-token-999"
    store.issue("admin")

    class BrokenSink:
        def log(self, event):
            raise RuntimeError(secret)

    monkeypatch.setattr(auth_audit, "_resolve_sink", lambda: BrokenSink())
    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BrokenSink())
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as denial:
            await web._admin_guard(Request({"x-admin-token": secret}))
        assert denial.value.status_code == 401
        valid = store.issue("admin")
        await web._admin_guard(Request({"x-admin-token": valid}))
        auth_audit.flush_pending()
    assert secret not in caplog.text


async def test_broken_warning_handler_does_not_change_guard_result(context, monkeypatch):
    web, store, _ = context
    store.issue("admin")

    class BrokenSink:
        def log(self, event):
            raise OSError("private exception value")

    def broken_warning(*args, **kwargs):
        raise OSError("warning backend failed")

    monkeypatch.setattr(auth_audit, "_resolve_sink", lambda: BrokenSink())
    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BrokenSink())
    monkeypatch.setattr(auth_audit.logger, "warning", broken_warning)
    monkeypatch.setattr(auth_audit, "_last_warning", 0.0)
    auth_audit.record_auth_event("auth_failure", tier="admin", reason="missing")
    with pytest.raises(HTTPException) as denial:
        await web._admin_guard(Request())
    assert denial.value.status_code == 401
    auth_audit.flush_pending()


def test_cli_lifecycle_rows_are_single_and_chain_verifies(context, capsys):
    _, store, audit = context
    assert token_store_mod._main(["issue", "admin"]) == 0
    first = capsys.readouterr().out.strip()
    assert store.verify(first) == "admin"
    assert token_store_mod._main(["rotate", "admin"]) == 0
    second = capsys.readouterr().out.strip()
    assert store.verify(first) is None
    assert store.verify(second) == "admin"
    assert token_store_mod._main(["revoke", "admin", "--revoke-env"]) == 0
    assert store.verify(second) is None
    assert store.env_revoked("admin") is True
    rows = audit.query(limit=20)
    kinds = [r.event_type.value for r in rows]
    assert kinds == ["token_revoked", "token_rotated", "token_issued"]
    assert audit.verify_chain() == (True, None)
    raw = (audit._db_path).read_bytes()
    assert first.encode() not in raw and second.encode() not in raw


def test_cli_process_persists_lifecycle_chain_before_exit(tmp_path):
    env = os.environ.copy()
    env["JARVIS_HOME"] = str(tmp_path)

    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "agents.core.security.token_store", *args],
            env=env, capture_output=True, text=True, timeout=10, check=True,
        )
        return result.stdout.strip()

    first = cli("issue", "admin")
    second = cli("rotate", "admin")
    assert first != second
    assert cli("revoke", "admin", "--revoke-env") == "revoked 1 token(s)"
    audit = AuditLogger(db_path=str(tmp_path / "security" / "audit.db"))
    assert [r.event_type.value for r in audit.query(limit=10)] == [
        "token_revoked", "token_rotated", "token_issued",
    ]
    assert audit.verify_chain() == (True, None)
    assert first.encode() not in audit._db_path.read_bytes()
    assert second.encode() not in audit._db_path.read_bytes()


def test_revoke_env_without_managed_rows_is_audited(context):
    _, store, audit = context
    assert store.revoke_all("user", revoke_env=True) == 0
    auth_audit.flush_pending()
    row = audit.query(event_type="token_revoked")[0]
    assert row.action_taken == "user:revoke"
    assert json.loads(row.content_preview)["count"] == 0
    assert json.loads(row.content_preview)["revoke_env"] is True


def test_token_mutation_survives_broken_sink(tmp_path):
    class BrokenSink:
        def log(self, event):
            raise RuntimeError("never print me")

    store = TokenStore(db_path=str(tmp_path / "tokens.db"), audit_sink=BrokenSink())
    old = store.issue("admin")
    fresh = store.rotate("admin")
    assert store.verify(old) is None
    assert store.verify(fresh) == "admin"
    assert store.revoke_all("admin", revoke_env=True) == 1
    assert store.verify(fresh) is None


def test_slow_lifecycle_sink_cannot_hold_new_credentials(tmp_path):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    issued = []

    class SlowSink:
        def log(self, event):
            started.set()
            release.wait(timeout=5)

    store = TokenStore(db_path=str(tmp_path / "tokens.db"), audit_sink=SlowSink())

    def mutate():
        first = store.issue("admin")
        second = store.rotate("admin")
        issued.extend((first, second))
        finished.set()

    worker = threading.Thread(target=mutate)
    worker.start()
    try:
        assert started.wait(timeout=2)
        assert finished.wait(timeout=0.5)
        assert store.verify(issued[0]) is None
        assert store.verify(issued[1]) == "admin"
    finally:
        release.set()
        worker.join(timeout=3)
        auth_audit.flush_pending()


def test_cli_prints_usable_token_when_audit_sink_stalls(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    output = io.StringIO()

    class SlowSink:
        def log(self, event):
            started.set()
            release.wait(timeout=5)

    store = TokenStore(db_path=str(tmp_path / "tokens.db"), audit_sink=SlowSink())
    monkeypatch.setattr(token_store_mod, "_store", store)

    def run_cli():
        with redirect_stdout(output):
            assert token_store_mod._main(["issue", "user"]) == 0
        finished.set()

    worker = threading.Thread(target=run_cli)
    worker.start()
    try:
        assert started.wait(timeout=2)
        assert finished.wait(timeout=1)
        assert store.verify(output.getvalue().strip()) == "user"
    finally:
        release.set()
        worker.join(timeout=3)
        auth_audit.flush_pending()


def test_admin_rotate_route_emits_one_typed_event(context):
    from fastapi.testclient import TestClient

    from agents.core.routers import _deps

    web, _, audit = context
    web.app.dependency_overrides[_deps.admin_guard] = lambda: None
    try:
        with TestClient(web.app) as client:
            response = client.post("/api/admin/rotate-tokens", json={"scope": "user"})
        assert response.status_code == 200
        auth_audit.flush_pending()
        assert len(audit.query(event_type="token_rotated")) == 1
        assert not [r for r in audit.query(event_type="audit_log")
                    if r.action_taken == "token_rotated"]
    finally:
        web.app.dependency_overrides.pop(_deps.admin_guard, None)


def test_auth_metadata_drops_secret_fields_before_sink(context):
    _, _, audit = context
    secret = "sensitive-token-999"
    auth_audit.record_auth_event(
        "auth_failure", tier="admin", reason="invalid", client="10.0.0.9",
        token=secret, authorization=secret, cookie=secret, state=secret,
        event_time=secret,
    )
    row = audit.query(event_type="auth_failure")[0]
    assert secret not in str(row)
    assert secret.encode() not in audit._db_path.read_bytes()


async def test_guard_queue_drops_at_fixed_cap_without_changing_auth(context, monkeypatch):
    web, store, _ = context
    started = threading.Event()
    release = threading.Event()
    calls = []

    class SlowSink:
        def log(self, event):
            started.set()
            release.wait(timeout=5)
            calls.append(event)

    slow = SlowSink()
    monkeypatch.setattr(auth_audit, "_active_sink", lambda: slow)
    try:
        for _ in range(65):
            auth_audit.submit_auth_event("auth_failure", tier="admin", reason="missing")
        assert started.wait(timeout=2)
        assert auth_audit._queue.unfinished_tasks == 64
        token = store.issue("admin")
        await web._admin_guard(Request({"x-admin-token": token}))
        with pytest.raises(HTTPException) as denial:
            await web._admin_guard(Request())
        assert denial.value.status_code == 401
        assert auth_audit._queue.unfinished_tasks == 64
    finally:
        release.set()
        auth_audit.flush_pending()
    assert len(calls) == 64


def test_queued_event_keeps_its_original_live_sink(tmp_path, monkeypatch):
    old_audit = AuditLogger(db_path=str(tmp_path / "old.db"))
    new_audit = AuditLogger(db_path=str(tmp_path / "new.db"))
    started = threading.Event()
    release = threading.Event()

    class BlockingOldSink:
        def log(self, event):
            started.set()
            release.wait(timeout=5)
            old_audit.log(event)

    active = [BlockingOldSink()]
    monkeypatch.setattr(auth_audit, "_active_sink", lambda: active[0])
    try:
        auth_audit.submit_auth_event("auth_failure", tier="admin", reason="missing")
        assert started.wait(timeout=2)
        auth_audit.submit_auth_event("auth_failure", tier="user", reason="missing")
        active[0] = new_audit
        auth_audit.submit_auth_event("auth_failure", tier="user", reason="invalid")
    finally:
        release.set()
        auth_audit.flush_pending()
    assert [r.action_taken for r in old_audit.query(limit=10)] == [
        "user:missing", "admin:missing",
    ]
    assert [r.action_taken for r in new_audit.query(limit=10)] == ["user:invalid"]


def test_queued_row_timestamp_is_submission_time(tmp_path, monkeypatch):
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    started = threading.Event()
    release = threading.Event()

    class BlockingSink:
        def log(self, event):
            if event.action_taken == "admin:missing":
                started.set()
                release.wait(timeout=5)
            audit.log(event)

    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BlockingSink())
    try:
        auth_audit.submit_auth_event("auth_failure", tier="admin", reason="missing")
        assert started.wait(timeout=2)
        before = time.time()
        auth_audit.submit_auth_event("auth_failure", tier="user", reason="missing")
        after = time.time()
        time.sleep(0.2)
    finally:
        release.set()
        auth_audit.flush_pending()
    queued = next(r for r in audit.query(limit=10) if r.action_taken == "user:missing")
    assert before <= queued.timestamp <= after


def test_queued_metadata_drops_secrets_before_enqueue(tmp_path, monkeypatch):
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    started = threading.Event()
    release = threading.Event()

    class BlockingSink:
        def log(self, event):
            started.set()
            release.wait(timeout=5)
            audit.log(event)

    monkeypatch.setattr(auth_audit, "_active_sink", lambda: BlockingSink())
    secret = "queued-secret-999"
    try:
        auth_audit.submit_auth_event("auth_failure", tier="admin", reason="missing")
        assert started.wait(timeout=2)
        auth_audit.submit_auth_event(
            "auth_failure", tier="admin", reason="invalid", client="10.0.0.9",
            token=secret, authorization=secret, event_time=secret,
        )
        assert secret not in repr(list(auth_audit._queue.queue))
    finally:
        release.set()
        auth_audit.flush_pending()
    assert secret.encode() not in audit._db_path.read_bytes()


def test_two_audit_connections_append_one_valid_chain(tmp_path, monkeypatch):
    path = tmp_path / "shared-audit.db"
    first = AuditLogger(db_path=str(path))
    second = AuditLogger(db_path=str(path))
    second_started = threading.Event()
    original_tail = first._tail_hash_unlocked

    def delayed_tail():
        tail = original_tail()
        assert second_started.wait(timeout=2)
        time.sleep(0.1)
        return tail

    monkeypatch.setattr(first, "_tail_hash_unlocked", delayed_tail)
    errors = []

    def write(logger, index):
        try:
            if index == 2:
                second_started.set()
            logger.log(SecurityEvent(SecurityEventType.AUTH_FAILURE, time.time(),
                                     content_preview=f"event {index}"))
        except Exception as exc:
            errors.append(exc)

    a = threading.Thread(target=write, args=(first, 1))
    b = threading.Thread(target=write, args=(second, 2))
    a.start()
    b.start()
    a.join(timeout=3)
    b.join(timeout=3)
    assert not a.is_alive() and not b.is_alive()
    assert not errors
    assert first.count() == 2
    assert first.verify_chain() == (True, None)
