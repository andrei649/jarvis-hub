"""Scheduled operator exclusions reach the real interpreter/RPC bridge.

The existing test sandbox uses a real local subprocess with an isolation shim;
this proves nested tool policy, not Docker/WASM isolation.
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.autonomy.jobs import JobRunner, JobStore
from agents.core.code_tools import register_code_tools
from agents.core.tool_rpc import ToolRPCServer
from tests.test_code_tools import OWNER, _sandbox, _settings


@pytest.mark.asyncio
async def test_operator_disabled_tools_stay_unavailable_inside_scheduled_code(tmp_path, monkeypatch):
    policy_path = tmp_path / "settings.db"
    monkeypatch.setattr(settings_db, "DB_PATH", policy_path)
    with sqlite3.connect(policy_path) as conn:
        conn.executescript(settings_db.SCHEMA)
        for category, key, value in (
            ("llm", "platform_toolsets", {}),
            ("agents", "disabled_toolsets", ["files", "web"]),
            ("autonomy", "allow_agent_scheduling", False),
        ):
            conn.execute("INSERT INTO settings VALUES (?,?,?,?,?,?)",
                         (category, key, json.dumps(value), key, "json", "[]"))

    server, calls, envelopes = ToolRPCServer(), [], []

    def handler(name):
        async def run(args):
            calls.append(name)
            return {"value": "synthetic " + name}
        return run

    for name in ("echo", "time", "file_read", "file_list", "file_search",
                 "file_write", "file_delete", "web_search", "web_extract"):
        server.register_tool(name, handler(name), gated=False)
    sandbox = _sandbox(tmp_path / "sandbox")
    register_code_tools(server, sandbox=lambda: sandbox, settings=_settings(),
                        principal=lambda: OWNER, session_id=lambda: "h456-synthetic")
    code = (
        "import json\n"
        "print(json.dumps([jarvis_tool_call(name, {}) "
        "for name in ['file_read', 'web_search', 'echo']]))"
    )

    async def process_detailed(prompt, **kwargs):
        envelope = await server.handle({"tool": "execute_code", "args": {"code": code}})
        envelopes.append(envelope)
        return "synthetic completed result", None

    store = JobStore(tmp_path / "jobs.db")
    try:
        job = store.create(name="bounded code", schedule_text="every day at 9",
                           action={"type": "ask", "prompt": "synthetic", "deliver": False})
        runner = JobRunner(store, orch=SimpleNamespace(
            process_detailed=process_detailed, tool_rpc=server), scheduler=lambda: None)
        await runner._ask(job, job.action)
        outer = envelopes[0]
        assert outer["ok"] and outer["result"]["ok"], outer
        nested = json.loads(outer["result"]["stdout"])
        assert [reply.get("reason") for reply in nested[:2]] == ["tool_not_offered"] * 2
        assert nested[2]["ok"] is True
        assert calls == ["echo"]
        assert "file_read" not in outer["result"]["offered_tools"]
        assert "web_search" not in outer["result"]["offered_tools"]
        assert "execute_code" not in outer["result"]["offered_tools"]
    finally:
        store.close()
