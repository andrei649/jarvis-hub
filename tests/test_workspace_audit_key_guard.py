"""A process whose audit key is not the trail's never writes (review fix OPS2-01).

Before the fix, a hub started with another ``JARVIS_AUDIT_KEY`` (a rebuild that followed
PILOT_GUIDE §4 "Generați cheile" again) signed every new row with it: the first sign-in
broke the chain for good, and restoring the right key could not repair it. Now every
write refuses with ``503 audit_key_mismatch`` and nothing is written; the operator checks
the key with the read-only ``check`` command before starting, and a key that is truly
lost is replaced on purpose with the audited ``audit-rekey`` command, which verification
then crosses.
"""

from __future__ import annotations

import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_admin, workspace_auth
from agents.core.workspace import audit, auth, cli, config
from agents.core.workspace import db as workspace_db
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    authed,
    db,
    login,
    make_app,
    origin_of,
    seed_company,
    ws,
)

OTHER_KEY = "b" * 64
THIRD_KEY = "c" * 64


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """The suite's environment is the configuration; never read a developer's .env."""
    monkeypatch.setattr(cli, "load_hub_env", lambda: {})


def _write(conn, n: int = 1, action: str = "department.created") -> None:
    for i in range(n):
        with workspace_db.tx(conn):
            audit.record(conn, actor=None, actor_email="cli", action=action,
                         target_type="department", target_id=i, details={"n": i})


def _count(conn, table: str = "audit") -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 (test tables)


def _client() -> TestClient:
    return TestClient(make_app(workspace_auth.router, workspace_admin.router))


def _post_login(client: TestClient, email: str):
    return client.post("/api/workspace/login", json={"email": email, "password": DEFAULT_PASSWORD},
                       headers={"Origin": origin_of(client)})


# ── the server refuses to sign with another key ──────────────────────────────────────

def test_a_hub_with_another_key_writes_nothing_and_the_right_key_still_verifies(
        ws, monkeypatch, caplog):
    """The finding's repro: sign in with a second key over a non-empty trail."""
    conn = db()
    company = seed_company(conn)
    client = _client()
    login(client, company.admin.email)
    rows, sessions = _count(conn), _count(conn, "sessions")
    trail_fp = conn.execute("SELECT key_fp FROM audit ORDER BY id DESC").fetchone()[0]

    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)      # e.g. a rebuild with fresh keys
    with caplog.at_level(logging.ERROR, logger="nerva.workspace.audit"):
        response = _post_login(_client(), company.admin.email)
    assert response.status_code == 503, response.text
    assert response.json()["error"] == "audit_key_mismatch"
    assert _count(conn) == rows, "nothing was written under the other key"
    assert _count(conn, "sessions") == sessions, "the sign-in was rolled back with its audit row"
    other_fp = audit.key_fingerprint(OTHER_KEY.encode())
    assert trail_fp in caplog.text and other_fp in caplog.text and "JARVIS_AUDIT_KEY" in caplog.text
    assert OTHER_KEY not in caplog.text, "the key itself is never logged"

    monkeypatch.delenv("JARVIS_AUDIT_KEY")                 # the remedy: the service's key is back
    login(_client(), company.admin.email)
    assert audit.verify_chain(conn) == {
        "ok": True, "checked": rows + 1, "broken_at": None, "keyed": True, "key_mismatch": False,
        "unverified": 0, "rekeyed_at": None}


def test_signed_in_requests_are_refused_too_and_verify_stays_readable(ws, monkeypatch):
    conn = db()
    company = seed_company(conn)
    client = _client()
    csrf = login(client, company.admin.email)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    response = client.post("/api/workspace/logout", headers=authed(client, csrf))
    assert response.status_code == 503 and response.json()["error"] == "audit_key_mismatch"
    verify = client.get("/api/workspace/admin/audit/verify")
    assert verify.status_code == 200, "verification only reads, so it still answers"
    assert verify.json()["ok"] is False and verify.json()["key_mismatch"] is True


def test_correct_passwords_refused_for_the_key_do_not_lock_the_account(ws, monkeypatch):
    """Five tries while the key is wrong must not leave the admin throttled once it is fixed."""
    conn = db()
    company = seed_company(conn)
    login(_client(), company.admin.email)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    for _ in range(auth.LOGIN_EMAIL_LIMIT + 1):
        response = _post_login(_client(), company.admin.email)
        assert response.status_code == 503, response.text
    monkeypatch.delenv("JARVIS_AUDIT_KEY")
    login(_client(), company.admin.email)
    assert audit.verify_chain(conn)["ok"] is True


def test_record_refuses_a_key_file_that_is_not_the_trails(ws, monkeypatch):
    conn = db()
    _write(conn, 2)
    key_file = ws.key_dir / audit.KEY_FILE
    original = key_file.read_bytes()
    key_file.write_bytes(OTHER_KEY.encode())               # another JARVIS_KEY_DIR's file
    with pytest.raises(audit.AuditKeyMismatch) as caught:
        _write(conn, 1)
    assert (caught.value.code, caught.value.status) == ("audit_key_mismatch", 503)
    assert isinstance(caught.value, audit.AuditKeyError)
    assert _count(conn) == 2
    assert audit.key_check(conn) == "mismatch"
    key_file.write_bytes(original)
    _write(conn, 1)
    assert audit.verify_chain(conn)["ok"] is True and _count(conn) == 3


def test_an_empty_trail_takes_whatever_key_it_is_given(ws, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    conn = db()
    _write(conn, 1)
    assert audit.verify_chain(conn)["ok"] is True


def test_the_hub_says_so_at_start_not_at_the_first_sign_in(ws, monkeypatch, caplog):
    conn = db()
    _write(conn, 1)
    trail_fp = audit.key_fingerprint()
    assert audit.startup_key_check() == "ok"
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    with caplog.at_level(logging.ERROR, logger="nerva.workspace.audit"):
        assert audit.startup_key_check() == "mismatch"
    assert "audit_key_mismatch" in caplog.text and trail_fp in caplog.text
    assert audit.key_fingerprint(OTHER_KEY.encode()) in caplog.text and "check" in caplog.text
    monkeypatch.delenv("JARVIS_AUDIT_KEY")
    (ws.key_dir / audit.KEY_FILE).unlink()
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="nerva.workspace.audit"):
        assert audit.startup_key_check() == "missing"
    assert "audit_key_missing" in caplog.text
    assert not (ws.key_dir / audit.KEY_FILE).exists(), "the check never mints a key"
    assert _count(conn) == 1


def test_the_start_check_creates_nothing(ws, monkeypatch):
    business = ws.data_dir / config.DATA_DIRNAME
    assert audit.startup_key_check() is None and not business.exists()
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    assert audit.startup_key_check() is None
    assert not (ws.key_dir / audit.KEY_FILE).exists()


def test_the_hub_lifespan_runs_the_start_check():
    """web.py wiring: the check runs in the lifespan, before the scheduler, guarded."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "agents" / "web.py").read_text("utf-8")
    check = source.index("workspace_audit.startup_key_check()")
    assert check < source.index("workspace_scheduler.start_background()")
    assert "except Exception" in source[check:check + 200]


# ── an explicit, audited re-key for a key that is truly lost ─────────────────────────

def test_a_rekey_adopts_the_new_key_and_verification_crosses_it(ws, monkeypatch):
    conn = db()
    _write(conn, 3)
    (ws.key_dir / audit.KEY_FILE).unlink()                 # the key is lost for good
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)      # a new one, generated per §4
    plan = audit.rekey_plan(conn)
    assert plan["state"] == "mismatch" and plan["rows"] == 3 and plan["unverified"] == 3
    assert plan["broken_at"] is None and plan["to_key_fp"] == audit.key_fingerprint(OTHER_KEY.encode())
    row_id = audit.rekey(conn, actor_email="cli")
    row = conn.execute("SELECT * FROM audit WHERE id = ?", (row_id,)).fetchone()
    details = json.loads(row["details_json"])
    assert row["action"] == "audit.rekeyed" and row["actor_email"] == "cli"
    assert details["from_key_fp"] == plan["from_key_fp"] and details["to_key_fp"] == plan["to_key_fp"]
    assert (details["through_id"], details["rows"], details["unverified"]) == (3, 3, 3)
    _write(conn, 2)                                        # the hub writes again
    assert audit.verify_chain(conn) == {
        "ok": True, "checked": 3, "broken_at": None, "keyed": True, "key_mismatch": False,
        "unverified": 3, "rekeyed_at": row_id}
    assert audit.key_check(conn) == "ok"


@pytest.mark.parametrize("tamper", [
    "UPDATE audit SET details_json = '{\"n\":99}' WHERE id = 2",
    "UPDATE audit SET actor_email = 'someone' WHERE id = 1",
    "UPDATE audit SET key_fp = 'x' WHERE id = 3",
    "DELETE FROM audit WHERE id = 2",
])
def test_rows_before_a_rekey_stay_pinned_by_it(ws, monkeypatch, tamper):
    """Nobody can re-check the lost key's rows, but nobody can edit them afterwards either."""
    conn = db()
    _write(conn, 3)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    row_id = audit.rekey(conn, actor_email="cli")
    _write(conn, 1)
    conn.execute(tamper)
    result = audit.verify_chain(conn)
    assert result["ok"] is False and result["broken_at"] in (1, 2, 3, row_id), result


def test_a_forged_or_edited_rekey_row_is_caught(ws, monkeypatch):
    conn = db()
    _write(conn, 2)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    row_id = audit.rekey(conn, actor_email="cli")
    conn.execute("UPDATE audit SET details_json = replace(details_json, '\"unverified\":2', "
                 "'\"unverified\":0') WHERE id = ?", (row_id,))
    result = audit.verify_chain(conn)
    assert result["ok"] is False and result["broken_at"] == row_id
    # A row someone inserts by hand cannot carry a valid HMAC either.
    conn2 = db()
    conn2.execute("DELETE FROM audit WHERE id = ?", (row_id,))
    assert audit.verify_chain(conn2)["key_mismatch"] is True


def test_rekey_refuses_a_trail_that_is_broken_for_another_reason(ws, monkeypatch):
    conn = db()
    _write(conn, 3)
    conn.execute("DELETE FROM audit WHERE id = 2")         # a real gap, not a key change
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    assert audit.rekey_plan(conn)["broken_at"] == 3
    with pytest.raises(audit.RekeyRefused):
        audit.rekey(conn, actor_email="cli")
    assert _count(conn) == 2


def test_rekey_refuses_a_row_of_the_new_key_that_fails_its_hmac(ws, monkeypatch):
    """Rows the new key signed can still be checked, so an edited one is not "retired"."""
    conn = db()
    _write(conn, 3)
    original = (ws.key_dir / audit.KEY_FILE).read_bytes().decode()
    conn.execute("UPDATE audit SET details_json = '{\"n\":7}' WHERE id = 2")   # an edit
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    assert audit.rekey_plan(conn)["broken_at"] is None, "under another key the edit is unseen"
    monkeypatch.setenv("JARVIS_AUDIT_KEY", original)
    conn.execute("UPDATE audit SET key_fp = 'x' WHERE id = 3")   # the newest row now "mismatches"
    plan = audit.rekey_plan(conn)
    assert plan["state"] == "mismatch" and plan["broken_at"] == 2
    with pytest.raises(audit.RekeyRefused):
        audit.rekey(conn, actor_email="cli")


def test_the_right_key_back_after_a_rekey_to_a_wrong_one_is_recoverable(ws, monkeypatch):
    """The newest re-key wins: rows of the key in use are checked again, the rest are counted."""
    conn = db()
    _write(conn, 3)
    original = (ws.key_dir / audit.KEY_FILE).read_bytes().decode()
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    audit.rekey(conn, actor_email="cli")                   # row 4, under the other key
    _write(conn, 2)                                        # rows 5-6
    monkeypatch.setenv("JARVIS_AUDIT_KEY", original)       # the old key turns up again
    with pytest.raises(audit.AuditKeyMismatch):
        _write(conn, 1)
    row_id = audit.rekey(conn, actor_email="cli")          # row 7, back under the original
    _write(conn, 1)
    result = audit.verify_chain(conn)
    assert result == {"ok": True, "checked": 3 + 1 + 1, "broken_at": None, "keyed": True,
                      "key_mismatch": False, "unverified": 3, "rekeyed_at": row_id}


def test_rekey_with_the_trails_own_key_is_a_no_op(ws):
    conn = db()
    _write(conn, 1)
    assert audit.rekey_plan(conn)["state"] == "ok"
    with pytest.raises(audit.RekeyRefused, match="already"):
        audit.rekey(conn, actor_email="cli")
    assert _count(conn) == 1


# ── the operator commands ────────────────────────────────────────────────────────────

def test_check_reports_a_ready_install_and_changes_nothing(ws, capsys):
    conn = db()
    seed_company(conn)
    _write(conn, 1)
    database = ws.data_dir / config.DATA_DIRNAME / "workspace.db"
    before = (database.stat().st_mtime_ns, _count(conn))
    assert cli.main(["check"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert f"data root: {ws.data_dir}" in out
    assert f"schema {workspace_db.schema_version()}" in out
    assert "audit key: ok" in out and audit.key_fingerprint() in out
    assert (database.stat().st_mtime_ns, _count(conn)) == before


def test_check_on_a_stopped_service_leaves_no_file_behind(ws, capsys):
    """Run as another user (root), a -wal/-shm it created would be unwritable for the service."""
    conn = db()
    _write(conn, 1)
    conn.close()                                           # the service stopped: WAL checkpointed
    business = ws.data_dir / config.DATA_DIRNAME
    before = sorted(path.name for path in business.iterdir())
    assert "workspace.db-wal" not in before
    assert cli.main(["check"]) == cli.EXIT_OK
    assert "audit key: ok" in capsys.readouterr().out
    assert sorted(path.name for path in business.iterdir()) == before


def test_check_names_a_mismatched_key_without_writing(ws, monkeypatch, capsys):
    conn = db()
    _write(conn, 2)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    assert cli.main(["check"]) == cli.EXIT_FAILED
    out = capsys.readouterr().out
    assert "audit key: mismatch" in out
    assert audit.key_fingerprint(OTHER_KEY.encode()) in out
    assert conn.execute("SELECT key_fp FROM audit ORDER BY id DESC").fetchone()[0] in out
    assert _count(conn) == 2


def test_check_names_a_missing_key_and_never_mints_one(ws, capsys):
    conn = db()
    _write(conn, 1)
    key_file = ws.key_dir / audit.KEY_FILE
    key_file.unlink()
    assert cli.main(["check"]) == cli.EXIT_FAILED
    assert "audit key: missing" in capsys.readouterr().out
    assert not key_file.exists()


def test_check_on_a_fresh_install_creates_nothing(ws, capsys):
    database = ws.data_dir / config.DATA_DIRNAME / "workspace.db"
    assert cli.main(["check"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "database: not created yet" in out and "audit key: ok" in out
    assert not database.exists() and not (ws.key_dir / audit.KEY_FILE).exists()


def test_check_reports_an_empty_key_file_before_the_first_row(ws, capsys):
    (ws.key_dir / audit.KEY_FILE).write_bytes(b"\n")      # the hub's first write would fail
    assert cli.main(["check"]) == cli.EXIT_FAILED
    assert "audit key: unreadable" in capsys.readouterr().out


def test_check_reports_a_disabled_workspace(ws, monkeypatch, capsys):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    assert cli.main(["check"]) == cli.EXIT_FAILED
    assert "workspace: off" in capsys.readouterr().out


def test_audit_rekey_asks_for_confirmation_then_writes_one_cli_row(ws, monkeypatch, capsys):
    conn = db()
    _write(conn, 2)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    assert cli.main(["audit-rekey"]) == cli.EXIT_REFUSED
    captured = capsys.readouterr()
    assert "--confirm" in captured.err and "2" in captured.out and _count(conn) == 2
    assert cli.main(["audit-rekey", "--confirm"]) == cli.EXIT_OK
    capsys.readouterr()
    row = conn.execute("SELECT action, actor_email FROM audit ORDER BY id DESC").fetchone()
    assert tuple(row) == ("audit.rekeyed", "cli")
    assert cli.main(["check"]) == cli.EXIT_OK
    assert cli.main(["audit-rekey", "--confirm"]) == cli.EXIT_OK, "nothing to do is not an error"
    assert "nothing to do" in capsys.readouterr().out and _count(conn) == 3


def test_audit_rekey_never_mints_a_key(ws, capsys):
    conn = db()
    _write(conn, 1)
    key_file = ws.key_dir / audit.KEY_FILE
    key_file.unlink()
    assert cli.main(["audit-rekey", "--confirm"]) == cli.EXIT_REFUSED
    assert "no audit key" in capsys.readouterr().err
    assert not key_file.exists() and _count(conn) == 1


def test_other_commands_still_refuse_a_mismatched_key(ws, monkeypatch, capsys):
    conn = db()
    company = seed_company(conn)
    _write(conn, 1)
    monkeypatch.setenv("JARVIS_AUDIT_KEY", OTHER_KEY)
    assert cli.main(["promote", "--email", company.member_a.email]) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "differs" in err and "audit-rekey" in err


def test_the_module_runs_check_as_a_script(ws, tmp_path):
    """``python -m agents.core.workspace check`` is what PILOT_GUIDE §14 tells operators to run."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("NERVA_")
           and key not in ("JARVIS_USER_HOME", "JARVIS_PROFILE", "JARVIS_AUDIT_KEY")}
    env.update({"NERVA_WORKSPACE": "1", "JARVIS_HOME": str(ws.data_dir),
                "JARVIS_KEY_DIR": str(ws.key_dir), "PYTHON_DOTENV_DISABLED": "1"})
    result = subprocess.run([sys.executable, "-m", "agents.core.workspace", "check"], cwd=repo,
                            env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "audit key: ok" in result.stdout
