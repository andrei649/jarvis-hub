"""
screen_grounding.py — H15.2 Local screen understanding (UI grounding).

Parses a vision model's grounding output (UI-TARS / Qwen3-VL via the H13.1 VLM
adapter) into located UI elements, and optionally **fuses** them with an
accessibility tree (the a11y tree is precise where the VLM is fuzzy, and vice
versa). Pure and offline-testable; the VLM that produces the grounding text is
the host seam.
"""

from __future__ import annotations

import json
import re
from typing import Optional

_COORD_RE = re.compile(r"(?P<label>[\w .,'\"-]+?)\s*(?:at|@)?\s*\(\s*(?P<x>\d+)\s*,\s*(?P<y>\d+)\s*\)")


def parse_grounding(vlm_output: str) -> "list[dict]":
    """Parse VLM grounding output into ``[{label, x, y, source}]``.

    Accepts a JSON array (``[{"label":..,"x":..,"y":..}]``) or free-text lines
    like ``"Submit button at (120, 340)"``.
    """
    text = (vlm_output or "").strip()
    # JSON form first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            out = []
            for e in data:
                if isinstance(e, dict) and "x" in e and "y" in e:
                    out.append({"label": str(e.get("label", "")).strip(),
                                "x": int(e["x"]), "y": int(e["y"]), "source": "vlm"})
            if out:
                return out
    except Exception:
        pass
    # free-text form
    out = []
    for m in _COORD_RE.finditer(text):
        out.append({"label": m.group("label").strip().strip('"').strip(),
                    "x": int(m.group("x")), "y": int(m.group("y")), "source": "vlm"})
    return out


def _close(a: dict, b: dict, tol: int = 24) -> bool:
    return abs(a["x"] - b["x"]) <= tol and abs(a["y"] - b["y"]) <= tol


def fuse_with_a11y(grounded: "list[dict]", a11y: "list[dict]", tol: int = 24) -> "list[dict]":
    """Merge VLM-grounded elements with accessibility-tree elements (dedup by proximity)."""
    fused = [dict(g) for g in grounded]
    for node in a11y or []:
        if "x" not in node or "y" not in node:
            continue
        match = next((g for g in fused if _close(g, node, tol)), None)
        if match is not None:
            match["a11y_label"] = node.get("label", "")
            match["role"] = node.get("role", "")
            match["source"] = "fused"
        else:
            fused.append({"label": node.get("label", ""), "x": int(node["x"]),
                          "y": int(node["y"]), "role": node.get("role", ""), "source": "a11y"})
    return fused


def locate(elements: "list[dict]", query: str) -> Optional[dict]:
    """Best element whose label (vlm or a11y) contains `query` (case-insensitive)."""
    q = (query or "").lower().strip()
    if not q:
        return None
    for e in elements or []:
        labels = f"{e.get('label', '')} {e.get('a11y_label', '')}".lower()
        if q in labels:
            return e
    return None


class ScreenGrounding:
    def ground(self, vlm_output: str, a11y: Optional[list] = None) -> "list[dict]":
        elements = parse_grounding(vlm_output)
        if a11y:
            elements = fuse_with_a11y(elements, a11y)
        return elements

    def locate(self, elements: "list[dict]", query: str) -> Optional[dict]:
        return locate(elements, query)
