"""Synthetic Second Brain sources only; never touch an owner's data files."""
import asyncio
import http.server
import json
import math
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from agents.core import trajectory
from agents.core.llm.base import OllamaBackend
from agents.core.llm.physical_local import physical_local_scope
from agents.core.memory import second_brain, turn_tools
from agents.core.orchestrator import Orchestrator
from agents.core.tool_result_store import threshold_for


@pytest.fixture(autouse=True)
def isolate_private_turn_marker():
    turn_tools.end()
    yield
    turn_tools.end()


def test_private_sources_refuse_before_open(monkeypatch, tmp_path):
    monkeypatch.setenv("NERVA_SECOND_BRAIN_MCP_SCRIPT", str(tmp_path / "memory_mcp_server.py"))
    monkeypatch.setenv("NERVA_VAULT_FTS_DB", str(tmp_path / "private.sqlite"))
    def deny():
        return False
    assert second_brain.call_mcp("search_memory_and_connections", {"question": "test"}, local_only=deny)["reason"] == "strict_local_required"
    assert second_brain.search_fts("test", source="vault", local_only=deny)["reason"] == "strict_local_required"
    assert second_brain.search_vault("test", local_only=deny)["reason"] == "strict_local_required"
    assert second_brain.recall_context("test", local_only=deny) == ""


def test_fixed_mcp_call_uses_restricted_child_env(monkeypatch, tmp_path):
    script = tmp_path / "memory_mcp_server.py"
    script.write_text(
        "import json,os,sys\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line)\n"
        " if r.get('id') == 2:\n"
        "  print(json.dumps({'id':2,'result':{'content':[{'type':'text','text':json.dumps({'name':r['params']['name'],'question':r['params']['arguments']['question'],'leaked':os.getenv('NERVA_TEST_SECRET')})}]}}),flush=True)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NERVA_SECOND_BRAIN_MCP_SCRIPT", str(script))
    monkeypatch.setenv("NERVA_TEST_SECRET", "must-not-pass")
    result = second_brain.call_mcp("search_memory_and_connections", {"question": "synthetic"}, local_only=lambda: True)
    assert result["ok"] is True
    assert json.loads(result["text"]) == {
        "name": "search_memory_and_connections", "question": "synthetic", "leaked": None}
    assert second_brain.call_mcp("delete_everything", {}, local_only=lambda: True)["reason"] == "source_unavailable"


def test_unverified_vault_fts_refused_and_ai_kb_read_only(monkeypatch, tmp_path):
    db = tmp_path / "knowledge.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE kb_docs(doc_id INTEGER PRIMARY KEY, source TEXT, title TEXT, content TEXT)")
        conn.execute("CREATE VIRTUAL TABLE kb_docs_fts USING fts5(content, content='kb_docs', content_rowid='doc_id')")
        conn.execute("INSERT INTO kb_docs VALUES(1,'synthetic','Example','Synthetic project ready to finish')")
        conn.execute("INSERT INTO kb_docs_fts(kb_docs_fts) VALUES('rebuild')")
    monkeypatch.setenv("NERVA_VAULT_FTS_DB", str(db))
    monkeypatch.setenv("NERVA_AI_KB_FTS_DB", str(db))
    assert second_brain.search_fts("project", source="vault", local_only=lambda: True)["reason"] == "unverified_source"
    result = second_brain.search_fts("project", source="ai_kb", local_only=lambda: True)
    assert result["ok"] is True
    assert len(result["hits"]) == 1
    monkeypatch.setattr(second_brain, "search_vault", lambda *a, **kw: {
        "ok": True, "hits": [{"path": "Projects/example.md", "text": "Synthetic project ready to finish"}]})
    block = second_brain.recall_context("project", local_only=lambda: True)
    assert "RETRIEVED MEMORY" in block
    assert "Synthetic" in block


def test_project_reply_uses_structured_priorities(monkeypatch):
    from agents.core.routers import jarvis_os

    class Engine:
        @staticmethod
        def project_priorities(cfg, query, limit=4):
            return [{"title": "Example", "nextStep": "Complete the draft"}]

        @staticmethod
        def structured_brief(cfg, kind, limit=5):
            if kind == "deadlines":
                return [{"title": "Example", "dueDate": "2026-12-01", "dueText": "Send draft"}]
            return [{"title": "Example", "role": kind}]

    monkeypatch.setattr(jarvis_os, "_engine", lambda: Engine())
    monkeypatch.setattr(jarvis_os, "_config", lambda engine: {"projectIndex": True,
                                                             "vaultMapPath": "Map/index.json"})
    monkeypatch.setattr(jarvis_os, "_vault_available", lambda cfg: True)
    assert "Example: Complete the draft" in second_brain.project_reply("ce proiecte sunt de terminat acum?")
    assert "2026-12-01" in second_brain.project_reply("ce termene am in 14 zile?")
    assert "Example" in second_brain.project_reply("termene")
    assert "Example" in second_brain.project_reply("Azi")
    assert "Example" in second_brain.project_reply("ce decizii avem?")
    assert "Example" in second_brain.project_reply("cum este organizat vaultul?")
    assert second_brain.project_reply("Hello") is None
    assert second_brain.project_reply("help me make a decision about lunch") is None
    assert second_brain.project_reply("explică ce înseamnă o decizie") is None
    assert second_brain.project_reply("what will the weather be in 14 zile?") is None
    assert second_brain.project_reply("explain what a deadline is") is None
    assert second_brain.project_reply("help me prioritize project ideas") is None
    monkeypatch.setattr(jarvis_os, "_config", lambda engine: {"projectIndex": False})
    assert second_brain.project_reply("ce proiecte sunt de terminat acum?") is None


def test_direct_local_project_metadata_is_ephemeral(monkeypatch):
    from agents.core import orchestrator
    from agents.core.routers import jarvis_os

    seen = []

    class Engine:
        @staticmethod
        def project_priorities(cfg, query, limit=4):
            seen.append(cfg.get("localProjectMetadata") is True)
            return ([{"id": "prj-001", "title": "Synthetic", "stage": "Active",
                     "nextStep": "Finish the draft"}] if cfg.get("localProjectMetadata") else [])

    class Memory:
        async def add_turn(self, *args, **kwargs):
            raise AssertionError("local metadata reply must not be persisted")

    monkeypatch.setattr(jarvis_os, "_engine", lambda: Engine())
    monkeypatch.setattr(jarvis_os, "_config", lambda engine: {"projectIndex": True})
    monkeypatch.setattr(jarvis_os, "_vault_available", lambda cfg: True)
    monkeypatch.setattr(orchestrator, "current_principal", lambda: SimpleNamespace(admin=True))
    fake = SimpleNamespace(memory=Memory(), session_id="synthetic-session")
    with second_brain.local_project_view(True):
        reply = asyncio.run(Orchestrator._second_brain_project_reply(
            fake, "ce proiecte sunt de terminat acum?", "web", None))
    assert "prj-001 · Synthetic (Active): Finish the draft" in reply
    assert seen == [True]
    assert second_brain.local_project_view_allowed() is False


def test_tools_hidden_and_rechecked_on_cloud(monkeypatch):
    class Server:
        def __init__(self):
            self.tools = {}

        def register_tool(self, name, handler, **kwargs):
            self.tools[name] = (handler, kwargs)

    allowed = False
    server = Server()
    second_brain.register_second_brain_tools(server, local_only=lambda: allowed)
    assert len(server.tools) == 3
    for handler, options in server.tools.values():
        assert options["visible"]() is False
        assert asyncio.run(handler({"query": "test"}))["reason"] == "strict_local_required"
    allowed = True
    assert all(options["visible"]() for _, options in server.tools.values())


def test_direct_rpc_without_bound_local_model_refuses(monkeypatch):
    class Server:
        def __init__(self):
            self.tools = {}

        def register_tool(self, name, handler, **kwargs):
            self.tools[name] = handler

    server = Server()
    second_brain.register_second_brain_tools(server, local_only=second_brain.tool_backend_local,
                                             visible=lambda: True)
    assert all(asyncio.run(handler({"query": "secret"}))["reason"] == "strict_local_required"
               for handler in server.tools.values())


def test_private_turn_skips_trajectory_and_spill(monkeypatch):
    saved = []
    monkeypatch.setenv("NERVA_SAVE_TRAJECTORIES", "1")
    monkeypatch.setattr(trajectory, "save", lambda *args: saved.append(args))
    turn_tools.begin()
    turn_tools.note({"event": "tool_result", "tool": "search_second_brain"})
    turn_tools.mark_private()
    with trajectory.capture(agent_id="frigga", model="local", system="private", prompt="private") as recorder:
        assert recorder is None
    turn_tools.begin()
    with trajectory.capture(agent_id="frigga", model="local", system="private", prompt="private") as recorder:
        assert recorder is not None
        trajectory.suppress_current()
        recorder.reply = "private answer"
    assert not saved
    assert math.isinf(threshold_for("search_private_memory", overrides={"search_private_memory": 1}))


def test_bound_backend_must_be_loopback_and_inside_physical_scope():
    backend = object.__new__(OllamaBackend)
    backend.base_url = "http://127.0.0.1:11434"
    token = second_brain.bind_tool_backend("frigga", backend)
    try:
        assert second_brain.tool_backend_local() is False
        with physical_local_scope():
            assert second_brain.tool_backend_local() is True
    finally:
        second_brain.reset_tool_backend(token)
    backend.base_url = "http://remote.invalid:11434"
    assert second_brain.strict_loopback_backend("frigga", backend) is False
    assert second_brain.strict_loopback_backend("jarvis", backend) is False


def test_private_answer_skips_shared_persistence():
    turn_tools.begin()
    turn_tools.note({"event": "tool_result", "tool": "search_private_memory"})
    turn_tools.mark_private()
    assert asyncio.run(Orchestrator._complete_llm_turn(
        object(), text="query", intent=None, plugin_data={}, responses={"frigga": "private"},
        synthesized="private", responder_id="frigga", route_name="local", channel="web",
        action_taken="test", t_classify=0, t_route=0, t_plugin=0, t_synthesize=0,
    )) is None


def test_private_pin_survives_capped_names_and_no_active_turn_refuses(monkeypatch):
    class Server:
        def __init__(self):
            self.tools = {}

        def register_tool(self, name, handler, **kwargs):
            self.tools[name] = handler

    server = Server()
    second_brain.register_second_brain_tools(server, local_only=lambda: True)
    called = []
    monkeypatch.setattr(second_brain, "search_vault", lambda *a, **kw: called.append(True) or {
        "ok": True, "hits": [{"text": "synthetic private payload"}]})
    handler = server.tools["search_second_brain"]
    assert asyncio.run(handler({"query": "synthetic"}))["reason"] == "strict_local_required"
    assert not called

    async def exercise():
        turn_tools.begin()
        for index in range(turn_tools.MAX_NOTED):
            turn_tools.note({"event": "tool_result", "tool": f"ordinary_{index}"})
        assert len(turn_tools.collected()) == turn_tools.MAX_NOTED
        assert (await asyncio.create_task(handler({"query": "synthetic"})))["ok"] is True
        assert called == [True]
        assert "search_second_brain" not in turn_tools.collected()
        assert second_brain.private_context_active() is True
        with trajectory.capture(agent_id="frigga", model="local", system="synthetic", prompt="synthetic") as recorder:
            assert recorder is None
        assert await Orchestrator._complete_llm_turn(
            object(), text="query", intent=None, plugin_data={}, responses={"frigga": "private"},
            synthesized="private", responder_id="frigga", route_name="local", channel="web",
            action_taken="test", t_classify=0, t_route=0, t_plugin=0, t_synthesize=0,
        ) is None
        turn_tools.begin()
        assert await asyncio.to_thread(turn_tools.mark_private) is True
        assert second_brain.private_context_active() is True

    asyncio.run(exercise())


def test_copilot_url_rejects_remote_or_redirectable_target(monkeypatch):
    for value in ("https://127.0.0.1:8765", "http://example.com:8765", "http://127.0.0.1:8765@remote.test:8765",
                  "http://127.0.0.1:8765/elsewhere"):
        monkeypatch.setenv("NERVA_MEMORY_COPILOT_URL", value)
        assert second_brain._copilot_url() is None
    monkeypatch.setenv("NERVA_MEMORY_COPILOT_URL", "http://127.0.0.1:8765")
    assert second_brain._copilot_url() == "http://127.0.0.1:8765"


def test_health_requires_expected_loopback_service(monkeypatch):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            data = json.dumps({"ok": True, "hardened": True, "service": "synthetic-service"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("NERVA_MEMORY_COPILOT_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("NERVA_MEMORY_COPILOT_SERVICE", "synthetic-service")
        assert second_brain.health()["connected"] is True
        monkeypatch.setenv("NERVA_MEMORY_COPILOT_SERVICE", "other-service")
        assert second_brain.health()["connected"] is False
    finally:
        server.shutdown()
        server.server_close()
