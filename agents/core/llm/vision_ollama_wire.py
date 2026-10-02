"""Translate prepared vision turns to Ollama's native /api/chat image wire."""

from __future__ import annotations

import base64

from .native_response import normalized_vision_text


def chat_payload(compatible: dict) -> dict:
    messages = []
    for message in compatible["messages"]:
        if message["role"] == "system":
            if not isinstance(message["content"], str):
                raise ValueError("invalid Ollama vision system message")
            messages.append({"role": "system", "content": message["content"]})
            continue
        if message["role"] != "user" or not isinstance(message["content"], list):
            raise ValueError("invalid Ollama vision message")
        texts = []
        images = []
        for part in message["content"]:
            if not isinstance(part, dict):
                raise ValueError("invalid Ollama vision block")
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif part.get("type") == "image_url":
                image = part.get("image_url")
                uri = image.get("url") if isinstance(image, dict) else None
                if not isinstance(uri, str):
                    raise ValueError("invalid Ollama vision image")
                header, separator, data = uri.partition(",")
                mime = header.removeprefix("data:").removesuffix(";base64")
                if (not separator or not header.startswith("data:") or
                        not header.endswith(";base64") or mime not in {
                            "image/png", "image/jpeg", "image/gif", "image/webp"} or not data):
                    raise ValueError("Ollama images require base64 data")
                base64.b64decode(data, validate=True)
                images.append(data)
            else:
                raise ValueError("invalid Ollama vision block")
        if not images:
            raise ValueError("Ollama vision image missing")
        messages.append({"role": "user", "content": "\n".join(texts), "images": images})
    max_tokens = compatible["max_tokens"]
    return {"model": compatible["model"], "messages": messages, "stream": False,
            "options": {"num_predict": max_tokens if max_tokens > 0 else -1,
                        "temperature": compatible["temperature"]}}


def _message(payload: object) -> dict:
    if (not isinstance(payload, dict) or "error" in payload or payload.get("done") is not True
            or payload.get("done_reason") not in (None, "stop", "length")):
        raise ValueError("invalid Ollama vision response")
    message = payload.get("message")
    if (not isinstance(message, dict) or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str)
            or message.get("tool_calls") not in (None, [])):
        raise ValueError("invalid Ollama vision response")
    return message


def chat_answer(payload: object) -> str:
    message = _message(payload)
    text = normalized_vision_text(message["content"])
    if text:
        return text
    thinking = message.get("thinking") or message.get("reasoning_content") or ""
    return normalized_vision_text(thinking) if isinstance(thinking, str) else ""


def chat_empty(payload: object) -> bool:
    try:
        message = _message(payload)
    except ValueError:
        return False
    return (payload.get("done_reason") == "stop" and not message["content"].strip()
            and not (message.get("thinking") or message.get("reasoning_content")))
