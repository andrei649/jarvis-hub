"""Validation and public receipts for existing session organization routes."""

from __future__ import annotations

from typing import Any

STAMP_ACTIONS = {"pin": ("pinned", True), "unpin": ("pinned", False),
                 "archive": ("archived", True), "unarchive": ("archived", False)}


def organization_title(raw: object) -> str:
    """Use the native title rules, while requiring explicitly one-line input."""
    from agents.core.session_titles import human_title

    if not isinstance(raw, str) or any(ch in raw for ch in "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
        raise ValueError("A title must be one line of 1 to 100 characters.")
    title = human_title(raw)
    if not title:
        raise ValueError("A title must be one line of 1 to 100 characters.")
    return title


def organization_receipt(raw: Any, session_id: str, action: str, title: str | None = None) -> dict:
    """Confirm the requested mutation, copying only its public response contract."""
    if not isinstance(raw, dict) or raw.get("ok") is not True or raw.get("session") != session_id:
        raise ValueError("Unconfirmed session organization response")
    receipt = {"ok": True, "session": session_id}
    if action == "rename":
        if raw.get("title") != title or raw.get("title_source") != "human":
            raise ValueError("Unconfirmed session organization response")
        return {**receipt, "title": title, "title_source": "human"}
    field, value = STAMP_ACTIONS[action]
    if raw.get(field) is not value:
        raise ValueError("Unconfirmed session organization response")
    return {**receipt, field: value}
