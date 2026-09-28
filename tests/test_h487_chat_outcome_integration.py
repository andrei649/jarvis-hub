"""Exact chat identity at the ToolRPC/prompt/persisted-answer boundary."""
from types import SimpleNamespace

import pytest

from agents.core.commands import Principal
from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal


@pytest.fixture
def chat(tmp_path, monkeypatch):
    from agents.core.agent import Agent
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.checkpoint import CheckpointManager
    from agents.core.tool_rpc import ToolRPCServer
    from tests.test_agent_runtime_v2 import _ScriptedBackend, _streamed_orchestrator_for

    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    cp = CheckpointManager(str(tmp_path / "cp.db"))
    cp.initialize()
    cp.create_session_record("s", "jarvis")
    worker = AutonomyWorker(queue)
    server = ToolRPCServer(enqueue=worker.govern_enqueue)
    executed = []
    async def send(args):
        executed.append(args)
        return {"ok": True}
    server.register_tool("send_mail", send, gated=True)
    backend = _ScriptedBackend([])
    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
    orch, _, _, turns = _streamed_orchestrator_for(agent, backend)
    orch.autonomy_queue, orch.checkpoints = queue, cp
    agent.llm_router = orch.llm_router
    original_add = orch.memory.add_turn
    async def add_turn(*args, tools=None, **kwargs):
        await original_add(*args, **kwargs)
    orch.memory.add_turn = add_turn
    async def empty(*args, **kwargs):
        return ""
    async def history(*args, **kwargs):
        return []
    orch.memory.get_agent_context, orch.memory.get_history = empty, history
    orch.memory.conversation = SimpleNamespace(sessions={})
    async def prompt_history(*args, staged=False, **kwargs):
        return SimpleNamespace(text="", publish=lambda: None) if staged else ""
    orch._history_for_prompt = prompt_history
    orch._build_agent_turn_text = Orchestrator._build_agent_turn_text.__get__(orch)
    orch._complete_llm_turn = Orchestrator._complete_llm_turn.__get__(orch)
    orch.audit = SimpleNamespace(preview=lambda text, cap: text[:cap], log=lambda event: None)
    for name in ("_maybe_checkpoint", "_record_living_memory_after_turn"):
        setattr(orch, name, empty)
    for name in ("_log_session", "_record_interactions", "_update_cognition",
                 "_spawn_background_review", "_nudge_persona_after_turn"):
        setattr(orch, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(orch, "_chat_control_enabled", lambda: False)
    yield SimpleNamespace(orch=orch, q=queue, cp=cp, worker=worker, backend=backend,
                          turns=turns, executed=executed, server=server)
    queue.close()
    cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("managed", [False, True])
async def test_actual_chat_tool_ask_reports_rejection_once_without_replay(chat, stream, managed):
    from agents.core.llm.tool_protocol import ToolCall, ToolTurn

    entry = chat.orch.handle_input_stream if stream else chat.orch.handle_input
    original_setting = chat.orch.get_setting
    chat.orch.get_setting = lambda key, default=None: managed if key == "memory.context_compression" else original_setting(key, default)
    principal = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        chat.backend.turns.append(ToolTurn(tool_calls=(ToolCall(
            id="ask1", name="send_mail", raw_arguments='{"to":"ana"}', arguments={"to": "ana"}),)))
        first = await entry("send the mail", channel="web", session_id="s")
        assert "approval" in first.lower()
        task = chat.q.list()[0]
        assert task.status == "blocked"
        await chat.worker.apply_decision(task.id, "reject", decided_by="owner", reason="keep this private")
        chat.backend.turns.append(ToolTurn(content="It was rejected; nothing was sent."))
        await entry("what happened?", channel="web", session_id="s")
        prompt = str(chat.backend.calls[-1]["messages"])
        assert "rejected" in prompt and "keep this private" in prompt
        assert "Do not replay" in prompt and chat.executed == []
        chat.backend.turns.append(ToolTurn(content="next answer"))
        await entry("next question", channel="web", session_id="s")
        assert "Approval outcome observations" not in str(chat.backend.calls[-1]["messages"])
        assert len(chat.q.list()) == 1
    finally:
        reset_turn_principal(principal)


async def _ask(chat, principal):
    from agents.core.llm.tool_protocol import ToolCall, ToolTurn
    token = bind_turn_principal(principal)
    try:
        chat.backend.turns.append(ToolTurn(tool_calls=(ToolCall(
            id="ask", name="send_mail", raw_arguments="{}", arguments={}),)))
        await chat.orch.handle_input("send it", channel=principal.channel, session_id="s")
        return chat.q.list()[0]
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_failed_model_turn_does_not_consume_observation(chat, stream):
    from agents.core.llm.tool_protocol import ToolTurn
    owner = Principal(channel="web", admin=True)
    task = await _ask(chat, owner)
    await chat.worker.apply_decision(task.id, "accept", decided_by="owner")
    token = bind_turn_principal(owner)
    entry = chat.orch.handle_input_stream if stream else chat.orch.handle_input
    try:
        chat.backend.turns.append(ToolTurn(content="[Gemini error: failed]"))
        await entry("status", channel="web", session_id="s")
        assert "approved_not_executed" in str(chat.backend.calls[-1]["messages"])
        chat.backend.turns.append(ToolTurn(content="approved, execution is pending"))
        await entry("status again", channel="web", session_id="s")
        assert "approved_not_executed" in str(chat.backend.calls[-1]["messages"])
        assert chat.executed == []
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", [
    Principal(channel="telegram", admin=True, sender="other", chat="room"),
    Principal(channel="telegram", admin=True, sender="alice", chat="other-room"),
    Principal(channel="web", admin=True),
])
async def test_exact_telegram_principal_cannot_cross_sender_chat_or_channel(chat, consumer):
    from agents.core.llm.tool_protocol import ToolTurn
    producer = Principal(channel="telegram", admin=True, sender="alice", chat="room")
    task = await _ask(chat, producer)
    await chat.worker.apply_decision(task.id, "reject", decided_by="owner", reason="private reason")
    token = bind_turn_principal(consumer)
    try:
        chat.backend.turns.append(ToolTurn(content="normal answer"))
        await chat.orch.handle_input("status", channel=consumer.channel, session_id="s")
        assert "private reason" not in str(chat.backend.calls[-1]["messages"])
    finally:
        reset_turn_principal(token)
    token = bind_turn_principal(producer)
    try:
        chat.backend.turns.append(ToolTurn(content="rejected"))
        await chat.orch.handle_input("status", channel="telegram", session_id="s")
        assert "private reason" in str(chat.backend.calls[-1]["messages"])
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_reply_persistence_retains_observation(chat, cancel):
    import asyncio

    from agents.core.llm.tool_protocol import ToolTurn
    owner = Principal(channel="web", admin=True)
    task = await _ask(chat, owner)
    await chat.worker.apply_decision(task.id, "reject", decided_by="owner", reason="retain me")
    original_add = chat.orch.memory.add_turn
    async def failed_add(sid, role, *args, **kwargs):
        if role == "assistant":
            raise asyncio.CancelledError() if cancel else RuntimeError("failed transcript write")
        await original_add(sid, role, *args, **kwargs)
    chat.orch.memory.add_turn = failed_add
    token = bind_turn_principal(owner)
    try:
        chat.backend.turns.append(ToolTurn(content="rejected"))
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await chat.orch.handle_input("status", channel="web", session_id="s")
        chat.orch.memory.add_turn = original_add
        chat.backend.turns.append(ToolTurn(content="rejected again"))
        await chat.orch.handle_input("status again", channel="web", session_id="s")
        assert "retain me" in str(chat.backend.calls[-1]["messages"])
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
async def test_command_and_no_model_turns_do_not_consume_observations(chat):
    from agents.core.llm.tool_protocol import ToolTurn
    owner = Principal(channel="web", admin=True)
    task = await _ask(chat, owner)
    await chat.worker.apply_decision(task.id, "reject", decided_by="owner", reason="still pending delivery")
    original_dispatch, original_select = chat.orch._dispatch_command, chat.orch.llm_router.select_backend
    async def command(text):
        return SimpleNamespace(reply="command completed")
    chat.orch._dispatch_command = command
    chat.orch._command_cognition = lambda outcome: {}
    token = bind_turn_principal(owner)
    try:
        assert await chat.orch.handle_input("/status", channel="web", session_id="s") == "command completed"
        chat.orch._dispatch_command = original_dispatch
        def missing(*args):
            raise RuntimeError("no model backend")
        chat.orch.llm_router.select_backend = missing
        await chat.orch.handle_input("status", channel="web", session_id="s")
        chat.orch.llm_router.select_backend = original_select
        chat.backend.turns.append(ToolTurn(content="rejected"))
        await chat.orch.handle_input("status again", channel="web", session_id="s")
        assert "still pending delivery" in str(chat.backend.calls[-1]["messages"])
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
async def test_unverified_turn_has_no_observation_context():
    from agents.core.approval_outcomes import current_approval_turn

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "s"
    orch.checkpoints = SimpleNamespace(clock_snapshot=lambda sid: SimpleNamespace(instance_id="instance"))
    orch.autonomy_queue = SimpleNamespace(chat_outcome_snapshot=lambda ctx: pytest.fail("unauthorized snapshot"))
    token = bind_turn_principal(Principal(channel="web", admin=False))
    try:
        orch._begin_chat_outcomes()
        assert current_approval_turn() is None
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
async def test_session_deletion_backs_up_and_purges_only_old_instance(tmp_path, monkeypatch):
    from agents.core import session_archive
    from agents.core.checkpoint import CheckpointManager

    cp = CheckpointManager(str(tmp_path / "cp.db"))
    cp.initialize()
    cp.create_session_record("s", "jarvis")
    instance = cp.clock_snapshot("s").instance_id
    calls, backups = [], []
    def export(sid, *, session_instance):
        calls.append(("backup", sid, session_instance))
        return {"origins": [{"session_instance": instance}], "tasks": []}
    def purge(sid, session_instance=None):
        assert cp.clock_snapshot(sid) is None
        calls.append(("purge", sid, session_instance))
        return 1
    q = SimpleNamespace(chat_outcomes_for_backup=export, purge_chat_outcomes=purge)
    monkeypatch.setattr(session_archive, "_files", lambda *args: {"snapshot": tmp_path / "s.json"})
    monkeypatch.setattr(session_archive, "_write_backup", lambda record, path: backups.append(record) or path)
    try:
        result = await session_archive.delete_session("s", checkpoints=cp, todos=None,
                                                     backup_root=tmp_path / "backups", outcomes_queue=q)
        assert result["ok"]
        assert calls == [("backup", "s", instance), ("purge", "s", instance)]
        assert backups[0]["chat_approval_outcomes"]["origins"][0]["session_instance"] == instance
    finally:
        cp.close()


@pytest.mark.asyncio
async def test_cleanup_failure_clears_private_stores_and_retry_is_leased(chat, tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    from agents.core import session_archive, todo_tool

    task = await _ask(chat, Principal(channel="web", admin=True))
    assert task.status == "blocked"
    old_instance = chat.cp.clock_snapshot("s").instance_id
    chat.orch._resolve_session("other")
    chat.orch.memory.conversation.sessions["s"] = ["private transcript"]
    chat.orch.memory.conversation.instances = {"s": old_instance}
    todos, notes, bindings, purges = [], [], [], []
    monkeypatch.setattr(todo_tool, "TODOS", SimpleNamespace(forget=lambda sid: todos.append(sid),
                                                          read=lambda sid: []))
    chat.orch.notes = SimpleNamespace(clear=lambda sid: notes.append(sid), get=lambda sid: "")
    chat.orch.forget_channel_session = lambda sid: bindings.append(sid)
    held = False
    @asynccontextmanager
    async def lease(sid):
        nonlocal held
        assert sid == "s" and not held
        held = True
        try:
            yield True
        finally:
            held = False
    chat.orch.turn_lease = lease
    original_purge = chat.q.purge_chat_outcomes
    def purge(sid, session_instance=None):
        assert held and chat.cp.clock_snapshot(sid) is None
        purges.append(session_instance)
        if len(purges) == 1:
            raise OSError("queue cleanup unavailable")
        return original_purge(sid, session_instance=session_instance)
    monkeypatch.setattr(chat.q, "purge_chat_outcomes", purge)
    monkeypatch.setattr(session_archive, "_files", lambda *args: {"snapshot": tmp_path / "s.json"})
    monkeypatch.setattr(session_archive, "_write_backup", lambda record, path: path)
    with pytest.raises(session_archive.SessionDeleteError, match="approval_outcomes_unavailable"):
        await session_archive.delete_leased(chat.orch, "s", live=[])
    assert "s" not in chat.orch.memory.conversation.sessions
    assert "s" not in chat.orch.memory.conversation.instances
    assert todos == notes == bindings == ["s"]
    result = await session_archive.delete_leased(chat.orch, "s", live=[])
    assert result["ok"] and purges == [old_instance, None]
    assert chat.q.chat_outcomes_for_backup("s") == {"origins": [], "tasks": []}


@pytest.mark.asyncio
async def test_detached_child_cannot_produce_after_origin_turn_finishes(chat):
    import asyncio
    import contextvars

    from agents.core.approval_outcomes import current_approval_turn
    from agents.core.llm.tool_protocol import ToolTurn

    saved = []
    async def generate(**kwargs):
        saved.append((current_approval_turn(), contextvars.copy_context()))
        return ToolTurn(content="normal answer")
    chat.backend.generate_tool_turn = generate
    token = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        await chat.orch.handle_input("hello", channel="web", session_id="s")
        context, inherited = saved[0]
        assert context is not None and not context.live()
        result = await asyncio.create_task(chat.server.handle({"tool": "send_mail", "args": {}}),
                                          context=inherited)
        assert result["task_id"] and len(chat.q.list()) == 1
        assert chat.q.chat_outcomes_for_backup("s") == {"origins": [], "tasks": []}
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
async def test_recreated_session_does_not_inherit_old_instance_outcome(chat):
    from agents.core.llm.tool_protocol import ToolTurn

    owner = Principal(channel="web", admin=True)
    task = await _ask(chat, owner)
    await chat.worker.apply_decision(task.id, "reject", decided_by="owner", reason="old instance private reason")
    old = chat.cp.clock_snapshot("s").instance_id
    chat.cp.delete_session_rows("s")
    chat.cp.create_session_record("s", "jarvis")
    assert chat.cp.clock_snapshot("s").instance_id != old
    token = bind_turn_principal(owner)
    try:
        chat.backend.turns.append(ToolTurn(content="normal answer"))
        await chat.orch.handle_input("hello", channel="web", session_id="s")
        assert "old instance private reason" not in str(chat.backend.calls[-1]["messages"])
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
async def test_real_multiagent_synthesis_receives_same_frozen_observation(chat):
    from agents.core.agent import Agent
    from agents.core.llm.tool_protocol import ToolTurn

    owner = Principal(channel="web", admin=True)
    task = await _ask(chat, owner)
    await chat.worker.apply_decision(task.id, "reject", decided_by="owner", reason="single frozen reason")
    specialist = Agent("athena", {"name": "Athena"}, llm_router=chat.orch.llm_router)
    specialist.tool_runtime = chat.orch.agents["jarvis"].tool_runtime
    chat.orch.agents["athena"] = specialist
    async def classify(*args):
        return SimpleNamespace(target_agents=["jarvis", "athena"], is_general=False,
                               confidence=1.0, context={})
    chat.orch.router.classify = classify
    original_synthesize = chat.orch._synthesize
    contributors = []
    async def synthesize(responses, intent):
        before = dict(responses)
        result = await original_synthesize(responses, intent)
        assert responses == before
        contributors.append(set(responses))
        return result
    chat.orch._synthesize = synthesize
    merges = []
    async def generate(**kwargs):
        merges.append(kwargs)
        return "merged answer"
    chat.backend.generate = generate
    chat.backend.turns.extend([ToolTurn(content="primary answer"), ToolTurn(content="specialist answer")])
    token = bind_turn_principal(owner)
    try:
        answer = await chat.orch.handle_input("status", channel="web", session_id="s")
        assert answer == "merged answer" and len(merges) == 1
        assert "single frozen reason" in merges[0]["prompt"]
        assert "Do not replay tools" in merges[0]["prompt"]
        assert all("single frozen reason" in str(call["messages"]) for call in chat.backend.calls[-2:])
        assert contributors == [{"jarvis", "athena"}]
        assert chat.executed == [] and len(chat.q.list()) == 1
        from agents.core.approval_outcomes import open_approval_turn
        context = open_approval_turn(session_id="s", session_instance=chat.cp.clock_snapshot("s").instance_id,
                                     principal=owner, session_is_live=lambda sid, instance: chat.cp.clock_snapshot(sid).instance_id == instance)
        assert chat.q.chat_outcome_snapshot(context) == []
    finally:
        reset_turn_principal(token)
