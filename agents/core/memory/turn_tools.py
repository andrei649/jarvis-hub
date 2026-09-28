"""H441 — which tools one turn called, so its reply can say ``[3 tool calls: …]``.

Turns persisted only role, content, agent, time and a token count, so a recap had no
tool calls to collapse. The orchestrator opens a collection when an owner turn arrives
(:func:`begin`); the agent's tool-event sink notes each finished call's tool name
(:func:`note`); the reply that closes the turn is stored with the names
(:func:`collected`). The collection lives in a context variable, so concurrent turns in
other sessions never mix, and a tool loop run in a worker thread (``asyncio.to_thread``
copies the context) still lands in its own turn. Names only: never arguments, never
results.
"""
from __future__ import annotations

from contextvars import ContextVar

#: Calls noted per turn; a runaway loop is capped long before this in the tool runtime.
MAX_NOTED = 200
_TERMINAL = frozenset({"tool_result", "tool_failed"})

_CURRENT: ContextVar[list[str] | None] = ContextVar("nerva_turn_tools", default=None)


def begin() -> list[str]:
    """Start collecting for the turn now arriving; returns the (empty) collection."""
    names: list[str] = []
    _CURRENT.set(names)
    return names


def note(event: object) -> None:
    """Record the tool of one finished call. Never raises: it rides the tool-event sink."""
    try:
        names = _CURRENT.get()
        if names is None or not isinstance(event, dict) or event.get("event") not in _TERMINAL:
            return
        tool = event.get("tool")
        if isinstance(tool, str) and tool.strip() and len(names) < MAX_NOTED:
            names.append(tool.strip()[:64])
    except Exception:  # noqa: BLE001, S110 - a recap detail never breaks a tool call
        return


def collected() -> list[str]:
    """The tools this turn called so far, in call order (a copy)."""
    names = _CURRENT.get()
    return list(names) if names else []
