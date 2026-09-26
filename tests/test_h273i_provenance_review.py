"""H273, the eighth review (review-H273i) — its findings, pinned.

- m1: the packaged recovery named one .env only, not the environment the app starts
  from (where PHONE_ACCESS puts the phone's token) nor a moved data home, and a LAN bind
  with no token left could not start. The documents name both places, unset the bind
  for the restart and name JARVIS_MEMORY_DIR (n3).
- m2: a valid user token calling an admin verb was called refused, and the hint's first
  command revoked the owner's working admin token. The hint reads the hub's reason for
  the tier it wanted, and recovery is the additive ``issue``.
- m3: the child's environment kept only the run-log key under test (M06); the hint's
  verb was unpinned (M12).
- nits: the status lines read the hub's reason (n4); ENV-163 and SEC-055 run the
  recovery script (n2); the supervisor's docstring names the named-pipe limit (n1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_h273g_provenance_review import _refused_hint

REPO = Path(__file__).resolve().parent.parent


def _client(url="http://127.0.0.1:8080", **env):
    from agents.cli.client import HubClient

    return HubClient.from_env({"NERVA_HUB_URL": url, **env})


# ── m2: the hint follows the tier the hub wanted ─────────────────────────────────

def test_a_valid_user_token_on_an_admin_verb_is_asked_for_the_admin_token():
    from agents.cli import nerva

    said = nerva._auth_hint(_client(JARVIS_USER_TOKEN="usr"), "admin token required")
    assert "needs JARVIS_ADMIN_TOKEN" in said and "JARVIS_USER_TOKEN is not enough" in said
    assert "refused" not in said and "rotate" not in said and "issue admin" in said


def test_a_refused_admin_token_is_renewed_with_issue_never_rotate_first():
    from agents.cli import nerva

    said = nerva._auth_hint(_client(JARVIS_ADMIN_TOKEN="adm"), "admin token required")
    assert said.startswith("The hub refused JARVIS_ADMIN_TOKEN:")
    assert "token_recover.py issue admin" in said and "rotate admin only if it leaked" in said


@pytest.mark.parametrize("env,start", [
    ({"JARVIS_USER_TOKEN": "u"}, "The hub refused JARVIS_USER_TOKEN:"),
    ({}, "Set JARVIS_USER_TOKEN"),
])
def test_a_user_tier_refusal(env, start):
    from agents.cli import nerva

    said = nerva._auth_hint(_client(**env), "user token required")
    assert said.startswith(start) and "issue user" in said and "rotate" not in said


@pytest.mark.parametrize("reason,name", [
    ("admin disabled from network — set JARVIS_ADMIN_TOKEN to enable remote access", "JARVIS_ADMIN_TOKEN"),
    ("user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access", "JARVIS_USER_TOKEN"),
])
def test_a_hub_with_no_token_of_the_tier_is_named_as_such(reason, name):
    from agents.cli import nerva

    said = nerva._auth_hint(_client("http://192.0.2.2:8080", JARVIS_USER_TOKEN="u"), reason)
    assert f"The hub has no {name} configured" in said and "refused JARVIS_USER_TOKEN" not in said


def test_the_verb_passes_the_hubs_reason_to_the_hint(monkeypatch):
    said = _refused_hint(monkeypatch, {"NERVA_HUB_URL": "http://127.0.0.1:8080",
                                       "JARVIS_USER_TOKEN": "usr"})
    assert "refused JARVIS_USER_TOKEN" in said                      # "refused": no tier named

    from agents.cli import nerva
    from agents.cli.client import HubError

    def admin_only(ns, ctx):
        raise HubError(401, "admin token required")

    monkeypatch.setitem(nerva._VERBS, "tools", admin_only)
    from tests.test_h273g_provenance_review import _Err

    err = _Err()
    ctx = nerva.Context(environ={"NERVA_HUB_URL": "http://127.0.0.1:8080", "JARVIS_USER_TOKEN": "usr"}, err=err)
    assert nerva.main(["tools"], context=ctx) == nerva.EXIT_AUTH
    text = "".join(err.chunks)
    assert "needs JARVIS_ADMIN_TOKEN" in text and "refused JARVIS_USER_TOKEN" not in text


# ── n4: the status lines read the hub's reason ───────────────────────────────────

def test_status_names_a_hub_with_no_user_token():
    import io

    from agents.cli import nerva
    from agents.cli.client import HubError

    class Lan:
        base_url = "http://192.0.2.2:8080"
        admin_token = ""
        user_token = "usr"

        def _sends_admin_token(self):
            return False

        def get(self, path, *args, **kwargs):
            if path == "/status":
                return {"version": "1", "agents": []}
            raise HubError(403, "user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access")

        post = get

    out = io.StringIO()
    assert nerva.main(["status"], context=nerva.Context(environ={}, out=out, client_factory=lambda env: Lan())) == 0
    lines = [line for line in out.getvalue().splitlines() if "runnable:" in line or "e-stop:" in line]
    assert len(lines) == 2
    assert all("the hub has no JARVIS_USER_TOKEN configured" in line and "expired" not in line for line in lines)


# ── m3 (M06): the child keeps its parent's environment ───────────────────────────

def test_the_child_keeps_every_other_variable(monkeypatch, tmp_path):
    from scripts import runtime_supervisor

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(tmp_path / "run.jsonl"))
    child = runtime_supervisor._child_env()
    assert child["JARVIS_HOME"] == str(tmp_path) and child.get("PATH") == __import__("os").environ.get("PATH")


# ── m1, n2, n3, n1: the documents ────────────────────────────────────────────────

def test_the_packaged_recovery_names_both_places_and_the_bind():
    packaging = (REPO / "docs/PACKAGING.md").read_text(encoding="utf-8")
    section = packaging[packaging.index("## Recovering a lost admin token"):packaging.index("## Relocating data")]
    for needed in ("the environment the app", "<JARVIS_USER_HOME>/.env", "unset `JARVIS_HOST`",
                   "$JARVIS_MEMORY_DIR/security/tokens.db", "$JARVIS_HOME/security/tokens.db"):
        assert needed in section, needed
    phone = (REPO / "docs/PHONE_ACCESS.md").read_text(encoding="utf-8")
    assert "the environment the app" in phone and "unset `JARVIS_HOST`" in phone


def test_the_manual_never_runs_the_bare_store_cli_for_recovery():
    env = (REPO / "docs/test-manual/01-environment-and-boot.md").read_text(encoding="utf-8")
    sec = (REPO / "docs/test-manual/08-security-privacy.md").read_text(encoding="utf-8")
    for row in ("| ENV-163 |", "| ENV-159 |"):
        line = next(line for line in env.splitlines() if line.startswith(row))
        assert "python -m agents.core.security.token_store" not in line
    sec055 = next(line for line in sec.splitlines() if line.startswith("| SEC-055 |"))
    assert "scripts/token_recover.py" in sec055


def test_the_supervisor_names_the_named_pipe_limit():
    from scripts import runtime_supervisor

    assert "named-pipe" in runtime_supervisor.__doc__
