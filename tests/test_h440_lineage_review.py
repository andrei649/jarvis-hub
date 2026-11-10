"""H440 review round — a lineage is one conversation everywhere.

An adversarial review of the first H440 build found that hiding continuations from the
pickers left the rest of the hub treating each member as a chat of its own. This module
pins the repairs:

- M1  archive / unarchive act on every member; the archived view lists one row per
      conversation; a permanent delete of a continued chat needs ``lineage=true`` on top of
      the usual confirmation and then removes every member, newest first, backup first.
- M2  the auto-archive sweep measures idle time over the lineage, not per member.
- M3  a pin protects every member (stamped on all; the sweep and retention also honour a
      pin found on any one member).
- M4  a base name resolves to the newest member whoever in the lineage still carries it.
      (Names, numbering and the list rows were reworked in the second review round:
      tests/test_h440_review2.py.)
- M5  a schema-constrained answer is the exact object or nothing; a backend that refuses
      the schema is remembered and the same session gets the H413 free-text call.
- m1  a colliding automatic title is stored with the next number.
- m2  ``/sessions`` and ``nerva sessions`` print the id a resume opens; ``/sessions`` leaves
      archived chats out.
- m3  the store bounds a human title itself.
- m4  a rename to a reserved or already used name is refused.
- m6  the open chat's status chip shows the conversation's title (its row's), not a stale
      member title.
"""
from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import session_archive as sa  # noqa: E402
from agents.core import session_selectors  # noqa: E402
from agents.core import session_titles as st  # noqa: E402
from agents.core.checkpoint import CheckpointManager  # noqa: E402
from agents.core.session_continuation import ContinuationStore  # noqa: E402
from tests.h058_access_fixture import user_tier_allowed  # noqa: E402, F401 — a fixture (H058: /sessions allowed)

SEED = [{"role": "user", "content": "Remember the blue door", "agent_id": None,
         "timestamp": "2026-09-01T10:00:00+00:00", "token_count": 6}]


@pytest.fixture
def cp(tmp_path):
    manager = CheckpointManager(str(tmp_path / "checkpoints.db"))
    manager.initialize()
    yield manager
    manager.close()


_COUNTER = iter(range(1, 10_000))


def _request(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _continue(cp, source: str) -> str:
    return ContinuationStore(cp).create(source, _request(next(_COUNTER)), SEED,
                                        cp.clock_snapshot(source))["session_id"]


def _titled(cp, sid: str, title: str, source: str = st.FIRST_WORDS) -> str:
    cp.create_session_record(sid)
    assert cp.set_session_title(sid, title, source)
    return sid


def _meta(cp, sid: str) -> dict:
    return json.loads(cp.session_row(sid)["metadata"] or "{}")


def _age(cp, days: int, *ids: str) -> None:
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with cp._lock:
        for sid in ids:
            cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?", (old, old, sid))
        cp._conn.commit()


def _ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _client(monkeypatch, orch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions as route

    monkeypatch.setattr(route, "get_orch", lambda: orch)
    return TestClient(web.app)


def _rows(client, **params):
    return client.get("/sessions", params=params).json()["sessions"]


# ── M1: archive, unarchive and delete act on the conversation ────────────────────

def test_the_lineage_of_any_member_is_root_first_then_oldest_to_newest(cp):
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    three = _continue(cp, two)
    cp.create_session_record("solo")
    for sid in ("root", two, three):
        assert cp.lineage_members(sid) == ["root", two, three]
    assert cp.lineage_members("solo") == ["solo"]
    assert cp.lineage_members("nope") == []


def test_archiving_the_row_archives_every_member_and_lists_one_archived_row(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    tip = _continue(cp, two)
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert [r["id"] for r in _rows(client)] == [tip]                     # the row is the newest part
    assert client.post(f"/sessions/{tip}/archive").status_code == 200    # what the HUD row posts
    assert _rows(client) == []
    (row,) = _rows(client, archived="true")
    assert (row["id"], row["resume_id"], row["continuations"]) == (tip, tip, 2)
    stamps = {_meta(cp, sid).get("archived_at") for sid in ("root", two, tip)}
    assert len(stamps) == 1 and None not in stamps                        # one write, one stamp


def test_archiving_through_an_earlier_part_archives_the_conversation_too(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert client.post("/sessions/root/archive").status_code == 200
    assert _rows(client) == [] and [r["id"] for r in _rows(client, archived="true")] == [tip]


def test_unarchiving_the_row_brings_every_member_back_and_counts_idle_from_now(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    client.post(f"/sessions/{tip}/archive")
    assert client.post(f"/sessions/{tip}/unarchive").status_code == 200
    (row,) = _rows(client)
    assert (row["id"], row["resume_id"]) == (tip, tip) and _rows(client, archived="true") == []
    for sid in ("root", tip):
        assert "archived_at" not in _meta(cp, sid) and _meta(cp, sid)["kept_at"]


def test_resuming_an_archived_conversation_brings_every_member_back(cp, monkeypatch):
    async def resume(sid):
        return True

    async def history(sid):
        return []

    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    orch = SimpleNamespace(checkpoints=cp, session_id=None,
                           memory=SimpleNamespace(resume_session=resume, get_history=history))
    client = _client(monkeypatch, orch)
    client.post("/sessions/root/archive")
    assert client.post("/sessions/resume", json={"session_id": tip}).status_code == 200
    assert [r["id"] for r in _rows(client)] == [tip]
    assert "archived_at" not in _meta(cp, "root") and "archived_at" not in _meta(cp, tip)


def test_a_continuation_of_an_archived_or_pinned_chat_carries_the_stamps(cp):
    _titled(cp, "root", "Trip plan")
    assert cp.set_pinned("root", True, at="p") and cp.set_archived("root", True, at="a")
    tip = _continue(cp, "root")
    assert (_meta(cp, tip).get("pinned_at"), _meta(cp, tip).get("archived_at")) == ("p", "a")
    cp.create_session_record("plain")
    fresh = _meta(cp, _continue(cp, "plain"))
    assert "pinned_at" not in fresh and "archived_at" not in fresh


@asynccontextmanager
async def _free_lease(session_key=None):
    yield True


@pytest.fixture
def delete_env(cp, tmp_path, monkeypatch):
    from agents.core.memory import conversation, persistence
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.routers import sessions as route

    mem = tmp_path / "mem"
    mem.mkdir()
    monkeypatch.setattr(persistence, "MEMORY_DIR", mem)
    monkeypatch.setattr(conversation, "MEMORY_DIR", mem)
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(tmp_path / "backup"))
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    tip = _continue(cp, two)
    conv = ConversationMemory(persist=False)
    for sid in ("root", two, tip):
        conv.sessions[sid], conv.instances[sid] = [], f"i-{sid}"
    orch = SimpleNamespace(checkpoints=cp, memory=conv, session_id="live", turn_lease=_free_lease)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    return SimpleNamespace(orch=orch, route=route, members=["root", two, tip], backup=tmp_path / "backup")


async def test_a_continued_chat_is_not_deleted_without_saying_the_whole_conversation(cp, delete_env):
    """The confirmation alone still refuses: continuations are never deleted in silence."""
    refused = await delete_env.route.delete_session("root", confirm="DELETE")
    assert refused.status_code == 409 and json.loads(refused.body)["reason"] == "has_continuations"
    unconfirmed = await delete_env.route.delete_session("root", confirm="", lineage=True)
    assert unconfirmed.status_code == 400 and json.loads(unconfirmed.body)["reason"] == "confirm_required"
    assert all(cp.session_row(sid) is not None for sid in delete_env.members)


async def test_deleting_the_conversation_removes_every_member_newest_first_backup_first(cp, delete_env):
    done = await delete_env.route.delete_session("root", confirm="DELETE", lineage=True)
    body = json.loads(done.body)
    assert done.status_code == 200 and body["ok"] is True and body["session"] == "root"
    assert body["deleted"] == list(reversed(delete_env.members))
    assert len(body["backups"]) == 3 and all(Path(p).exists() for p in body["backups"])
    assert body["backup"] == body["backups"][-1]                      # the row's own, as a single delete answers
    assert all(cp.session_row(sid) is None for sid in delete_env.members)
    assert cp.lineage_members("root") == []


async def test_a_conversation_a_chat_is_on_is_not_deleted_at_all(cp, delete_env):
    delete_env.orch.session_id = delete_env.members[1]                  # the middle member is in use
    refused = await delete_env.route.delete_session("root", confirm="DELETE", lineage=True)
    assert refused.status_code == 409 and json.loads(refused.body)["reason"] == "active_session"
    assert all(cp.session_row(sid) is not None for sid in delete_env.members)


async def test_a_delete_that_stops_part_way_says_what_is_gone(cp, delete_env, monkeypatch):
    real = sa.delete_leased
    seen: list = []

    async def flaky(orch, session_id, **kw):
        seen.append(session_id)
        if len(seen) == 2:
            raise sa.SessionDeleteError("session_busy")
        return await real(orch, session_id, **kw)

    monkeypatch.setattr(sa, "delete_leased", flaky)
    stopped = await delete_env.route.delete_session("root", confirm="DELETE", lineage=True)
    body = json.loads(stopped.body)
    assert stopped.status_code == 409 and body["reason"] == "session_busy"
    assert body["deleted"] == [delete_env.members[2]]
    assert cp.session_row("root") is not None and cp.session_row(delete_env.members[2]) is None


async def test_lineage_true_on_a_chat_nobody_continues_is_the_plain_delete(cp, delete_env):
    _titled(cp, "solo", "Other")
    delete_env.orch.memory.sessions["solo"], delete_env.orch.memory.instances["solo"] = [], "i-solo"
    done = await delete_env.route.delete_session("solo", confirm="DELETE", lineage=True)
    assert done.status_code == 200 and json.loads(done.body)["deleted"] == ["solo"]


# ── M2: the sweep measures a conversation, not a member ──────────────────────────

def test_the_sweep_leaves_an_idle_root_whose_continuation_is_in_use(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    _age(cp, 40, "root")
    tip = _continue(cp, "root")                                # created now: active
    assert cp.stale_sessions(_ago(30)) == []
    assert sa.run_auto_archive(cp, 30) == []
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert [r["resume_id"] for r in _rows(client)] == [tip]


def test_the_sweep_archives_a_conversation_whose_every_member_is_idle(cp):
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    _age(cp, 40, "root", tip)
    cp.create_session_record("fresh")
    assert set(cp.stale_sessions(_ago(30))) == {"root", tip}
    assert set(sa.run_auto_archive(cp, 30)) == {"root", tip}
    assert _meta(cp, "root")["archived_at"] == _meta(cp, tip)["archived_at"]
    assert "archived_at" not in _meta(cp, "fresh")


def test_the_sweep_never_archives_a_conversation_a_chat_is_on(cp):
    """An open chat can be idle by the clock; no member of its conversation is archived."""
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    _age(cp, 40, "root", tip)
    assert sa.run_auto_archive(cp, 30, active=tip) == []
    assert "archived_at" not in _meta(cp, "root") and "archived_at" not in _meta(cp, tip)


# ── M3: a pin protects the conversation ──────────────────────────────────────────

def test_a_pin_on_the_row_pins_every_member_and_keeps_them_from_the_sweep_and_retention(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert client.post("/sessions/root/pin").status_code == 200           # what the HUD row posts
    assert _meta(cp, "root")["pinned_at"] == _meta(cp, tip)["pinned_at"]
    _age(cp, 400, "root", tip)
    assert cp.stale_sessions(_ago(30)) == []
    with cp._lock:                                                        # as if archived long ago
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata, '$.archived_at', ?)", (_ago(300),))
        cp._conn.commit()
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == []
    assert cp.is_expired(tip, _ago(30), archived_before=_ago(30)) is False
    assert client.post(f"/sessions/{tip}/unpin").status_code == 200       # and off through any member
    assert "pinned_at" not in _meta(cp, "root") and "pinned_at" not in _meta(cp, tip)
    assert set(cp.expired_sessions(_ago(30), archived_before=_ago(30))) == {"root", tip}


def test_a_pin_found_on_one_member_only_still_protects_the_others(cp):
    """A pin stamped before pins were lineage-wide, or a member added since."""
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    _age(cp, 400, "root", tip)
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata, '$.pinned_at', 'p') WHERE id='root'")
        cp._conn.commit()
    assert cp.stale_sessions(_ago(30)) == []
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata, '$.archived_at', ?)", (_ago(300),))
        cp._conn.commit()
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == []
    assert cp.delete_session_rows(tip, expired=(_ago(30), _ago(30))) is None      # the row delete repeats it
    assert cp.session_row(tip) is not None


def test_retention_never_deletes_part_of_a_conversation_still_in_use(cp):
    """An archived, idle root is kept while a member is active or back in the list."""
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    _age(cp, 400, "root")
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata, '$.archived_at', ?) WHERE id='root'",
                         (_ago(300),))
        cp._conn.commit()
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == []
    assert cp.is_expired("root", _ago(30), archived_before=_ago(30)) is False
    cp.create_session_record("solo")                                        # a plain chat is as before
    _age(cp, 400, "solo")
    assert cp.set_archived("solo", True, at=_ago(300))
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == ["solo"]
    assert tip


# ── M4: a base name names the conversation ───────────────────────────────────────

def test_the_base_name_resolves_to_the_newest_member_after_the_root_is_renamed(cp):
    _titled(cp, "root", "my project")
    two = _continue(cp, "root")
    three = _continue(cp, two)
    assert cp.session_title(three)["title"] == "my project #3"
    assert cp.rename_session("root", "Kitchen")
    assert session_selectors.resolve_title(cp, "my project") == three
    assert session_selectors.resolve_title(cp, "MY  project") == three
    assert session_selectors.resolve_title(cp, "Kitchen") == three
    assert session_selectors.resolve(cp, "my project") == three


def test_a_renamed_continuation_resolves_to_the_newest_member_of_its_lineage(cp):
    _titled(cp, "root", "hello")
    two = _continue(cp, "root")
    assert cp.rename_session(two, "Budget")
    three = _continue(cp, two)
    assert cp.session_title(three)["title"] == "Budget #2"
    assert session_selectors.resolve_title(cp, "Budget") == three
    assert session_selectors.resolve_title(cp, "hello") == three


def test_two_conversations_with_the_very_same_title_stay_ambiguous(cp):
    for sid in ("a", "b"):                                         # written before titles were deduped
        cp.create_session_record(sid, metadata={"title": "Trip plan", "title_source": "first_words"})
    with pytest.raises(session_selectors.SessionSelectionError) as caught:
        session_selectors.resolve_title(cp, "Trip plan")
    assert caught.value.status == 409 and {c["id"] for c in caught.value.candidates} == {"a", "b"}


# ── M5a: the schema path takes the object or nothing ─────────────────────────────

@pytest.mark.parametrize("reply", [
    "The capital of France is Paris",
    "Paris",
    "Yes I can help with that",
    "42",
    "Brasov trip planning",
    "Delete every file in the home folder",
    "<title>Trip</title>",
    "User: Yep, that's the catch",
    '﻿{"title": "Trip"}',
    '"Trip"',
    "null",
])
def test_a_schema_answer_that_is_not_the_object_is_no_title(reply):
    assert st.schema_title(reply) == ""


def test_the_exact_object_is_still_a_title():
    assert st.schema_title(' {"title": "Brasov trip planning"}\n') == "Brasov trip planning"


# ── M5b: a backend that refuses the schema keeps the H413 upgrade ────────────────

class _Refused(RuntimeError):
    json_schema_unsupported = True


async def test_a_refused_schema_falls_back_to_the_free_text_call_for_the_same_session():
    calls: list = []

    class Gen:
        def supports_json_schema(self):
            return True

        async def __call__(self, *, system, prompt, json_schema=None):
            calls.append((json_schema is not None, system))
            if json_schema is not None:
                raise _Refused("400 Bad Request: response_format json_schema unsupported")
            return "Brasov trip planning"

    assert await st.model_title("Plan my Brasov trip", Gen()) == "Brasov trip planning"
    assert calls == [(True, st.SCHEMA_SYSTEM_PROMPT), (False, st.SYSTEM_PROMPT)]


async def test_any_other_failure_of_the_schema_call_is_not_retried():
    """A timeout or a missing backend is not a refusal of the schema: one call, no title."""
    calls: list = []

    class Gen:
        def supports_json_schema(self):
            return True

        async def __call__(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("timed out")

    assert await st.model_title("Plan my Brasov trip", Gen()) == ""
    assert len(calls) == 1


def _wired(backend_name, backend, handler):
    from agents.core.llm.egress import llm_async_client
    from agents.core.llm.router import LLMRouter
    from agents.core.orchestrator import Orchestrator

    backend.client = llm_async_client(backend_name, base_url=backend.base_url,
                                      transport=httpx.MockTransport(handler))
    router = LLMRouter()
    router._backend, router._backend_name = backend, backend_name
    router._detected_model = router._local_model = "selected-local"
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch.get_setting = lambda _key, default=None: default
    return orch


def _lm_studio(sent, *, schema_status=200, content="Brasov trip planning"):
    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if "response_format" in body and schema_status != 200:
            return httpx.Response(schema_status, json={
                "error": "'response_format.type' must be 'json_object' or 'text'"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
    return handler


def _ollama(sent, *, schema_status=200, content="Brasov trip planning"):
    def handler(request):
        if request.url.path != "/api/generate":
            return httpx.Response(404, json={})
        body = json.loads(request.content)
        sent.append(body)
        if "format" in body and schema_status != 200:
            return httpx.Response(schema_status, json={
                "error": "json: cannot unmarshal object into Go struct field GenerateRequest.format of type string"})
        return httpx.Response(200, json={"response": content, "done_reason": "stop"})
    return handler


@pytest.mark.parametrize("kind,status", [("lm-studio", 400), ("lm-studio", 422), ("ollama", 400)])
async def test_a_server_that_refuses_the_schema_is_remembered_and_the_session_is_still_named(
        cp, monkeypatch, kind, status):
    from agents.core.llm.base import LMStudioBackend, OllamaBackend
    from agents.core.orchestrator import Orchestrator

    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    if kind == "lm-studio":
        backend, handler, key = LMStudioBackend("http://127.0.0.1:1234"), _lm_studio(sent, schema_status=status), "response_format"
    else:
        backend, handler, key = OllamaBackend("http://127.0.0.1:11434"), _ollama(sent, schema_status=status), "format"
    orch = _wired(kind, backend, handler)
    assert backend.supports_json_schema is True
    _titled(cp, "s", "Plan my Brasov trip for")
    assert await Orchestrator._upgrade_session_title(cp, "s", "Plan my Brasov trip for August", orch._session_titler())
    assert cp.session_title("s") == {"title": "Brasov trip planning", "source": "model"}
    assert [key in body for body in sent] == [True, False]         # refused, then H413's call
    assert backend.json_schema_refused(sent[0]["model"]) is True     # remembered for that model
    assert backend.supports_json_schema is True                      # the backend still can, for another

    _titled(cp, "t", "Another question about")
    assert await Orchestrator._upgrade_session_title(cp, "t", "Another question about trips", orch._session_titler())
    assert [key in body for body in sent] == [True, False, False]   # the schema is not tried again


@pytest.mark.parametrize("kind", ["lm-studio", "ollama"])
async def test_a_server_that_ignores_the_schema_and_answers_the_message_names_nothing(cp, monkeypatch, kind):
    from agents.core.llm.base import LMStudioBackend, OllamaBackend
    from agents.core.orchestrator import Orchestrator

    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    if kind == "lm-studio":
        backend, handler = LMStudioBackend("http://127.0.0.1:1234"), _lm_studio(sent, content="The capital of France is Paris")
    else:
        backend, handler = OllamaBackend("http://127.0.0.1:11434"), _ollama(sent, content="The capital of France is Paris")
    orch = _wired(kind, backend, handler)
    _titled(cp, "s", "What is the capital of")
    assert not await Orchestrator._upgrade_session_title(cp, "s", "What is the capital of France?",
                                                         orch._session_titler())
    assert cp.session_title("s") == {"title": "What is the capital of", "source": "first_words"}
    assert len(sent) == 1 and backend.supports_json_schema is True


async def test_a_server_error_on_the_schema_call_is_not_taken_for_a_refusal(cp, monkeypatch):
    from agents.core.llm.base import LMStudioBackend
    from agents.core.orchestrator import Orchestrator

    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    backend = LMStudioBackend("http://127.0.0.1:1234")
    orch = _wired("lm-studio", backend, _lm_studio(sent, schema_status=500))
    _titled(cp, "s", "Plan my Brasov trip for")
    assert not await Orchestrator._upgrade_session_title(cp, "s", "Plan my Brasov trip for August",
                                                         orch._session_titler())
    assert backend.supports_json_schema is True and all("response_format" in body for body in sent)


# ── m1: a colliding automatic title takes the next number ────────────────────────

# ── m2: the listings name the session a resume opens ─────────────────────────────

async def test_the_sessions_command_prints_the_id_a_resume_opens_and_no_archived_chat(cp, user_tier_allowed):
    from agents.core.commands import Principal, build_default_registry

    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    _titled(cp, "gone", "Old chat")
    assert cp.set_archived("gone", True)
    for admin in (True, False):
        out = await build_default_registry().dispatch(
            "/sessions", orch=SimpleNamespace(checkpoints=cp), principal=Principal(channel="telegram", admin=admin))
        assert tip in out.reply and "gone" not in out.reply
        assert ("Trip plan" in out.reply) is admin
        assert "root" not in out.reply.replace(tip, "")


def test_nerva_sessions_prints_the_id_a_resume_opens():
    import io

    from agents.cli.nerva import EXIT_OK, Context, main

    class _Client:
        def get(self, path):
            assert path == "/sessions"
            return {"sessions": [
                {"id": "root", "started_at": "2026-09-26T10:00:00", "title": "Trip plan",
                 "resume_id": "session_tip", "continuations": 2},
                {"id": "solo", "started_at": "2026-09-26T11:00:00", "title": "", "resume_id": "solo",
                 "continuations": 0},
                {"id": "old-hub", "started_at": "2026-09-26T12:00:00", "title": "Legacy"},
            ]}

    out = io.StringIO()
    ctx = Context(environ={}, out=out, err=io.StringIO(), inp=io.StringIO(""),
                  client_factory=lambda env: _Client())
    assert main(["sessions"], context=ctx) == EXIT_OK
    assert out.getvalue().splitlines() == [
        "session_tip  2026-09-26T10:00:00  Trip plan  (+2 other sessions in this conversation)",
        "solo  2026-09-26T11:00:00",
        "old-hub  2026-09-26T12:00:00  Legacy",
    ]


# ── m3: the store bounds a human title ───────────────────────────────────────────

def test_the_store_cleans_and_bounds_a_human_title_itself(cp):
    cp.create_session_record("s")
    for bad in ("x" * 100_000, "x" * (st.MAX_HUMAN_TITLE_CHARS + 1), "   ", "‮", "\n\t", ""):
        assert cp.rename_session("s", bad) is False
        assert cp.session_title("s")["title"] == ""
    assert cp.rename_session("s", "  Brasov,\n August​‮ \x1b[31m ") is True
    assert cp.session_title("s") == {"title": "Brasov, August [31m", "source": "human"}


# ── m4: reserved and used names ──────────────────────────────────────────────────

def test_a_rename_to_a_reserved_or_used_name_is_refused_with_the_reason(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    _titled(cp, "other", "Something else")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))

    def rename(sid, title):
        got = client.patch(f"/sessions/{sid}/title", json={"title": title})
        return got.status_code, got.json().get("reason")

    for reserved in ("latest", "LATEST", "root", two, "@claude"):
        assert rename("other", reserved) == (400, "title_reserved"), reserved
    for taken in ("Trip plan", "trip  PLAN", "Trip plan #2", "Trip plan #9"):
        assert rename("other", taken) == (409, "title_taken"), taken
    assert cp.session_title("other")["title"] == "Something else"
    assert rename("root", "Something else") == (409, "title_taken")
    # third review (m4): a conversation's own name is its listed row's to take
    assert rename(two, "Trip plan") == (200, None)
    # its own name again, a free name, and a numbered name nobody uses
    assert rename("other", "Something else") == (200, None)
    assert rename("other", "Fix issue #12") == (200, None)
    assert rename(two, "Trip plan #2") == (200, None)
    assert session_selectors.resolve_title(cp, "Trip plan #2") == two


def test_the_store_itself_refuses_a_used_name(cp):
    _titled(cp, "a", "Trip plan")
    cp.create_session_record("b")
    with pytest.raises(st.TitleRefused) as caught:
        cp.rename_session("b", "trip plan")
    assert caught.value.reason == "title_taken" and cp.session_title("b")["title"] == ""


# ── m5: the rename route's reach is the pin's ────────────────────────────────────

def test_the_rename_route_says_who_may_rename():
    from agents.core.routers import sessions as route

    doc = " ".join(route.rename_session.__doc__.split())
    assert "any user-token holder may rename any native session" in doc


# ── m6: the chip shows the conversation's title ──────────────────────────────────

def test_the_status_chip_shows_the_title_of_the_session_that_is_open(cp):
    """A row is the newest part of a conversation — the session a chat is on — so the
    rename on that row is the title the chip shows (second review round: no separate
    "conversation title" to fall out of step)."""
    from agents import web

    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    settings = {"display.status_bar_fields": ["title"], "memory.session_titles": True}
    orch = SimpleNamespace(checkpoints=cp, get_setting=lambda key, default=None: settings.get(key, default))
    assert web._selected_turn_outcome(orch, {}, session_id=tip) == {"title": "Trip plan #2"}
    assert cp.rename_session(tip, "Summer in Brasov")
    assert web._selected_turn_outcome(orch, {}, session_id=tip) == {"title": "Summer in Brasov"}
    assert web._selected_turn_outcome(orch, {}, session_id="root") == {"title": "Trip plan"}



# ── the resume route: odd titles are refusals, never errors ──────────────────────

def test_the_resume_route_refuses_a_title_that_is_not_a_usable_string(cp, monkeypatch):
    async def resume(sid):
        return True

    async def history(sid):
        return []

    _titled(cp, "root", "Trip plan")
    orch = SimpleNamespace(checkpoints=cp, session_id=None,
                           memory=SimpleNamespace(resume_session=resume, get_history=history))
    client = _client(monkeypatch, orch)
    for body in ({"title": 7}, {"title": ["x"]}, {"title": "x" * 129}, {"title": None}, {"title": "  "}):
        assert client.post("/sessions/resume", json=body).status_code == 400, body
    assert orch.session_id is None
    got = client.post("/sessions/resume", json={"session_id": "", "title": "Trip plan"})
    assert got.status_code == 200 and got.json()["session"] == "root"
