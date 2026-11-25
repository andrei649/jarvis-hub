import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agents.core import turn_outcome
from agents.core.memory.conversation import ConversationMemory, Turn, validated_tool_activity


def test_tool_activity_snapshot_requires_active_measurement_and_keeps_unknown():
    sink, token = turn_outcome.open_turn_outcome()
    try:
        assert sink.tool_activity_snapshot() is None
        assert sink.claim()
        assert sink.begin(1.0)
        assert sink.tool_activity_snapshot() == {
            "proposed": 0, "queued": 0, "executed": 0, "failures": 0, "basis": "observed"}
        turn_outcome.record_tool_proposed(queued=True)
        turn_outcome.record_tool_executed(success=None, known_invocation=False)
        assert sink.tool_activity_snapshot() == {
            "proposed": 1, "queued": 1, "executed": None, "failures": None, "basis": "unknown"}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.parametrize("bad", [
    {"proposed": True, "queued": 0, "executed": 0, "failures": 0, "basis": "observed"},
    {"proposed": -1, "queued": 0, "executed": 0, "failures": 0, "basis": "observed"},
    {"proposed": 0, "queued": 0, "executed": None, "failures": None, "basis": "observed"},
    {"proposed": 0, "queued": 0, "executed": 0, "failures": 0, "basis": "unknown"},
    {"proposed": 0, "queued": 0, "executed": 0, "failures": 0, "basis": "observed", "prompt": "secret"},
    {"proposed": 0, "queued": 0, "executed": 0, "failures": 0, "basis": "observed", "args": "secret"},
])
def test_tool_activity_rejects_malformed_and_untrusted_rows(bad):
    assert validated_tool_activity(bad) is None
    assert "tool_activity" not in Turn("assistant", "answer", foreign_origin="codex",
                                       tool_activity={"proposed": 1, "queued": 0, "executed": 0,
                                                      "failures": 0, "basis": "observed"}).to_dict()


def test_continuation_seed_drops_injected_activity():
    import json

    from agents.core.session_continuation import seed_json

    seed = [{"role": "assistant", "content": "answer", "agent_id": "jarvis",
             "timestamp": "2026-11-22T00:00:00+00:00", "token_count": 1,
             "tool_activity": {"proposed": 1, "queued": 0, "executed": 1,
                               "failures": 0, "basis": "observed"}}]
    assert "tool_activity" not in json.loads(seed_json(seed))[0]


@pytest.mark.asyncio
async def test_tool_activity_survives_history_restore_and_is_not_on_user_rows(tmp_path, monkeypatch):
    from agents.core.memory import conversation, persistence

    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    activity = {"proposed": 2, "queued": 1, "executed": 1,
                "failures": 0, "basis": "observed"}
    memory = ConversationMemory(persist=True)
    memory.instances["reply_tools"] = "native-instance"
    await memory.add_turn("reply_tools", "user", "hello", tool_activity=activity)
    await memory.add_turn("reply_tools", "assistant", "answer", tool_activity=activity)
    assert "tool_activity" not in (await memory.get_history("reply_tools"))[0]
    assert (await memory.get_history("reply_tools"))[1]["tool_activity"] == activity
    restored = ConversationMemory(persist=True)
    assert (await restored.get_history("reply_tools"))[1]["tool_activity"] == activity


@pytest.mark.asyncio
async def test_ordinary_reply_append_uses_only_its_own_live_outcome(monkeypatch):
    from agents.core import orchestrator, plan_commands
    from agents.core.memory import turn_tools
    from agents.core.memory.manager import MemoryManager

    monkeypatch.setattr(orchestrator, "_turn_is_untrusted", lambda: False)
    monkeypatch.setattr(orchestrator, "turn_read_unproven", lambda: False)
    monkeypatch.setattr(turn_tools, "collected", lambda: [])
    monkeypatch.setattr(plan_commands, "finish_plan_turn", AsyncMock())
    saved = {}

    async def one(sid, count):
        memory = object.__new__(MemoryManager)
        async def add_turn(session, role, content, **kwargs):
            saved[sid] = kwargs.get("tool_activity")
        memory.add_turn = add_turn
        fake = SimpleNamespace(
            session_id=sid, memory=memory,
            _maybe_micro_compact=AsyncMock(), _maybe_checkpoint=AsyncMock(),
            _log_session=Mock(), _record_interactions=Mock(),
            audit=SimpleNamespace(preview=lambda content, length: content[:length], log=Mock()),
            _nudge_persona_after_turn=Mock(), _record_living_memory_after_turn=AsyncMock(),
            _update_cognition=Mock(), _spawn_background_review=Mock(),
        )
        sink, token = turn_outcome.open_turn_outcome()
        try:
            assert sink.claim() and sink.begin(1.0)
            for _ in range(count):
                turn_outcome.record_tool_proposed()
            await asyncio.sleep(0)
            await orchestrator.Orchestrator._complete_llm_turn(
                fake, text="question", intent=None, plugin_data={}, responses={},
                synthesized="answer", responder_id="jarvis", route_name="jarvis", channel="web",
                action_taken="answer", t_classify=0, t_route=0, t_plugin=0, t_synthesize=0)
        finally:
            turn_outcome.reset_turn_outcome(token)

    await asyncio.gather(one("first", 1), one("second", 3))
    assert saved["first"]["proposed"] == 1
    assert saved["second"]["proposed"] == 3
