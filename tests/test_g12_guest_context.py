"""G12 review — a guest's turn gets none of the owner's private context and writes none of
the owner's memory, through every guest door.

The doors: a guest key of the OpenAI-compatible API, a non-admin token at the HUD, a
non-owner on Telegram (or any chat channel), and the embedded widget. Each binds a
non-owner principal (and the inbound doors an inbound origin). For each:

* no live plugin data (calendar, mail, money, social) is gathered for the prompt;
* no long-term recall and no core-memory block reaches the prompt;
* the turn writes nothing into the entity index or the knowledge graph, and the learning
  ledger keeps its metrics without its words.

The owner, on the HUD or any channel, and internal turns (no principal) keep all of it.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.commands import Principal
from agents.core.orchestrator import (
    Orchestrator,
    _turn_is_guest,
    bind_turn_principal,
    reset_turn_principal,
)
from tests.test_g12_openai_compat import (  # noqa: F401 — fixtures
    _auth,
    _chat,
    _key,
    client,
    enabled,
    settings,
    store,
)

#: door -> (principal, action origin), as each door binds them
GUESTS = {
    "openai_api guest key": (Principal(channel="openai_api", sender="apikey:key_x", admin=False), "inbound"),
    "HUD user token": (Principal(channel="web", sender=None, admin=False), "generated"),
    "Telegram non-owner": (Principal(channel="telegram", sender="99", admin=False, chat="99"), "inbound"),
    "widget": (Principal(channel="widget", sender=None, admin=False), "inbound"),
}
OWNERS = {
    "HUD owner": (Principal(channel="web", admin=True), "generated"),
    "Telegram owner": (Principal(channel="telegram", sender="1", admin=True, chat="1"), "inbound"),
    "openai_api owner key": (Principal(channel="web", admin=True), "generated"),
    "internal turn": (None, "generated"),
}


class _bound:
    def __init__(self, principal, origin):
        self.principal, self.origin = principal, origin

    def __enter__(self):
        self.tokens = (bind_turn_principal(self.principal) if self.principal is not None else None,
                       bind_action_origin(self.origin))
        return self

    def __exit__(self, *exc):
        principal_token, origin_token = self.tokens
        reset_action_origin(origin_token)
        if principal_token is not None:
            reset_turn_principal(principal_token)


@pytest.mark.parametrize("door", sorted(GUESTS))
def test_every_guest_door_reads_as_a_guest(door):
    with _bound(*GUESTS[door]):
        assert _turn_is_guest() is True


@pytest.mark.parametrize("door", sorted(OWNERS))
def test_the_owner_and_internal_turns_are_not_guests(door):
    with _bound(*OWNERS[door]):
        assert _turn_is_guest() is False


def _bare(**settings):
    orch = Orchestrator.__new__(Orchestrator)
    orch._runtime_settings = dict(settings)
    return orch


@pytest.mark.parametrize("door", sorted(GUESTS))
def test_a_guest_gets_no_plugin_data_and_no_recall(door, monkeypatch):
    from agents.core import plugin_gatherer

    async def owner_data(orch, text, intent):
        return {"calendar": "OWNER-SECRET-MEETING", "email": "OWNER-SECRET-EMAIL"}

    monkeypatch.setattr(plugin_gatherer, "gather_plugin_data", owner_data)
    orch = _bare(**{"memory.recall_enabled": True})
    with _bound(*GUESTS[door]):
        assert asyncio.run(orch._gather_plugin_data("calendar and inbox?", None)) == {}
        assert asyncio.run(orch._recall_block("what do you know about me?")) == ""
    with _bound(*OWNERS["HUD owner"]):
        assert asyncio.run(orch._gather_plugin_data("calendar and inbox?", None))["calendar"] == "OWNER-SECRET-MEETING"


class _Spy:
    def __init__(self):
        self.calls = []

    def ingest_text(self, text, source=""):
        self.calls.append(text)

    def ingest(self, text, source=""):
        self.calls.append(text)

    def record(self, **kw):
        self.calls.append(kw)


def _recording_orch():
    orch = _bare()
    orch.entities, orch.kg_updater, orch.learning, orch.bench = _Spy(), _Spy(), _Spy(), _Spy()
    orch.agents = {"jarvis": SimpleNamespace(config={"model": ""})}
    return orch


@pytest.mark.parametrize("door", sorted(GUESTS))
def test_a_guest_turn_writes_nothing_into_the_owners_memory(door):
    orch = _recording_orch()
    with _bound(*GUESTS[door]):
        orch._record_interactions("Mara's sister is Ioana; my PIN is 1234", {"jarvis": "ok"}, "ok")
    assert orch.entities.calls == [] and orch.kg_updater.calls == []
    learned = orch.learning.calls[0]
    assert learned["task"] == "" and learned["response"] == ""          # metrics kept, words not
    assert "metadata" in learned and learned["success"] is True


def test_the_owner_turn_still_feeds_the_owners_memory():
    orch = _recording_orch()
    with _bound(*OWNERS["HUD owner"]):
        orch._record_interactions("Mara's sister is Ioana", {"jarvis": "ok"}, "ok")
    assert orch.entities.calls == ["Mara's sister is Ioana"] == orch.kg_updater.calls
    assert orch.learning.calls[0]["task"] == "Mara's sister is Ioana"


# ── end to end: a guest API key against a real orchestrator ──────────────────

@pytest.fixture
def real(enabled, store, client, monkeypatch):
    from agents import web
    from tests.test_o26_golden_loop_chat import REPLY, FakeBackend, _orch

    orch = _orch()
    prompts: list[str] = []

    class Spy(FakeBackend):
        async def generate(self, model, prompt, system="", **kw):
            prompts.append(prompt + "\n" + (system or ""))
            return REPLY

        async def generate_stream(self, model, prompt, system="", on_token=None, **kw):
            prompts.append(prompt + "\n" + (system or ""))
            if on_token:
                on_token(REPLY)
            return REPLY

    spy = Spy()
    monkeypatch.setattr(orch.llm_router, "select_backend", lambda agent_id, prompt="": (spy, "fake-model", "local"))

    class Google:
        access_token = "tok"

        async def get_today_events(self):
            return [{"summary": "OWNER-SECRET-MEETING with the bank"}]

        async def list_messages(self, max_results=5):
            return [{"subject": "OWNER-SECRET-EMAIL password reset"}]

    monkeypatch.setitem(orch.plugins, "google-calendar", Google())
    monkeypatch.setitem(orch.plugins, "gmail", Google())
    monkeypatch.setattr(web, "orch", orch)
    return orch, prompts


def test_a_guest_key_never_sees_the_owners_calendar_or_mail(real, store, client):
    orch, prompts = real
    guest, _ = _key(store, name="guest")
    res = client.post("/v1/chat/completions", json=_chat("what is on my calendar and in my email inbox?"),
                      headers=_auth(guest))
    assert res.status_code == 200, res.text
    assert prompts and not any("OWNER-SECRET" in p for p in prompts)
    owner, _ = _key(store, owner=True, name="owner")
    client.post("/v1/chat/completions", json=_chat("what is on my calendar and in my email inbox?"),
                headers=_auth(owner))
    assert any("OWNER-SECRET" in p for p in prompts)        # the gate is the speaker, not the plugin


def test_a_guest_key_does_not_write_the_owners_knowledge_graph(real, store, client):
    orch, _prompts = real
    from tests.test_o26_golden_loop_chat import _counts

    before = _counts(orch)
    guest, _ = _key(store, name="guest")
    res = client.post("/v1/chat/completions",
                      json=_chat("Remember: Mara's flight is AB123 and Mara's sister is Ioana Popescu."),
                      headers=_auth(guest))
    assert res.status_code == 200, res.text
    after = _counts(orch)
    assert after["kg"] == before["kg"]


def test_a_guest_key_never_gets_the_owners_core_memory(real, store, client, monkeypatch):
    orch, prompts = real
    monkeypatch.setattr(orch, "_living_core_memory_block", lambda freeze=True: "OWNER-CORE-FACT: lives at X")
    guest, _ = _key(store, name="guest")
    assert client.post("/v1/chat/completions", json=_chat("who am I?"), headers=_auth(guest)).status_code == 200
    assert prompts and not any("OWNER-CORE-FACT" in p for p in prompts)
    owner, _ = _key(store, owner=True, name="owner")
    client.post("/v1/chat/completions", json=_chat("who am I?"), headers=_auth(owner))
    assert any("OWNER-CORE-FACT" in p for p in prompts)
