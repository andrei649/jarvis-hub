"""Pure classification of a valid but empty compatible native completion."""

from __future__ import annotations


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
