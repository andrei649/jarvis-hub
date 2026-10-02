"""Private active image parts must never become durable conversation content."""

import importlib

import pytest

from agents.core.memory.conversation import ConversationMemory


def _history(**kwargs):
    try:
        module = importlib.import_module("agents.core.llm.vision_history")
    except ModuleNotFoundError:
        pytest.fail("active image history implementation is missing")
    return module.ActiveImageHistory(**kwargs), module.ActiveImageUnavailable


def test_active_images_are_scoped_to_session_instance_and_agent():
    history, unavailable = _history()
    handle = history.remember("session_a", "instance_a", "jarvis", "What is here?", [b"PNG-1"])

    assert isinstance(handle, str) and len(handle) >= 24
    assert history.list("session_a", "instance_a", "jarvis") == [
        {"handle": handle, "count": 1, "question": "What is here?"}
    ]
    assert history.resolve("session_a", "instance_a", "jarvis", [handle]) == (b"PNG-1",)
    for session, instance, agent in (
        ("session_b", "instance_a", "jarvis"),
        ("session_a", "instance_b", "jarvis"),
        ("session_a", "instance_a", "researcher"),
    ):
        assert history.list(session, instance, agent) == []
        with pytest.raises(unavailable):
            history.resolve(session, instance, agent, [handle])

    history.clear("session_a")
    with pytest.raises(unavailable):
        history.resolve("session_a", "instance_a", "jarvis", [handle])


def test_active_images_expire_and_evict_oldest_without_reusing_handles():
    now = [0.0]
    history, unavailable = _history(clock=lambda: now[0], ttl_seconds=5,
                                    max_bytes=8, max_handles=2)
    first = history.remember("s", "i", "jarvis", "first", [b"1234"])
    second = history.remember("s", "i", "jarvis", "second", [b"5678"])
    third = history.remember("s", "i", "jarvis", "third", [b"ABCD"])
    assert len({first, second, third}) == 3
    assert [row["handle"] for row in history.list("s", "i", "jarvis")] == [second, third]
    with pytest.raises(unavailable):
        history.resolve("s", "i", "jarvis", [first])
    now[0] = 5.0
    assert history.list("s", "i", "jarvis") == []
    with pytest.raises(unavailable):
        history.resolve("s", "i", "jarvis", [third])


def test_active_images_copy_mutable_input_and_keep_bytes_out_of_public_shapes():
    history, unavailable = _history(max_bytes=16, max_handles=2, max_image_bytes=8)
    source = bytearray(b"private-image")
    assert history.remember("s", "i", "jarvis", "oversize", [source]) is None
    source = bytearray(b"secret")
    handle = history.remember("s", "i", "jarvis", "\n what? \r", [source])
    source[:] = b"changed"
    assert history.resolve("s", "i", "jarvis", [handle]) == (b"secret",)
    public = history.list("s", "i", "jarvis")
    assert public == [{"handle": handle, "count": 1, "question": "what?"}]
    assert "secret" not in repr(history) and "secret" not in repr(public)
    with pytest.raises(unavailable):
        history.resolve("s", "i", "jarvis", [handle, handle])


@pytest.mark.asyncio
async def test_conversation_clear_drops_active_images_without_persisting_them():
    memory = ConversationMemory(persist=False)
    await memory.new_session("selected_s")
    assert hasattr(memory, "active_images")
    instance = memory.active_image_instance("selected_s")
    handle = memory.active_images.remember("selected_s", instance, "jarvis", "question", [b"private"])
    await memory.add_turn("selected_s", "user", "question\n[1 image attached]",
                          media={"kind": "image", "count": 1, "model": "vision-model",
                                 "backend": "lmstudio", "local": True})
    assert b"private" not in repr(await memory.get_history("selected_s")).encode()

    await memory.clear("selected_s")
    assert memory.active_image_instance("selected_s") is None
    await memory.new_session("selected_s")
    assert memory.active_image_instance("selected_s") != instance
    with pytest.raises(_history()[1]):
        memory.active_images.resolve("selected_s", instance, "jarvis", [handle])
