"""Tests for H10.20 — Chat Channels / Rooms."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.rooms import RoomStore


# ── CRUD + history ───────────────────────────────────────────────────────────

def test_create_get_list_delete(tmp_path):
    s = RoomStore(path=tmp_path / "r.json")
    room = s.create("Project X", "context here", agents=["gecko", "pepper"])
    rid = room["id"]
    assert "history" not in room                     # public view hides history
    assert s.get(rid)["name"] == "Project X"
    assert len(s.list()) == 1
    assert s.delete(rid) is True and s.get(rid) is None


def test_history_persists_and_caps(tmp_path):
    p = tmp_path / "r.json"
    s = RoomStore(path=p)
    rid = s.create("R")["id"]
    s.add_message(rid, "user", "hi")
    s.add_message(rid, "assistant", "hello", agent="jarvis")
    assert len(RoomStore(path=p).history(rid)) == 2   # persisted
    assert RoomStore(path=p).history(rid)[-1]["agent"] == "jarvis"


# ── @mention routing ─────────────────────────────────────────────────────────

def test_parse_mentions():
    assert RoomStore.parse_mentions("hey @gecko and @Pepper") == ["gecko", "pepper"]
    assert RoomStore.parse_mentions("no mentions") == []


def test_route_prefers_mention_in_roster(tmp_path):
    s = RoomStore(path=tmp_path / "r.json")
    rid = s.create("R", agents=["gecko", "pepper"], default_agent="jarvis")["id"]
    assert s.route(rid, "@gecko balance?") == "gecko"
    # mention not in roster → fall through to default
    assert s.route(rid, "@stranger hi") == "jarvis"
    assert s.route(rid, "no mention") == "jarvis"


def test_context_for(tmp_path):
    s = RoomStore(path=tmp_path / "r.json")
    rid = s.create("Ops", "deploy notes")["id"]
    assert s.context_for(rid).startswith("[Room: Ops]") and "deploy notes" in s.context_for(rid)
    rid2 = s.create("Empty")["id"]
    assert s.context_for(rid2) == ""


# ── endpoints ────────────────────────────────────────────────────────────────

def test_room_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "rooms", None) is None:
            return
        assert c.post("/api/rooms", json={}).status_code == 400
        created = c.post("/api/rooms", json={"name": "Test Room", "agents": ["jarvis"]})
        assert created.status_code == 200
        rid = created.json()["room"]["id"]
        assert c.get(f"/api/rooms/{rid}").json()["name"] == "Test Room"

        captured = {}
        async def fake_handle(message, channel="web", agent_override=None):
            captured["agent"] = agent_override
            captured["msg"] = message
            return "room reply"
        orig = web.orch.handle_input
        web.orch.handle_input = fake_handle
        try:
            r = c.post(f"/api/rooms/{rid}/message", json={"message": "@jarvis hello"})
            assert r.status_code == 200 and r.json()["reply"] == "room reply"
            assert r.json()["agent"] == "jarvis" and r.json()["mentioned"] == ["jarvis"]
        finally:
            web.orch.handle_input = orig

        assert len(c.get(f"/api/rooms/{rid}/history").json()["history"]) == 2
        assert c.delete(f"/api/rooms/{rid}").status_code == 200
        assert c.get(f"/api/rooms/{rid}").status_code == 404
