"""What the editor is shown (G11, H543/H544): tool-call cards, approval cards, the plan.

Everything here is projection. Nothing decides, approves or runs anything.

* A live tool call arrives from the hub as a bounded tool event (``event``, ``tool``,
  ``call_id``, ``status`` — never its arguments or its result, the same promise
  ``observability.tool_events`` makes the HUD) and becomes an ACP ``tool_call`` /
  ``tool_call_update`` with a kind the editor knows how to draw.
* An approval card the turn queued becomes the ``toolCall`` of a
  ``session/request_permission``: a file write is drawn as the real diff of the text it
  would leave on disk, a command as the exact command, anything else as its payload.
* The session's checklist (Nerva's ``todo`` tool) becomes the editor's plan panel.

Text that came from the hub or the model is made safe for a UI first: control, format
(bidi, zero-width), separator, surrogate and private-use characters are removed, so a
card cannot reorder or hide what sits beside the Accept button.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

MAX_TITLE_CHARS = 200
MAX_BLOCK_CHARS = 8000
MAX_DIFF_CHARS = 512 * 1024

_UNSAFE = {"Cc", "Cf", "Zl", "Zp", "Cs", "Co"}

#: ACP tool kinds by Nerva tool name (anything else is ``other``).
_KINDS = {
    "file_read": "read", "skill_view": "read",
    "file_list": "search", "file_search": "search", "web_search": "search",
    "session_search": "search", "search_memory": "search", "skills_list": "search",
    "file_write": "edit",
    "file_delete": "delete",
    "terminal_run": "execute", "execute_code": "execute", "browser_run": "execute",
    "desktop_run": "execute",
    "web_extract": "fetch",
    "todo": "think", "clarify": "think",
}
_STATUSES = {"requested": "pending", "running": "in_progress", "ok": "completed",
             "completed": "completed", "failed": "failed", "error": "failed"}


def safe_line(text: Any, width: int = MAX_TITLE_CHARS) -> str:
    """One line of UI text: unsafe characters removed, whitespace collapsed, bounded."""
    kept = [" " if unicodedata.category(ch) in _UNSAFE else ch for ch in str("" if text is None else text)]
    line = " ".join("".join(kept).split())
    return line if len(line) <= width else line[: width - 1] + "…"


def safe_block(text: Any, width: int = MAX_BLOCK_CHARS) -> str:
    """Multi-line UI text: each line made safe, newlines kept, bounded overall."""
    raw = str("" if text is None else text).replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in raw.split("\n"):
        lines.append("".join("" if unicodedata.category(ch) in _UNSAFE and ch != "\t" else ch
                             for ch in line))
    out = "\n".join(lines)
    return out if len(out) <= width else out[: width - 1] + "…"


def tool_kind(name: Any) -> str:
    name = str(name or "")
    if name.startswith("mcp__"):
        return "other"
    return _KINDS.get(name, "other")


def tool_title(name: Any) -> str:
    name = safe_line(name, 80) or "tool"
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3:
            return f"MCP {parts[1]} · {'__'.join(parts[2:])}"
    return name.replace("_", " ")


def tool_status(event: dict[str, Any]) -> str:
    name = str(event.get("event") or "")
    if name == "tool_failed":
        return "failed"
    if name == "tool_result":
        status = str(event.get("status") or "")
        return "failed" if status in ("failed", "error", "refused") else "completed"
    if name == "tool_started":
        return "in_progress"
    return _STATUSES.get(str(event.get("status") or ""), "pending")


def text_block(text: str) -> dict[str, Any]:
    return {"type": "content", "content": {"type": "text", "text": text}}


def _args(card: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = card.get("payload") if isinstance(card.get("payload"), dict) else {}
    tool = payload.get("tool") if isinstance(payload.get("tool"), str) else ""
    kind = str(card.get("kind") or "")
    if not tool and kind.startswith("toolrpc."):
        tool = kind[len("toolrpc."):]
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    return tool, args if args else payload


def card_target(card: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """``(tool, path, new_text)`` for a file mutation card; path/new_text None otherwise."""
    tool, args = _args(card)
    if tool in ("file_write", "file_delete"):
        path = args.get("path") if isinstance(args.get("path"), str) else None
        if tool == "file_delete":
            return tool, path, ""
        content = args.get("content") if isinstance(args.get("content"), str) else None
        return tool, path, content
    return tool, None, None


def _command_text(args: dict[str, Any]) -> str | None:
    for key in ("command", "cmd", "argv", "code", "script"):
        if key in args:
            value = args[key]
            if isinstance(value, list):
                return " ".join(str(part) for part in value)
            return str(value)
    return None


def card_tool_call(card: dict[str, Any], *, diff: dict[str, Any] | None = None,
                   note: str | None = None) -> dict[str, Any]:
    """The ``toolCall`` of a ``session/request_permission`` for one approval card.

    *diff* is ``{"path", "oldText", "newText"}`` when the real before/after was drawn;
    *note* is one line of Nerva's own words shown above the content (why there is no diff,
    say)."""
    tool, args = _args(card)
    task_id = card.get("id")
    reversible = bool(card.get("reversible"))
    tier = safe_line(card.get("tier_name") or card.get("risk_tier") or "?", 24)
    flag = "" if reversible else "IRREVERSIBLE · "
    title = safe_line(f"{flag}#{task_id} {card.get('title') or tool or card.get('kind') or 'action'}")
    content: list[dict[str, Any]] = []
    header = f"Approval #{task_id} · tier {tier} · {'reversible' if reversible else 'irreversible'}"
    origin = safe_line(card.get("origin") or "", 40)
    if origin:
        header += f" · origin {origin}"
    content.append(text_block(header))
    if note:
        content.append(text_block(safe_line(note, 400)))
    locations: list[dict[str, Any]] = []
    if diff is not None:
        content.append({"type": "diff", "path": diff["path"], "oldText": diff.get("oldText"),
                        "newText": diff["newText"]})
        locations.append({"path": diff["path"]})
    else:
        command = _command_text(args)
        if command is not None:
            content.append(text_block("```\n" + safe_block(command) + "\n```"))
        elif args:
            try:
                shown = json.dumps(args, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            except (TypeError, ValueError):
                shown = str(args)
            content.append(text_block("```json\n" + safe_block(shown) + "\n```"))
    rollback = card.get("rollback")
    if isinstance(rollback, dict) and rollback.get("description"):
        content.append(text_block("Rollback: " + safe_line(rollback["description"], 400)))
    call: dict[str, Any] = {
        "toolCallId": f"approval-{task_id}",
        "title": title,
        "kind": "delete" if tool == "file_delete" else ("edit" if diff is not None else tool_kind(tool)),
        "status": "pending",
        "content": content,
    }
    if locations:
        call["locations"] = locations
    return call


def permission_options(card: dict[str, Any]) -> list[dict[str, Any]]:
    """The choices offered for one card. "Always" is offered only where the hub itself
    offers a reusable consent for this exact card (``consent_offer``) and the card is
    reversible: the editor never invents a standing permission the HUD would not."""
    options = [{"optionId": "accept", "name": "Accept", "kind": "allow_once"}]
    if consent_offer(card) is not None and card.get("reversible"):
        options.append({"optionId": "consent_session", "name": "Allow matching requests this session",
                        "kind": "allow_always"})
        options.append({"optionId": "consent_always", "name": "Always allow matching requests",
                        "kind": "allow_always"})
    options.append({"optionId": "reject", "name": "Reject", "kind": "reject_once"})
    return options


def consent_offer(card: dict[str, Any]) -> dict[str, Any] | None:
    offer = card.get("consent_offer")
    if (isinstance(offer, dict) and isinstance(offer.get("revision"), str)
            and len(offer["revision"]) == 64
            and all(ch in "0123456789abcdef" for ch in offer["revision"])):
        return offer
    return None


_PLAN_STATUS = {"pending": "pending", "in_progress": "in_progress", "completed": "completed"}


def plan_entries(todos: Any) -> list[dict[str, Any]]:
    """Nerva's checklist as ACP plan entries (cancelled items are left out)."""
    entries = []
    for item in todos if isinstance(todos, list) else []:
        if not isinstance(item, dict):
            continue
        status = _PLAN_STATUS.get(str(item.get("status") or ""))
        if status is None:
            continue
        entries.append({"content": safe_line(item.get("content"), 400), "priority": "medium",
                        "status": status})
        if len(entries) >= 100:
            break
    return entries


__all__ = [
    "card_target", "card_tool_call", "consent_offer", "permission_options", "plan_entries",
    "safe_block", "safe_line", "text_block", "tool_kind", "tool_status", "tool_title",
]
