"""H440 second review round.

- B1  deleting a whole conversation prunes old backups once, after the run, keeping the
      usual few on top of the ones it just wrote: every backup it reports is on disk.
- J1  a name opens the newest session that continues its bearer — a numbered name too.
- J2  ``#N`` means "the Nth part of a conversation" and nothing else: a title's own trailing
      number is part of its name, two chats opened with the same words are told apart with
      ``(2)``, an exact name wins over look-alikes, and an imported chat's title never
      changes a native one.
- J3  a session can be continued more than once. The lists show one row per session nobody
      continued yet (each is where a conversation can be picked up); the earlier parts are
      hidden; archive, pin, the sweep and retention stay conversation-wide.
- J4  only an answer that names the schema feature turns the JSON schema off, and only for
      that model on that server.
- m1  the lineage queries are index-driven.   m2  a title is deduped atomically.
- m3  a member a chat opens during a whole-conversation delete is not deleted.
- m4  retention collects a conversation child first.
"""
from __future__ import annotations

import json
import os
import sys
import threading
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
from agents.core import session_selectors as sel  # noqa: E402
from agents.core import session_titles as st  # noqa: E402
from agents.core.checkpoint import CheckpointManager  # noqa: E402
from agents.core.session_continuation import ContinuationStore  # noqa: E402

SEED = [{"role": "user", "content": "Remember the blue door", "agent_id": None,
         "timestamp": "2026-09-01T10:00:00+00:00", "token_count": 6}]
_COUNTER = iter(range(1, 100_000))


@pytest.fixture
def cp(tmp_path):
    manager = CheckpointManager(str(tmp_path / "checkpoints.db"))
    manager.initialize()
    yield manager
    manager.close()


def _request(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _continue(cp, source: str) -> str:
    return ContinuationStore(cp).create(source, _request(next(_COUNTER)), SEED,
                                        cp.clock_snapshot(source))["session_id"]


def _titled(cp, sid: str, title: str, source: str = st.FIRST_WORDS) -> str:
    cp.create_session_record(sid)
    assert cp.set_session_title(sid, title, source)
    return sid


def _title(cp, sid: str) -> str:
    return cp.session_title(sid)["title"]


def _meta(cp, sid: str) -> dict:
    return json.loads(cp.session_row(sid)["metadata"] or "{}")


def _ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _age(cp, days: float, *ids: str) -> None:
    with cp._lock:
        for sid in ids:
            cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?", (_ago(days), _ago(days), sid))
        cp._conn.commit()


def _client(monkeypatch, orch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions as route

    monkeypatch.setattr(route, "get_orch", lambda: orch)
    return TestClient(web.app)


def _rows(client, **params):
    return client.get("/sessions", params=params).json()["sessions"]


@asynccontextmanager
async def _free_lease(session_key=None):
    yield True


def _delete_orch(cp, tmp_path, monkeypatch, ids):
    from agents.core.memory import conversation, persistence
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.routers import sessions as route

    mem = tmp_path / "mem"
    mem.mkdir(exist_ok=True)
    monkeypatch.setattr(persistence, "MEMORY_DIR", mem)
    monkeypatch.setattr(conversation, "MEMORY_DIR", mem)
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(tmp_path / "backup"))
    conv = ConversationMemory(persist=False)
    for sid in ids:
        conv.sessions[sid], conv.instances[sid] = [], f"i-{sid}"
    orch = SimpleNamespace(checkpoints=cp, memory=conv, session_id="live", turn_lease=_free_lease)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    return orch, route


def _chain(cp, length: int, title: str = "Long chat") -> list[str]:
    ids = [_titled(cp, "root", title)]
    for _ in range(length - 1):
        ids.append(_continue(cp, ids[-1]))
    return ids


# ── B1: every reported backup is on disk ─────────────────────────────────────────

async def test_a_conversation_longer_than_the_backup_keep_loses_no_backup(cp, tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SESSION_BACKUP_KEEP", raising=False)
    ids = _chain(cp, 13)
    _orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    done = await route.delete_session(ids[-1], confirm="DELETE", lineage=True)
    body = json.loads(done.body)
    assert done.status_code == 200 and len(body["deleted"]) == 13
    assert len(body["backups"]) == 13 and all(Path(p).exists() for p in body["backups"])
    assert body["pruned"] == []
    assert len(list(sa.default_backup_dir().glob(f"*{sa.BACKUP_SUFFIX}"))) == 13


def _old_backups(count: int) -> list[Path]:
    root = sa.default_backup_dir()
    root.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(count):
        path = root / f"old-{i}{sa.BACKUP_SUFFIX}"
        path.write_bytes(b"x")
        stamp = (datetime.now(UTC) - timedelta(days=30 - i)).timestamp()      # old-0 is the oldest
        os.utime(path, (stamp, stamp))
        made.append(path)
    return made


async def test_the_prune_keeps_the_usual_few_on_top_of_the_ones_just_written(cp, tmp_path, monkeypatch):
    ids = _chain(cp, 4)
    _orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", "2")
    old = _old_backups(5)
    body = json.loads((await route.delete_session("root", confirm="DELETE", lineage=True)).body)
    assert len(body["backups"]) == 4 and all(Path(p).exists() for p in body["backups"])
    assert sorted(body["pruned"]) == sorted(p.name for p in old[:3])        # the truth, not []
    assert [p.exists() for p in old] == [False, False, False, True, True]


async def test_a_run_that_stops_part_way_still_prunes_once_and_keeps_what_it_wrote(cp, tmp_path, monkeypatch):
    ids = _chain(cp, 4)
    orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", "1")
    old = _old_backups(3)

    @asynccontextmanager
    async def busy(session_key=None):
        yield session_key != ids[1]

    orch.turn_lease = busy
    stopped = await route.delete_session("root", confirm="DELETE", lineage=True)
    body = json.loads(stopped.body)
    assert stopped.status_code == 409 and body["reason"] == "session_busy"
    assert body["deleted"] == [ids[3], ids[2]]
    assert len(body["backups"]) == 2 and all(Path(p).exists() for p in body["backups"])
    assert sorted(body["pruned"]) == sorted(p.name for p in old[:2]) and old[2].exists()


# ── J1: a name opens the newest session that continues its bearer ────────────────

def test_a_numbered_name_opens_the_newest_continuation_of_that_member(cp):
    _titled(cp, "root", "hello")
    two = _continue(cp, "root")
    assert _title(cp, two) == "hello #2" and sel.resolve_title(cp, "hello #2") == two
    three = _continue(cp, two)
    for name in ("hello #2", "hello", "hello #3", "HELLO  #2"):
        assert sel.resolve_title(cp, name) == three, name
    assert sel.resolve(cp, "hello #2") == three
    assert sel.resolve(cp, two) == two                       # an id is exactly that session
    with pytest.raises(sel.SessionSelectionError) as caught:
        sel.resolve_title(cp, "hello #9")
    assert caught.value.status == 404


# ── J2: one meaning for #N ───────────────────────────────────────────────────────

def test_a_titles_own_trailing_number_is_part_of_its_name(cp):
    _titled(cp, "s", "Fix issue #12")
    two = _continue(cp, "s")
    assert _title(cp, two) == "Fix issue #12 #2"
    assert _title(cp, _continue(cp, two)) == "Fix issue #12 #3"
    assert sel.resolve_title(cp, "Fix issue #12") != "s"       # … and it opens the newest part
    cp.create_session_record("h")
    assert cp.rename_session("h", "Sprint #4")                 # the owner's own number, too
    assert _title(cp, _continue(cp, "h")) == "Sprint #4 #2"


def test_two_chats_opened_with_the_same_words_are_told_apart_without_a_part_number(cp):
    _titled(cp, "a", "hello")
    _titled(cp, "b", "Hello ")
    _titled(cp, "c", "hello")
    assert [_title(cp, s) for s in "abc"] == ["hello", "Hello (2)", "hello (3)"]
    _titled(cp, "f1", "Fix issue #12")
    _titled(cp, "f2", "Fix issue #12")
    assert _title(cp, "f2") == "Fix issue #12 (2)"
    assert sel.resolve_title(cp, "hello") == "a" and sel.resolve_title(cp, "hello (2)") == "b"


def test_a_model_title_that_collides_is_told_apart_the_same_way_and_never_from_itself(cp):
    _titled(cp, "a", "Trip planning", st.MODEL)
    _titled(cp, "b", "Plan my trip")
    assert cp.set_session_title("b", "Trip planning", st.MODEL, replace=(st.FIRST_WORDS,))
    assert cp.session_title("b") == {"title": "Trip planning (2)", "source": "model"}
    _titled(cp, "c", "Brasov")
    assert cp.set_session_title("c", "Brasov", st.MODEL, replace=(st.FIRST_WORDS,))
    assert cp.session_title("c") == {"title": "Brasov", "source": "model"}


def test_a_chat_opened_with_a_renamed_chats_words_does_not_take_over_its_name(cp):
    _titled(cp, "a", "Budget")
    assert cp.rename_session("a", "Taxes 2026")
    _titled(cp, "b", "Taxes 2026")
    assert _title(cp, "b") == "Taxes 2026 (2)"
    tip = _continue(cp, "a")
    assert _title(cp, tip) == "Taxes 2026 #2"
    assert sel.resolve_title(cp, "Taxes 2026") == tip          # the renamed conversation, not "b"


def test_an_exact_name_wins_over_a_separate_chat_that_only_looks_alike(cp):
    _titled(cp, "h1", "hello")
    _titled(cp, "h2", "hello")                                   # "hello (2)"
    tip = _continue(cp, "h1")
    _age(cp, 5, "h1", tip)                                       # the look-alike is the newer chat
    assert sel.resolve_title(cp, "hello") == tip and sel.resolve(cp, "hello") == tip
    assert sel.resolve_title(cp, "hello (2)") == "h2"


def test_an_imported_chats_title_never_changes_a_native_one(cp):
    """A guest must not learn from a "(2)" that an imported chat goes by those words."""
    from agents.core.session_import import import_turns

    imported = import_turns(cp, source="claude", external_id="e1", request_id=_request(990), source_sha256=None,
                            turns=[{"role": "user", "content": "hi", "timestamp": "2026-10-01T00:00:00+00:00"}],
                            )["session_id"]
    assert cp.rename_session(imported, "Secret import")
    _titled(cp, "native", "Secret import")
    assert _title(cp, "native") == "Secret import"
    cp.create_session_record("other")
    assert cp.rename_session("other", "secret import (2)") is True    # nor is a rename refused for it
    assert cp.rename_session("native", "Something") and cp.rename_session("other", "Secret import") is True


def test_a_rename_into_another_conversations_part_numbers_is_refused(cp):
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    cp.create_session_record("other")
    for name in ("Trip plan", "Trip plan #2", "Trip plan #9", "trip  PLAN #40"):
        with pytest.raises(st.TitleRefused) as caught:
            cp.rename_session("other", name)
        assert caught.value.reason == "title_taken", name
    assert cp.rename_session("other", "Fix issue #12") is True          # nobody's part number
    assert cp.rename_session(two, "Trip plan #7") is True               # its own conversation's
    # third review (m4): the conversation's own first name is its listed row's to take
    assert cp.rename_session(two, "Trip plan") is True


# ── J3: branches ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tree(cp):
    """root → c2 → c3, root → b2, c2 → c4: three sessions nobody continued yet."""
    _titled(cp, "root", "Trip plan")
    c2 = _continue(cp, "root")
    c3 = _continue(cp, c2)
    b2 = _continue(cp, "root")
    c4 = _continue(cp, c2)
    return SimpleNamespace(root="root", c2=c2, c3=c3, b2=b2, c4=c4, all=["root", c2, c3, b2, c4],
                           leaves=[c3, b2, c4])


def test_every_session_nobody_continued_is_a_row_and_the_earlier_parts_are_hidden(cp, tree, monkeypatch):
    assert [_title(cp, s) for s in tree.all] == ["Trip plan", "Trip plan #2", "Trip plan #3", "Trip plan #4",
                                                 "Trip plan #5"]
    assert {r["id"] for r in cp.get_sessions(hide_continuations=True)} == set(tree.leaves)
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    rows = {r["id"]: r for r in _rows(client)}
    assert set(rows) == set(tree.leaves)                               # no leaf is unreachable
    for sid, row in rows.items():
        assert row["resume_id"] == sid and row["continuations"] == 4 and row["title"] == _title(cp, sid)
    assert cp.lineage_others(tree.leaves + ["nope"]) == {tree.c3: 4, tree.b2: 4, tree.c4: 4}


def test_a_chat_continued_once_is_one_row_under_its_newest_part(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    cp.create_session_record("solo")
    two = _continue(cp, "root")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    rows = {r["id"]: r for r in _rows(client)}
    assert set(rows) == {two, "solo"}
    assert (rows[two]["title"], rows[two]["resume_id"], rows[two]["continuations"]) == ("Trip plan #2", two, 1)
    assert (rows["solo"]["resume_id"], rows["solo"]["continuations"]) == ("solo", 0)
    assert [r["id"] for r in cp.get_sessions(limit=1, hide_continuations=True)] == [two]   # hidden before the limit


def test_a_name_opens_the_newest_branch_of_its_bearer_and_never_a_branch_without_it(cp, tree):
    assert sel.resolve_title(cp, "Trip plan") == tree.c4               # newest of the three
    assert sel.resolve_title(cp, "Trip plan #2") == tree.c4            # c2's newest continuation
    assert sel.resolve_title(cp, "Trip plan #3") == tree.c3
    assert sel.resolve_title(cp, "Trip plan #4") == tree.b2
    _titled(cp, "r", "Rome")
    a = _continue(cp, "r")
    assert cp.rename_session(a, "Paris")
    b = _continue(cp, "r")                                              # a branch that never was "Paris"
    assert sel.resolve_title(cp, "Paris") == a and sel.resolve_title(cp, "Rome") == b


def test_two_sessions_under_one_name_are_reported_as_ambiguous(cp, tree):
    with cp._lock:                                                      # as an older hub could leave them
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata, '$.title', 'Trip plan #3') WHERE id=?",
                         (tree.b2,))
        cp._conn.commit()
    with pytest.raises(sel.SessionSelectionError) as caught:
        sel.resolve_title(cp, "Trip plan #3")
    assert caught.value.status == 409 and {c["id"] for c in caught.value.candidates} == {tree.c3, tree.b2}


def test_archive_pin_and_the_sweep_stay_conversation_wide_across_branches(cp, tree, monkeypatch):
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert client.post(f"/sessions/{tree.c3}/archive").status_code == 200
    assert all("archived_at" in _meta(cp, s) for s in tree.all)
    assert _rows(client) == [] and {r["id"] for r in _rows(client, archived="true")} == set(tree.leaves)
    assert client.post(f"/sessions/{tree.b2}/unarchive").status_code == 200
    assert not any("archived_at" in _meta(cp, s) for s in tree.all)
    assert client.post(f"/sessions/{tree.c4}/pin").status_code == 200
    assert all("pinned_at" in _meta(cp, s) for s in tree.all)
    assert client.post(f"/sessions/{tree.b2}/unpin").status_code == 200
    _age(cp, 40, *tree.all)
    with cp._lock:                                                      # the unarchive above was a "keep"
        cp._conn.execute("UPDATE sessions SET metadata=json_remove(metadata, '$.kept_at')")
        cp._conn.commit()
    assert set(cp.stale_sessions(_ago(30))) == set(tree.all)
    _age(cp, 1, tree.b2)                                                # one branch is in use
    assert cp.stale_sessions(_ago(30)) == []


async def test_deleting_the_conversation_from_one_branch_says_and_deletes_all_of_it(cp, tree, tmp_path, monkeypatch):
    _orch, route = _delete_orch(cp, tmp_path, monkeypatch, tree.all)
    one = await route.delete_session(tree.b2, confirm="DELETE")        # the row alone: just that session
    assert one.status_code == 200 and cp.session_row(tree.b2) is None
    assert {r["id"] for r in cp.get_sessions(hide_continuations=True)} == {tree.c3, tree.c4}
    done = await route.delete_session(tree.c3, confirm="DELETE", lineage=True)
    body = json.loads(done.body)
    assert set(body["deleted"]) == {"root", tree.c2, tree.c3, tree.c4} and body["deleted"][-1] == "root"
    assert body["deleted"].index(tree.c2) > max(body["deleted"].index(tree.c3), body["deleted"].index(tree.c4))
    assert all(cp.session_row(s) is None for s in tree.all)


def test_a_part_whose_root_is_gone_is_still_listed(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    cp.delete_session_rows("root")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert [(r["id"], r["continuations"]) for r in _rows(client)] == [(two, 0)]
    assert cp.lineage_members(two) == [two] and sel.resolve_title(cp, "Trip plan #2") == two


# ── J4: what counts as "this server refuses the schema" ──────────────────────────

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


def _server(kind, sent, decide):
    """``decide(has_schema, call_number) -> (status, text)``."""
    def handler(request):
        if kind == "ollama" and request.url.path != "/api/generate":
            return httpx.Response(404, json={})
        body = json.loads(request.content)
        sent.append(body)
        status, text = decide(("response_format" if kind == "lm-studio" else "format") in body, len(sent))
        if status != 200:
            return httpx.Response(status, content=text.encode() if text is not None else b"")
        if kind == "lm-studio":
            return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})
        return httpx.Response(200, json={"response": text, "done_reason": "stop"})
    return handler


def _backend(kind):
    from agents.core.llm.base import LMStudioBackend, OllamaBackend

    return (LMStudioBackend("http://127.0.0.1:1234") if kind == "lm-studio"
            else OllamaBackend("http://127.0.0.1:11434"))


async def _upgrade(cp, orch, sid):
    from agents.core.orchestrator import Orchestrator

    _titled(cp, sid, f"Plan my Brasov trip {sid}")
    return await Orchestrator._upgrade_session_title(cp, sid, "Plan my Brasov trip for August", orch._session_titler())


GOOD = '{"title": "Brasov trip planning"}'
REFUSALS = {
    "lm-studio": '{"error": "\'response_format.type\' must be \'json_object\' or \'text\'"}',
    "ollama": '{"error": "json: cannot unmarshal object into Go struct field GenerateRequest.format of type string"}',
}


@pytest.mark.parametrize("kind", ["lm-studio", "ollama"])
@pytest.mark.parametrize("body", ['{"error": {"message": "No models loaded. Please load a model."}}', "", None,
                                  '{"error": "model is loading"}'])
async def test_an_unrelated_400_is_an_ordinary_failure_and_the_schema_stays_on(cp, monkeypatch, kind, body):
    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    down = {"now": True}
    backend = _backend(kind)
    orch = _wired(kind, backend, _server(kind, sent, lambda has, n: (400, body) if down["now"] else (200, GOOD)))
    key = "response_format" if kind == "lm-studio" else "format"
    assert not await _upgrade(cp, orch, "s1")                        # no title this time
    assert sent and all(key in b for b in sent)                      # never a free-text second call
    down["now"], before = False, len(sent)
    assert await _upgrade(cp, orch, "s2")                            # and the schema is still asked for
    assert [key in b for b in sent[before:]] == [True]
    assert cp.session_title("s2") == {"title": "Brasov trip planning", "source": "model"}


@pytest.mark.parametrize("kind", ["lm-studio", "ollama"])
async def test_a_refusal_that_names_the_schema_turns_it_off_for_that_model_only(cp, monkeypatch, kind):
    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    backend = _backend(kind)
    orch = _wired(kind, backend, _server(
        kind, sent, lambda has, n: (400, REFUSALS[kind]) if has and n < 4 else (200, GOOD if has else "Brasov trip planning")))
    key = "response_format" if kind == "lm-studio" else "format"
    assert await _upgrade(cp, orch, "s1") and await _upgrade(cp, orch, "s2")
    assert [key in b for b in sent] == [True, False, False]          # refused, free text, then free text only
    first_model = sent[0]["model"]
    assert backend.json_schema_refused(first_model) is True
    assert backend.json_schema_refused("another-model") is False
    monkeypatch.setenv("JARVIS_AUX_SESSION_TITLE_MODEL", "another-model")     # the owner switches the title model
    assert await _upgrade(cp, orch, "s3")
    assert sent[-1]["model"] == "another-model" and key in sent[-1]           # asked for the schema again


def test_the_refusal_is_forgotten_when_the_server_address_changes():
    backend = _backend("lm-studio")
    backend._note_schema_refusal("m")
    assert backend.json_schema_refused("m") is True
    backend.base_url = "http://127.0.0.1:4321"
    assert backend.json_schema_refused("m") is False


@pytest.mark.parametrize("status", [401, 403, 404, 408, 429, 500, 503])
async def test_other_statuses_never_turn_the_schema_off_even_when_the_body_mentions_it(cp, monkeypatch, status):
    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    backend = _backend("lm-studio")
    orch = _wired("lm-studio", backend, _server("lm-studio", sent, lambda has, n: (status, REFUSALS["lm-studio"])))
    assert not await _upgrade(cp, orch, "s1")
    assert all("response_format" in b for b in sent) and backend.json_schema_refused(sent[0]["model"]) is False


# ── m1: index-driven lineage queries ─────────────────────────────────────────────

def test_the_lineage_columns_are_indexed(cp):
    indexed = set()
    for (name,) in cp._conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='session_continuations'"):
        indexed.add(tuple(row[2] for row in cp._conn.execute(f"PRAGMA index_info({name})")))  # noqa: S608
    assert ("root_id", "created_at") in indexed and ("parent_id",) in indexed


def test_no_lineage_query_scans_a_table_once_per_session(cp):
    def plan(sql, params):
        return [row[3] for row in cp._conn.execute("EXPLAIN QUERY PLAN " + sql, params)]  # noqa: S608

    def args(sql):
        return ("x",) * (sql.count("?") - 1) + (5,)

    listing = cp._sessions_sql(archived=False, native_only=True, hide_continuations=True)
    plans = {name: plan(sql, args(sql)) for name, sql in (
        ("stale", cp._STALE_SQL), ("expired", cp._EXPIRED_SQL), ("is_expired", cp._IS_EXPIRED_SQL),
        ("delete_expired", cp._DELETE_EXPIRED_SQL), ("list", listing))}
    for name, steps in plans.items():
        inner = [step for step in steps if step.startswith("SCAN") and not step.startswith("SCAN sessions")]
        assert inner == [], (name, steps)
        assert sum(step.startswith("SCAN sessions") for step in steps) <= 1, (name, steps)
    assert not any(step.startswith("SCAN") for step in plans["is_expired"] + plans["delete_expired"])


def test_the_lineage_queries_stay_fast_on_a_large_store(cp):
    import time
    import uuid

    old = _ago(400)
    rows, links = [], []
    for i in range(6000):
        rid = f"session_r{i:06d}"
        rows.append((rid, old, old, json.dumps({"title": f"chat {i}", "title_source": "first_words"})))
        parent = rid
        for j in range(3 if i % 4 == 0 else 0):
            sid = f"session_c{i:06d}_{j}"
            rows.append((sid, old, old, json.dumps({"title": f"chat {i} #{j + 2}", "title_source": "lineage"})))
            links.append((sid, "i", uuid.uuid4().hex, parent, "i", rid, "i", old, "[]", "x", old))
            parent = sid
    with cp._lock:
        cp._conn.executemany("INSERT INTO sessions(id,started_at,ended_at,turn_count,metadata) VALUES(?,?,?,1,?)", rows)
        cp._conn.executemany("INSERT INTO session_continuations VALUES(?,?,?,?,?,?,?,?,?,?,?)", links)
        cp._conn.commit()
    started = time.perf_counter()
    assert len(cp.stale_sessions(_ago(30), limit=100_000)) == len(rows)
    assert len(cp.get_sessions(limit=20, archived=False, hide_continuations=True)) == 20
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata,'$.archived_at',?)", (_ago(100),))
        cp._conn.commit()
    assert len(cp.expired_sessions(_ago(30), archived_before=_ago(30), limit=100_000)) == len(rows)
    assert time.perf_counter() - started < 20          # it took minutes when each row scanned the table


# ── m2: an atomic dedupe ─────────────────────────────────────────────────────────

def test_two_connections_titling_with_the_same_words_never_end_with_one_title(cp, tmp_path):
    other = CheckpointManager(cp.db_path)
    other.initialize()
    try:
        for i in range(40):
            a, b = f"a{i}", f"b{i}"
            cp.create_session_record(a)
            other.create_session_record(b)
            gate = threading.Barrier(2)

            def go(manager, sid, words=f"hello there {i}", gate=gate):
                gate.wait()
                assert manager.set_session_title(sid, words, st.FIRST_WORDS)

            threads = [threading.Thread(target=go, args=(cp, a)), threading.Thread(target=go, args=(other, b))]
            [t.start() for t in threads]
            [t.join() for t in threads]
            assert {_title(cp, a), _title(cp, b)} == {f"hello there {i}", f"hello there {i} (2)"}
    finally:
        other.close()


# ── m3: a member that goes live during the run ───────────────────────────────────

async def test_a_member_a_chat_opens_mid_run_is_not_deleted(cp, tmp_path, monkeypatch):
    ids = _chain(cp, 3)
    orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    live: set = set()
    orch.live_session_ids = lambda: set(live)

    @asynccontextmanager
    async def lease(session_key=None):
        if session_key == ids[2]:
            live.add(ids[1])              # a channel chat opens the middle member meanwhile
        yield True

    orch.turn_lease = lease
    stopped = await route.delete_session("root", confirm="DELETE", lineage=True)
    body = json.loads(stopped.body)
    assert stopped.status_code == 409 and body["reason"] == "active_session" and body["deleted"] == [ids[2]]
    assert cp.session_row(ids[1]) is not None and cp.session_row("root") is not None


# ── m4: retention takes a conversation child first ───────────────────────────────

def test_expired_sessions_come_child_first_whatever_their_activity(cp):
    ids = _chain(cp, 3)
    _age(cp, 400, *ids)
    _age(cp, 200, "root")                              # the root was used again after it was continued
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata,'$.archived_at',?)", (_ago(100),))
        cp._conn.commit()
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == [ids[2], ids[1], "root"]
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30), limit=1) == [ids[2]]


# ── NITs ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ['{"title": "Trip", "title": "Other plan"}', '{"title": "Trip", "title": "Trip"}'])
def test_an_object_with_a_repeated_key_is_no_title(raw):
    assert st.schema_title(raw) == ""


@pytest.mark.parametrize("reserved", ["latest", "LATEST", "@claude", "taken-id"])
def test_a_reserved_name_is_never_stored_as_an_automatic_title(cp, reserved):
    cp.create_session_record("taken-id")
    for source in (st.FIRST_WORDS, st.MODEL):
        cp.create_session_record("s")
        assert cp.set_session_title("s", reserved, source) is False
        assert _title(cp, "s") == ""
    assert cp.set_session_title("s", "A real name", st.FIRST_WORDS) is True


def test_an_exact_title_wins_over_an_id_prefix_and_a_full_id_over_both(cp):
    _titled(cp, "session_abc", "notes")
    _titled(cp, "notes_x1", "other")
    _titled(cp, "notes", "third")                    # a session whose id is another's title
    assert sel.resolve(cp, "notes") == "notes"       # the exact id
    cp.delete_session_rows("notes")
    assert sel.resolve(cp, "notes") == "session_abc"  # the exact title, not the id prefix notes_x1
    assert sel.resolve(cp, "notes_") == "notes_x1"   # a prefix still works when no title is meant
