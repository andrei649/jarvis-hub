"""Pure classification of a valid but empty compatible native completion."""

from __future__ import annotations

import re

from .base import strip_thinking

_THOUGHT_TAGS = re.compile(
    r"<(think|thinking|reasoning|thought|REASONING_SCRATCHPAD|思考|反思|推理|推敲)>.*?</\1\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)


def normalized_vision_text(text: str) -> str:
    """Hide known closed thought tags, then apply Nerva's existing filter."""
    return strip_thinking(_THOUGHT_TAGS.sub("", text)).strip()


def compatible_vision_answer(payload: object) -> str:
    """Extract text from one typed compatible completion for native vision.

    A malformed or alternate-output envelope is terminal even when it also
    carries plausible visible text. Empty text is left to the caller's existing
    raw-empty retry predicate.
    """
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("invalid compatible vision response")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("invalid compatible vision response")
    choice = choices[0]
    message = choice.get("message")
    finish = choice.get("finish_reason")
    if ("error" in choice or not isinstance(message, dict) or "error" in message
            or finish not in (None, "stop", "length")):
        raise ValueError("invalid compatible vision response")
    refusal = message.get("refusal")
    if ((refusal is not None and (not isinstance(refusal, str) or bool(refusal)))
            or message.get("function_call") is not None
            or message.get("audio") is not None):
        raise ValueError("invalid compatible vision response")
    tools = message.get("tool_calls")
    if tools is not None and (not isinstance(tools, list) or tools):
        raise ValueError("invalid compatible vision response")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("invalid compatible vision response")
    visible = normalized_vision_text(content) if content else ""
    if visible:
        return visible

    pieces: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> bool:
        if not isinstance(value, str):
            return False
        cleaned = normalized_vision_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            pieces.append(cleaned)
        return bool(cleaned)

    add(message.get("reasoning"))
    add(message.get("reasoning_content"))
    details = message.get("reasoning_details")
    if isinstance(details, list):
        for detail in details:
            # Typed opaque blocks are transport state, never answer text.
            # Untyped legacy details retain the existing text-field contract.
            if (isinstance(detail, dict)
                    and detail.get("type") in (None, "reasoning.text", "reasoning.summary")):
                for key in ("summary", "content", "text"):
                    if add(detail.get(key)):
                        break
    return "\n\n".join(pieces)


def compatible_empty_success(payload: object) -> bool:
    """Require an explicit stop and no alternate output or error envelope."""
    if not isinstance(payload, dict) or "error" in payload:
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return False
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or not isinstance(message, dict) or "content" not in message:
        return False
    if "error" in choice or "error" in message:
        return False
    content = message["content"]
    if content is not None and (not isinstance(content, str) or content.strip()):
        return False
    refusal = message.get("refusal")
    if refusal is not None and (not isinstance(refusal, str) or bool(refusal)):
        return False
    tools = message.get("tool_calls")
    if tools is not None and (not isinstance(tools, list) or bool(tools)):
        return False
    if message.get("function_call") is not None or message.get("audio") is not None:
        return False
    for key in ("reasoning", "reasoning_content"):
        value = message.get(key)
        if value is not None and (not isinstance(value, str) or bool(value.strip())):
            return False
    details = message.get("reasoning_details")
    return details is None or (isinstance(details, list) and not details)
