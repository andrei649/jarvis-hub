"""H542/H544/H545 — editor sessions that outlive one ``nerva acp`` process.

``session/list``, ``session/load`` (with transcript replay), ``session/resume`` and
``session/fork`` over the real pipes against the fake hub of ``test_g11_acp``; the hub
side (the durable index, the same-folder rule, a fork that stays an editor conversation)
against a real MemoryManager/CheckpointManager; prompt usage; Windows-to-WSL paths;
``nerva acp --version``.
"""

from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from agents.core.acp import render
from agents.core.acp.jsonrpc import RpcError
from agents.core.acp.paths import AcpPathError, confine, session_root, translate
from agents.core.acp.server import BackendRefused
from tests.test_g11_acp import Editor, FakeBackend, _wire


class SessionsBackend(FakeBackend):
    """The fake hub, plus the earlier conversations an editor opened."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loads: list[tuple] = []
        self.listed: list[tuple] = []
        self.usage = None
        self.history = [{"role": "user", "content": "fix the bug\x1b[31m"},
                        {"role": "assistant", "content": "Done: see a.py"}]

    async def open_session(self, cwd, *, load=None, fork=None):
        self.loads.append((cwd, load, fork))
        if load == "acp_refused":
            raise BackendRefused(409, "cwd_mismatch")
        if load is not None:
            return load
        if fork is not None:
            return "session_" + "f" * 32
        return await super().open_session(cwd)

    async def list_sessions(self, cwd, cursor):
        self.listed.append((cwd, cursor))
        return {"sessions": [{"session_id": "acp_" + "1" * 24, "cwd": cwd or "/x", "created": "2026-11-17T10:00:00+00:00",
                              "parent": None, "live": False},
                             {"session_id": "session_" + "2" * 32, "cwd": cwd or "/x",
                              "created": "2026-11-17T09:00:00+00:00", "parent": "acp_" + "1" * 24},
                             "junk"],
                "next_cursor": "50"}

    async def transcript(self, session_id):
        return list(self.history)

    async def stream_turn(self, session_id, message, on_event, cancel, *, attachments=None):
        end = await super().stream_turn(session_id, message, on_event, cancel, attachments=attachments)
        if end is not None and self.usage is not None:
            end["usage"] = self.usage
        return end


async def _initialize(editor):
    return await editor.conn.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})


async def test_load_replays_the_transcript_and_resume_does_not(tmp_path):
    backend, editor = SessionsBackend(), Editor()
    server, close = await _wire(backend, editor)
    try:
        await _initialize(editor)
        sid = "acp_" + "a" * 24
        assert await editor.conn.request("session/load", {"sessionId": sid, "cwd": str(tmp_path),
                                                          "mcpServers": []}) == {}
        assert backend.loads[-1] == (str(tmp_path.resolve()), sid, None)
        users = editor.kinds("user_message_chunk")
        agents = [u for u in editor.kinds("agent_message_chunk") if u["content"]["text"] == "Done: see a.py"]
        assert [u["content"]["text"] for u in users] == ["fix the bug[31m"]   # control characters gone
        assert agents
        with pytest.raises(RpcError):                      # already open in this editor
            await editor.conn.request("session/load", {"sessionId": sid, "cwd": str(tmp_path)})
        before = len(editor.updates)
        other = "acp_" + "b" * 24
        assert await editor.conn.request("session/resume", {"sessionId": other, "cwd": str(tmp_path)}) == {}
        assert not [u for u in editor.updates[before:] if u.get("sessionUpdate") == "user_message_chunk"]
        result = await editor.conn.request("session/prompt", {"sessionId": other, "prompt": [
            {"type": "text", "text": "go on"}]})
        assert result["stopReason"] == "end_turn" and backend.turn_sessions[-1] == other
        assert set(server.sessions) == {sid, other}
    finally:
        await close()
    assert set(backend.closed) == {sid, "acp_" + "b" * 24}       # both released with the editor


async def test_fork_returns_the_new_conversation_and_the_hub_refusal_is_relayed(tmp_path):
    backend, editor = SessionsBackend(), Editor()
    _server, close = await _wire(backend, editor)
    try:
        await _initialize(editor)
        forked = await editor.conn.request("session/fork", {"sessionId": "acp_" + "c" * 24, "cwd": str(tmp_path)})
        assert forked == {"sessionId": "session_" + "f" * 32}
        assert backend.loads[-1][2] == "acp_" + "c" * 24
        with pytest.raises(RpcError) as refused:
            await editor.conn.request("session/load", {"sessionId": "acp_refused", "cwd": str(tmp_path)})
        assert "409" in str(refused.value.message)
        for bad in ({"cwd": str(tmp_path)}, {"sessionId": "../x", "cwd": str(tmp_path)},
                    {"sessionId": "acp_" + "d" * 24, "cwd": "relative"}):
            with pytest.raises(RpcError):
                await editor.conn.request("session/load", bad)
        for method in ("session/set_mode", "session/set_config_option", "session/set_model"):
            with pytest.raises(RpcError):
                await editor.conn.request(method, {"sessionId": "x"})
    finally:
        await close()


async def test_list_maps_the_hub_page_and_validates_the_cursor(tmp_path):
    backend, editor = SessionsBackend(), Editor()
    _server, close = await _wire(backend, editor)
    try:
        await _initialize(editor)
        page = await editor.conn.request("session/list", {"cwd": str(tmp_path)})
        assert page["nextCursor"] == "50" and len(page["sessions"]) == 2
        assert page["sessions"][0] == {"sessionId": "acp_" + "1" * 24, "cwd": str(tmp_path.resolve()),
                                       "updatedAt": "2026-11-17T10:00:00+00:00"}
        assert page["sessions"][1]["title"].startswith("fork of acp_")
        await editor.conn.request("session/list", {"cursor": "50"})
        assert backend.listed == [(str(tmp_path.resolve()), None), (None, "50")]
        with pytest.raises(RpcError):
            await editor.conn.request("session/list", {"cursor": "-1"})
    finally:
        await close()


async def test_mcp_servers_on_load_wait_for_the_owner_like_on_new(tmp_path):
    backend, editor = SessionsBackend(), Editor(answer=lambda p: "skip")
    _server, close = await _wire(backend, editor)
    try:
        await _initialize(editor)
        sid = "acp_" + "e" * 24
        await editor.conn.request("session/resume", {"sessionId": sid, "cwd": str(tmp_path), "mcpServers": [
            {"name": "docs", "command": "docs-server", "args": [], "env": []}]})
        assert backend.mcp == []                                   # nothing started on resume
        await editor.conn.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "hi"}]})
        assert editor.permissions and backend.mcp == []            # asked, declined, never registered
        with pytest.raises(RpcError):
            await editor.conn.request("session/load", {"sessionId": "acp_" + "9" * 24, "cwd": str(tmp_path),
                                                       "mcpServers": [{"name": "x", "command": "a", "type": "http"}]})
    finally:
        await close()


async def test_prompt_reports_measured_usage_only(tmp_path):
    backend, editor = SessionsBackend(), Editor()
    _server, close = await _wire(backend, editor)
    try:
        await _initialize(editor)
        sid = (await editor.conn.request("session/new", {"cwd": str(tmp_path)}))["sessionId"]
        backend.usage = {"input_tokens": 120, "output_tokens": 30, "model": "m", "estimated_cost_usd": 0.1}
        result = await editor.conn.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "a"}]})
        assert result["usage"] == {"inputTokens": 120, "outputTokens": 30, "totalTokens": 150}
        backend.usage = {"input_tokens": None, "output_tokens": None, "usage_basis": "unknown"}
        result = await editor.conn.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "b"}]})
        assert "usage" not in result
    finally:
        await close()
    assert render.prompt_usage({"input_tokens": True, "output_tokens": 1}) is None
    assert render.prompt_usage({"input_tokens": -1, "output_tokens": 1}) is None


# ── the hub side ─────────────────────────────────────────────────────────────


async def _hub(tmp_path, monkeypatch):
    from agents.core import app_state
    from agents.core.acp import sessions as acp_sessions
    from agents.core.checkpoint import CheckpointManager
    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.routers import acp as acp_router

    acp_sessions._reset_for_tests()
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "mem")
    roots = tmp_path / "roots"
    (roots / "project").mkdir(parents=True)
    (roots / "other").mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(roots))
    cp = CheckpointManager(str(tmp_path / "cp.db"))
    cp.initialize()
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    await memory.new_session("hud_session")

    @asynccontextmanager
    async def lease(_sid):
        yield True

    orch = SimpleNamespace(memory=memory, checkpoints=cp, mcp=SimpleNamespace(servers={}), turn_lease=lease)
    monkeypatch.setattr(app_state, "get_orch", lambda: orch)
    monkeypatch.setattr(acp_router, "get_orch", lambda: orch)
    return orch, roots, acp_router, acp_sessions


async def test_router_load_list_and_fork_keep_the_folder_binding(tmp_path, monkeypatch):
    from agents.core.session_continuation import ContinuationRefused, prepare_session

    orch, roots, router, acp_sessions = await _hub(tmp_path, monkeypatch)
    project, other = roots / "project", roots / "other"
    body = router.AcpSessionBody
    try:
        sid = json.loads((await router.acp_open_session(body(cwd=str(project)))).body)["session_id"]
        await prepare_session(orch, sid)
        await orch.memory.add_turn(sid, "user", "fix the bug")
        await orch.memory.add_turn(sid, "assistant", "fixed")
        assert acp_sessions.index_path().stat().st_mode & 0o077 == 0     # owner-only index

        held = await router.acp_open_session(body(cwd=str(project), load=sid))
        assert held.status_code == 409 and json.loads(held.body)["error"] == "session_in_use"

        acp_sessions._reset_for_tests()                                  # a hub restart
        orch.memory.conversation.sessions.pop(sid, None)
        with pytest.raises(ContinuationRefused):
            await prepare_session(orch, sid)                             # unbound: refused
        wrong = await router.acp_open_session(body(cwd=str(other), load=sid))
        assert wrong.status_code == 409 and json.loads(wrong.body)["error"] == "cwd_mismatch"
        unknown = await router.acp_open_session(body(cwd=str(project), load="acp_" + "0" * 24))
        assert unknown.status_code == 404
        hud = await router.acp_open_session(body(cwd=str(project), load="hud_session"))
        assert hud.status_code == 404                                    # never a HUD conversation
        both = await router.acp_open_session(body(cwd=str(project), load=sid, fork=sid))
        assert both.status_code == 400

        loaded = json.loads((await router.acp_open_session(body(cwd=str(project), load=sid))).body)
        assert loaded["session_id"] == sid and loaded["loaded"] is True
        await prepare_session(orch, sid)
        assert [t["content"] for t in await orch.memory.get_history(sid)] == ["fix the bug", "fixed"]
        assert acp_sessions.cwd_for(sid) == project.resolve()
        assert orch.memory.conversation.current_session_id == "hud_session"

        forked = json.loads((await router.acp_open_session(body(cwd=str(project), fork=sid))).body)
        child = forked["session_id"]
        assert child != sid and not child.startswith(acp_sessions.PREFIX) and forked["forked_from"] == sid
        await prepare_session(orch, child)
        assert [t["content"] for t in await orch.memory.get_history(child)] == ["fix the bug", "fixed"]
        assert acp_sessions.cwd_for(child) == project.resolve()

        listed = json.loads((await router.acp_list_sessions(cwd=str(project))).body)
        assert [r["session_id"] for r in listed["sessions"]][:2] in ([child, sid], [sid, child])
        assert {r["session_id"]: r["parent"] for r in listed["sessions"]}[child] == sid
        assert all(r["live"] for r in listed["sessions"]) and listed["next_cursor"] is None
        assert json.loads((await router.acp_list_sessions(cwd=str(other))).body)["sessions"] == []
        assert (await router.acp_list_sessions(cursor="x")).status_code == 400
        assert (await router.acp_list_sessions(cwd=str(tmp_path))).status_code == 409

        # The fork is an editor conversation for good: after a restart it is refused
        # (never run unbound in the HUD's scope) until an editor loads it again.
        acp_sessions._reset_for_tests()
        orch.memory.conversation.sessions.pop(child, None)
        with pytest.raises(ContinuationRefused) as refused:
            await prepare_session(orch, child)
        assert refused.value.status == 410
    finally:
        orch.checkpoints.close()
        acp_sessions._reset_for_tests()


async def test_router_loads_an_empty_editor_conversation_after_a_restart(tmp_path, monkeypatch):
    from agents.core.session_continuation import prepare_session

    orch, roots, router, acp_sessions = await _hub(tmp_path, monkeypatch)
    project = roots / "project"
    try:
        sid = json.loads((await router.acp_open_session(router.AcpSessionBody(cwd=str(project)))).body)["session_id"]
        acp_sessions._reset_for_tests()
        orch.memory.conversation.sessions.pop(sid, None)
        reply = await router.acp_open_session(router.AcpSessionBody(cwd=str(project), load=sid))
        assert reply.status_code == 200
        await prepare_session(orch, sid)
        assert orch.memory.conversation.current_session_id == "hud_session"
    finally:
        orch.checkpoints.close()
        acp_sessions._reset_for_tests()


def test_index_bounds_and_a_corrupt_index_is_not_trusted(tmp_path, monkeypatch):
    from agents.core.acp import sessions as acp_sessions
    from agents.core.memory import persistence

    acp_sessions._reset_for_tests()
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(acp_sessions, "MAX_INDEX", 3)
    try:
        for i in range(5):
            acp_sessions.remember(f"acp_{i:024x}", tmp_path)
        rows, following = acp_sessions.listing()
        assert len(rows) == 3 and following is None
        acp_sessions.index_path().write_text('{"sessions": {"x": {"cwd": 1}}}')
        acp_sessions._reset_for_tests()
        assert acp_sessions.listing() == ([], None)
        assert acp_sessions.known("x") is None
        acp_sessions.index_path().write_text("not json")
        acp_sessions._reset_for_tests()
        assert acp_sessions.is_editor_conversation("session_abc") is False
        assert acp_sessions.is_editor_conversation("acp_" + "1" * 24) is True    # the prefix rule stays
    finally:
        acp_sessions._reset_for_tests()


# ── Windows → WSL paths ──────────────────────────────────────────────────────


def test_windows_paths_translate_only_under_wsl_and_stay_confined(tmp_path, monkeypatch):
    from agents.core.acp import paths

    assert translate("C:\\src\\app", wsl=True) == "/mnt/c/src/app"
    assert translate("/D:/src/app", wsl=True) == "/mnt/d/src/app"            # a file:///D:/… URI's path
    assert translate("\\\\wsl$\\Ubuntu\\home\\me", wsl=True) == "/home/me"
    assert translate("//wsl.localhost/Ubuntu/home/me", wsl=True) == "/home/me"
    assert translate("C:\\src", wsl=False) == "C:\\src"
    assert translate("/home/me", wsl=True) == "/home/me"
    monkeypatch.setattr(paths, "translate", lambda raw, wsl=None: translate(raw, wsl=True))
    share = "\\\\wsl$\\Ubuntu" + str(tmp_path).replace("/", "\\")
    assert session_root(share) == tmp_path.resolve()
    assert confine(tmp_path, share + "\\a.txt") == tmp_path.resolve() / "a.txt"
    with pytest.raises(AcpPathError):
        confine(tmp_path, "C:\\Windows\\system32")                        # translated, then confined
    with pytest.raises(AcpPathError):
        confine(tmp_path, share + "\\..\\..\\etc\\passwd")


def test_nerva_acp_version_prints_and_exits():
    from agents.cli import nerva

    out, err = io.StringIO(), io.StringIO()
    code = nerva.main(["acp", "--version"], context=nerva.Context(environ={}, out=out, err=err))
    assert code == 0 and out.getvalue().startswith("nerva acp ") and "Agent Client Protocol 1" in out.getvalue()
