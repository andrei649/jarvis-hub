"""The keyed, tamper-evident audit chain (spec §6 "Audit")."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import stat
import threading

import pytest

from agents.core.workspace import audit
from agents.core.workspace import db as workspace_db
from tests.support.workspace_fixtures import (  # noqa: F401
    db,
    freeze_clock,
    make_user,
    seed_company,
    ws,
)


def _write(conn, n: int = 3, **kwargs) -> None:
    for i in range(n):
        with workspace_db.tx(conn):
            audit.record(conn, actor=None, actor_email="cli", action="department.created",
                         target_type="department", target_id=i, details={"n": i, **kwargs})


def test_record_requires_a_transaction(ws):
    conn = db()
    with pytest.raises(RuntimeError, match="transaction"):
        audit.record(conn, actor=None, action="auth.logout")
    assert conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0


def test_chain_links_and_verifies(ws):
    conn = db()
    _write(conn, 4)
    rows = conn.execute("SELECT * FROM audit ORDER BY id").fetchall()
    assert rows[0]["prev_hash"] == audit.GENESIS_HASH
    for previous, current in zip(rows, rows[1:], strict=False):
        assert current["prev_hash"] == previous["hash"]
    assert {row["key_fp"] for row in rows} == {audit.key_fingerprint()}
    assert audit.verify_chain(conn) == {"ok": True, "checked": 4, "broken_at": None, "keyed": True,
                                        "key_mismatch": False}


def test_empty_chain_verifies(ws):
    assert audit.verify_chain(db())["checked"] == 0


def test_hash_is_the_documented_hmac(ws):
    conn = db()
    company = seed_company(conn)
    with workspace_db.tx(conn):
        audit.record(conn, actor=company.admin, action="org.updated", target_type="org", target_id=1,
                     department_id=company.dept_a, ip="10.0.0.1", details={"fields": ["name"], "ă": "ș"})
    row = conn.execute("SELECT * FROM audit").fetchone()
    canonical = json.dumps({
        "ts": row["ts"], "actor_user_id": company.admin.id, "actor_email": company.admin.email,
        "action": "org.updated", "target_type": "org", "target_id": "1",
        "department_id": company.dept_a, "ip": "10.0.0.1", "details": {"fields": ["name"], "ă": "ș"},
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    key = audit.audit_key()
    expected = hmac.new(key, b"nerva-ws-audit-v1" + audit.GENESIS_HASH.encode() + canonical.encode(),
                        hashlib.sha256).hexdigest()
    assert row["hash"] == expected
    assert row["hash"] != hashlib.sha256(canonical.encode()).hexdigest(), "keyed, not a bare digest"
    assert row["key_fp"] == hashlib.sha256(key).hexdigest()[:16]
    assert row["actor_email"] == company.admin.email


def test_key_file_is_private_and_reused(ws):
    key = audit.audit_key()
    path = ws.key_dir / audit.KEY_FILE
    assert path.exists() and audit.key_path() == path
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert audit.audit_key() == key and len(key) == 64
    assert not str(path).startswith(str(ws.data_dir)), "the key lives outside the data root"


def test_env_key_wins(ws, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "  an-operator-key  ")
    assert audit.audit_key() == b"an-operator-key"
    assert not (ws.key_dir / audit.KEY_FILE).exists()


def test_empty_key_file_fails_loudly(ws):
    (ws.key_dir / audit.KEY_FILE).write_bytes(b"\n")
    with pytest.raises(RuntimeError, match="empty"):
        audit.audit_key()


@pytest.mark.parametrize("tamper", [
    "UPDATE audit SET details_json = '{\"n\":99}' WHERE id = 2",
    "UPDATE audit SET action = 'auth.login' WHERE id = 2",
    "UPDATE audit SET ts = ts + 1 WHERE id = 2",
    "UPDATE audit SET actor_email = 'someone' WHERE id = 2",
    "UPDATE audit SET hash = '00' WHERE id = 2",
    "DELETE FROM audit WHERE id = 2",
])
def test_tampering_is_detected(ws, tamper):
    conn = db()
    _write(conn, 3)
    conn.execute(tamper)
    result = audit.verify_chain(conn)
    assert result["ok"] is False and result["checked"] == 1 and result["key_mismatch"] is False
    assert result["broken_at"] in (2, 3)


def test_rewriting_without_the_key_cannot_fix_the_chain(ws):
    conn = db()
    _write(conn, 2)
    row = conn.execute("SELECT * FROM audit WHERE id = 2").fetchone()
    forged = hashlib.sha256((row["prev_hash"] + "forged").encode()).hexdigest()
    conn.execute("UPDATE audit SET details_json = '{\"n\":7}', hash = ? WHERE id = 2", (forged,))
    assert audit.verify_chain(conn)["broken_at"] == 2


def test_key_mismatch_is_reported(ws, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "first-key")
    conn = db()
    _write(conn, 2)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "second-key")
    result = audit.verify_chain(conn)
    assert result == {"ok": False, "checked": 0, "broken_at": 1, "keyed": True, "key_mismatch": True}


def test_forbidden_detail_keys_never_reach_the_table(ws, caplog):
    conn = db()
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.audit"), workspace_db.tx(conn):
        audit.record(conn, actor=None, action="auth.login_failed",
                     details={"reason": "x", "password": "hunter2-hunter2", "token": "abc",
                              "prompt": "secret question", "content": "doc text"})
    details = json.loads(conn.execute("SELECT details_json FROM audit").fetchone()[0])
    assert details == {"reason": "x"}
    assert "hunter2" not in caplog.text and "'password'" in caplog.text
    assert audit.verify_chain(conn)["ok"] is True


def test_credential_keys_are_dropped_at_any_depth(ws, caplog):
    conn = db()
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.audit"), workspace_db.tx(conn):
        audit.record(conn, actor=None, action="smtp.updated", details={
            "fields": ["host", "password"], "has_password": True, "token_revoked": False,
            "prompt_tokens": 512, "smtp_password": "hunter2-hunter2", "API_Token": "abc-123-xyz",
            "password_reset": {"note": "nested under a credential name"},
            "smtp": {"host": "mail.acme.test", "password": "hunter2-hunter2",
                     "auth": [{"client_secret": "s3cr3t-value", "user": "ana"}]},
        })
    stored = conn.execute("SELECT details_json FROM audit").fetchone()[0]
    assert json.loads(stored) == {
        "fields": ["host", "password"], "has_password": True, "token_revoked": False,
        "prompt_tokens": 512, "smtp": {"host": "mail.acme.test", "auth": [{"user": "ana"}]},
    }
    for leaked in ("hunter2", "abc-123-xyz", "s3cr3t-value"):
        assert leaked not in stored and leaked not in caplog.text
    assert "'smtp.password'" in caplog.text and "'smtp.auth.client_secret'" in caplog.text
    assert audit.verify_chain(conn)["ok"] is True


def test_integer_clock_values_still_verify(ws, monkeypatch):
    freeze_clock(monkeypatch, start=1_800_000_000)
    conn = db()
    _write(conn, 2)
    assert audit.verify_chain(conn)["ok"] is True


def test_concurrent_writers_keep_one_valid_chain(ws):
    db().close()  # migrate once up front
    errors: list[BaseException] = []

    def writer(worker: int) -> None:
        conn = workspace_db.connect()
        try:
            for i in range(15):
                with workspace_db.tx(conn):
                    audit.record(conn, actor=None, actor_email=f"w{worker}", action="chat.asked",
                                 details={"i": i})
        except BaseException as exc:  # surfaced below
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    result = audit.verify_chain(db())
    assert result["ok"] is True and result["checked"] == 60


def test_actor_and_explicit_email(ws):
    conn = db()
    company = seed_company(conn)
    with workspace_db.tx(conn):
        audit.record(conn, actor=company.member_a, action="auth.login")
        audit.record(conn, actor=None, actor_email="ghost@acme.test", action="auth.login_failed")
        audit.record(conn, actor=company.member_a, actor_email="cli", action="user.promoted")
    rows = conn.execute("SELECT actor_user_id, actor_email FROM audit ORDER BY id").fetchall()
    assert [tuple(row) for row in rows] == [(company.member_a.id, company.member_a.email),
                                            (None, "ghost@acme.test"), (company.member_a.id, "cli")]
