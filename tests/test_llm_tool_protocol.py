"""Contract tests for provider-neutral LLM tool turns."""

import pytest

from agents.core.llm.base import LLMBackend, LMStudioBackend
from agents.core.llm.tool_protocol import (
    ToolCall,
    ToolSpec,
    ToolTurn,
    parse_openai_tool_calls,
)


def test_tool_spec_uses_exact_openai_function_schema():
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    assert ToolSpec("echo", "Echo a value", schema).as_openai() == {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echo a value",
            "parameters": schema,
        },
    }


def test_tool_call_openai_shape_preserves_provider_argument_string():
    raw_arguments = '{ "value" : "hi" }'
    call = ToolCall(
        id="call-1",
        name="echo",
        raw_arguments=raw_arguments,
        arguments={"value": "hi"},
    )

    assert call.as_openai() == {
        "id": "call-1",
        "type": "function",
        "function": {"name": "echo", "arguments": raw_arguments},
    }


def test_tool_turn_assistant_message_omits_empty_tool_calls():
    assert ToolTurn(content="plain answer").as_assistant_message() == {
        "role": "assistant",
        "content": "plain answer",
    }


def test_tool_turn_assistant_message_includes_ordered_tool_calls():
    first = ToolCall(id="call-1", name="echo", raw_arguments='{"value":"one"}')
    second = ToolCall(id="call-2", name="echo", raw_arguments='{"value":"two"}')

    assert ToolTurn(tool_calls=(first, second)).as_assistant_message() == {
        "role": "assistant",
        "content": "",
        "tool_calls": [first.as_openai(), second.as_openai()],
    }


def test_parse_openai_tool_calls_preserves_raw_and_parses_arguments():
    raw_arguments = '{ "value" : "hi" }'

    calls = parse_openai_tool_calls(
        [
            {
                "id": "call-1",
                "function": {"name": "echo", "arguments": raw_arguments},
            }
        ]
    )

    assert calls == (
        ToolCall(
            id="call-1",
            name="echo",
            raw_arguments=raw_arguments,
            arguments={"value": "hi"},
        ),
    )


def test_parse_openai_tool_calls_marks_invalid_json_without_raising():
    calls = parse_openai_tool_calls(
        [
            {
                "id": "call-1",
                "function": {"name": "echo", "arguments": "{broken"},
            }
        ]
    )

    assert calls[0].arguments is None
    assert calls[0].parse_error == "invalid_json"
    assert calls[0].raw_arguments == "{broken"


@pytest.mark.parametrize("raw_arguments", ["[]", "42", "null"])
def test_parse_openai_tool_calls_rejects_non_object_json(raw_arguments):
    calls = parse_openai_tool_calls(
        [
            {
                "id": "call-1",
                "function": {"name": "echo", "arguments": raw_arguments},
            }
        ]
    )

    assert calls[0].arguments is None
    assert calls[0].parse_error == "arguments_not_object"
    assert calls[0].raw_arguments == raw_arguments


class _TextBackend(LLMBackend):
    def __init__(self):
        self.generate_kwargs = None

    async def generate(
        self, model, prompt, system="", max_tokens=1024, temperature=0.7
    ):
        self.generate_kwargs = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        return "plain answer"


async def test_generate_tool_turn_falls_back_to_generate_for_text_backends():
    backend = _TextBackend()

    turn = await backend.generate_tool_turn(
        model="m",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        tools=[],
        max_tokens=321,
        temperature=0.2,
    )

    assert backend.supports_tools is False
    assert turn.content == "plain answer"
    assert turn.tool_calls == ()
    assert backend.generate_kwargs == {
        "model": "m",
        "prompt": "hello",
        "system": "sys",
        "max_tokens": 321,
        "temperature": 0.2,
    }


async def test_generate_tool_turn_joins_systems_and_uses_last_user_or_tool():
    backend = _TextBackend()

    await backend.generate_tool_turn(
        model="m",
        messages=[
            {"role": "system", "content": "first system"},
            {"role": "system", "content": "second system"},
            {"role": "user", "content": "older user content"},
            {"role": "assistant", "content": "ignored assistant content"},
            {"role": "tool", "content": "latest tool content"},
            {"role": "assistant", "content": "also ignored"},
        ],
        tools=[],
    )

    assert backend.generate_kwargs["system"] == "first system\n\nsecond system"
    assert backend.generate_kwargs["prompt"] == "latest tool content"


class _FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class _RecordingAsyncClient:
    def __init__(self, response_data):
        self.response_data = response_data
        self.posts = []

    async def post(self, path, json):
        self.posts.append({"path": path, "json": json})
        return _FakeResponse(self.response_data)


class _FailingAsyncClient:
    async def post(self, path, json):
        raise ConnectionError("LM Studio is down")


def _lmstudio_backend(response_data):
    backend = LMStudioBackend.__new__(LMStudioBackend)
    backend.base_url = "http://lmstudio.test"
    backend.client = _RecordingAsyncClient(response_data)
    return backend


async def test_lmstudio_tool_turn_sends_tools_and_parses_tool_calls():
    response_data = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-echo",
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "arguments": '{"value":"hi"}',
                            },
                        }
                    ],
                },
            }
        ]
    }
    backend = _lmstudio_backend(response_data)
    messages = [{"role": "user", "content": "Say hi through echo"}]
    original_messages = [message.copy() for message in messages]
    tool = ToolSpec(
        "echo",
        "Echo a value",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )

    turn = await backend.generate_tool_turn(
        model="local-model",
        messages=messages,
        tools=[tool],
        max_tokens=0,
        temperature=0.2,
    )

    assert backend.supports_tools is True
    assert backend.client.posts == [
        {
            "path": "/v1/chat/completions",
            "json": {
                "model": "local-model",
                "messages": original_messages,
                "temperature": 0.2,
                "stream": False,
                "tools": [tool.as_openai()],
                "tool_choice": "auto",
            },
        }
    ]
    assert messages == original_messages
    assert turn == ToolTurn(
        tool_calls=(
            ToolCall(
                id="call-echo",
                name="echo",
                raw_arguments='{"value":"hi"}',
                arguments={"value": "hi"},
            ),
        ),
        finish_reason="tool_calls",
    )


async def test_lmstudio_content_only_response_becomes_final_tool_turn():
    backend = _lmstudio_backend(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "Final answer"},
                }
            ]
        }
    )

    turn = await backend.generate_tool_turn(
        model="local-model",
        messages=[{"role": "user", "content": "Answer directly"}],
        tools=[],
        max_tokens=123,
    )

    assert turn == ToolTurn(content="Final answer", finish_reason="stop")
    assert backend.client.posts[0]["json"]["max_tokens"] == 123


async def test_lmstudio_malformed_tool_arguments_return_parse_error():
    backend = _lmstudio_backend(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-broken",
                                "type": "function",
                                "function": {
                                    "name": "echo",
                                    "arguments": "{broken",
                                },
                            }
                        ],
                    },
                }
            ]
        }
    )

    turn = await backend.generate_tool_turn(
        model="local-model",
        messages=[{"role": "user", "content": "Echo this"}],
        tools=[ToolSpec("echo")],
    )

    assert turn.tool_calls[0].arguments is None
    assert turn.tool_calls[0].parse_error == "invalid_json"
    assert turn.tool_calls[0].raw_arguments == "{broken"


async def test_lmstudio_tool_turn_returns_degraded_reply_when_request_fails():
    backend = LMStudioBackend.__new__(LMStudioBackend)
    backend.base_url = "http://lmstudio.test"
    backend.client = _FailingAsyncClient()

    turn = await backend.generate_tool_turn(
        model="local-model",
        messages=[{"role": "user", "content": "Hello"}],
        tools=[ToolSpec("echo")],
    )

    assert "can't reach the local LM Studio model" in turn.content
    assert turn.tool_calls == ()
    assert turn.finish_reason is None
