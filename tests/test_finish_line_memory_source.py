"""A curated fact saved from a reviewed native chat turn keeps its exact source."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from agents.core.checkpoint import CheckpointManager
from agents.core.cognition.memory import CoreMemory, CoreMemoryDrift
from agents.core.memory import conversation, persistence
from agents.core.memory.manager import MemoryManager
from agents.core.orchestrator import Orchestrator
from agents.core.session_transcript import read_transcript


class _Audit:
    def record(self, **_kwargs):
        pass


def test_source_references_require_admin_even_when_user_can_read_entries(monkeypatch):
    """Exercise the real route guards before any memory store is read."""
    from agents import web
    from agents.core.routers import dashboard
    from agents.core.routers._deps import user_guard

    monkeypatch.setattr(web, "USER_TOKEN", "synthetic-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "synthetic-owner")
    monkeypatch.setattr(web, "get_token_store", lambda: SimpleNamespace(
        verify=lambda _token: None, env_revoked=lambda _scope: False))
    monkeypatch.setattr(dashboard, "get_orch", lambda: None)
    monkeypatch.delitem(web.app.dependency_overrides, user_guard, raising=False)
    client = TestClient(web.app, base_url="http://127.0.0.1")
    for path in ("/api/dashboard/today/entries", "/api/dashboard/today/entries/memory:synthetic"):
        user = {"x-user-token": "synthetic-user"}
        assert client.get(path, headers=user).status_code == 503
        assert client.get(path + "?references=true", headers=user).status_code == 401
        assert client.get(path + "?references=true", headers={"x-admin-token": "synthetic-owner"}).status_code == 503


@pytest.mark.asyncio
async def test_chat_source_survives_reload_without_lending_it_to_manual_or_replaced_facts(tmp_path, monkeypatch):
    from agents.core import memory_tool, safe_mode
    from agents.core.routers import dashboard

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory_tool, "UNDO", memory_tool.UndoStore(tmp_path / "undo.json"))
    monkeypatch.setattr(safe_mode, "enabled", lambda: False)
    monkeypatch.setattr(dashboard, "_learning_write_denied", lambda *_args: None)
    monkeypatch.setattr(dashboard, "_store_rows", lambda: _empty_rows())
    async def owner_only(req):
        if req is None or req.headers.get("x-admin-token") != "synthetic-owner":
            raise HTTPException(status_code=401, detail="admin token required")
    monkeypatch.setattr(dashboard, "admin_guard", owner_only)
    owner_req = Request({"type": "http", "method": "GET", "path": "/api/dashboard/today/entries",
                         "headers": [(b"x-admin-token", b"synthetic-owner")],
                         "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 1), "scheme": "http"})

    cp = CheckpointManager(str(tmp_path / "checkpoints.db"))
    cp.initialize()
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    orch = Orchestrator.__new__(Orchestrator)
    orch.checkpoints, orch.memory = cp, memory
    orch._session_id_default = "default"
    orch._turn_lease_max_wait = 0.01
    orch.session_trust = lambda _sid: "clean"
    orch.intent_log = _Audit()
    orch.get_setting = lambda _key, default=None: default
    living = SimpleNamespace(core=CoreMemory(path=tmp_path / "core.json"),
                             user_core=CoreMemory(path=tmp_path / "user.json"))
    orch.cognition = SimpleNamespace(sub_enabled=lambda key: key == "memory_enabled",
                                     module=lambda _key: living)
    monkeypatch.setattr(dashboard, "get_orch", lambda: orch)
    try:
        cp.create_session_record("source-chat")
        await memory.new_session("source-chat")
        await memory.add_turn("source-chat", "user", "My synthetic project color is cobalt")
        await memory.add_turn("source-chat", "assistant", "I noted cobalt", agent_id="jarvis")
        row = json.loads(await read_transcript(orch, "source-chat", references=True))["turns"][0]
        source = {"session_id": "source-chat", "turn": 0,
                  "revision": row["reference_revision"], "excerpt": "project color is cobalt"}
        expected = {"session_id": "source-chat", "turn": 0,
                    "revision": source["revision"], "role": "user"}
        body = dashboard.TimelineEntryCreate(store="memory", value="Project color is cobalt", source=source)
        saved = await dashboard.dashboard_today_entry_create(body)
        assert json.loads(saved.body)["entry"]["source"] == expected

        living.core = CoreMemory(path=tmp_path / "core.json")
        default = await dashboard.dashboard_today_entries(store="memory", limit=1000)
        assert "source" not in json.loads(default.body)["entries"][0]
        with pytest.raises(HTTPException) as refused:
            await dashboard.dashboard_today_entries(store="memory", limit=1000, references=True)
        assert refused.value.status_code == 401
        listed = await dashboard.dashboard_today_entries(store="memory", limit=1000,
                                                         references=True, req=owner_req)
        entries = json.loads(listed.body)["entries"]
        assert len(entries) == 1 and entries[0]["source"] == expected
        first_saved_at = entries[0]["ts"]
        detail = await dashboard.dashboard_today_entry(entries[0]["entry_id"], references=True, req=owner_req)
        assert json.loads(detail.body)["entry"]["source"] == expected
        default_detail = await dashboard.dashboard_today_entry(entries[0]["entry_id"])
        assert "source" not in json.loads(default_detail.body)["entry"]
        assert "excerpt" not in json.dumps((tmp_path / "core.json").read_text())

        manual = await dashboard.dashboard_today_entry_create(
            dashboard.TimelineEntryCreate(store="memory", value="Manual synthetic fact"))
        manual_entry = json.loads(manual.body)["entry"]
        assert "source" not in manual_entry
        second_turn = json.loads(await read_transcript(orch, "source-chat", references=True))["turns"][1]
        duplicate = await dashboard.dashboard_today_entry_create(dashboard.TimelineEntryCreate(
            store="memory", value="Project color is cobalt",
            source={"session_id": "source-chat", "turn": 1,
                    "revision": second_turn["reference_revision"], "excerpt": "noted cobalt"}))
        assert json.loads(duplicate.body)["changed"] is False
        assert json.loads(duplicate.body)["entry"]["source"] == expected
        after_manual = await dashboard.dashboard_today_entries(store="memory", limit=1000,
                                                               references=True, req=owner_req)
        assert next(item for item in json.loads(after_manual.body)["entries"]
                    if item["value"] == "Project color is cobalt")["ts"] == first_saved_at

        edited = await dashboard.dashboard_today_entry_edit(
            entries[0]["entry_id"], dashboard.TimelineEntryEdit(value="Project color is amber"))
        edited_body = json.loads(edited.body)
        assert edited_body["changed"] is True
        assert "source" not in edited_body["entry"]
        assert living.core.source_map() == {}
        memory_tool.undo(edited_body["undo_ref"], living=living, audit=orch.intent_log)
        assert living.core.source_for("Project color is cobalt") == expected

        forged = await dashboard.dashboard_today_entry_create(
            dashboard.TimelineEntryCreate(store="memory", value="Forged fact",
                                          source={**source, "revision": "0" * 64}))
        assert forged.status_code == 409
        assert "Forged fact" not in living.core.list()

        removed = await dashboard.dashboard_today_entry_delete(entries[0]["entry_id"])
        assert json.loads(removed.body)["deleted"] == entries[0]["entry_id"]
        replacement = await dashboard.dashboard_today_entry_create(
            dashboard.TimelineEntryCreate(store="memory", value="Project color is cobalt"))
        assert "source" not in json.loads(replacement.body)["entry"]
        living.core = CoreMemory(path=tmp_path / "core.json")
        listed = await dashboard.dashboard_today_entries(store="memory", limit=1000,
                                                         references=True, req=owner_req)
        assert all("source" not in entry for entry in json.loads(listed.body)["entries"])

        legacy_path = tmp_path / "legacy.json"
        legacy_path.write_text('{"facts":["Legacy synthetic fact"]}', encoding="utf-8")
        legacy = CoreMemory(path=legacy_path)
        assert legacy.list() == ["Legacy synthetic fact"]
        assert legacy.source_map() == {}
        living.core.clear()
        assert living.core.source_map() == {}
        assert CoreMemory(path=tmp_path / "core.json").source_map() == {}
    finally:
        cp.close()


async def _empty_rows():
    return []


def test_untrusted_ring_file_cannot_attest_a_forged_chat_source(tmp_path):
    fact = "Synthetic unverified fact"
    key = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:32]
    path = tmp_path / "hand-edited.json"
    path.write_text(json.dumps({"facts": [fact], "sources": {key: {
        "session_id": "source-chat", "turn": 0, "revision": "0" * 64, "role": "user"}}}),
        encoding="utf-8")
    ring = CoreMemory(path=path)
    assert ring.source_map() == {}
    with pytest.raises(CoreMemoryDrift):
        ring.put("Another fact")
