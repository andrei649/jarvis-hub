"""Contract tests for provider-neutral LLM tool turns."""

from agents.core.llm.base import LLMBackend
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
