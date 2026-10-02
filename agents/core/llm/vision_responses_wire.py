"""Bounded image-only Responses codec for a selected, reviewed conversation turn."""

from __future__ import annotations

import base64
import binascii
import json

from .native_response import normalized_vision_text

MAX_INLINE_REQUEST_BYTES = 20_000_000
IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


def responses_payload(compatible: dict, *, retention: str) -> dict:
    if retention not in {"in_memory", "24h"}:
        raise ValueError("invalid Responses image retention")
    instructions: list[str] = []
    user: list[dict] = []
    for message in compatible["messages"]:
        if message["role"] == "system":
            if not isinstance(message["content"], str):
                raise ValueError("invalid Responses image system message")
            instructions.append(message["content"])
            continue
        if message["role"] != "user" or user:
            raise ValueError("invalid Responses image turn")
        parts = message["content"]
        if not isinstance(parts, list):
            raise ValueError("invalid Responses image content")
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("invalid Responses image part")
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                user.append({"type": "input_text", "text": part["text"]})
            elif part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
                uri = part["image_url"].get("url")
                if not isinstance(uri, str):
                    raise ValueError("invalid Responses image data")
                header, separator, encoded = uri.partition(",")
                mime = header.removeprefix("data:").removesuffix(";base64")
                if (not separator or not header.startswith("data:") or not header.endswith(";base64")
                        or mime not in IMAGE_MIMES or not encoded):
                    raise ValueError("invalid Responses image data")
                if len(encoded) > MAX_INLINE_REQUEST_BYTES:
                    raise ValueError("Responses inline image request too large")
                try:
                    base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise ValueError("invalid Responses image data") from None
                user.append({"type": "input_image", "image_url": uri, "detail": "auto"})
            else:
                raise ValueError("invalid Responses image part")
    if not user or not any(part["type"] == "input_image" for part in user):
        raise ValueError("invalid Responses image turn")
    payload = {
        "model": compatible["model"],
        "input": ([{"role": "system", "content": "\n\n".join(instructions)}] if instructions else [])
                 + [{"role": "user", "content": user}],
        "store": False,
        "max_output_tokens": compatible["max_tokens"],
        "temperature": compatible["temperature"],
        "prompt_cache_retention": retention,
    }
    if len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_INLINE_REQUEST_BYTES:
        raise ValueError("Responses inline image request too large")
    return payload


def _text(payload: object) -> str:
    if (not isinstance(payload, dict) or payload.get("status") != "completed"
            or payload.get("error") or payload.get("incomplete_details")):
        raise ValueError("invalid Responses image answer")
    rows = payload.get("output")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("invalid Responses image answer")
    row = rows[0]
    if (row.get("type") != "message" or row.get("role") != "assistant"
            or row.get("status", "completed") != "completed"):
        raise ValueError("invalid Responses image answer")
    blocks = row.get("content")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 32:
        raise ValueError("invalid Responses image answer")
    pieces = []
    for block in blocks:
        if (not isinstance(block, dict) or block.get("type") != "output_text"
                or not isinstance(block.get("text"), str)):
            raise ValueError("invalid Responses image answer")
        pieces.append(block["text"])
    return normalized_vision_text("".join(pieces))


def responses_answer(payload: object) -> str:
    return _text(payload)


def responses_empty(payload: object) -> bool:
    try:
        return not _text(payload)
    except ValueError:
        return False
