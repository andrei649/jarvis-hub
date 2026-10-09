"""Bounded image provenance survives history without storing image bytes."""

import asyncio
import json

import pytest

from agents.core.memory import conversation, persistence
from agents.core.memory.conversation import ConversationMemory, Turn
from agents.core.memory.manager import MemoryManager
from agents.core.session_continuation import ContinuationRefused, seed_json

MEDIA = {"kind": "image", "count": 2, "model": "grok-4.5", "backend": "xai", "local": False}


@pytest.mark.asyncio
async def test_image_provenance_round_trips_as_text_only(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    memory = ConversationMemory(persist=True)
    sid = await memory.new_session("image_provenance")
    await memory.add_turn(sid, "user", "What is here?\n[2 images attached]", media=MEDIA)
    await memory.add_turn(sid, "assistant", "Two blue squares.", agent_id="jarvis", media=MEDIA)

    saved = (tmp_path / f"{sid}.json").read_text(encoding="utf-8")
    assert "data:image/" not in saved
    assert json.loads(saved)["turns"][0]["media"] == MEDIA

    restored = ConversationMemory(persist=True)
    assert [row["media"] for row in await restored.get_history(sid)] == [MEDIA, MEDIA]
    assert "media" not in await restored.get_context(sid)


@pytest.mark.parametrize("media", [
    {**MEDIA, "count": True},
    {**MEDIA, "count": 9},
    {**MEDIA, "backend": "xai\nAuthorization: secret"},
    {**MEDIA, "model": "data:image/png;base64,secret"},
    {**MEDIA, "destination": "https://secret.example"},
])
def test_invalid_image_provenance_is_refused(media):
    with pytest.raises(ValueError):
        Turn("user", "question", media=media)


def test_continuation_seed_preserves_valid_image_provenance():
    turn = Turn("assistant", "Two blue squares.", agent_id="jarvis", media=MEDIA)
    canonical = json.loads(seed_json([turn.to_dict()]))
    assert canonical[0]["media"] == MEDIA


def test_continuation_seed_refuses_edited_image_provenance():
    turn = Turn("assistant", "Two blue squares.", agent_id="jarvis").to_dict()
    turn["media"] = {**MEDIA, "credential": "secret"}
    with pytest.raises(ContinuationRefused):
        seed_json([turn])


@pytest.mark.asyncio
async def test_manager_carries_media_without_embedding_it():
    manager = MemoryManager.__new__(MemoryManager)
    manager.conversation = ConversationMemory(persist=False)
    manager._lock = asyncio.Lock()
    manager.embed_turns = True
    embedded = []
    manager._queue_turn_embedding = lambda content, metadata: embedded.append((content, metadata))
    sid = await manager.new_session("image_manager")
    await manager.add_turn(sid, "assistant", "Two blue squares.", agent_id="jarvis",
                           channel="web", media=MEDIA)
    assert (await manager.get_history(sid))[0]["media"] == MEDIA
    assert embedded == [("Two blue squares.", {
        "role": "assistant", "agent": "jarvis", "session": sid,
        "channel": "web", "origin": "generated",
    })]


@pytest.mark.asyncio
async def test_edited_snapshot_drops_malformed_media_but_keeps_text(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    (tmp_path / "image_edited.json").write_text(json.dumps({
        "session_id": "image_edited",
        "turns": [{"role": "user", "content": "question", "media": {"kind": "image", "count": 1, "credential": "secret"}}],
    }), encoding="utf-8")
    restored = ConversationMemory(persist=True)
    row = (await restored.get_history("image_edited"))[0]
    assert row["content"] == "question"
    assert "media" not in row
