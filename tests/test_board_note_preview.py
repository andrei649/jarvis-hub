"""A board-note draft contains only reviewed, current source excerpts."""

import hashlib
import json
import sqlite3

import pytest

from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from tests.test_board_chat_reference_api import OWNER, boards
from tests.test_session_transcript import host


PATH = "/api/kanban/board-note/preview"


def test_preview_keeps_selected_text_literal_and_source_identity(boards, monkeypatch):
    orch, home, refs, http = boards
    excerpt = "**bold**\r\n```\r\n<script>alert(1)</script>\r\n[link](https://example.test)"
    with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
        with kb.connect(board="north") as conn:
            whole = "private neighbor\r\n" + excerpt + "\r\nprivate tail"
            conn.execute("UPDATE tasks SET title=?, result=? WHERE id=?",
                         ("**Actual**\n# heading", whole, refs[0]["task_id"]))
            conn.commit()
    refs[0].update(excerpt=excerpt, sha256=hashlib.sha256(whole.encode()).hexdigest())
    orch.handle_input = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model called"))
    open_board = kb.connect

    def read_only(*args, **kwargs):
        conn = open_board(*args, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("UPDATE tasks SET title=title WHERE 0")
        conn.rollback()
        return conn

    monkeypatch.setattr(kb, "connect", read_only)
    response = http.post(PATH, headers=OWNER, json={"references": refs})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"title", "content"} and len(body["title"]) <= 120
    assert "no-store" in response.headers["cache-control"]
    assert body["content"].count(excerpt) == 1
    assert "private neighbor" not in body["content"] and "private tail" not in body["content"]
    assert "north/" + refs[0]["task_id"] in body["content"]
    assert "south/" + refs[1]["task_id"] in body["content"]
    assert 'Task: "**Actual**\\n# heading"' in body["content"]
    assert "Source: Recorded result" in body["content"]
    assert "Source: Latest summary" in body["content"]
    assert all(ref["sha256"] in body["content"] for ref in refs)
    assert "````text\n" in body["content"]
    assert "Assignee:" not in body["content"]
    assert http.post(PATH, headers=OWNER, json={"references": refs}).json() == body


def test_preview_refuses_stale_missing_duplicate_and_other_profile(boards, monkeypatch, tmp_path):
    _orch, home, refs, http = boards
    assert http.post(PATH, headers=OWNER, json={"references": [refs[0], refs[0]]}).status_code == 422
    missing = {**refs[0], "task_id": "missing"}
    assert http.post(PATH, headers=OWNER, json={"references": [missing]}).status_code == 404
    stale = {**refs[0], "sha256": "a" * 64}
    assert http.post(PATH, headers=OWNER, json={"references": [stale]}).status_code == 409
    from agents.core.routers import kanban
    monkeypatch.setattr(kanban, "data_path", lambda _: tmp_path / "other-profile")
    assert http.post(PATH, headers=OWNER, json={"references": refs}).status_code == 404


def test_preview_rejects_invalid_and_oversize_payloads(boards):
    _orch, home, refs, http = boards
    assert http.post(PATH, headers=OWNER, json={"references": []}).status_code == 422
    assert http.post(PATH, headers=OWNER, json={"references": refs * 5}).status_code == 422
    malformed = {**refs[0], "excerpt": "private-marker", "extra": "do-not-echo"}
    denial = http.post(PATH, headers=OWNER, json={"references": [malformed]})
    assert denial.status_code == 422 and "private-marker" not in denial.text and "do-not-echo" not in denial.text
    assert http.post(PATH, headers=OWNER, content=json.dumps(
        {"references": [{**refs[0], "excerpt": "\ud800"}]})).status_code == 422
    assert http.post(PATH, headers=OWNER, json={"references": [{**refs[0], "excerpt": "é" * 33_000}]}).status_code == 413
    too_many_bytes = [{**ref, "excerpt": "x" * 50_000} for ref in refs]
    too_many_bytes.append({**refs[0], "task_id": "other", "excerpt": "x" * 50_000})
    assert http.post(PATH, headers=OWNER, json={"references": too_many_bytes}).status_code == 413
    with kanban_scope(KanbanContext(home, "owner", can_mutate=True)):
        for board, ref in zip(("north", "south"), refs):
            with kb.connect(board=board) as conn:
                whole = "x" * 50_000 + ref["excerpt"]
                conn.execute("UPDATE tasks SET result=? WHERE id=?", (whole, ref["task_id"]))
                conn.commit()
                ref.update(excerpt=whole, source="result", sha256=hashlib.sha256(whole.encode()).hexdigest())
    assert http.post(PATH, headers=OWNER, json={"references": refs}).status_code == 413


def test_preview_requires_actual_owner_even_with_owner_cookie_and_guest_header(boards, monkeypatch):
    _orch, _home, refs, http = boards
    from agents import web
    from agents.core.security import browser_session

    async def owner_session(_request):
        return browser_session.OK

    monkeypatch.setattr(web, "_owner_session_async", owner_session)
    assert http.post(PATH, headers={"X-User-Token": "guest-secret", "Cookie": "nerva_session=owner"},
                     json={"references": refs}).status_code == 403
    assert http.post(PATH, headers=OWNER, json={"references": refs}).status_code == 200
