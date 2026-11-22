"""Reviewed Kanban sources at both production chat doors, using scoped SQLite data."""
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from tests.test_session_transcript import client, host, seed


OWNER = {"X-Admin-Token": "owner-secret"}


@pytest.fixture
def boards(host, monkeypatch):
    from agents import web
    from agents.core.routers import kanban

    orch, root = host
    home = root / "boards-home"
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(kanban, "_enabled", lambda: True)
    monkeypatch.setattr(kanban, "data_path", lambda _: home)
    orch.agents = {"frigga": object(), "jarvis": object()}
    orch.session_trust = lambda _sid: "clean"
    orch._pending_input_service = lambda: None
    refs = []
    with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
        for board, field, excerpt in (("north", "result", "Copper 731"), ("south", "latest_summary", "Juniper 284")):
            kb.create_board(board)
            with closing(kb.connect(board=board)) as conn:
                task = kb.create_task(conn, title="Arrival")
                whole = f"private neighbor\r\n{excerpt}"
                conn.execute("UPDATE tasks SET status='done', result=? WHERE id=?", (whole if field == "result" else None, task))
                if field == "latest_summary":
                    conn.execute("INSERT INTO task_runs (task_id,status,started_at,summary) VALUES (?,?,?,?)", (task, "done", 100, whole))
                conn.commit()
                refs.append(dict(board=board, task_id=task, source=field, excerpt=excerpt,
                                 sha256=hashlib.sha256(whole.encode()).hexdigest()))
    return orch, home, refs, client(monkeypatch, orch)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_both_selected_sources_are_verified_and_recorded_together(boards, path, monkeypatch):
    from agents.core import context_refs

    orch, _, refs, http = boards
    await seed(orch, "destination")
    orch.session_id = "destination"
    open_board = kb.connect

    def expect_read_only(*args, **kwargs):
        conn = open_board(*args, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE tasks SET title=title WHERE 0")
        conn.rollback()
        return conn

    monkeypatch.setattr(kb, "connect", expect_read_only)
    for ref in refs:
        task = http.get(f"/api/kanban/tasks/{ref['task_id']}", params={"board": ref["board"]}, headers=OWNER)
        assert task.json()["task"]["board_source_sha256"] == ref["sha256"]
    seen = []

    async def handle(message, **kwargs):
        seen.append(context_refs.attached_block())
        await orch.memory.add_turn("destination", "user", message, channel="web")
        return "Both deliveries"

    orch.handle_input = orch.handle_input_stream = handle
    body = {"message": "Compare the arrivals", "agent": "frigga", "board_references": refs}
    answer = http.post(path, headers=OWNER, json=body)
    assert answer.status_code == 200, answer.text
    evt = answer.json() if path == "/chat" else [json.loads(line[6:]) for line in answer.text.splitlines() if line.startswith("data: ")][-1]
    citations = [{key: value for key, value in ref.items() if key != "excerpt"} for ref in refs]
    assert evt["board_sources"] == citations
    assert len(seen) == 1 and "private neighbor" not in seen[0]
    for ref in refs:
        assert ref["excerpt"] in seen[0] and f"({ref['board']}/{ref['task_id']})" in seen[0]
    user = orch.memory.conversation.sessions["destination"][-1].to_dict()
    assert user["content"] == body["message"] and user["board_sources"] == citations


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_source_denials_and_digest_race_never_start_a_turn(boards, path):
    orch, home, refs, http = boards
    await seed(orch, "destination")
    calls = []

    async def handle(*args, **kwargs):
        calls.append(args)
        return "unexpected"
    orch.handle_input = orch.handle_input_stream = handle
    body = dict(message="Compare", session_id="destination", agent="frigga", board_references=refs)
    assert http.post(path, json=body, headers={"X-User-Token": "guest-secret"}).status_code == 403
    for patch, code in (({"agent": "jarvis"}, 403), ({"message": "/new"}, 400),
                        ({"board_references": [refs[0], refs[0]]}, 422),
                        ({"board_references": [dict(refs[0], excerpt="X" * 64_001)]}, 422),
                        ({"board_references": [dict(refs[0], excerpt="ø" * 36_000)]}, 413),
                        ({"board_references": [dict(refs[0], excerpt="private-other-card-text")]}, 409),
                        ({"board_references": [dict(refs[0], source="latest_summary")]}, 409),
                        ({"attachments": [{"name": f"Kanban   result ({refs[0]['board']}/{refs[0]['task_id']})",
                                           "text": "invented result"}]}, 422),
                        ({"board_references": [dict(refs[0], board="../bad", excerpt="hidden")]}, 422)):
        res = http.post(path, json={**body, **patch}, headers=OWNER)
        assert res.status_code == code, res.text
        assert "private-other-card-text" not in res.text and "hidden" not in res.text
    with kanban_scope(KanbanContext(home, "owner", can_mutate=True)), closing(kb.connect(board="north")) as conn:
        conn.execute("UPDATE tasks SET result = result || ' extra neighbor' WHERE id=?", (refs[0]["task_id"],))
        conn.commit()
    res = http.post(path, json=body, headers=OWNER)
    assert res.status_code == 409 and res.json()["detail"] == "board_source_changed"
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_shared_attachment_budget_refuses_entire_reviewed_send(boards, monkeypatch, path):
    from agents.core import context_refs
    orch, _, refs, http = boards
    await seed(orch, "destination")
    captured = []

    async def handle(*args, **kwargs):
        captured.append(args)
        return "unused"
    orch.handle_input = orch.handle_input_stream = handle
    # Simulate two ordinary @file references already occupying the common byte budget.
    monkeypatch.setattr(context_refs, "expand", lambda text: context_refs.attach_editor_content(
        None, text, [{"name": name, "text": "x" * 64_000} for name in ("first", "second")]))
    r = http.post(path, headers=OWNER, json=dict(message="Compare", agent="frigga",
        session_id="destination", board_references=refs))
    assert r.status_code == 413 and "attachment_limit" in r.json()["detail"]
    assert not captured and len(orch.memory.conversation.sessions["destination"]) == 2
