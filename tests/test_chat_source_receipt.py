import json

import pytest

from agents.core import context_refs
from agents.core.memory import conversation, persistence
from agents.core.session_continuation import seed_json

BOARD_SOURCE = {"board": "default", "task_id": "t_1", "source": "latest_summary",
                "sha256": "a" * 64}


@pytest.mark.asyncio
async def test_source_receipt_stays_on_the_addressed_native_question_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    memory = conversation.ConversationMemory(persist=True)
    memory.instances["destination"] = "native-instance"
    receipt = {"session_id": "earlier", "turn": 3, "role": "assistant", "revision": "d" * 64}
    expansion = context_refs.attach_editor_content(None, "Current question", [
        {"name": "Earlier message", "text": "PRIVATE source excerpt"},
    ])
    expansion.history_source = receipt
    token = context_refs.bind_attached(expansion)
    try:
        assert context_refs.pending_history_source("other", "Current question") is None
        expansion.history_destination = "destination"
        await memory.add_turn("other", "user", "Current question", channel="web")
        await memory.add_turn("destination", "user", "Current question", channel="web")
        await memory.add_turn("destination", "assistant", "Model answer", channel="web")
        await memory.add_turn("destination", "user", "Next question", channel="web")
    finally:
        context_refs.reset_attached(token)
    assert "history_source" not in (await memory.get_history("other"))[0]
    restored = conversation.ConversationMemory(persist=True)
    await restored.resume_session("destination")
    rows = await restored.get_history("destination")
    assert rows[0]["history_source"] == receipt
    assert rows[0]["content"] == "Current question"
    assert "PRIVATE source excerpt" not in json.dumps(rows)
    assert all("history_source" not in row for row in rows[1:])
    assert json.loads(seed_json(rows))[0]["history_source"] == receipt


def test_restored_source_metadata_cannot_carry_private_text_or_claim_a_foreign_turn():
    receipt = {"session_id": "earlier", "turn": 3, "role": "assistant", "revision": "d" * 64}
    for invalid in ({**receipt, "excerpt": "Private"}, {**receipt, "turn": True}, {**receipt, "session_id": "../x"}):
        assert "history_source" not in conversation.Turn("user", "Question", history_source=invalid).to_dict()
    for row in (conversation.Turn("assistant", "Reply", history_source=receipt),
                conversation.Turn("user", "Imported", foreign_origin="codex", history_source=receipt)):
        assert "history_source" not in row.to_dict()


@pytest.mark.asyncio
async def test_failed_destination_snapshot_does_not_acknowledge_a_sourced_question(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    memory = conversation.ConversationMemory(persist=True)

    def fail_snapshot(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(conversation, "save_memory", fail_snapshot)
    source = {"session_id": "earlier", "turn": 0, "role": "user", "revision": "a" * 64}
    expansion = context_refs.attach_editor_content(None, "Question", [{"name": "Source", "text": "passage"}])
    expansion.history_source = source
    expansion.history_destination = "destination"
    token = context_refs.bind_attached(expansion)
    try:
        with pytest.raises(OSError, match="snapshot"):
            await memory.add_turn("destination", "user", "Question", channel="web")
        assert expansion.history_source == source
        assert await memory.get_history("destination") == []
        assert not (tmp_path / "destination.jsonl").exists()
    finally:
        context_refs.reset_attached(token)


@pytest.mark.asyncio
async def test_reviewed_board_receipt_is_durable_once_and_hidden_from_ordinary_history(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    memory = conversation.ConversationMemory(persist=True)
    memory.instances["destination"] = "native-instance"
    expansion = context_refs.attach_editor_content(None, "Question", [
        {"name": "Reviewed board result", "text": "private full source"},
    ])
    expansion.board_sources = [BOARD_SOURCE]
    expansion.history_destination = "destination"
    token = context_refs.bind_attached(expansion)
    try:
        await memory.add_turn("other", "user", "Question", channel="web")
        await memory.add_turn("destination", "user", "Different", channel="web")
        assert expansion.board_sources == [BOARD_SOURCE]
        await memory.add_turn("destination", "user", "Question", channel="web")
        assert expansion.board_sources is None
        assert expansion.board_sources_recorded is True
        await memory.add_turn("destination", "assistant", "Answer", channel="web")
        await memory.add_turn("destination", "user", "Question", channel="web")
    finally:
        context_refs.reset_attached(token)
    assert all("board_sources" not in row for row in await memory.get_history("destination"))
    restored = conversation.ConversationMemory(persist=True)
    await restored.resume_session("destination")
    rows = await restored.get_history("destination", include_board_sources=True)
    assert rows[1]["board_sources"] == [BOARD_SOURCE]
    assert all("board_sources" not in row for i, row in enumerate(rows) if i != 1)
    assert json.loads((tmp_path / "destination.json").read_text(encoding="utf-8"))["turns"][1]["board_sources"] == [BOARD_SOURCE]
    assert '"board_sources"' in (tmp_path / "destination.jsonl").read_text(encoding="utf-8")
    assert "private full source" not in json.dumps(rows)
    assert json.loads(seed_json(rows))[1]["board_sources"] == [BOARD_SOURCE]


def test_board_receipts_reject_text_and_foreign_or_assistant_claims():
    for invalid in ({**BOARD_SOURCE, "excerpt": "private"}, {**BOARD_SOURCE, "board": "../bad"},
                    {**BOARD_SOURCE, "sha256": "A" * 64}, {**BOARD_SOURCE, "source": "body"}):
        assert "board_sources" not in conversation.Turn("user", "Question", board_sources=[invalid]).to_dict()
    assert "board_sources" not in conversation.Turn("user", "Question", board_sources=[BOARD_SOURCE] * 2).to_dict()
    nine = [{**BOARD_SOURCE, "task_id": f"t_{i}"} for i in range(9)]
    assert "board_sources" not in conversation.Turn("user", "Question", board_sources=nine).to_dict()
    for turn in (conversation.Turn("assistant", "Reply", board_sources=[BOARD_SOURCE]),
                 conversation.Turn("user", "Imported", foreign_origin="codex", board_sources=[BOARD_SOURCE])):
        assert "board_sources" not in turn.to_dict()


@pytest.mark.asyncio
async def test_board_receipt_is_not_acknowledged_if_snapshot_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    memory = conversation.ConversationMemory(persist=True)
    monkeypatch.setattr(conversation, "save_memory", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("full")))
    expansion = context_refs.attach_editor_content(None, "Question", [{"name": "Board", "text": "reviewed"}])
    expansion.board_sources = [BOARD_SOURCE]
    expansion.history_destination = "destination"
    token = context_refs.bind_attached(expansion)
    try:
        with pytest.raises(OSError, match="snapshot"):
            await memory.add_turn("destination", "user", "Question", channel="web")
        assert expansion.board_sources == [BOARD_SOURCE]
        assert expansion.board_sources_recorded is False
        assert await memory.get_history("destination") == []
    finally:
        context_refs.reset_attached(token)
