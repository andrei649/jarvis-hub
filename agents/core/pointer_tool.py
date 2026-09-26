"""H309 — the model points at the HUD: a one-line tip on an element, or a short tour.

Hermes can show the owner where something is instead of describing it. Here the model
calls ``canvas_point`` with a ``target`` and a ``caption`` (a tip), or a ``title`` and up to
:data:`~agents.core.canvas.MAX_TOUR_STEPS` ``steps`` (a tour). The element goes through
:class:`~agents.core.canvas.CanvasStore` like every other canvas element — sanitised, one
line per caption, bounded — and the HUD's pointer overlay draws it next to the named
element, paging a tour with Back and Next.

- **Ungated.** A tip only draws on the owner's own screen; it runs nothing and changes no
  state beyond the canvas, which the owner clears.
- **Named places only.** A target must be one of :data:`~agents.core.canvas.POINTER_ANCHORS`
  (the rail's modes, the message box, the Decision Inbox panel, the Console button); the
  schema offers exactly that list, so a tip can never land on an approve or reject button.
- **Said who wrote it.** A tip written by an untrusted turn (an inbound channel, a
  recalled or fetched text) or by a turn that is not the owner's is marked ``untrusted``,
  and the HUD shows it as such.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agents.core.canvas import MAX_CAPTION, MAX_TOUR_STEPS, POINTER_ANCHORS

logger = logging.getLogger("jarvis.pointer_tool")

TOOL_NAME = "canvas_point"
CAPABILITY_ID = "tool:canvas_point"
DESCRIPTION = (
    "Point at part of the owner's HUD. Pass target + caption for one tip, or title + steps "
    "(each a target + caption) for a short tour the owner pages through. Captions are one line."
)
_STEP = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "enum": list(POINTER_ANCHORS)},
        "caption": {"type": "string", "maxLength": MAX_CAPTION * 2},
    },
    "required": ["target", "caption"],
    "additionalProperties": False,
}
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "target": _STEP["properties"]["target"],
        "caption": _STEP["properties"]["caption"],
        "title": {"type": "string", "maxLength": 200},
        "steps": {"type": "array", "minItems": 1, "maxItems": MAX_TOUR_STEPS, "items": _STEP},
    },
    "additionalProperties": False,
}


def _turn_origin() -> str:
    from agents.core.action_origin import current_action_origin

    return current_action_origin()


def register_pointer_tool(
    server: Any,
    *,
    canvas: Callable[[], Any],
    posture: Callable[[], str] | None = None,
    origin: Callable[[], str] = _turn_origin,
) -> str:
    """Expose ``canvas_point`` on a ToolRPC server (ungated). ``canvas`` returns the live
    CanvasStore (read per call); ``posture`` and ``origin`` say whose turn this is — a
    getter that fails counts as untrusted."""
    from agents.core.security.taint import is_untrusted_source

    def _untrusted() -> bool:
        try:
            if is_untrusted_source(origin()):
                return True
            where = posture() if posture is not None else "owner/owner"
            return not str(where).endswith("/owner")
        except Exception:
            logger.warning("canvas_point: the turn's origin could not be read; marked untrusted", exc_info=True)
            return True

    async def _handle(args: dict) -> dict:
        from agents.core.tool_rpc import current_tool_actor

        steps, target = args.get("steps"), args.get("target")
        if steps is not None and target is not None:
            return {"ok": False, "reason": "tip_or_tour", "detail": "pass target + caption, or steps — not both"}
        if steps is None and target is None:
            return {"ok": False, "reason": "nothing_to_point_at"}
        store = canvas()
        if store is None:
            return {"ok": False, "reason": "canvas_unavailable"}
        untrusted = _untrusted()
        if steps is not None:
            el_type, payload = "tour", {"title": args.get("title"), "steps": steps, "untrusted": untrusted}
        else:
            el_type, payload = "tip", {"target": target, "caption": args.get("caption"), "untrusted": untrusted}
        try:
            el = store.post(current_tool_actor() or "jarvis", el_type, payload)
        except ValueError as exc:
            return {"ok": False, "reason": "invalid", "detail": str(exc)[:200]}
        return {"ok": True, "id": el["id"], "type": el_type, "untrusted": untrusted,
                "shown": "on the owner's HUD, next to the named element"}

    server.register_tool(
        TOOL_NAME,
        _handle,
        gated=False,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        capability_id=CAPABILITY_ID,
    )
    return TOOL_NAME


__all__ = ["CAPABILITY_ID", "DESCRIPTION", "INPUT_SCHEMA", "TOOL_NAME", "register_pointer_tool"]
