"""Operator CLI: setup-code, reset-link, promote — refused while disabled, audited as 'cli'."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth
from agents.core.workspace import auth, cli, config
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    SETUP_CODE,
    db,
    login,
    make_app,
    make_user,
    seed_company,
    ws,
)

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """The suite's environment is the configuration; never read a developer's .env."""
    monkeypatch.setattr(cli, "load_hub_env", lambda: {})


def _audit(conn):
    return [(row["action"], row["actor_email"], json.loads(row["details_json"]))
            for row in conn.execute("SELECT * FROM audit ORDER BY id")]


def test_refuses_while_disabled(ws, monkeypatch, capsys):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    assert cli.main(["setup-code"]) == cli.EXIT_REFUSED
    assert "disabled" in capsys.readouterr().err


def test_loads_the_hub_env_before_checking_the_flag(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")

    def hub_env():
        monkeypatch.setenv("NERVA_WORKSPACE", "1")
        return {}

    monkeypatch.setattr(cli, "load_hub_env", hub_env)
    assert cli.main(["setup-code"]) == cli.EXIT_OK


def test_setup_code_prints_the_env_code(ws, capsys):
    assert cli.main(["setup-code"]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == SETUP_CODE


def test_setup_code_prints_the_generated_file(ws, monkeypatch, capsys):
    monkeypatch.delenv("NERVA_WORKSPACE_SETUP_CODE")
    assert cli.main(["setup-code"]) == cli.EXIT_OK
    printed = capsys.readouterr().out.strip()
    assert printed == config.setup_code_path().read_bytes().decode("utf-8")


def test_setup_code_after_setup_is_an_error(ws, capsys):
    seed_company(db())
    assert cli.main(["setup-code"]) == cli.EXIT_FAILED
    assert "already set up" in capsys.readouterr().err


def test_reset_link_for_an_active_user(ws, capsys):
    conn = db()
    company = seed_company(conn)
    phone = TestClient(make_app(workspace_auth.router))
    login(phone, company.member_a.email)
    code = cli.main(["reset-link", "--email", company.member_a.email.upper(),
                     "--base-url", "https://nerva.example.com/"])
    assert code == cli.EXIT_OK
    out = capsys.readouterr()
    url = out.out.strip()
    assert url.startswith("https://nerva.example.com/workspace/invite#t=")
    assert "reset link" in out.err and "single use" in out.err
    token = url.split("#t=")[1]
    lookup = TestClient(make_app(workspace_auth.router)).post("/api/workspace/invites/lookup",
                                                              json={"token": token})
    assert lookup.json()["purpose"] == "reset"
    assert _audit(conn)[-1][:2] == ("auth.reset_link_issued", "cli")
    assert phone.get("/api/workspace/me").status_code == 200, "issuing a link signs nobody out"


def test_reset_link_for_an_invited_user_is_an_invite(ws, capsys):
    conn = db()
    company = seed_company(conn)
    invited = make_user(conn, role="member", department_ids=[company.dept_a], status="invited")
    assert cli.main(["reset-link", "--email", invited.email, "--base-url", "http://10.0.0.5:8000"]) == 0
    assert capsys.readouterr().out.startswith("http://10.0.0.5:8000/workspace/invite#t=")
    action, actor, details = _audit(conn)[-1]
    assert (action, actor, details["purpose"]) == ("user.invite_issued", "cli", "invite")


@pytest.mark.parametrize(("args", "message"), [
    (["--email", "ghost@acme.test", "--base-url", "https://x.example"], "no user"),
    (["--email", "DISABLED", "--base-url", "https://x.example"], "disabled"),
    (["--email", "MEMBER", "--base-url", "ftp://x.example"], "base-url"),
    (["--email", "MEMBER", "--base-url", "https://x.example/?q=1"], "base-url"),
    (["--email", "MEMBER", "--base-url", "nerva.example.com"], "base-url"),
])
def test_reset_link_errors(ws, capsys, args, message):
    conn = db()
    company = seed_company(conn)
    disabled = make_user(conn, role="member", department_ids=[company.dept_a], status="disabled")
    args = [{"DISABLED": disabled.email, "MEMBER": company.member_a.email}.get(a, a) for a in args]
    assert cli.main(["reset-link", *args]) == cli.EXIT_FAILED
    assert message in capsys.readouterr().err
    assert conn.execute("SELECT COUNT(*) FROM invites").fetchone()[0] == 0


def test_promote_a_member(ws, capsys):
    conn = db()
    company = seed_company(conn)
    phone = TestClient(make_app(workspace_auth.router))
    login(phone, company.member_a.email)
    assert cli.main(["promote", "--email", company.member_a.email]) == cli.EXIT_OK
    assert "now an admin" in capsys.readouterr().out
    assert conn.execute("SELECT role FROM users WHERE id = ?", (company.member_a.id,)).fetchone()[0] == "admin"
    assert phone.get("/api/workspace/me").status_code == 401, "a role change revokes sessions"
    action, actor, details = _audit(conn)[-1]
    assert (action, actor) == ("user.promoted", "cli")
    assert details == {"from_role": "member", "from_status": "active", "to_status": "active"}


@pytest.mark.parametrize(("has_password", "status"), [(True, "active"), (False, "invited")])
def test_promote_restores_a_disabled_account(ws, capsys, has_password, status):
    conn = db()
    company = seed_company(conn)
    user = make_user(conn, role="member", department_ids=[company.dept_a], status="disabled")
    if not has_password:
        conn.execute("UPDATE users SET password_hash = NULL WHERE id = ?", (user.id,))
    assert cli.main(["promote", "--email", user.email]) == cli.EXIT_OK
    row = conn.execute("SELECT role, status FROM users WHERE id = ?", (user.id,)).fetchone()
    assert (row["role"], row["status"]) == ("admin", status)
    assert ("reset-link" in capsys.readouterr().out) is (not has_password)


def test_promote_is_idempotent_and_needs_a_user(ws, capsys):
    conn = db()
    company = seed_company(conn)
    before = len(_audit(conn))
    assert cli.main(["promote", "--email", company.admin.email]) == cli.EXIT_OK
    assert "already" in capsys.readouterr().out
    assert len(_audit(conn)) == before
    assert cli.main(["promote", "--email", "ghost@acme.test"]) == cli.EXIT_FAILED


def test_usage_errors_exit_2(ws):
    with pytest.raises(SystemExit) as caught:
        cli.main(["reset-link", "--email", "x@acme.test"])
    assert caught.value.code == 2
    with pytest.raises(SystemExit):
        cli.main([])


def test_module_entry_point_runs(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("NERVA_") and key not in ("JARVIS_USER_HOME", "JARVIS_PROFILE")}
    env.update({"JARVIS_HOME": str(tmp_path / "data"), "JARVIS_KEY_DIR": str(tmp_path / "keys"),
                "NERVA_WORKSPACE": "0", "PYTHON_DOTENV_DISABLED": "1"})
    result = subprocess.run([sys.executable, "-m", "agents.core.workspace", "setup-code"],
                            cwd=REPO, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == cli.EXIT_REFUSED, result.stderr
    assert "NERVA_WORKSPACE" in result.stderr


def test_issued_links_are_valid_for_72_hours(ws):
    conn = db()
    company = seed_company(conn)
    assert cli.main(["reset-link", "--email", company.member_b.email,
                     "--base-url", "https://x.example"]) == 0
    row = conn.execute("SELECT expires_at - created_at, created_by FROM invites").fetchone()
    assert row[0] == pytest.approx(auth.INVITE_TTL_SECONDS) and row[1] is None


# ── review fixes OPS-01/02/03: the CLI must act on the service's data, with its key ───

@pytest.mark.parametrize("base_url", [
    "https://nerva.example.com/workspace/", "https://nerva.example.com/workspace",
    "https://nerva.example.com", "https://nerva.example.com/",
])
def test_the_address_people_open_gives_a_working_link(ws, capsys, base_url):
    conn = db()
    company = seed_company(conn)
    assert cli.main(["reset-link", "--email", company.member_a.email, "--base-url", base_url]) == 0
    url = capsys.readouterr().out.strip()
    assert url.startswith("https://nerva.example.com/workspace/invite#t="), url


def test_a_root_path_is_kept_and_the_workspace_suffix_dropped(ws, capsys):
    conn = db()
    company = seed_company(conn)
    assert cli.main(["reset-link", "--email", company.member_a.email,
                     "--base-url", "https://firma.example/nerva/workspace/"]) == 0
    assert capsys.readouterr().out.startswith("https://firma.example/nerva/workspace/invite#t=")


@pytest.mark.parametrize("base_url", ["https://x.example/workspace/invite",
                                      "https://x.example/workspace/admin/users"])
def test_a_page_below_workspace_is_refused_and_no_link_is_revoked(ws, capsys, base_url):
    conn = db()
    company = seed_company(conn)
    assert cli.main(["reset-link", "--email", company.member_a.email,
                     "--base-url", "https://x.example"]) == 0
    capsys.readouterr()
    before = conn.execute("SELECT token_hash FROM invites").fetchall()
    assert cli.main(["reset-link", "--email", company.member_a.email,
                     "--base-url", base_url]) == cli.EXIT_FAILED
    assert "not the /workspace/ page" in capsys.readouterr().err
    assert conn.execute("SELECT token_hash FROM invites").fetchall() == before


def test_disabled_message_points_at_the_service_environment(ws, monkeypatch, capsys):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    assert cli.main(["setup-code"]) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "nerva-run" in err and "set NERVA_WORKSPACE=1" not in err


@pytest.mark.parametrize("command", [["setup-code"],
                                     ["reset-link", "--email", "a@acme.test", "--base-url", "https://x.example"],
                                     ["promote", "--email", "a@acme.test"]])
def test_an_unchosen_data_root_inside_the_checkout_is_refused(ws, monkeypatch, capsys, tmp_path,
                                                              command):
    checkout = tmp_path / "checkout"
    monkeypatch.delenv("JARVIS_HOME")
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    monkeypatch.setattr(cli.paths, "data_root", lambda environ=None: checkout / "memory_logs")
    monkeypatch.setattr(cli.paths, "app_root", lambda: checkout)
    assert cli.main(command) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "JARVIS_HOME is not set" in err and "nerva-run" in err
    assert not (checkout / "memory_logs").exists(), "nothing was created"


@pytest.mark.parametrize("command", [["reset-link", "--email", "a@acme.test", "--base-url", "https://x.example"],
                                     ["promote", "--email", "a@acme.test"]])
def test_a_missing_database_is_refused_not_created(ws, capsys, command):
    database = ws.data_dir / config.DATA_DIRNAME / "workspace.db"
    assert not database.exists()
    assert cli.main(command) == cli.EXIT_REFUSED
    assert "no Nerva Workspace database" in capsys.readouterr().err
    assert not database.exists()


def test_a_cli_without_the_services_audit_key_changes_nothing(ws, capsys):
    """Reproduces OPS-02: a bare shell would have minted a key and broken the chain for good."""
    from agents.core.workspace import audit

    conn = db()
    company = seed_company(conn)
    login(TestClient(make_app(workspace_auth.router)), company.admin.email)   # one audit row
    key_file = ws.key_dir / audit.KEY_FILE
    original = key_file.read_bytes()
    key_file.unlink()                                  # the shell has another JARVIS_KEY_DIR
    rows = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    for command in (["reset-link", "--email", company.member_a.email, "--base-url", "https://x.example"],
                    ["promote", "--email", company.member_a.email]):
        assert cli.main(command) == cli.EXIT_REFUSED
        err = capsys.readouterr().err
        assert "no audit key" in err and "nothing was changed" in err and "nerva-run" in err
    assert not key_file.exists(), "no key was minted"
    assert conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == rows
    assert conn.execute("SELECT COUNT(*) FROM invites").fetchone()[0] == 0
    assert conn.execute("SELECT role FROM users WHERE id = ?",
                        (company.member_a.id,)).fetchone()[0] == "member"
    key_file.write_bytes(b"0" * 64)                    # a key, but not the trail's
    assert cli.main(["promote", "--email", company.member_a.email]) == cli.EXIT_REFUSED
    assert "differs" in capsys.readouterr().err
    key_file.write_bytes(original)
    assert cli.main(["promote", "--email", company.member_a.email]) == cli.EXIT_OK
    assert audit.verify_chain(conn)["ok"] is True
