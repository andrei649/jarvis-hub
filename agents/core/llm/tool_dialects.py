"""Translate the runtime's one tool dialect into each provider's own, and back.

`AgentToolRuntime` speaks OpenAI's shape only: `ToolSpec.as_openai()` for the offered tools,
`{"role": "assistant", "tool_calls": [...]}` / `{"role": "tool", "tool_call_id": ...}` for the
history it replays. Backends that can call tools translate here — never inside the runtime — so
the governed path (`ToolRPC` → Action Kernel → approval queue) is identical no matter which
provider answered.

Every provider call is reshaped into an OpenAI-style raw call and handed to
`parse_openai_tool_calls`, the single fail-closed boundary. These helpers reshape; they do not
validate. A malformed Claude `input` or Gemini `args` reaches the runtime as a `parse_error`
exactly as a malformed LM Studio call would, and the runtime answers it with
`bad_tool_arguments` instead of executing anything.

Hermes absorption, wave 0.1 — see docs/HERMES_ABSORPTION.md.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .tool_protocol import ToolSpec

SYNTHETIC_ID_PREFIX = "nerva_call_"
_synthetic_counter = itertools.count(1)

# Anthropic validates tool ids and names against this shape; anything else is a 400.
_ANTHROPIC_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ANTHROPIC_FALLBACK_NAME = "invalid_tool"

# OpenAI's finish vocabulary is the shared one; each provider maps into it.
ANTHROPIC_FINISH_REASONS: Mapping[str, str] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "refusal": "content_filter",
}
GEMINI_FINISH_REASONS: Mapping[str, str] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
}

# The OpenAPI subset Gemini's `Schema` accepts. Everything else (additionalProperties, $schema,
# $ref, oneOf, const, exclusiveMinimum, unknown formats, ...) is a 400 on the real API.
_GEMINI_FORMATS = frozenset({"date-time", "enum", "int32", "int64", "float", "double"})
_GEMINI_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object"})
_GEMINI_STRING_KEYS = ("title", "description", "pattern")
_GEMINI_NUMBER_KEYS = (
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minProperties",
    "maxProperties",
)
_GEMINI_THOUGHT_SIGNATURE_LIMIT = 256


# ── shared ───────────────────────────────────────────────────────────────────


def synthetic_call_id() -> str:
    """A process-unique id for a provider call that arrived without one."""
    return f"{SYNTHETIC_ID_PREFIX}{next(_synthetic_counter)}"


def is_synthetic_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SYNTHETIC_ID_PREFIX)


def normalize_finish_reason(table: Mapping[str, str], raw: Any) -> str | None:
    """Map a provider stop reason into the shared vocabulary; unknown ones pass through lowered."""
    if not isinstance(raw, str) or not raw:
        return None
    return table.get(raw, raw.lower())


def _text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _parse_arguments(value: Any) -> dict[str, Any]:
    """Replay-side: an OpenAI JSON-string argument blob back into an object, `{}` if it never was one."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _dump_arguments(value: Any) -> str:
    """Response-side: a provider's structured arguments into the JSON string the boundary parses.

    Non-object values are dumped as-is so `parse_openai_tool_calls` rejects them
    (`arguments_not_object`); non-finite numbers survive as `NaN` so it rejects those too.
    """
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def _replayed_calls(message: Mapping[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(id, name, arguments) for every replayed assistant tool call, tolerant of bad shapes."""
    calls: list[tuple[str, str, dict[str, Any]]] = []
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return calls
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        function = function if isinstance(function, dict) else {}
        name = function.get("name")
        call_id = raw_call.get("id")
        calls.append(
            (
                call_id if isinstance(call_id, str) else "",
                name if isinstance(name, str) else "",
                _parse_arguments(function.get("arguments")),
            )
        )
    return calls


# ── Anthropic Messages API ───────────────────────────────────────────────────


def anthropic_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools
    ]


def anthropic_messages(messages: Sequence[Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI history → (system text, Messages-API messages).

    System turns are lifted into the top-level `system`. Assistant tool calls become `tool_use`
    blocks; the `tool` turns that follow are merged into one `user` turn of `tool_result` blocks,
    which is the only place the API accepts them. Ids the API would refuse are replaced by
    stable placeholders on both sides so every result still points at its call. Empty text blocks
    are dropped because the API rejects them.
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    replacements: dict[str, list[str]] = {}
    placeholder = itertools.count(1)

    def _safe_id(raw_id: str) -> str:
        if _ANTHROPIC_TOKEN.match(raw_id):
            return raw_id
        return f"toolu_nerva_{next(placeholder)}"

    for message in messages:
        role = message.get("role")
        text = _text(message)
        if role == "system":
            if text.strip():
                system_parts.append(text)
        elif role == "user":
            if text.strip():
                converted.append({"role": "user", "content": text})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if text.strip():
                blocks.append({"type": "text", "text": text})
            for raw_id, name, arguments in _replayed_calls(message):
                safe_id = _safe_id(raw_id)
                replacements.setdefault(raw_id, []).append(safe_id)
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": safe_id,
                        "name": name if _ANTHROPIC_TOKEN.match(name) else _ANTHROPIC_FALLBACK_NAME,
                        "input": arguments,
                    }
                )
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            raw_id = message.get("tool_call_id")
            raw_id = raw_id if isinstance(raw_id, str) else ""
            queued = replacements.get(raw_id)
            use_id = queued.pop(0) if queued else _safe_id(raw_id)
            block: dict[str, Any] = {"type": "tool_result", "tool_use_id": use_id}
            if text:
                block["content"] = text
            previous = converted[-1] if converted else None
            if (
                previous is not None
                and previous["role"] == "user"
                and isinstance(previous["content"], list)
            ):
                previous["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
    return "\n\n".join(system_parts), converted


def anthropic_text(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    return "".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    )


def anthropic_tool_calls(blocks: Any) -> list[Any]:
    """`tool_use` blocks → OpenAI-shaped raw calls for `parse_openai_tool_calls`."""
    if not isinstance(blocks, list):
        return []
    raw_calls: list[Any] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        raw_calls.append(
            {
                "id": block.get("id"),
                "type": "function",
                "function": {
                    "name": block.get("name"),
                    "arguments": _dump_arguments(block.get("input", {})),
                },
            }
        )
    return raw_calls


# ── Gemini generateContent ───────────────────────────────────────────────────


def gemini_schema(schema: Any) -> dict[str, Any]:
    """Project a JSON Schema onto the OpenAPI subset Gemini accepts, recursively.

    Drops keywords Gemini rejects, folds `["string", "null"]` into `nullable`, `const` into a
    one-value `enum`, `oneOf` into `anyOf`, stringifies enum values, keeps only the formats the
    API knows, and filters `required` to declared properties.
    """
    if not isinstance(schema, dict):
        return {}
    out: dict[str, Any] = {}
    nullable = bool(schema.get("nullable"))
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        names = [name for name in raw_type if isinstance(name, str)]
        if "null" in names:
            nullable = True
        names = [name for name in names if name != "null"]
        raw_type = names[0] if names else None
    if isinstance(raw_type, str) and raw_type.lower() in _GEMINI_TYPES:
        out["type"] = raw_type.lower()

    for key in _GEMINI_STRING_KEYS:
        value = schema.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    if "default" in schema:
        out["default"] = schema["default"]
    fmt = schema.get("format")
    if isinstance(fmt, str) and fmt in _GEMINI_FORMATS:
        out["format"] = fmt
    for key in _GEMINI_NUMBER_KEYS:
        value = schema.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = value
    if nullable:
        out["nullable"] = True

    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        out["enum"] = [str(value) for value in enum]
        out.setdefault("type", "string")
    elif "const" in schema:
        out["enum"] = [str(schema["const"])]
        out.setdefault("type", "string")

    properties = schema.get("properties")
    if isinstance(properties, dict):
        cleaned = {
            name: gemini_schema(value)
            for name, value in properties.items()
            if isinstance(name, str) and isinstance(value, dict)
        }
        out.setdefault("type", "object")
        if cleaned:
            out["properties"] = cleaned
            required = schema.get("required")
            if isinstance(required, list):
                kept = [name for name in required if isinstance(name, str) and name in cleaned]
                if kept:
                    out["required"] = kept
    items = schema.get("items")
    if isinstance(items, dict):
        out["items"] = gemini_schema(items)
        out.setdefault("type", "array")
    variants = schema.get("anyOf", schema.get("oneOf"))
    if isinstance(variants, list):
        cleaned_variants = [gemini_schema(variant) for variant in variants if isinstance(variant, dict)]
        if cleaned_variants:
            out["anyOf"] = cleaned_variants
    return out


def gemini_function_declarations(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """`functionDeclarations`; a tool without properties omits `parameters` (empty OBJECTs are a 400)."""
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        declaration: dict[str, Any] = {"name": tool.name, "description": tool.description}
        parameters = gemini_schema(tool.input_schema)
        if parameters.get("properties"):
            parameters["type"] = "object"
            declaration["parameters"] = parameters
        declarations.append(declaration)
    return declarations


def gemini_contents(
    messages: Sequence[Mapping[str, Any]],
    *,
    thought_signatures: Mapping[str, str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI history → (system text, `contents`).

    Assistant tool calls become `functionCall` parts on a `model` turn, carrying back the
    `thoughtSignature` Gemini attached when it made the call (thinking models refuse a replayed
    call without it). Tool results become `functionResponse` parts on a `user` turn, named after
    the call they answer; a JSON-object result is passed structured, anything else is wrapped.
    Ids are echoed only when Gemini minted them — a synthetic id means the API never saw one.
    """
    signatures = thought_signatures or {}
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        text = _text(message)
        if role == "system":
            if text.strip():
                system_parts.append(text)
        elif role == "user":
            if text.strip():
                contents.append({"role": "user", "parts": [{"text": text}]})
        elif role == "assistant":
            parts: list[dict[str, Any]] = []
            if text.strip():
                parts.append({"text": text})
            for call_id, name, arguments in _replayed_calls(message):
                if call_id:
                    names[call_id] = name
                function_call: dict[str, Any] = {"name": name, "args": arguments}
                if call_id and not is_synthetic_id(call_id):
                    function_call["id"] = call_id
                part: dict[str, Any] = {"functionCall": function_call}
                signature = signatures.get(call_id)
                if isinstance(signature, str) and signature:
                    part["thoughtSignature"] = signature
                parts.append(part)
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            call_id = message.get("tool_call_id")
            call_id = call_id if isinstance(call_id, str) else ""
            response = _gemini_response_payload(text)
            function_response: dict[str, Any] = {
                "name": names.get(call_id, "") or "unknown_tool",
                "response": response,
            }
            if call_id and not is_synthetic_id(call_id):
                function_response["id"] = call_id
            part = {"functionResponse": function_response}
            previous = contents[-1] if contents else None
            if (
                previous is not None
                and previous["role"] == "user"
                and previous["parts"]
                and "functionResponse" in previous["parts"][0]
            ):
                previous["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
    return "\n\n".join(system_parts), contents


def _gemini_response_payload(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    return parsed if isinstance(parsed, dict) else {"result": text}


def gemini_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    return "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str) and not part.get("thought")
    )


def gemini_tool_calls(
    parts: Any,
    *,
    new_id: Callable[[], str] = synthetic_call_id,
) -> tuple[list[Any], dict[str, str]]:
    """`functionCall` parts → (OpenAI-shaped raw calls, {call id: thoughtSignature}).

    Gemini rarely mints ids, so one is synthesized per call; `args` may be absent for an
    argument-free call and defaults to `{}`. Anything malformed is passed through in a shape
    `parse_openai_tool_calls` will reject.
    """
    if not isinstance(parts, list):
        return [], {}
    raw_calls: list[Any] = []
    signatures: dict[str, str] = {}
    for part in parts:
        if not isinstance(part, dict) or "functionCall" not in part:
            continue
        function_call = part["functionCall"]
        if not isinstance(function_call, dict):
            raw_calls.append({"id": new_id(), "type": "function", "function": function_call})
            continue
        provided = function_call.get("id")
        call_id = provided if isinstance(provided, str) and provided else new_id()
        raw_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": function_call.get("name"),
                    "arguments": _dump_arguments(function_call.get("args", {})),
                },
            }
        )
        signature = part.get("thoughtSignature")
        if isinstance(signature, str) and signature:
            signatures[call_id] = signature
    return raw_calls, signatures


def remember_thought_signatures(store: dict[str, str], signatures: Mapping[str, str]) -> None:
    """Keep the most recent signatures only; the loop is bounded, the store must be too."""
    store.update(signatures)
    while len(store) > _GEMINI_THOUGHT_SIGNATURE_LIMIT:
        del store[next(iter(store))]


# ── Ollama /api/chat ─────────────────────────────────────────────────────────


def ollama_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI history → Ollama chat messages.

    Ollama wants object arguments on replayed calls and the function name on tool results
    (`tool_name` is what its chat templates key on; `tool_call_id` rides along for newer
    servers, and older ones ignore fields they do not know). Empty system turns are dropped for
    the same reason `_chat_messages` drops them.
    """
    converted: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        if not isinstance(role, str):
            continue
        text = _text(message)
        if role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            calls = []
            for call_id, name, arguments in _replayed_calls(message):
                if call_id:
                    names[call_id] = name
                call: dict[str, Any] = {"function": {"name": name, "arguments": arguments}}
                if call_id:
                    call["id"] = call_id
                calls.append(call)
            if calls:
                entry["tool_calls"] = calls
            converted.append(entry)
        elif role == "tool":
            entry = {"role": "tool", "content": text}
            call_id = message.get("tool_call_id")
            if isinstance(call_id, str) and call_id:
                entry["tool_call_id"] = call_id
                if names.get(call_id):
                    entry["tool_name"] = names[call_id]
            converted.append(entry)
        elif role == "system":
            if text.strip():
                converted.append({"role": "system", "content": text})
        else:
            converted.append({"role": role, "content": text})
    return converted


def ollama_tool_calls(raw_calls: Any, *, new_id: Callable[[], str] = synthetic_call_id) -> Any:
    """Ollama's `message.tool_calls` → OpenAI-shaped raw calls.

    Ollama returns object `arguments` and usually no `id`; the object is dumped to the JSON
    string the boundary parses and a missing id is synthesized. A non-list, a non-object call or
    a wrongly typed field is passed through untouched so `parse_openai_tool_calls` names the
    fault instead of this function guessing.
    """
    if not isinstance(raw_calls, list):
        return raw_calls
    converted: list[Any] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            converted.append(raw_call)
            continue
        call_id = raw_call.get("id")
        if call_id is None or call_id == "":
            call_id = new_id()
        function = raw_call.get("function")
        if isinstance(function, dict):
            arguments = function.get("arguments", {})
            function = {
                "name": function.get("name"),
                "arguments": arguments if isinstance(arguments, str) else _dump_arguments(arguments),
            }
        converted.append({"id": call_id, "type": "function", "function": function})
    return converted
