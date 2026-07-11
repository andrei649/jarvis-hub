"""Provider-neutral values for LLM tool-calling turns."""

import json
import math
from dataclasses import dataclass, field
from typing import Any

MAX_PARSED_TOOL_CALLS = 33


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
    arguments: dict[str, Any] | None = field(default_factory=dict)
    parse_error: str | None = None

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
    finish_reason: str | None = None

    def as_assistant_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [call.as_openai() for call in self.tool_calls]
        return message


def parse_openai_tool_calls(
    raw_calls: Any,
) -> tuple[ToolCall, ...]:
    """Normalize untrusted provider tool calls into a typed, fail-closed boundary."""
    if not isinstance(raw_calls, list):
        return (_invalid_tool_call("tool_calls_not_array"),)

    calls: list[ToolCall] = []
    for raw_call in raw_calls[:MAX_PARSED_TOOL_CALLS]:
        if not isinstance(raw_call, dict):
            calls.append(_invalid_tool_call("call_not_object"))
            continue

        raw_id = raw_call.get("id", "")
        function = raw_call.get("function")
        if isinstance(function, dict):
            raw_name = function.get("name", "")
            raw_arguments = function.get("arguments", "{}")
        else:
            raw_name = ""
            raw_arguments = ""

        call_id = raw_id if isinstance(raw_id, str) and _valid_unicode(raw_id) else ""
        name = raw_name if isinstance(raw_name, str) and _valid_unicode(raw_name) else ""
        arguments_text = (
            raw_arguments
            if isinstance(raw_arguments, str) and _valid_unicode(raw_arguments)
            else ""
        )

        if not isinstance(raw_id, str):
            calls.append(
                _invalid_tool_call(
                    "id_not_string",
                    name=name,
                    raw_arguments=arguments_text,
                )
            )
            continue
        if not _valid_unicode(raw_id):
            calls.append(
                _invalid_tool_call(
                    "id_invalid_unicode",
                    name=name,
                    raw_arguments=arguments_text,
                )
            )
            continue
        if not isinstance(function, dict):
            calls.append(
                _invalid_tool_call("function_not_object", call_id=call_id)
            )
            continue
        if not isinstance(raw_name, str):
            calls.append(
                _invalid_tool_call(
                    "name_not_string",
                    call_id=call_id,
                    raw_arguments=arguments_text,
                )
            )
            continue
        if not _valid_unicode(raw_name):
            calls.append(
                _invalid_tool_call(
                    "name_invalid_unicode",
                    call_id=call_id,
                    raw_arguments=arguments_text,
                )
            )
            continue
        if not isinstance(raw_arguments, str):
            calls.append(
                _invalid_tool_call(
                    "arguments_not_string",
                    call_id=call_id,
                    name=name,
                )
            )
            continue
        if not _valid_unicode(raw_arguments):
            calls.append(
                _invalid_tool_call(
                    "arguments_invalid_unicode",
                    call_id=call_id,
                    name=name,
                )
            )
            continue

        try:
            parsed_arguments = json.loads(
                raw_arguments,
                parse_constant=_reject_non_finite_constant,
            )
        except _NonFiniteNumber:
            arguments = None
            parse_error = "non_finite_number"
        except (TypeError, RecursionError, ValueError):
            arguments = None
            parse_error = "invalid_json"
        else:
            if isinstance(parsed_arguments, dict):
                parse_error = _json_value_error(parsed_arguments)
                arguments = parsed_arguments if parse_error is None else None
            else:
                arguments = None
                parse_error = "arguments_not_object"
        calls.append(
            ToolCall(
                id=call_id,
                name=name,
                raw_arguments=arguments_text,
                arguments=arguments,
                parse_error=parse_error,
            )
        )
    return tuple(calls)


class _NonFiniteNumber(ValueError):
    pass


def _reject_non_finite_constant(value: str) -> None:
    raise _NonFiniteNumber(value)


def _valid_unicode(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _json_value_error(value: Any) -> str | None:
    """Return a stable parse error for unsafe values at any JSON depth."""
    pending = [value]
    while pending:
        current = pending.pop()
        current_type = type(current)
        if current is None or current_type in {bool, int}:
            continue
        if current_type is float:
            if not math.isfinite(current):
                return "non_finite_number"
            continue
        if current_type is str:
            if not _valid_unicode(current):
                return "arguments_invalid_unicode"
            continue
        if current_type is list:
            pending.extend(current)
            continue
        if current_type is dict:
            for key, item in current.items():
                if type(key) is not str or not _valid_unicode(key):
                    return "arguments_invalid_unicode"
                pending.append(item)
            continue
        return "invalid_json_value"
    return None


def _invalid_tool_call(
    parse_error: str,
    *,
    call_id: str = "",
    name: str = "",
    raw_arguments: str = "",
) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        raw_arguments=raw_arguments,
        arguments=None,
        parse_error=parse_error,
    )
