"""Bounded Gemini generateContent image codec for a reviewed composer turn."""

from __future__ import annotations

import base64
import binascii
import json

from .video_native import VideoNativeEmpty, VideoNativeRefused, gemini_video_answer

MAX_INLINE_REQUEST_BYTES = 20_000_000
IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


def generate_content_payload(compatible: dict) -> dict:
    system: list[str] = []
    contents: list[dict] = []
    next_role = "user"
    image_count = 0
    for message in compatible["messages"]:
        if message["role"] == "system":
            if contents or not isinstance(message["content"], str):
                raise ValueError("invalid Gemini image system message")
            system.append(message["content"])
            continue
        role = message["role"]
        if role != next_role:
            raise ValueError("invalid Gemini image role")
        parts = message["content"]
        if role == "assistant" and isinstance(parts, str):
            parts = [{"type": "text", "text": parts}]
        if not isinstance(parts, list):
            raise ValueError("invalid Gemini image content")
        blocks = []
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("invalid Gemini image part")
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                blocks.append({"text": part["text"]})
            elif (role == "user" and part.get("type") == "image_url"
                  and isinstance(part.get("image_url"), dict)):
                uri = part["image_url"].get("url")
                if not isinstance(uri, str):
                    raise ValueError("invalid Gemini image data")
                header, separator, encoded = uri.partition(",")
                mime = header.removeprefix("data:").removesuffix(";base64")
                if (not separator or not header.startswith("data:") or not header.endswith(";base64")
                        or mime not in IMAGE_MIMES or not encoded):
                    raise ValueError("invalid Gemini image data")
                if len(encoded) > MAX_INLINE_REQUEST_BYTES:
                    raise ValueError("Gemini inline image request too large")
                try:
                    base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise ValueError("invalid Gemini image data") from None
                blocks.append({"inline_data": {"mime_type": mime, "data": encoded}})
                image_count += 1
            else:
                raise ValueError("invalid Gemini image part")
        if not blocks:
            raise ValueError("invalid Gemini image turn")
        contents.append({"role": "model" if role == "assistant" else "user", "parts": blocks})
        next_role = "user" if role == "assistant" else "assistant"
    if next_role != "assistant" or not image_count:
        raise ValueError("invalid Gemini image turn")
    payload = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": compatible["max_tokens"],
            "temperature": compatible["temperature"],
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_INLINE_REQUEST_BYTES:
        raise ValueError("Gemini inline image request too large")
    return payload


def generate_content_answer(payload: object) -> str:
    try:
        return gemini_video_answer(payload)
    except VideoNativeEmpty:
        return ""
    except VideoNativeRefused:
        raise ValueError("invalid Gemini image answer") from None


def generate_content_empty(payload: object) -> bool:
    try:
        gemini_video_answer(payload)
    except VideoNativeEmpty:
        return True
    except VideoNativeRefused:
        pass
    return False
