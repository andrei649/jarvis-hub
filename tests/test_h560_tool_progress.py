"""H560 — tool progress in a streamed chat completion (Hermes ``hermes.tool.progress``).

Asked for with ``stream_options.include_tool_progress``, the turn's own tool events arrive
as typed ``nerva.tool.progress`` frames between the role chunk and the answer: the tool,
the call id and its stage only — never arguments or results, never another turn's tools.
Not asked for, the stream is exactly the plain ``data:`` chunks a strict client expects.
"""

from __future__ import annotations

import json

from agents.core.observability.tool_events import ToolEventLog
from agents.core.openai_api import protocol
from tests.test_g12_openai_compat import (  # noqa: F401 - pytest fixtures
    _auth,
    _chat,
    _Hub,
    _key,
    client,
    enabled,
    settings,
    store,
)

TRAIL = ToolEventLog()


class _ToolHub(_Hub):
    async def _stream_turn(self, text, channel, on_token, agent_override, session_id):
        TRAIL.record({"event": "tool_requested", "tool": "file_read", "call_id": "c1", "status": "requested",
                      "args": {"path": "/etc/shadow"}})
        TRAIL.record({"event": "tool_result", "tool": "file_read", "call_id": "c1", "status": "ok",
                      "result": "root:secret"})
        TRAIL.record({"event": "todo_updated", "tool": "todo"})
        return await super()._stream_turn(text, channel, on_token, agent_override, session_id)


def _blocks(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        event = lines[0][len("event: "):] if lines[0].startswith("event: ") else None
        data = lines[-1][len("data: "):]
        out.append((event, data if data == "[DONE]" else json.loads(data)))
    return out


def test_tool_progress_frames_only_when_asked(enabled, store, client, tmp_path, monkeypatch):
    from agents import web

    hub = _ToolHub(tmp_path)
    monkeypatch.setattr(web, "orch", hub.orch)
    key, _ = _key(store)                                   # a guest key: its own turn's tools only
    TRAIL.record({"event": "tool_result", "tool": "other_turn_tool", "call_id": "x", "status": "ok"})
    asked = _blocks(client.post("/v1/chat/completions", headers=_auth(key), json=_chat(
        stream=True, stream_options={"include_tool_progress": True})).text)
    typed = [data for event, data in asked if event == protocol.TOOL_PROGRESS_EVENT]
    assert typed == [
        {"object": "nerva.tool.progress", "tool": "file_read", "stage": "requested", "call_id": "c1",
         "status": "requested"},
        {"object": "nerva.tool.progress", "tool": "file_read", "stage": "completed", "call_id": "c1", "status": "ok"},
    ]
    assert "shadow" not in json.dumps(asked) and "root:secret" not in json.dumps(asked)
    plain = [data for event, data in asked if event is None]
    assert plain[-1] == "[DONE]" and plain[0]["choices"][0]["delta"]["role"] == "assistant"
    first_tool = next(i for i, (event, _) in enumerate(asked) if event)
    answer = next(i for i, (_, data) in enumerate(asked) if isinstance(data, dict)
                  and data.get("choices") and data["choices"][0]["delta"].get("content"))
    assert first_tool < answer                                  # progress arrives before the answer

    quiet = _blocks(client.post("/v1/chat/completions", headers=_auth(key), json=_chat(stream=True)).text)
    assert all(event is None for event, _ in quiet)             # strict clients see plain chunks


def test_tool_progress_payload_is_bounded():
    assert protocol.tool_progress({"event": "tool_heartbeat", "tool": "t" * 500, "call_id": "c" * 500,
                                   "status": "s" * 500}) == {
        "object": "nerva.tool.progress", "tool": "t" * 128, "stage": "running", "call_id": "c" * 128,
        "status": "running"}
    # H560 review: a failed call's status is its free-text reason; the frame carries a fixed word.
    failed = protocol.tool_progress({"event": "tool_failed", "tool": "file_read", "call_id": "c",
                                     "status": "permission denied: /home/owner/secret.txt"})
    assert failed["status"] == "failed" and "secret" not in json.dumps(failed)
    assert protocol.tool_progress({"event": "todo_updated", "tool": "todo"}) is None
    assert protocol.tool_progress({"event": "tool_result"}) is None
    assert protocol.tool_progress("nope") is None
