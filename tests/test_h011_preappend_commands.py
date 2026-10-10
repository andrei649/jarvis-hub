"""Checkpoint commands address the current exchange without becoming a new one."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from agents.core.commands import ADMIN, CommandRegistry, Principal, SlashCommand
from agents.core.memory.conversation import ConversationMemory, Turn
from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal
from tests.h441_native_fixture import bind_native


@pytest.fixture
def context(monkeypatch):
    import agents.core.orchestrator as module

    token = module._active_session.set(module._SESSION_UNSET)
    shared = module._session_is_shared.set(None)
    conversation = ConversationMemory(persist=False)
    conversation.sessions["h011_entry"] = [
        Turn("user", "earlier request"), Turn("assistant", "earlier reply"),
        Turn("user", "current request"), Turn("assistant", "current reply"),
    ]
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "h011_entry"
    bind_native(orch, monkeypatch, session_ids=("h011_entry",))

    async def add_turn(sid, role, content, agent_id=None, *, channel=None, **kwargs):
        await conversation.add_turn(sid, role, content, agent_id, **kwargs)

    orch.memory = SimpleNamespace(conversation=conversation,
                                  add_turn=add_turn,
                                  get_history=conversation.get_history)
    orch.commands = CommandRegistry()
    orch.get_setting = lambda key, default=None: default
    seen = {"handlers": [], "titles": [], "context": [], "outcomes": []}
    orch._title_session = lambda text, channel: seen["titles"].append(text)
    orch._begin_chat_outcomes = lambda: seen["outcomes"].append(True)

    async def project(_):
        seen["context"].append(True)

    monkeypatch.setattr(module, "_begin_project_context", project)

    async def command(ctx):
        history = await orch.memory.get_history(orch.session_id)
        seen["handlers"].append((ctx.name, ctx.args, history))
        return "checkpoint answer"

    for name in ("rollback", "checkpoints", "status"):
        orch.commands.register(SlashCommand(name, name, command, tier=ADMIN))
    yield orch, seen, conversation
    module._active_session.reset(token)
    module._session_is_shared.reset(shared)


async def entry(orch, text, *, stream=False, admin=True):
    principal = bind_turn_principal(Principal(channel="web", admin=admin))
    emitted = []
    try:
        if stream:
            reply = await orch._handle_input_stream_prepared(
                text, channel="web", on_token=emitted.append, session_id="h011_entry"
            )
        else:
            reply = await orch._handle_input(text, channel="web", session_id="h011_entry")
        return reply, emitted
    finally:
        reset_turn_principal(principal)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("command", ["/rollback old_checkpoint", "/CHECKPOINTS@NervaBot status"])
async def test_current_last_user_is_visible_before_command_and_reply_append(context, stream, command):
    orch, seen, conversation = context
    before = await conversation.get_history("h011_entry")
    reply, emitted = await entry(orch, command, stream=stream)
    assert reply == "checkpoint answer"
    assert seen["handlers"][0][2] == before
    assert await conversation.get_history("h011_entry") == before
    assert seen["titles"] == seen["context"] == seen["outcomes"] == []
    assert emitted == ([reply] if stream else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_guest_is_refused_before_history_or_owner_handler(context, stream):
    orch, seen, conversation = context
    before = await conversation.get_history("h011_entry")
    reply, emitted = await entry(orch, "/rollback older", stream=stream, admin=False)
    assert "owner command" in reply
    assert not seen["handlers"]
    assert await conversation.get_history("h011_entry") == before
    assert seen["titles"] == seen["context"] == []
    assert emitted == ([reply] if stream else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("text,code", [
    ("/checkpoints status", "checkpoint.complete"),
    ("/checkpoints clear --dry-run", "checkpoint.preview"),
    ("/rollback", "checkpoint.complete"),
])
async def test_real_owner_registry_query_keeps_current_exchange(
    context, tmp_path, monkeypatch, stream, text, code,
):
    from agents.core.commands import build_default_registry
    from agents.core.file_tools import SnapshotStore
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices

    orch, seen, conversation = context
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))
    orch.commands = build_default_registry()
    before = await conversation.get_history("h011_entry")
    notices, token = open_turn_notices()
    try:
        reply, emitted = await entry(orch, text, stream=stream)
    finally:
        reset_turn_notices(token)
    assert notices == [{"code": code, "text": reply}]
    assert await conversation.get_history("h011_entry") == before
    assert seen["titles"] == seen["context"] == seen["outcomes"] == []
    assert emitted == ([reply] if stream else [])
    assert not SnapshotStore().directory.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("args,owner,corrupt,expected_code", [
    ([], True, False, "checkpoint.complete"),
    (["list"], True, False, "checkpoint.complete"),
    (["clear"], True, False, "checkpoint.preview"),
    (["clear", "--execute"], True, False, "checkpoint.unavailable"),
    (["status"], False, False, "checkpoint.refused"),
    (["status"], True, True, "checkpoint.partial"),
])
async def test_cli_web_owner_registry_contract_preserves_history_and_exit_status(
    context, tmp_path, monkeypatch, args, owner, corrupt, expected_code,
):
    import asyncio
    import io

    from agents import web
    from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main
    from agents.core.commands import build_default_registry
    from agents.core.file_tools import SnapshotStore
    from agents.core.security.token_store import TokenStore

    orch, seen, conversation = context
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    monkeypatch.setenv("JARVIS_TERMINAL_LOCAL_ROOTS", str(tmp_path))
    monkeypatch.setenv("JARVIS_KEEP_AWAKE", "0")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "fixture-owner-token")
    token_store = TokenStore(str(tmp_path / "tokens.sqlite3"))
    monkeypatch.setattr(web, "get_token_store", lambda: token_store)
    monkeypatch.setattr(web, "orch", orch)
    orch.commands = build_default_registry()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("checkpoint command must not call notes or attachment readers")

    from agents.core import context_refs
    orch.notes = SimpleNamespace(context_for=forbidden)
    monkeypatch.setattr(context_refs, "expand", forbidden)
    snapshots = SnapshotStore()
    if corrupt:
        snapshots.directory.mkdir(parents=True)
        (snapshots.directory / "history.sqlite3").write_bytes(b"invalid sqlite fixture")
    headers = [(b"x-admin-token", b"fixture-owner-token")] if owner else []
    request = Request({"type": "http", "method": "POST", "path": "/chat", "headers": headers,
                       "client": ("127.0.0.1", 43123), "scheme": "http"})
    before = await conversation.get_history("h011_entry")
    loop = asyncio.get_running_loop()
    responses = []

    class InProcessHub:
        # Replace only the network hop; web command, credential, notices, lease,
        # public orchestrator and registry all execute production code.
        base_url = "http://127.0.0.1:8080"

        def post(self, path, body):
            assert path == "/chat"
            future = asyncio.run_coroutine_threadsafe(
                web.chat(web.ChatRequest(message=body["message"]), request), loop,
            )
            response = future.result(timeout=10).model_dump()
            responses.append(response)
            return response

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, client_factory=lambda _: InProcessHub())
    code = await asyncio.to_thread(main, ["checkpoints", *args], context=ctx)
    success = expected_code in {"checkpoint.complete", "checkpoint.preview"}
    assert code == (EXIT_OK if success else EXIT_FAILED), (out.getvalue(), err.getvalue(), responses)
    assert [n["code"] for n in responses[0]["notices"]] == [expected_code]
    assert bool(out.getvalue()) is success and bool(err.getvalue()) is not success
    assert await conversation.get_history("h011_entry") == before
    assert seen["titles"] == seen["context"] == seen["outcomes"] == []
    assert not responses[0]["pending_approvals"]
    if not corrupt:
        assert not snapshots.directory.exists()


@pytest.mark.asyncio
async def test_ordinary_owner_command_keeps_existing_transcript_semantics(context):
    orch, seen, conversation = context
    before = await conversation.get_history("h011_entry")
    reply, _ = await entry(orch, "/status")
    history = await conversation.get_history("h011_entry")
    assert history[:len(before)] == before
    assert [t["content"] for t in history[len(before):]] == ["/status", reply]
    assert seen["titles"] == ["/status"] and seen["context"] == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["missing", "throws", "user_tier", "oversize"])
async def test_failed_reserved_command_never_becomes_model_or_transcript_input(context, broken):
    orch, seen, conversation = context
    before = await conversation.get_history("h011_entry")
    if broken == "missing":
        orch.commands = None
    elif broken == "throws":
        async def fail(*args, **kwargs):
            raise RuntimeError("broken registry")
        orch.commands.dispatch = fail
    elif broken == "user_tier":
        orch.commands._commands["rollback"] = SlashCommand("rollback", "bad", lambda _: "bad")
    text = "/rollback " + ("x" * 2200 if broken == "oversize" else "old")
    reply, _ = await entry(orch, text)
    assert reply and reply != "checkpoint answer" and reply != "bad"
    assert await conversation.get_history("h011_entry") == before
    assert not seen["handlers"] and not seen["titles"] and not seen["context"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_web_raw_checkpoint_command_skips_notes_and_attached_file_reads(context, monkeypatch, stream):
    from agents import web
    from agents.core import context_refs

    orch, seen, conversation = context
    raw = "/checkpoints list --project '@file:private.txt'"
    before = await conversation.get_history("h011_entry")
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "_web_principal", lambda _: Principal(channel="web", admin=True))

    def forbidden(*args, **kwargs):
        raise AssertionError("checkpoint command must not prepare model context")

    orch.notes = SimpleNamespace(context_for=forbidden)
    monkeypatch.setattr(context_refs, "expand", forbidden)
    request = Request({"type": "http", "method": "POST", "path": "/chat", "headers": [],
                       "client": ("127.0.0.1", 43123), "scheme": "http"})
    req = web.ChatRequest(message=raw)
    if stream:
        async def events(_orch, message, *_args, **kwargs):
            assert message == raw and kwargs["attached"] is None
            yield "verified raw command"
        monkeypatch.setattr(web, "_chat_event_stream", events)
        response = await web.chat_stream(req, request)
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == ["verified raw command"]
    else:
        async def handle(text, **kwargs):
            assert text == raw
            return "verified raw command"
        orch.handle_input = handle
        response = await web.chat(req, request)
        assert response.reply == "verified raw command"
    assert await conversation.get_history("h011_entry") == before
    assert not seen["handlers"]
