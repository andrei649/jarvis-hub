"""Bounded text/function-only Responses dialect; no provider-side tool execution."""

import json

from .tool_protocol import TokenUsage, ToolTurn, parse_openai_tool_calls

MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 512 * 1024
MAX_CALLS = 32


class ResponsesRefused(ValueError):
    def __init__(self):
        super().__init__("Unsupported or invalid OpenAI Responses request or response")


def text(value):
    if not isinstance(value, str):
        raise ResponsesRefused()
    try:
        if len(value.encode("utf-8")) > MAX_TEXT:
            raise ResponsesRefused()
    except UnicodeError:
        raise ResponsesRefused() from None
    return value


def identifier(value):
    if not text(value) or len(value) > 256:
        raise ResponsesRefused()
    return value


def input_items(messages):
    if not isinstance(messages, list) or len(messages) > 4096:
        raise ResponsesRefused()
    items, pending, used = [], set(), set()
    for message in messages:
        if not isinstance(message, dict):
            raise ResponsesRefused()
        role = message.get("role")
        content = message.get("content", "")
        if role == "tool":
            call_id = identifier(message.get("tool_call_id"))
            if call_id not in pending:
                raise ResponsesRefused()
            pending.remove(call_id)
            items.append(
                {"type": "function_call_output", "call_id": call_id, "output": text(content)}
            )
            continue
        if role not in {"system", "developer", "user", "assistant"} or pending:
            raise ResponsesRefused()
        content = text("" if role == "assistant" and content is None else content)
        calls = message.get("tool_calls", [])
        if role != "assistant" and calls:
            raise ResponsesRefused()
        if content or not calls:
            items.append({"role": role, "content": content})
        if not isinstance(calls, list) or len(calls) > MAX_CALLS:
            raise ResponsesRefused()
        for call in calls:
            if (
                not isinstance(call, dict)
                or call.get("type") != "function"
                or not isinstance(call.get("function"), dict)
            ):
                raise ResponsesRefused()
            call_id = identifier(call.get("id"))
            if call_id in used:
                raise ResponsesRefused()
            used.add(call_id)
            pending.add(call_id)
            fn = call["function"]
            items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": identifier(fn.get("name")),
                    "arguments": text(fn.get("arguments")),
                }
            )
    if pending:
        raise ResponsesRefused()
    return items


def usage(raw):
    if not isinstance(raw, dict):
        return TokenUsage()

    def count(value):
        return value if type(value) is int and 0 <= value <= 2**63 - 1 else 0

    total, output = count(raw.get("input_tokens")), count(raw.get("output_tokens"))
    details = raw.get("input_tokens_details")
    cached = count(details.get("cached_tokens")) if isinstance(details, dict) else 0
    if cached > total:
        cached = 0
    return TokenUsage(input_tokens=total - cached, output_tokens=output, cache_read=cached)


def parse_response(value):
    if not isinstance(value, dict) or value.get("status") != "completed" or value.get("error"):
        raise ResponsesRefused()
    rows = value.get("output")
    if not isinstance(rows, list) or len(rows) > 256:
        raise ResponsesRefused()
    parts, calls, ids = [], [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get("status", "completed") != "completed":
            raise ResponsesRefused()
        if row.get("type") == "message":
            if row.get("role") != "assistant" or not isinstance(row.get("content"), list):
                raise ResponsesRefused()
            for block in row["content"]:
                if not isinstance(block, dict):
                    raise ResponsesRefused()
                if block.get("type") == "output_text":
                    parts.append(text(block.get("text")))
                elif block.get("type") == "refusal":
                    parts.append(text(block.get("refusal")))
                else:
                    raise ResponsesRefused()
        elif row.get("type") == "function_call":
            call_id = identifier(row.get("call_id"))
            if call_id in ids or len(calls) >= MAX_CALLS:
                raise ResponsesRefused()
            ids.add(call_id)
            calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": row.get("name"),
                        "arguments": row.get("arguments"),
                    },
                }
            )
        else:
            # Reasoning items and hosted tools are outside this fixed-model adapter.
            raise ResponsesRefused()
    return ToolTurn(
        content=text("".join(parts)),
        tool_calls=parse_openai_tool_calls(calls),
        finish_reason="tool_calls" if calls else "stop",
        usage=usage(value.get("usage")),
    )


def encoded(payload):
    try:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ResponsesRefused() from None
    if len(data) > MAX_BYTES:
        raise ResponsesRefused()
    return data
