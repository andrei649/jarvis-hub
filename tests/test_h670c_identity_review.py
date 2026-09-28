"""H670, the second review (review-H670b) — its findings, pinned.

- m-1: scoping the contract to "replies to the owner" also lifted the honesty rules
  from drafted text; now only the reply rules are scoped, and honesty holds for
  everything an agent writes.
- m-2: a shipped contract that stopped being UTF-8 emptied the contract at a boundary;
  any read failure now keeps the contract in force.
- m-3: the vanish-between-stat-and-read case and the start-time version record are
  pinned through the real code, not a stand-in or the source text.
- nits: a kept contract is reported as failed-open and warned once per episode (2); an
  unreadable override's fallback follows an edit of the shipped file (3); a permission
  error while locating the contract never stops an agent, and any unreadable override
  falls back to the shipped contract (4); the house fallback rules appear once when
  both bands are blocked (5); docs (6); CHT-117 drafts with Veronica (7).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

from agents.core import agent as agent_mod

REPO = Path(__file__).resolve().parent.parent
SHIPPED = REPO / "agents" / "_identity" / "IDENTITY.md"


@pytest.fixture(autouse=True)
def _fresh():
    agent_mod._IDENTITY_CACHE.clear()
    agent_mod._IDENTITY_KEEP_WARNED.clear()
    yield
    agent_mod._IDENTITY_CACHE.clear()
    agent_mod._IDENTITY_KEEP_WARNED.clear()


def _contract() -> str:
    return agent_mod._strip_maintainer_note(SHIPPED.read_text(encoding="utf-8")).strip()


def _old(path: Path, age: float = 60) -> None:
    then = time.time() - age
    os.utime(path, (then, then))


@pytest.fixture
def app(tmp_path, monkeypatch):
    from agents.core import paths

    root = tmp_path / "app"
    (root / "agents" / "_identity").mkdir(parents=True)
    shipped = root / "agents" / "_identity" / "IDENTITY.md"
    shipped.write_text("# Contract\n- shipped rule\n", encoding="utf-8")
    _old(shipped)
    monkeypatch.setattr(paths, "app_root", lambda: root)
    monkeypatch.setattr(paths, "user_souls_dir", lambda: None)
    return root


def _agent():
    return agent_mod.Agent("no-such-agent-h670c", {"name": "X"})


# ── m-1: honesty is not scoped ───────────────────────────────────────────────────

def test_only_the_reply_rules_are_scoped_and_honesty_holds_for_everything():
    text = _contract().lower()
    assert "the honesty rules hold for everything you write, drafted text included" in text
    replies, honesty = text.split("## honesty", 1)
    assert "## replies" in replies and "no filler" in replies
    assert "agree because it is right" in honesty and "never present a guess as a fact" in honesty
    assert "no filler" not in honesty


def test_the_mirror_follows():
    mirror = agent_mod._strip_maintainer_note((REPO / "SOUL.md").read_text(encoding="utf-8")).strip()
    assert mirror == _contract()


# ── m-2: a shipped contract that is not UTF-8 ────────────────────────────────────

def test_a_shipped_contract_that_stops_being_utf8_is_kept(app, caplog):
    agent = _agent()
    shipped = app / "agents" / "_identity" / "IDENTITY.md"
    shipped.write_bytes("# Contract\n- regulă\n".encode("cp1250"))
    _old(shipped, 30)
    with caplog.at_level(logging.WARNING, logger="jarvis.agent"):
        out = agent.refresh_soul()
    assert agent.system_prompt() == "# Contract\n- shipped rule"
    assert out.reason == "failed-open" and not out.changed
    assert "keeping the last-good" in caplog.text


# ── m-3: the real paths ──────────────────────────────────────────────────────────

def test_a_contract_that_vanishes_before_the_real_read_is_kept(app, monkeypatch):
    agent = _agent()
    shipped = app / "agents" / "_identity" / "IDENTITY.md"
    shipped.write_text("# Contract\n- edited rule\n", encoding="utf-8")
    _old(shipped, 30)
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == "IDENTITY.md":
            raise FileNotFoundError(str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert agent._refresh_identity() is False and agent._identity_kept is True
    assert agent.system_prompt() == "# Contract\n- shipped rule"


def test_starting_the_hub_records_the_contract_in_force():
    from fastapi.testclient import TestClient

    from agents import web

    with TestClient(web.app):
        store = web.orch.soul_versions
        assert (store.current(agent_mod.IDENTITY_KEY) or {}).get("content") == _contract()


# ── nits ─────────────────────────────────────────────────────────────────────────

def test_a_kept_contract_is_warned_once_per_episode(app, caplog):
    agents = [_agent() for _ in range(3)]
    (app / "agents" / "_identity" / "IDENTITY.md").unlink()
    with caplog.at_level(logging.WARNING, logger="jarvis.agent"):
        for _ in range(2):
            for agent in agents:
                assert agent.refresh_soul().reason == "failed-open"
    kept = [r for r in caplog.records if "keeping the last-good" in r.getMessage()]
    assert len(kept) == 1


def test_an_unreadable_overrides_fallback_follows_an_edit_of_the_shipped_file(app):
    local = app / "agents" / "_identity" / "IDENTITY.local.md"
    local.write_bytes(b"\xff\xfe bad")
    _old(local)
    assert _agent().system_prompt() == "# Contract\n- shipped rule"
    shipped = app / "agents" / "_identity" / "IDENTITY.md"
    shipped.write_text("# Contract\n- edited shipped rule\n", encoding="utf-8")
    _old(shipped, 30)
    assert _agent().system_prompt() == "# Contract\n- edited shipped rule"


def test_an_override_that_is_a_directory_falls_back_to_the_shipped_contract(app):
    (app / "agents" / "_identity" / "IDENTITY.local.md").mkdir()
    got = agent_mod.read_identity()
    assert got["content"] == "# Contract\n- shipped rule" and got["error"]


def test_a_permission_error_while_locating_never_stops_an_agent(app, monkeypatch, caplog):
    real = agent_mod._soul_signature

    def denied(path):
        if "IDENTITY" in str(path):
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(agent_mod, "_soul_signature", denied)
    with caplog.at_level(logging.ERROR, logger="jarvis.agent"):
        agent = _agent()
    assert agent.identity["content"] == "" and "could not be read" in caplog.text


def test_a_permission_error_at_a_boundary_keeps_the_contract(app, monkeypatch):
    agent = _agent()

    def denied():
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(agent_mod, "identity_path", denied)
    assert agent._refresh_identity() is False and agent._identity_kept is True
    assert agent.system_prompt() == "# Contract\n- shipped rule"


def test_the_fallback_rules_appear_once_when_both_bands_are_blocked(app):
    agent = _agent()
    stub = agent_mod._blocked_soul_body("IDENTITY.local.md", "shared contract")
    agent.identity = {"content": stub, "blocked": True}
    agent.soul = {"content": agent_mod._blocked_soul_body("SOUL.md")}
    prompt = agent.system_prompt()
    assert prompt.count(agent_mod._SOUL_FALLBACK_RULES) == 1
    assert "without its shared contract" in prompt and "without its persona" in prompt


def test_the_docs_describe_the_contract_as_it_is():
    arch = (REPO / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "own 4,000-character cap" in arch
    manual = (REPO / "docs/test-manual/02-chat-routing-agents.md").read_text(encoding="utf-8")
    row = next(line for line in manual.splitlines() if line.startswith("| CHT-117 |"))
    assert "ask Veronica to draft" in row and "Howard" not in row


def test_a_reader_that_raises_is_reported_failed_open(app, monkeypatch):
    agent = _agent()
    shipped = app / "agents" / "_identity" / "IDENTITY.md"
    shipped.write_text("# Contract\n- edited rule\n", encoding="utf-8")
    _old(shipped, 30)

    def boom(path=None):
        raise RuntimeError("parser crash")

    monkeypatch.setattr(agent_mod, "read_identity", boom)
    assert agent.refresh_soul().reason == "failed-open"
    assert agent.system_prompt() == "# Contract\n- shipped rule"


def test_a_second_episode_is_warned_again(app, caplog):
    agent = _agent()
    shipped = app / "agents" / "_identity" / "IDENTITY.md"
    with caplog.at_level(logging.WARNING, logger="jarvis.agent"):
        shipped.unlink()
        agent.refresh_soul()
        shipped.write_text("# Contract\n- back\n", encoding="utf-8")
        _old(shipped, 30)
        agent.refresh_soul()
        assert agent.system_prompt() == "# Contract\n- back"
        shipped.unlink()
        agent.refresh_soul()
    assert len([r for r in caplog.records if "keeping the last-good" in r.getMessage()]) == 2
