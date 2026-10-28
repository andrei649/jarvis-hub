"""H297 (review round 3) — tool-result images on the owner's real path.

* production never hands the tool loop a bare provider: ``Agent`` binds the
  guardrails policy first, and the loop must still see that Claude carries images;
* the guardrails wrapper passes the ``images`` key through to the provider;
* ``file_read`` decodes an image before attaching it: a corrupt one is refused by
  name and one past the provider's 8,000 px side limit is scaled down to fit;
* a provider that refuses a request carrying images as invalid (400/413) does not
  end the turn: the images are detached and the request is sent once more without
  them; a transient failure (429, 529, 5xx, 401, a transport error) is not a refusal:
  the turn ends with its error and nothing is resent blind (review round 4);
* a model-pinned job charges an attached image its flat token cost, not its base64
  text, so reading an ordinary screenshot does not refuse the job (review round 4).
"""
from __future__ import annotations

import base64
import io
import json
import os
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from agents.core import agent_runtime
from agents.core.agent import Agent
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.file_tools import (
    MAX_IMAGE_SIDE,
    FileScope,
    FileTools,
    SnapshotStore,
    register_file_tools,
)
from agents.core.llm import job_selection
from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.provider_request import ProfileRequestRefused
from agents.core.llm.tool_protocol import PROVIDER_REJECTED_FINISH, ToolSpec, ToolTurn
from agents.core.security import bind_guardrails
from agents.core.security.guardrails import GuardrailsEngine, RedactionMode
from agents.core.tool_rpc import ToolContent, ToolRPCServer

MODEL = "claude-sonnet-4-5"


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(out, format="PNG")
    return out.getvalue()


def _tool_results(payload: dict) -> list[dict]:
    return [block for message in payload["messages"] if isinstance(message["content"], list)
            for block in message["content"] if block.get("type") == "tool_result"]


def _file_server(tmp_path, name: str, data: bytes):
    root = tmp_path / "files"
    root.mkdir()
    (root / name).write_bytes(data)
    server = ToolRPCServer()
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))
    assert "file_read" in register_file_tools(server, tools, enabled=True)
    return server, root / name


def _claude(monkeypatch, replies: list) -> tuple[ClaudeBackend, list[dict]]:
    backend = ClaudeBackend("test-key", model=MODEL)
    payloads: list[dict] = []

    async def post(payload):
        payloads.append(json.loads(json.dumps(payload)))
        reply = replies.pop(0)
        if isinstance(reply, tuple):   # (error text, HTTP status or None)
            return None, reply[0], reply[1]
        return (None, reply, None) if isinstance(reply, str) else (reply, "", 200)

    monkeypatch.setattr(backend, "_post_messages", post)
    return backend, payloads


def _read_call(path) -> dict:
    return {"content": [{"type": "tool_use", "id": "toolu_1", "name": "file_read",
                         "input": {"path": str(path)}}], "stop_reason": "tool_use"}


def _answer(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}


# ── the guardrails wrapper does not hide the capability ─────────────────────

def test_guarded_claude_backend_still_carries_tool_result_images():
    claude = ClaudeBackend("test-key", model=MODEL)
    guarded = bind_guardrails(GuardrailsEngine(), claude)
    assert guarded is not claude and guarded.supports_tools is True
    assert agent_runtime._tool_result_images_supported(claude) is True
    assert agent_runtime._tool_result_images_supported(guarded) is True


def test_a_guarded_text_only_backend_does_not():
    class _TextOnly:
        supports_tools = True
        supports_tool_result_images = False

    assert agent_runtime._tool_result_images_supported(
        bind_guardrails(GuardrailsEngine(), _TextOnly())) is False
    assert agent_runtime._tool_result_images_supported(object()) is False
    assert agent_runtime._tool_result_images_supported(GuardrailsEngine()) is False


@pytest.mark.asyncio
async def test_guardrails_pass_image_rows_through_to_the_provider():
    seen: list[list[dict]] = []

    class _Recorder:
        supports_tools = True

        async def generate_tool_turn(self, *, messages, **_kwargs):
            seen.append(messages)
            return ToolTurn(content="ok")

    images = [{"media_type": "image/png", "data": base64.b64encode(_png(2, 2)).decode()}]
    guarded = GuardrailsEngine(mode=RedactionMode.WARN).bind(_Recorder())
    await guarded.generate_tool_turn(
        model=MODEL, tools=[ToolSpec("file_read")],
        messages=[{"role": "user", "content": "look"},
                  {"role": "tool", "tool_call_id": "c1", "content": "shot", "images": images}])
    assert seen[0][1]["images"] == images


# ── the owner's path: Agent -> guardrails -> tool loop -> Claude ────────────

@pytest.mark.asyncio
async def test_agent_process_sends_file_read_image_through_guardrails(tmp_path, monkeypatch):
    png = _png(3, 2)
    server, path = _file_server(tmp_path, "shot.png", png)
    backend, payloads = _claude(monkeypatch, [_read_call(path), _answer("a dark rectangle")])
    router = SimpleNamespace(model_manager=None, select_backend=lambda *_: (backend, MODEL, "claude"))
    agent = Agent("jarvis", {"name": "Jarvis"}, router)
    agent.guardrails = GuardrailsEngine(mode=RedactionMode.WARN)
    agent._gen_params = lambda _: (256, 0.0)
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)

    assert await agent.process("what is in shot.png?", {}) == "a dark rectangle"
    assert agent.guardrails.stats()["counters"]["scanned"] > 0
    (result,) = _tool_results(payloads[1])
    text, image = result["content"]
    assert text["type"] == "text" and "3x2 px" in text["text"]
    assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                 "data": base64.b64encode(png).decode()}}


# ── file_read decodes what it attaches ──────────────────────────────────────

@pytest.mark.asyncio
async def test_corrupt_png_is_refused_not_attached(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    bad = root / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(200))
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))
    refused = await tools.read_file({"path": str(bad)})
    assert not isinstance(refused, ToolContent)
    assert refused["ok"] is False and refused["reason"] == "image_unreadable"
    assert "raw=true" in refused["detail"]
    paged = await tools.read_file({"path": str(bad), "raw": True})
    assert paged["ok"] is True and paged["bytes"] == 208


@pytest.mark.asyncio
async def test_truncated_png_is_refused(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    whole = _png(64, 64)
    cut = root / "cut.png"
    cut.write_bytes(whole[: len(whole) // 2])
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))
    refused = await tools.read_file({"path": str(cut)})
    assert isinstance(refused, dict) and refused["reason"] == "image_unreadable"


@pytest.mark.asyncio
async def test_tall_screenshot_is_scaled_under_the_side_limit(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    tall = root / "tall.png"
    tall.write_bytes(_png(10, 9000))
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))
    result = await tools.read_file({"path": str(tall)})
    assert isinstance(result, ToolContent)
    sent = result.parts[1]["data"]
    with Image.open(io.BytesIO(sent)) as decoded:
        assert max(decoded.size) <= MAX_IMAGE_SIDE == 8000
        assert decoded.size[1] == 8000
    assert result.structured["original_height"] == 9000
    assert result.structured["height"] == 8000
    assert "Scaled down from 10x9000 px" in result.parts[0]["text"]


@pytest.mark.asyncio
async def test_image_with_too_many_pixels_is_refused_by_name(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    huge = root / "huge.png"
    out = io.BytesIO()
    Image.new("1", (8000, 6000)).save(out, format="PNG")
    huge.write_bytes(out.getvalue())
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))
    refused = await tools.read_file({"path": str(huge)})
    assert isinstance(refused, dict) and refused["reason"] == "image_dimensions_too_large"
    assert (refused["width"], refused["height"]) == (8000, 6000)


# ── a provider refusal detaches the images and resends once ─────────────────

@pytest.mark.asyncio
async def test_provider_rejection_of_an_image_request_retries_without_images(tmp_path, monkeypatch):
    server, path = _file_server(tmp_path, "shot.png", _png(4, 4))
    rejected = "[Claude API error: Client error '400 Bad Request': Could not process image]"
    backend, payloads = _claude(monkeypatch, [_read_call(path), (rejected, 400),
                                              _answer("I could not see it")])
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    runtime = AgentToolRuntime(server, enabled=lambda: True)
    answer = await runtime.run(agent_id="jarvis", backend=bind_guardrails(GuardrailsEngine(), backend),
                               model=MODEL, prompt="what is in shot.png?", system="sys",
                               max_tokens=64, temperature=0.0, event_sink=sink)
    assert answer == "I could not see it"
    assert len(payloads) == 3
    (with_image,) = _tool_results(payloads[1])
    assert [part["type"] for part in with_image["content"]] == ["text", "image"]
    (retried,) = _tool_results(payloads[2])
    parts = retried["content"] if isinstance(retried["content"], list) else [retried["content"]]
    assert not any(isinstance(part, dict) and part.get("type") == "image" for part in parts)
    retried_text = json.dumps(retried["content"])
    assert "provider_rejected" in retried_text
    assert any(e.get("event") == "tool_result_images_detached" for e in events)


@pytest.mark.asyncio
async def test_a_provider_error_without_images_is_not_retried(monkeypatch):
    backend, payloads = _claude(monkeypatch, [("[Claude API error: 400]", 400)])
    turn = await backend.generate_tool_turn(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                                            tools=[ToolSpec("file_read")])
    assert turn.finish_reason == PROVIDER_REJECTED_FINISH and turn.content == "[Claude API error: 400]"

    server = ToolRPCServer()

    async def noop(args):
        return {"ok": True}

    server.register_tool("noop", noop, description="noop", input_schema={"type": "object", "properties": {}})
    # Even a real 400 refusal is not retried when the request carried no image.
    backend, payloads = _claude(monkeypatch, [("[Claude API error: 400]", 400)])
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    answer = await runtime.run(agent_id="jarvis", backend=backend, model=MODEL, prompt="hi",
                               system="sys", max_tokens=64, temperature=0.0)
    assert answer == "[Claude API error: 400]"
    assert len(payloads) == 1


# ── review round 4: only a real refusal detaches; a transient failure keeps the images ──

def _http_claude(handler) -> ClaudeBackend:
    """A ClaudeBackend whose real ``_post_messages`` talks to *handler*."""
    backend = ClaudeBackend("test-key", model=MODEL)
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return backend


def _error(status: int, kind: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"type": "error", "error": {"type": kind, "message": message}})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,rejected", [
    (400, True), (413, True), (401, False), (429, False), (500, False), (503, False), (529, False),
])
async def test_only_an_invalid_request_status_is_marked_rejected(status, rejected):
    backend = _http_claude(lambda request: _error(status, "some_error", "m"))
    turn = await backend.generate_tool_turn(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                                            tools=[ToolSpec("file_read")])
    assert turn.content.startswith("[Claude API error:") and str(status) in turn.content
    assert (turn.finish_reason == PROVIDER_REJECTED_FINISH) is rejected


@pytest.mark.asyncio
async def test_a_transport_error_is_not_marked_rejected():
    def handler(request):
        raise httpx.ConnectError("connection reset", request=request)

    turn = await _http_claude(handler).generate_tool_turn(
        model=MODEL, messages=[{"role": "user", "content": "hi"}], tools=[ToolSpec("file_read")])
    assert turn.content.startswith("[Claude API error:") and "connection reset" in turn.content
    assert turn.finish_reason != PROVIDER_REJECTED_FINISH


async def _run_image_turn(tmp_path, backend):
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    server, _ = _file_server(tmp_path, "shot.png", _png(4, 4))
    runtime = AgentToolRuntime(server, enabled=lambda: True)
    answer = await runtime.run(agent_id="jarvis", backend=bind_guardrails(GuardrailsEngine(), backend),
                               model=MODEL, prompt="what is in shot.png?", system="sys",
                               max_tokens=64, temperature=0.0, event_sink=sink)
    return answer, events


def _scripted(tmp_path, sent: list, failure):
    """Answer the first request with a file_read call and every later one with *failure*."""
    path = tmp_path / "files" / "shot.png"

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(200, json=_read_call(path))
        return failure(request, len(sent))
    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 529])
async def test_a_transient_status_on_an_image_request_keeps_the_images(tmp_path, status):
    sent: list[dict] = []
    handler = _scripted(tmp_path, sent, lambda request, n: _error(status, "overloaded_error", "Overloaded"))
    answer, events = await _run_image_turn(tmp_path, _http_claude(handler))
    assert len(sent) == 2   # the tool call, then ONE image request — never a blind resend
    (with_image,) = _tool_results(sent[1])
    assert [part["type"] for part in with_image["content"]] == ["text", "image"]
    assert answer.startswith("[Claude API error:") and str(status) in answer
    assert "provider_rejected" not in json.dumps(sent)
    assert not any(e.get("event") == "tool_result_images_detached" for e in events)


@pytest.mark.asyncio
async def test_a_transport_error_on_an_image_request_keeps_the_images(tmp_path):
    sent: list[dict] = []

    def timeout(request, n):
        raise httpx.ReadTimeout("timed out", request=request)

    answer, events = await _run_image_turn(tmp_path, _http_claude(_scripted(tmp_path, sent, timeout)))
    assert len(sent) == 2
    (with_image,) = _tool_results(sent[1])
    assert [part["type"] for part in with_image["content"]] == ["text", "image"]
    assert answer.startswith("[Claude API error:") and "timed out" in answer
    assert not any(e.get("event") == "tool_result_images_detached" for e in events)


@pytest.mark.asyncio
async def test_a_real_400_on_an_image_request_detaches_and_resends_once(tmp_path):
    sent: list[dict] = []

    def reject_then_answer(request, n):
        if n == 2:
            return _error(400, "invalid_request_error", "Could not process image")
        return httpx.Response(200, json=_answer("I could not see it"))

    answer, events = await _run_image_turn(tmp_path, _http_claude(_scripted(tmp_path, sent, reject_then_answer)))
    assert answer == "I could not see it" and len(sent) == 3
    (with_image,) = _tool_results(sent[1])
    assert [part["type"] for part in with_image["content"]] == ["text", "image"]
    (retried,) = _tool_results(sent[2])
    assert '"type": "image"' not in json.dumps(retried["content"])
    assert "provider_rejected" in json.dumps(retried["content"])
    assert any(e.get("event") == "tool_result_images_detached" for e in events)


# ── review round 4: a model-pinned job charges an image its flat cost ──────────

def _noise_png(target: int) -> bytes:
    side = 64
    while True:
        out = io.BytesIO()
        Image.frombytes("RGB", (side, side), os.urandom(side * side * 3)).save(out, format="PNG")
        if out.tell() >= target:
            return out.getvalue()
        side += 32


@pytest.mark.asyncio
async def test_builtin_tool_image_history_is_owned_without_widening_text_only_history():
    image = base64.b64encode(_noise_png(300_000)).decode("ascii")
    rows = [{"role": "user", "content": "inspect"},
            {"role": "tool", "tool_call_id": "toolu_1", "content": "shot.png",
             "images": [{"media_type": "image/png", "data": image}]}]
    original = json.loads(json.dumps(rows))
    backend = ClaudeBackend("synthetic-key", model=MODEL)
    payload, _ = await backend._tool_payload(MODEL, rows, [], 64, 0.0)
    assert rows == original
    assert image in json.dumps(payload)
    with pytest.raises(ProfileRequestRefused, match="declaration too large"):
        await backend._tool_payload(MODEL, [{"role": "user", "content": "x" * 300_000}],
                                    [], 64, 0.0)
    malformed = [{"role": "tool", "content": "shot.png",
                  "images": [{"media_type": "image/png", "data": "not-base64" * 40_000}]}]
    with pytest.raises(ProfileRequestRefused, match="declaration too large"):
        await backend._tool_payload(MODEL, malformed, [], 64, 0.0)


@pytest.mark.asyncio
async def test_a_model_pinned_job_that_reads_a_screenshot_completes(tmp_path, monkeypatch):
    data = _noise_png(300_000)
    root = tmp_path / "files"
    root.mkdir()
    (root / "shot.png").write_bytes(data)
    server = ToolRPCServer()
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"),
                      max_bytes=len(data) * 2)
    assert "file_read" in register_file_tools(server, tools, enabled=True)
    claude, payloads = _claude(monkeypatch, [_read_call(root / "shot.png"), _answer("noise")])
    with job_selection.selection_scope({"model": MODEL}):
        scoped, model, _route = job_selection.apply_selection(
            SimpleNamespace(), "jarvis", bind_guardrails(GuardrailsEngine(), claude), MODEL, "claude")
        assert isinstance(scoped, job_selection._ScopedBackend)
        assert job_selection.current_selection().lifetime.resolved[2] == 200_000
        runtime = AgentToolRuntime(server, enabled=lambda: True)
        answer = await runtime.run(agent_id="jarvis", backend=scoped, model=model,
                                   prompt="what is in shot.png?", system="sys",
                                   max_tokens=64, temperature=0.0)
    assert answer == "noise"
    assert len(payloads) == 2
    (with_image,) = _tool_results(payloads[1])
    image = with_image["content"][1]
    assert image["type"] == "image"
    assert len(image["source"]["data"]) >= 400_000   # the raw base64 really was sent


def test_a_pinned_job_estimate_charges_each_image_its_flat_cost():
    from agents.core.llm.tokenizer import IMAGE_TOKEN_COST
    assert agent_runtime._IMAGE_TOKEN_COST == IMAGE_TOKEN_COST
    blob = base64.b64encode(os.urandom(150_000)).decode()
    image = {"media_type": "image/png", "data": blob}
    rows = [{"role": "user", "content": "hi"}, {"role": "tool", "content": "shot.png", "images": [image, image]}]
    bare = [{"role": "user", "content": "hi"}, {"role": "tool", "content": "shot.png"}]
    estimate = job_selection._prompt_estimate
    assert estimate((MODEL,), {"messages": rows}) == estimate((MODEL,), {"messages": bare}) + 2 * IMAGE_TOKEN_COST
    assert estimate((MODEL, rows), {}) == estimate((MODEL, bare), {}) + 2 * IMAGE_TOKEN_COST
    assert estimate((MODEL, "a prompt"), {}) > 0
    assert rows[1]["images"] == [image, image]   # the caller's rows are not touched
