"""Stateless xAI image codec: native Responses input, opaque reasoning output."""

from __future__ import annotations

import json

from .vision_responses_wire import MAX_INLINE_REQUEST_BYTES, responses_answer, responses_payload

XAI_IMAGE_MIMES = frozenset({"image/png", "image/jpeg"})


def xai_payload(compatible: dict, *, reasoning_effort: str) -> dict:
    if reasoning_effort not in {"", "low", "medium", "high", "xhigh"}:
        raise ValueError("invalid xAI image reasoning effort")
    payload = responses_payload(compatible, retention=None, allowed_mimes=XAI_IMAGE_MIMES)
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_INLINE_REQUEST_BYTES:
        raise ValueError("xAI inline image request too large")
    return payload


def _message_only(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("output"), list):
        raise ValueError("invalid xAI image answer")
    rows = payload["output"]
    if len(rows) > 32:
        raise ValueError("invalid xAI image answer")
    visible = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status", "completed") != "completed":
            raise ValueError("invalid xAI image answer")
        if row.get("type") == "reasoning":
            for key in ("summary", "content"):
                if key in row and not isinstance(row[key], list):
                    raise ValueError("invalid xAI image answer")
            continue
        visible.append(row)
    return {**payload, "output": visible}


def xai_answer(payload: object) -> str:
    return responses_answer(_message_only(payload))


def xai_empty(payload: object) -> bool:
    try:
        return not xai_answer(payload)
    except ValueError:
        return False
