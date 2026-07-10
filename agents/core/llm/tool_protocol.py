"""Provider-neutral values for LLM tool-calling turns."""

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def as_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    raw_arguments: str = "{}"
    arguments: Optional[dict[str, Any]] = field(default_factory=dict)
    parse_error: Optional[str] = None

    def as_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.raw_arguments,
            },
        }


@dataclass(frozen=True)
class ToolTurn:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: Optional[str] = None

    def as_assistant_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [call.as_openai() for call in self.tool_calls]
        return message


def parse_openai_tool_calls(
    raw_calls: list[dict[str, Any]],
) -> tuple[ToolCall, ...]:
    calls = []
    for raw_call in raw_calls:
        function = raw_call.get("function", {})
        raw_arguments = function.get("arguments", "{}")
        try:
            parsed_arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError):
            arguments = None
            parse_error = "invalid_json"
        else:
            if isinstance(parsed_arguments, dict):
                arguments = parsed_arguments
                parse_error = None
            else:
                arguments = None
                parse_error = "arguments_not_object"
        calls.append(
            ToolCall(
                id=raw_call.get("id", ""),
                name=function.get("name", ""),
                raw_arguments=raw_arguments,
                arguments=arguments,
                parse_error=parse_error,
            )
        )
    return tuple(calls)
