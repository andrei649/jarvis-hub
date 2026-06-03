"""Tests for H10.21 — Conversation Notes."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.notes import NotesStore, MAX_LEN


# ── store ────────────────────────────────────────────────────────────────────

def test_set_get_clear_persistence(tmp_path):
    p = tmp_path / "n.json"
    s = NotesStore(path=p)
    assert s.get("sess1") == ""
    s.set("sess1", "remember: be concise")
    assert NotesStore(path=p).get("sess1") == "remember: be concise"   # persisted
    assert s.clear("sess1") is True
    assert s.get("sess1") == "" and s.clear("sess1") is False


def test_length_capped(tmp_path):
    s = NotesStore(path=tmp_path / "n.json")
    saved = s.set("x", "a" * (MAX_LEN + 500))
    assert len(saved["content"]) == MAX_LEN


def test_context_for_renders_block_or_empty(tmp_path):
    s = NotesStore(path=tmp_path / "n.json")
    assert s.context_for("x") == ""                       # empty → no block
    s.set("x", "key facts")
    block = s.context_for("x")
    assert block.startswith("[Session notes]") and "key facts" in block and block.endswith("\n\n")


# ── endpoints + injection ────────────────────────────────────────────────────

def test_notes_endpoints_and_injection():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "notes", None) is None:
            return
        sid = getattr(web.orch, "session_id", "web")
        web.orch.notes.clear(sid)

        assert c.get("/api/notes").json()["content"] == ""
        put = c.put("/api/notes", json={"content": "always reply in French"})
        assert put.status_code == 200
        assert c.get("/api/notes").json()["content"] == "always reply in French"

        # injection: the note is prepended to the chat message
        captured = {}

        async def fake_handle(message, channel="web", agent_override=None):
            captured["msg"] = message
            return "ok"
        orig = web.orch.handle_input
        web.orch.handle_input = fake_handle
        try:
            r = c.post("/chat", json={"message": "hello"})
            assert r.status_code == 200
            assert "[Session notes]" in captured["msg"] and "always reply in French" in captured["msg"]
            assert captured["msg"].endswith("hello")
        finally:
            web.orch.handle_input = orig

        assert c.delete("/api/notes").json()["cleared"] is True


def test_rewrite_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "notes", None) is None:
            return
        sid = getattr(web.orch, "session_id", "web")
        web.orch.notes.clear(sid)
        # empty note → 400
        assert c.post("/api/notes/rewrite", json={}).status_code == 400
        web.orch.notes.set(sid, "msgy notes here")

        async def fake_handle(message, channel="web", agent_override=None):
            return "CLEAN NOTES"
        orig = web.orch.handle_input
        web.orch.handle_input = fake_handle
        try:
            r = c.post("/api/notes/rewrite", json={"save": True})
            assert r.status_code == 200 and r.json()["rewritten"] == "CLEAN NOTES"
            assert r.json()["saved"] is True
            assert web.orch.notes.get(sid) == "CLEAN NOTES"     # saved back
        finally:
            web.orch.handle_input = orig
        web.orch.notes.clear(sid)
