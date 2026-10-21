"""H297 — a named tool call returns a bounded, well-formed result.

Three gaps closed here: a multimodal content-parts envelope (text + image parts,
validated and delivered to an image-capable provider), a sanitised, length-bounded
error message beside ``tool_error``, and sync handlers bridged onto a worker thread.
"""
from __future__ import annotations

import asyncio
import base64
import functools
import json
import threading

import pytest

from agents.core import agent_runtime
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.tool_dialects import anthropic_messages
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.security.secret_broker import SecretBroker
from agents.core.tool_rpc import (
    MAX_ERROR_CHARS,
    MAX_IMAGE_PARTS,
    ToolContent,
    ToolRPCServer,
    current_tool_actor,
    sanitize_error,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


class _Task:
    def __init__(self, payload, agent=None):
        self.kind = "toolrpc.x"
        self.payload = payload
        self.agent = agent


# ── sanitised, bounded error message ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_handler_error_carries_a_sanitised_bounded_message():
    broker = SecretBroker()
    broker.put("db", "hunter2-very-secret-value")
    server = ToolRPCServer(secret_broker=broker)

    async def boom(args):
        raise FileNotFoundError(
            "no such file: /tmp/x\n\x1b[31mtoken hunter2-very-secret-value\u200b"
            + " pad" * 400)

    server.register_tool("boom", boom)
    out = await server.handle({"tool": "boom", "args": {}})
    assert out["ok"] is False and out["reason"] == "tool_error" and out["tool"] == "boom"
    error = out["error"]
    assert error.startswith("FileNotFoundError: no such file: /tmp/x")
    assert "hunter2-very-secret-value" not in error
    assert "\n" not in error and "\x1b" not in error and "\u200b" not in error
    assert len(error) <= MAX_ERROR_CHARS and error.endswith("…")


@pytest.mark.asyncio
async def test_handler_error_redacts_pattern_secrets_without_a_broker():
    server = ToolRPCServer()
    key = "sk-ant-api03-" + "A" * 90

    async def boom(args):
        raise RuntimeError(f"auth failed for {key}")

    server.register_tool("boom", boom)
    out = await server.handle({"tool": "boom", "args": {}})
    assert out["reason"] == "tool_error"
    assert key not in out["error"] and "[REDACTED" in out["error"]
    assert out["error"].startswith("RuntimeError: auth failed for")


def test_sanitize_error_bare_exception_is_its_type_name():
    assert sanitize_error(ValueError()) == "ValueError"
    assert len(sanitize_error(ValueError("x" * 5000), limit=50)) == 50


@pytest.mark.asyncio
async def test_approved_execute_error_also_carries_the_bounded_message():
    server = ToolRPCServer(enqueue=lambda *a, **k: 7)

    async def boom(args):
        raise PermissionError("denied by remote\r\nsecond line")

    server.register_tool("send", boom, gated=True)
    out = await server.execute(_Task({"tool": "send", "args": {}}))
    assert out == {"status": "failed", "reason": "tool_error", "tool": "send",
                   "error": "PermissionError: denied by remote second line"}


# ── sync-handler bridging ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_handler_runs_on_a_worker_thread_with_the_call_context():
    server = ToolRPCServer()
    seen = {}

    def sync_tool(args):
        seen["thread"] = threading.get_ident()
        seen["actor"] = current_tool_actor()
        return {"double": args["n"] * 2}

    server.register_tool("double", sync_tool)
    out = await server.handle({"tool": "double", "args": {"n": 21}}, actor="atlas")
    assert out == {"ok": True, "tool": "double", "result": {"double": 42}}
    assert seen["thread"] != threading.get_ident()
    assert seen["actor"] == "atlas"


@pytest.mark.asyncio
async def test_blocking_sync_handler_does_not_stall_the_event_loop():
    server = ToolRPCServer()
    gate = threading.Event()

    def blocking(args):
        assert gate.wait(5), "the loop never ran while the handler blocked"
        return {"released": True}

    server.register_tool("blocking", blocking)

    async def release():
        await asyncio.sleep(0.01)
        gate.set()

    out, _ = await asyncio.gather(server.handle({"tool": "blocking", "args": {}}), release())
    assert out["result"] == {"released": True}


@pytest.mark.asyncio
async def test_sync_handler_error_is_bounded_like_an_async_one():
    server = ToolRPCServer()

    def bad(args):
        raise KeyError("missing")

    server.register_tool("bad", bad)
    out = await server.handle({"tool": "bad", "args": {}})
    assert out == {"ok": False, "reason": "tool_error", "tool": "bad", "error": "KeyError: 'missing'"}


@pytest.mark.asyncio
async def test_sync_callable_returning_a_coroutine_and_async_partial_are_awaited():
    server = ToolRPCServer()

    async def impl(args, *, suffix=""):
        return {"v": f"{args['v']}{suffix}"}

    server.register_tool("lam", lambda args: impl(args, suffix="!"))
    server.register_tool("part", functools.partial(impl, suffix="?"))
    assert (await server.handle({"tool": "lam", "args": {"v": "a"}}))["result"] == {"v": "a!"}
    assert (await server.handle({"tool": "part", "args": {"v": "b"}}))["result"] == {"v": "b?"}


# ── multimodal content envelope ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_content_becomes_a_well_formed_multimodal_envelope():
    broker = SecretBroker()
    broker.put("token", "tok-abcdef-123456")
    server = ToolRPCServer(secret_broker=broker)

    async def shot(args):
        return ToolContent(
            [ToolContent.text("screen\U000E0041 of tok-abcdef-123456"),
             ToolContent.image(PNG, "image/png"),
             ToolContent.image(base64.b64encode(JPEG).decode(), "image/jpeg")],
            structured={"width": 2},
        )

    server.register_tool("screenshot", shot)
    out = await server.handle({"tool": "screenshot", "args": {}})
    assert out["ok"] is True and out["tool"] == "screenshot"
    assert out["result"] == {"width": 2}
    text, png, jpeg = out["content"]
    assert text == {"type": "text", "text": "screen of [REDACTED:token]"}
    assert png == {"type": "image", "media_type": "image/png",
                   "data": base64.b64encode(PNG).decode(), "bytes": len(PNG)}
    assert jpeg["media_type"] == "image/jpeg" and base64.b64decode(jpeg["data"]) == JPEG
    json.dumps(out, allow_nan=False)  # plain JSON end to end


@pytest.mark.parametrize("parts, cause", [
    ([], "content_empty"),
    ([{"type": "video", "data": "x"}], "part_type"),
    ([{"type": "text", "text": 5}], "text_not_string"),
    ([ToolContent.image(PNG, "image/svg+xml")], "image_media_type"),
    ([ToolContent.image(JPEG, "image/png")], "image_signature_mismatch"),
    ([ToolContent.image(b"RIFF\x00\x00\x00\x00WAVE", "image/webp")], "image_signature_mismatch"),
    ([ToolContent.image("not base64!!", "image/png")], "image_not_base64"),
    ([ToolContent.image(PNG, "image/png")] * (MAX_IMAGE_PARTS + 1), "too_many_images"),
])
@pytest.mark.asyncio
async def test_malformed_content_is_refused_as_invalid_result(parts, cause):
    server = ToolRPCServer()

    async def bad(args):
        return ToolContent(parts)

    server.register_tool("bad", bad)
    out = await server.handle({"tool": "bad", "args": {}})
    assert out == {"ok": False, "reason": "invalid_result", "tool": "bad", "error": cause}


@pytest.mark.asyncio
async def test_webp_and_gif_are_accepted():
    server = ToolRPCServer()

    async def pics(args):
        return ToolContent([ToolContent.image(WEBP, "image/webp"),
                            ToolContent.image(b"GIF89a" + b"\x00" * 8, "image/gif")])

    server.register_tool("pics", pics)
    out = await server.handle({"tool": "pics", "args": {}})
    assert [p["media_type"] for p in out["content"]] == ["image/webp", "image/gif"]
    assert out["result"] is None


@pytest.mark.asyncio
async def test_a_plain_dict_cannot_promote_itself_into_image_parts():
    server = ToolRPCServer()
    page = {"content": [{"type": "image", "media_type": "image/png", "data": "AAAA"}]}

    async def fetch(args):
        return page

    server.register_tool("fetch", fetch)
    out = await server.handle({"tool": "fetch", "args": {}})
    assert out == {"ok": True, "tool": "fetch", "result": page}
    assert "content" not in out


@pytest.mark.asyncio
async def test_approved_execute_returns_the_content_envelope():
    server = ToolRPCServer(enqueue=lambda *a, **k: 3)

    async def render(args):
        return ToolContent([ToolContent.text("done"), ToolContent.image(PNG, "image/png")])

    server.register_tool("render", render, gated=True)
    out = await server.execute(_Task({"tool": "render", "args": {}}))
    assert out["status"] == "ok" and out["tool"] == "render"
    assert [p["type"] for p in out["content"]] == ["text", "image"]


# ── delivery through the tool loop ───────────────────────────────────────────

def _call(number: int = 1) -> ToolCall:
    return ToolCall(id=f"call-{number}", name="shot", raw_arguments="{}", arguments={})


class _Backend:
    supports_tools = True

    def __init__(self, *turns, images: bool):
        self.turns = list(turns)
        self.seen: list[list[dict]] = []
        self.supports_tool_result_images = images

    async def generate_tool_turn(self, *, messages, **_kwargs):
        self.seen.append(messages)
        return self.turns.pop(0)


def _shot_server() -> ToolRPCServer:
    server = ToolRPCServer()

    async def shot(args):
        return ToolContent([ToolContent.text("the screen"), ToolContent.image(PNG, "image/png")])

    server.register_tool("shot", shot)
    return server


async def _run(backend):
    runtime = AgentToolRuntime(_shot_server(), enabled=lambda: True)
    return await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="look",
                             system="sys", max_tokens=64, temperature=0.0)


@pytest.mark.asyncio
async def test_image_capable_backend_receives_the_image_beside_a_descriptor():
    backend = _Backend(ToolTurn(tool_calls=[_call()]), ToolTurn(content="seen"), images=True)
    assert await _run(backend) == "seen"
    tool_message = [m for m in backend.seen[1] if m.get("role") == "tool"][0]
    assert tool_message["images"] == [{"media_type": "image/png",
                                       "data": base64.b64encode(PNG).decode()}]
    shown = json.loads(tool_message["content"])
    text_part, descriptor = shown["content"]
    assert text_part == {"type": "text", "text": "the screen"}
    assert descriptor["type"] == "image" and descriptor["bytes"] == len(PNG)
    assert "data" not in descriptor and len(descriptor["sha256"]) == 16


@pytest.mark.asyncio
async def test_text_only_backend_never_receives_image_bytes():
    backend = _Backend(ToolTurn(tool_calls=[_call()]), ToolTurn(content="ok"), images=False)
    assert await _run(backend) == "ok"
    tool_message = [m for m in backend.seen[1] if m.get("role") == "tool"][0]
    assert "images" not in tool_message
    assert base64.b64encode(PNG).decode() not in tool_message["content"]


def test_split_images_caps_attachments_per_turn():
    spent = {"images": agent_runtime._MAX_IMAGES_PER_TURN - 1}
    envelope = {"ok": True, "tool": "t", "result": None, "content": [
        {"type": "image", "media_type": "image/png", "data": "QQ==", "bytes": 1},
        {"type": "image", "media_type": "image/png", "data": "Qg==", "bytes": 1},
    ]}
    described, images = agent_runtime._split_images(envelope, spent)
    assert len(images) == 1 and spent["images"] == agent_runtime._MAX_IMAGES_PER_TURN
    assert "omitted" not in described["content"][0]
    assert described["content"][1]["omitted"] == "per_turn_image_cap"
    failed = {"ok": False, "reason": "x", "content": envelope["content"]}
    assert agent_runtime._split_images(failed, spent) == (failed, [])


def test_anthropic_tool_result_carries_image_blocks():
    data = base64.b64encode(PNG).decode()
    _system, converted = anthropic_messages([
        {"role": "user", "content": "look"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "shot", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{\"ok\": true}",
         "images": [{"media_type": "image/png", "data": data},
                    {"media_type": "text/html", "data": "x"}]},
    ])
    block = converted[-1]["content"][0]
    assert block["type"] == "tool_result"
    assert block["content"] == [
        {"type": "text", "text": "{\"ok\": true}"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
    ]


def test_claude_backend_declares_tool_result_images_and_the_base_does_not():
    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.base import LLMBackend
    assert ClaudeBackend.supports_tool_result_images is True
    assert LLMBackend.supports_tool_result_images is False
