"""H273, the seventh review (review-H273h) — its findings, pinned.

- m1: with a named-pipe .env the supervisor handed its default run-log path down, so the
  coordinator wrote there while the hub's brief read the path the pipe names, and the
  brief showed no runtime. Only a path the supervisor found (the process, or a regular
  .env) is handed down; with a pipe the child reads it, as the hub does.
- m2: the packaged recovery (delete ``tokens.db``) revived every env token that had been
  rotated away or revoked. The documents remove those lines first (docs only; pinned
  here by their text).
- m3: a token that was set, sent and refused was asked for again. It is named as
  refused, on the verbs and on ``nerva status``'s lines.
- m4: the survivors: ``scripts/token_recover.py`` run as documented, and the two spawn
  sites in the supervisor's ``main()``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── m1: with a named pipe the child reads the path, as the hub does ──────────────

def _feed(fifo: Path, text: str) -> threading.Thread:
    def write():
        with open(fifo, "w", encoding="utf-8") as fh:
            fh.write(text)

    thread = threading.Thread(target=write, daemon=True)
    thread.start()
    return thread


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes")
def test_a_named_pipe_run_log_reaches_the_child_and_the_hub_alike(tmp_path, monkeypatch):
    from agents.core import env_provenance as ep
    from agents.core.observability import runtime_log
    from scripts import runtime_supervisor

    repo_env = tmp_path / "repo.env"
    os.mkfifo(repo_env)
    named = str(tmp_path / "fifo.jsonl")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    for key in ("JARVIS_RUNTIME_LOG", "JARVIS_USER_HOME"):
        monkeypatch.setenv(key, "")                       # so the teardown unsets a loaded key
        monkeypatch.delenv(key)
    child = runtime_supervisor._child_env()
    assert "JARVIS_RUNTIME_LOG" not in child              # nothing the child could not read itself

    seen = []
    for _process in ("coordinator", "hub"):               # each loads the pipe once
        monkeypatch.setattr(ep, "_HUB_LOADED", None)
        monkeypatch.setenv("JARVIS_RUNTIME_LOG", "")
        monkeypatch.delenv("JARVIS_RUNTIME_LOG")
        feeder = _feed(repo_env, f"JARVIS_RUNTIME_LOG={named}\n")
        ep.load_hub_env()
        feeder.join(timeout=10)
        seen.append(str(runtime_log.default_log_path()))
    assert seen == [named, named]


def test_a_path_in_the_process_is_handed_down_as_it_is(monkeypatch, tmp_path):
    from scripts import runtime_supervisor

    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(tmp_path / "proc.jsonl"))
    assert runtime_supervisor._child_env()["JARVIS_RUNTIME_LOG"] == str(tmp_path / "proc.jsonl")


def test_an_app_that_cannot_import_hands_nothing_down(monkeypatch):
    from scripts import runtime_supervisor

    monkeypatch.setenv("JARVIS_RUNTIME_LOG", "")
    monkeypatch.delenv("JARVIS_RUNTIME_LOG")
    monkeypatch.setitem(sys.modules, "agents.core.env_provenance", None)   # import fails
    assert "JARVIS_RUNTIME_LOG" not in runtime_supervisor._child_env()


# ── m2: the packaged recovery removes the env tokens first ───────────────────────

@pytest.mark.parametrize("doc", ["docs/PACKAGING.md", "docs/PHONE_ACCESS.md"])
def test_the_packaged_recovery_removes_the_env_tokens_before_the_file(doc):
    text = (REPO / doc).read_text(encoding="utf-8")
    first = text.index("JARVIS_USER_TOKEN", text.index("ships"))
    assert "**first**" in text.lower()
    assert first < text.index("tokens.db", first)
    assert "work again" in text or "works again" in text


def test_the_packaged_recovery_names_the_jarvis_home_path():
    text = (REPO / "docs/PACKAGING.md").read_text(encoding="utf-8")
    assert "$JARVIS_HOME/security/tokens.db" in text


# ── m3: a token that is set is never asked for again ─────────────────────────────

def _client(**env):
    from agents.cli.client import HubClient

    return HubClient.from_env({"NERVA_HUB_URL": "http://127.0.0.1:8080", **env})


@pytest.mark.parametrize("env,named", [
    ({"JARVIS_ADMIN_TOKEN": "stale"}, "JARVIS_ADMIN_TOKEN"),
    ({"JARVIS_USER_TOKEN": "stale"}, "JARVIS_USER_TOKEN"),
    ({"JARVIS_ADMIN_TOKEN": "a", "JARVIS_USER_TOKEN": "u"}, "JARVIS_ADMIN_TOKEN and JARVIS_USER_TOKEN"),
])
def test_a_refused_token_that_is_set_is_named_as_refused(env, named):
    from agents.cli import nerva

    said = nerva._auth_hint(_client(**env))
    assert f"The hub refused {named}:" in said and "Set JARVIS_" not in said
    assert "token_recover.py" in said


def test_with_no_token_set_the_hint_asks_for_one():
    from agents.cli import nerva

    said = nerva._auth_hint(_client())
    assert said.startswith("Set JARVIS_ADMIN_TOKEN") and "token_recover.py issue admin" in said


def test_status_reads_a_set_token_as_refused():
    from agents.cli import nerva

    for client in (_client(JARVIS_ADMIN_TOKEN="a"), _client(JARVIS_USER_TOKEN="u")):
        line = nerva._runnable_line({"reason": "needs_token"}, client)
        assert line.startswith("(refused:") and "needs" not in line
    assert nerva._read_hint(_client()) == "(needs JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN to read)"


def test_status_over_lan_with_both_set_asks_for_neither():
    from agents.cli import nerva
    from agents.cli.client import HubClient

    both = HubClient.from_env({"NERVA_HUB_URL": "http://192.0.2.2:8080",
                               "JARVIS_ADMIN_TOKEN": "a", "JARVIS_USER_TOKEN": "u"})
    line = nerva._read_hint(both)
    assert "JARVIS_ADMIN_TOKEN is withheld" in line and "needs" not in line
    only_admin = HubClient.from_env({"NERVA_HUB_URL": "http://192.0.2.2:8080", "JARVIS_ADMIN_TOKEN": "a"})
    assert nerva._read_hint(only_admin).startswith("(needs JARVIS_USER_TOKEN to read here")


# ── m4 (H15): run as documented, the recovery imports the app ───────────────────

def test_token_recover_run_as_a_script_writes_the_store_it_names(tmp_path):
    data = tmp_path / "data"
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "JARVIS_MEMORY_DIR", "JARVIS_ADMIN_TOKEN", "JARVIS_USER_TOKEN")}
    env.update({"JARVIS_HOME": str(data), "JARVIS_USER_HOME": str(tmp_path / "home"),
                "HOME": str(tmp_path)})
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "token_recover.py"), "list"],  # noqa: S603
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert str(data / "security" / "tokens.db") in out.stderr


# ── m4 (H19, H20): every spawn in main() carries the child's environment ─────────

def test_the_first_spawn_and_the_respawn_both_carry_the_run_log(tmp_path, monkeypatch):
    from agents.core import env_provenance as ep
    from scripts import runtime_supervisor as rs

    repo_env = tmp_path / "repo.env"
    run_log = tmp_path / "from-env.jsonl"
    repo_env.write_text(f"JARVIS_RUNTIME_LOG={run_log}\n", encoding="utf-8")
    monkeypatch.setattr(ep, "REPO_ENV_FILE", repo_env)
    monkeypatch.delenv("JARVIS_RUNTIME_LOG", raising=False)
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)
    handlers, spawned = {}, []

    class Child:
        def __init__(self, argv, env=None):
            spawned.append(env)
            self.pid = 1000 + len(spawned)

        def wait(self):
            if len(spawned) == 1:
                return 1                                  # the first child dies
            handlers[rs.signal.SIGTERM](rs.signal.SIGTERM, None)   # stop during the second
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(rs.subprocess, "Popen", Child)
    monkeypatch.setattr(rs.signal, "signal", lambda sig, fn: handlers.__setitem__(sig, fn))
    monkeypatch.setattr(rs.time, "sleep", lambda seconds: None)
    assert rs.main() == 0
    assert len(spawned) == 2
    assert all(env and env.get("JARVIS_RUNTIME_LOG") == str(run_log) for env in spawned)
    lines = run_log.read_text(encoding="utf-8")
    assert '"spawned"' in lines and '"respawned"' in lines and '"stopped"' in lines
