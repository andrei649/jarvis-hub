"""
canvas.py — H12.18 Agent Canvas / A2UI (governed visual surface).

An agent can post **typed, sanitized** elements to a shared canvas that the HUD
renders over the network-brain view. "Governed" is the whole point: an agent
never emits raw HTML/script — only a small set of known-safe element types whose
fields are whitelisted and length/count-bounded (the same "validate down to a
known-safe config" discipline as the AI workflow builder). Every element is
attributed to its author and can be inspected, pinned, or cleared by the owner.

File-backed (JSON under ``memory_logs/canvas.json``), pure-Python, offline-testable.
The SVG/React rendering of these elements in HUD v2 is a separate frontend step.
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .persistence import JsonStore

DEFAULT_PATH = Path("memory_logs/canvas.json")

_MAX_ELEMENTS = 200          # bound the canvas (evict oldest unpinned)
_SAFE_SCHEMES = ("http", "https")


def _s(v, limit: int) -> str:
    """Coerce to a length-bounded, stripped string."""
    return str(v if v is not None else "").strip()[:limit]


def _safe_url(v) -> str:
    u = _s(v, 500)
    if not u:
        return ""
    if u.startswith("/static/") or u.startswith("/"):   # same-origin asset
        return u
    try:
        return u if urlparse(u).scheme in _SAFE_SCHEMES else ""
    except ValueError:
        return ""


def _list_of_str(v, max_items: int, item_len: int) -> list[str]:
    if not isinstance(v, (list, tuple)):
        return []
    return [_s(x, item_len) for x in list(v)[:max_items] if _s(x, item_len)]


def _sanitize(el_type: str, payload: dict) -> dict:
    """Return a sanitized payload for a known type, or raise ValueError."""
    p = payload if isinstance(payload, dict) else {}
    if el_type in ("text", "markdown"):
        body = _s(p.get("body"), 4000 if el_type == "markdown" else 2000)
        if not body:
            raise ValueError("body is required")
        return {"title": _s(p.get("title"), 120), "body": body}
    if el_type == "list":
        items = _list_of_str(p.get("items"), 50, 200)
        if not items:
            raise ValueError("items is required")
        return {"title": _s(p.get("title"), 120), "items": items}
    if el_type == "link":
        url = _safe_url(p.get("url"))
        if not url:
            raise ValueError("a valid http(s) url is required")
        return {"title": _s(p.get("title"), 120), "url": url, "label": _s(p.get("label"), 120)}
    if el_type == "metric":
        label = _s(p.get("label"), 120)
        if not label:
            raise ValueError("label is required")
        return {"label": label, "value": _s(p.get("value"), 60), "delta": _s(p.get("delta"), 60)}
    if el_type == "table":
        cols = _list_of_str(p.get("columns"), 12, 80)
        rows = [_list_of_str(r, 12, 200) for r in (p.get("rows") or [])[:50]
                if isinstance(r, (list, tuple))]
        if not cols and not rows:
            raise ValueError("columns or rows required")
        return {"title": _s(p.get("title"), 120), "columns": cols, "rows": rows}
    if el_type == "image_ref":
        src = _safe_url(p.get("src"))
        if not src:
            raise ValueError("a valid src is required")
        return {"title": _s(p.get("title"), 120), "src": src, "alt": _s(p.get("alt"), 200)}
    raise ValueError(f"unknown element type: {el_type}")


ALLOWED_TYPES = ("text", "markdown", "list", "link", "metric", "table", "image_ref")


class CanvasStore(JsonStore):
    """Agent-posted, governed visual elements."""

    def __init__(self, path: "str | Path | None" = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"elements": self._elements}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._elements = raw.get("elements", [])

    def post(self, agent: str, el_type: str, payload: dict, *, pinned: bool = False) -> dict:
        """Validate + sanitize an element and add it. Raises ValueError if unsafe."""
        clean = _sanitize(el_type, payload)        # raises on unknown type / bad payload
        el = {
            "id": secrets.token_urlsafe(8),
            "agent": _s(agent, 64) or "agent",
            "type": el_type,
            "payload": clean,
            "pinned": bool(pinned),
            "created_at": time.time(),
        }
        with self._lock:
            self._elements.append(el)
            self._evict()
            self._save()
        return dict(el)

    def _evict(self) -> None:
        if len(self._elements) <= _MAX_ELEMENTS:
            return
        # drop oldest *unpinned* first
        unpinned = [e for e in self._elements if not e.get("pinned")]
        drop = len(self._elements) - _MAX_ELEMENTS
        to_remove = {id(e) for e in unpinned[:drop]}
        self._elements = [e for e in self._elements if id(e) not in to_remove][-_MAX_ELEMENTS:]

    def list(self, agent: Optional[str] = None) -> list[dict]:
        items = [dict(e) for e in self._elements if agent is None or e.get("agent") == agent]
        return items[::-1]                         # newest first

    def get(self, el_id: str) -> Optional[dict]:
        for e in self._elements:
            if e["id"] == el_id:
                return dict(e)
        return None

    def pin(self, el_id: str, pinned: bool = True) -> Optional[dict]:
        for e in self._elements:
            if e["id"] == el_id:
                e["pinned"] = bool(pinned)
                with self._lock:
                    self._save()
                return dict(e)
        return None

    def remove(self, el_id: str) -> bool:
        before = len(self._elements)
        self._elements = [e for e in self._elements if e["id"] != el_id]
        if len(self._elements) != before:
            with self._lock:
                self._save()
            return True
        return False

    def clear(self, agent: Optional[str] = None, *, keep_pinned: bool = True) -> int:
        """Clear elements (optionally only one agent's); pinned kept by default."""
        def _keep(e):
            if agent is not None and e.get("agent") != agent:
                return True
            if keep_pinned and e.get("pinned"):
                return True
            return False
        kept = [e for e in self._elements if _keep(e)]
        removed = len(self._elements) - len(kept)
        if removed:
            self._elements = kept
            with self._lock:
                self._save()
        return removed
