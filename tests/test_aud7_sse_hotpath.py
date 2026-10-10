"""AUD-7 — SSE hot path: cancellation-safety (F8) + off-loop turn persistence (F9).

F8: a client that disconnects mid-stream must cancel the model turn, not leave it
running orphaned. F9: ``ConversationMemory.add_turn`` must not do its blocking disk
writes (append-log + full snapshot) on the event loop, while keeping per-turn
durability unchanged.
"""

import asyncio
import json
import threading

from agents import web
from agents.core.memory import conversation as conv
from agents.core.memory import persistence


def _payload(chunk: str) -> dict:
    assert chunk.startswith("data: ") and chunk.endswith("\n\n")
    return json.loads(chunk[len("data: "):])


# ── F8 — SSE cancellation safety ───────────────────────────────────
async def test_sse_cancels_model_turn_on_client_disconnect():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class FakeOrch:
        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            started.set()
            try:
                await asyncio.sleep(30)  # a long-running model turn
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return "never reached"

    agen = web._chat_event_stream(FakeOrch(), "hi", "jarvis", None)
    assert _payload(await agen.__anext__())["type"] == "start"
    await asyncio.wait_for(started.wait(), 1)   # runner is mid-turn
    await agen.aclose()                          # client disconnects → GeneratorExit
    # The finally must have cancelled AND reaped the runner.
    assert cancelled.is_set()


async def test_sse_normal_completion_emits_start_tokens_end():
    class FakeOrch:
        session_id = "aud7_session"

        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            await on_token("hel")
            await on_token("lo")
            return "hello"

    events = [_payload(c) async for c in web._chat_event_stream(FakeOrch(), "hi", "friday", "friday")]
    assert events[0] == {"type": "start", "agent": "friday"}
    assert [e["text"] for e in events if e["type"] == "token"] == ["hel", "lo"]
    # `pending_approvals` rides on every end event (empty when the turn queued
    # nothing), so a client never has to branch on whether the key is there; so
    # do H677's `warming` (false once the boot warm-up is over) and H674's
    # `notices` (empty when the turn had nothing to say beside its reply).
    usage = events[-1].pop("usage")
    assert usage["usage_basis"] == usage["cost_basis"] == "measured_zero"
    assert usage["api_calls"] == 0
    assert events[-1].pop("runtime_stops") == []
    assert events[-1] == {"type": "end", "agent": "friday", "text": "hello",
                          "session_id": "aud7_session",
                          "pending_approvals": [], "warming": False, "notices": [], "outcome": None}


async def test_sse_runner_error_surfaces_as_end_event():
    class FakeOrch:
        async def handle_input_stream(self, message, channel, on_token, agent_override=None):
            raise RuntimeError("boom")

    events = [_payload(c) async for c in web._chat_event_stream(FakeOrch(), "hi", "jarvis", None)]
    assert events[-1]["type"] == "end"
    assert "Eroare internă" in events[-1]["text"]


# ── F9 — add_turn persistence off the event loop ───────────────────
async def test_add_turn_writes_snapshot_off_the_event_loop(monkeypatch, tmp_path):
    main_thread = threading.main_thread()
    seen = {}
    monkeypatch.setattr(conv, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    save = conv.save_memory
    append = conv.ConversationMemory._append_log_dict

    def observe_save(session_id, turns, **metadata):
        seen["off_loop"] = threading.current_thread() is not main_thread
        seen["turns"] = len(turns)
        seen["revision"] = metadata["revision"]
        save(session_id, turns, **metadata)

    def observe_append(self, sid, turn):
        seen["append_off_loop"] = threading.current_thread() is not main_thread
        append(self, sid, turn)

    monkeypatch.setattr(conv, "save_memory", observe_save)
    monkeypatch.setattr(conv.ConversationMemory, "_append_log_dict", observe_append)

    cm = conv.ConversationMemory(persist=True)
    await cm.add_turn("session_aud7_offloop", "user", "hello")

    assert seen["off_loop"] is True      # the snapshot ran in a worker thread, not the loop
    assert seen["append_off_loop"] is True
    assert seen["turns"] == 1
    assert seen["revision"] == 1
    snapshot = json.loads((tmp_path / "session_aud7_offloop.json").read_text())
    assert snapshot["revision"] == 1
    assert [turn["content"] for turn in snapshot["turns"]] == ["hello"]
    logged = json.loads((tmp_path / "session_aud7_offloop.jsonl").read_text())
    assert logged == snapshot["turns"][0]


async def test_add_turn_keeps_per_turn_snapshot_durability(monkeypatch, tmp_path):
    saves = []
    monkeypatch.setattr(conv, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    save = conv.save_memory

    def observe_save(sid, turns, **metadata):
        save(sid, turns, **metadata)
        snapshot = json.loads((tmp_path / f"{sid}.json").read_text())
        saves.append((sid, snapshot["revision"], [turn["content"] for turn in snapshot["turns"]]))

    monkeypatch.setattr(conv, "save_memory", observe_save)

    cm = conv.ConversationMemory(persist=True)
    await cm.add_turn("session_aud7_dura", "user", "a")
    await cm.add_turn("session_aud7_dura", "assistant", "b")

    # Full snapshot still written EVERY turn (growing) — durability unchanged.
    assert saves == [("session_aud7_dura", 1, ["a"]), ("session_aud7_dura", 2, ["a", "b"])]
    logged = [json.loads(line) for line in (tmp_path / "session_aud7_dura.jsonl").read_text().splitlines()]
    assert [turn["content"] for turn in logged] == ["a", "b"]
