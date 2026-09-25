"""H441 — a free recap of a conversation: the last exchanges, rendered locally.

Resuming a session used to hand back its last 20 raw turns and leave the owner to
re-read them; there was no recap anywhere. Hermes shows a "Previous Conversation"
panel on resume and answers ``/recap`` from the in-memory transcript, and it does so
with no model call on purpose: a generated recap costs a cache miss and latency and
is no more accurate than the turns themselves. This module is that renderer:

- the last ``exchanges`` exchanges (an owner turn and the replies that follow it);
- each turn cut to ``max_chars`` on one line, control characters removed;
- the tools a reply used collapsed to a count and their names,
  ``[3 tool calls: terminal_run, web_search]``, never their arguments or results.

It reads only the turn list it is given. Nothing here calls a model, a tool or the
network; the resume route, ``/recap`` in every channel and the HUD all render from it.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

#: Exchanges shown by default, as Hermes shows its last 10.
DEFAULT_EXCHANGES = 10
MAX_EXCHANGES = 50
#: One turn's text, on one line, in characters.
DEFAULT_TURN_CHARS = 280
MAX_TURN_CHARS = 2000
#: Tool names listed after the count; the count is always the true total.
MAX_TOOL_NAMES = 6

_SPACE = re.compile(r"\s+")


def _clean(text: Any, limit: int) -> str:
    """One line of plain text: whitespace folded, control and bidi characters removed,
    cut to ``limit`` characters with an ellipsis."""
    raw = text if isinstance(text, str) else ("" if text is None else str(text))
    kept = "".join(ch for ch in raw if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf"))
    flat = _SPACE.sub(" ", kept).strip()
    if len(flat) > limit:
        return flat[: max(1, limit - 1)].rstrip() + "…"
    return flat


def _tool_names(turn: dict) -> list[str]:
    tools = turn.get("tools")
    if not isinstance(tools, list):
        return []
    return [_clean(name, 64) for name in tools if isinstance(name, str) and name.strip()]


def tool_line(names: list[str]) -> str:
    """``[3 tool calls: a, b]``: the count of calls, then the distinct names in order."""
    if not names:
        return ""
    distinct = list(dict.fromkeys(names))
    shown = ", ".join(distinct[:MAX_TOOL_NAMES]) + (", …" if len(distinct) > MAX_TOOL_NAMES else "")
    word = "call" if len(names) == 1 else "calls"
    return f"[{len(names)} tool {word}: {shown}]"


def _exchanges(turns: list[dict]) -> list[list[dict]]:
    """Turns grouped by owner turn; replies before the first owner turn form their own."""
    groups: list[list[dict]] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if turn.get("role") == "user" or not groups:
            groups.append([turn])
        else:
            groups[-1].append(turn)
    return groups


def render_recap(turns: list[dict] | None, *, exchanges: int = DEFAULT_EXCHANGES,
                 max_chars: int = DEFAULT_TURN_CHARS) -> dict:
    """The recap of ``turns`` (oldest first, as ``get_history`` returns them).

    Returns ``{"exchanges": [...], "shown": n, "total": m, "text": "..."}``: each
    exchange is a list of ``{"role", "agent", "text", "tools", "tool_calls"}`` entries,
    and ``text`` is the same recap as plain lines for a chat channel. Never calls a model.
    """
    exchanges = max(1, min(int(exchanges or DEFAULT_EXCHANGES), MAX_EXCHANGES))
    max_chars = max(20, min(int(max_chars or DEFAULT_TURN_CHARS), MAX_TURN_CHARS))
    groups = _exchanges(list(turns or []))
    kept = groups[-exchanges:]
    rendered: list[list[dict]] = []
    lines: list[str] = []
    for group in kept:
        entries = []
        for turn in group:
            role = "user" if turn.get("role") == "user" else "assistant"
            names = _tool_names(turn) if role == "assistant" else []
            entry = {
                "role": role,
                "agent": _clean(turn.get("agent_id"), 64) if role == "assistant" else "",
                "text": _clean(turn.get("content"), max_chars),
                "tool_calls": len(names),
                "tools": list(dict.fromkeys(names)),
            }
            entries.append(entry)
            if role == "user":
                lines.append(f"● you: {entry['text']}")
            else:
                speaker = entry["agent"] or "nerva"
                tail = f"  {tool_line(names)}" if names else ""
                lines.append(f"◆ {speaker}: {entry['text']}{tail}")
        rendered.append(entries)
    if not rendered:
        text = "Nothing to recap yet: this conversation has no turns."
    else:
        head = (f"Previous conversation (the last {len(rendered)} of {len(groups)} exchanges):"
                if len(groups) > len(rendered) else "Previous conversation:")
        text = "\n".join([head, *lines])
    return {"exchanges": rendered, "shown": len(rendered), "total": len(groups), "text": text}
