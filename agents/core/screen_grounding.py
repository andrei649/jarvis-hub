"""
screen_grounding.py — H15.2 Local screen understanding (UI grounding).

Parses a vision model's grounding output (UI-TARS / Qwen3-VL via the H13.1 VLM
adapter) into located UI elements, and optionally **fuses** them with an
accessibility tree (the a11y tree is precise where the VLM is fuzzy, and vice
versa). Pure and offline-testable; the VLM that produces the grounding text is
the host seam.

Coordinate conventions (op-visual-grounding): open grounders do not agree on
what a number means — OS-Atlas / Qwen3-VL emit 0–1000 relative coordinates,
UI-TARS / Holo emit absolute pixels on the *resized* image the model saw.
``normalize_coords`` converts any of the named conventions to absolute pixels on
the original screenshot, which is the only thing a click can consume. Parsing
also understands the box forms those models emit (``[x1, y1, x2, y2]``,
``bbox_2d`` / ``point_2d`` JSON) and carries a ``rect`` when a box was given.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Optional

CONVENTION_ABSOLUTE = "absolute"
CONVENTION_ABSOLUTE_RESIZED = "absolute_resized"
CONVENTION_RELATIVE_1000 = "relative_1000"
CONVENTION_RELATIVE_UNIT = "relative_unit"
CONVENTIONS: tuple[str, ...] = (
    CONVENTION_ABSOLUTE,
    CONVENTION_ABSOLUTE_RESIZED,
    CONVENTION_RELATIVE_1000,
    CONVENTION_RELATIVE_UNIT,
)

_COORD_RE = re.compile(r"(?P<label>[\w .,'\"-]+?)\s*(?:at|@)?\s*\(\s*(?P<x>\d+)\s*,\s*(?P<y>\d+)\s*\)")
# ``label [x1, y1, x2, y2]`` / ``label: [[x1,y1,x2,y2]]`` — OS-Atlas / Qwen box form.
_BOX_RE = re.compile(
    r"(?P<label>[\w .,'\"-]+?)?\s*[:=]?\s*\[\[?\s*(?P<x1>\d+)\s*,\s*(?P<y1>\d+)\s*,"
    r"\s*(?P<x2>\d+)\s*,\s*(?P<y2>\d+)\s*\]?\]"
)
_STRIP_CHARS = " \t\"'`:=<>|"


def _clean_label(raw: Optional[str]) -> str:
    text = (raw or "").strip().strip(_STRIP_CHARS).strip()
    # Model markers such as ``<|box_start|>`` leave a bare token; drop it.
    if text.startswith("<|") or text.endswith("|>"):
        return ""
    return text


def _box_to_element(label: str, box: Sequence, source: str = "vlm") -> Optional[dict]:
    try:
        x1, y1, x2, y2 = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    return {
        "label": label,
        "x": (left + right) // 2,
        "y": (top + bottom) // 2,
        "rect": {"left": left, "top": top, "width": right - left, "height": bottom - top},
        "source": source,
    }


def _json_element(entry: Mapping) -> Optional[dict]:
    label = _clean_label(str(entry.get("label", entry.get("name", ""))))
    if "x" in entry and "y" in entry:
        try:
            return {"label": label, "x": int(entry["x"]), "y": int(entry["y"]), "source": "vlm"}
        except (TypeError, ValueError):
            return None
    for key in ("bbox_2d", "bbox", "box"):
        box = entry.get(key)
        if isinstance(box, Sequence) and not isinstance(box, str) and len(box) == 4:
            return _box_to_element(label, box)
    for key in ("point_2d", "point"):
        point = entry.get(key)
        if isinstance(point, Sequence) and not isinstance(point, str) and len(point) == 2:
            try:
                return {"label": label, "x": int(round(float(point[0]))),
                        "y": int(round(float(point[1]))), "source": "vlm"}
            except (TypeError, ValueError):
                return None
    return None


def parse_grounding(vlm_output: str) -> "list[dict]":
    """Parse VLM grounding output into ``[{label, x, y, source[, rect]}]``.

    Accepts a JSON array (``[{"label":..,"x":..,"y":..}]``, Qwen-style
    ``{"bbox_2d": [x1,y1,x2,y2]}`` / ``{"point_2d": [x,y]}``), a single JSON
    object, or free-text lines like ``"Submit button at (120, 340)"`` and the
    box form ``"Submit [120, 330, 160, 350]"``. Box forms carry a ``rect``; the
    element's ``x``/``y`` is the box centre. Coordinates are returned **as
    emitted** — apply :func:`normalize_coords` with the model's convention.
    """
    text = (vlm_output or "").strip()
    # JSON form first
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            out = []
            for e in data:
                if isinstance(e, Mapping):
                    element = _json_element(e)
                    if element is not None:
                        out.append(element)
            if out:
                return out
    except Exception:
        # not valid JSON → fall through to the free-text grounding parse below
        pass
    # free-text form
    out = []
    for m in _COORD_RE.finditer(text):
        out.append({"label": _clean_label(m.group("label")),
                    "x": int(m.group("x")), "y": int(m.group("y")), "source": "vlm"})
    if out:
        return out
    for m in _BOX_RE.finditer(text):
        element = _box_to_element(
            _clean_label(m.group("label")),
            (m.group("x1"), m.group("y1"), m.group("x2"), m.group("y2")),
        )
        if element is not None:
            out.append(element)
    return out


# ── coordinate conventions ───────────────────────────────────────────────────


def _pair(value, name: str) -> tuple[int, int]:
    if isinstance(value, Mapping):
        value = (value.get("width", value.get("w")), value.get("height", value.get("h")))
    try:
        width, height = int(value[0]), int(value[1])
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"{name} must be a (width, height) pair") from None
    if width <= 0 or height <= 0:
        raise ValueError(f"{name} must be positive")
    return width, height


def resized_dims(image_size, max_dim: int) -> tuple[int, int]:
    """Dimensions the VLM adapter hands the model (mirrors ``vlm._downscale``)."""
    width, height = _pair(image_size, "image_size")
    if max_dim <= 0 or max(width, height) <= max_dim:
        return width, height
    scale = max_dim / float(max(width, height))
    return max(1, int(width * scale)), max(1, int(height * scale))


def normalize_point(x, y, *, convention: str, image_size, resized_size=None) -> tuple[int, int]:
    """Convert one emitted coordinate to absolute pixels on the original image.

    ``image_size`` is the original screenshot's ``(width, height)``;
    ``resized_size`` is what the model actually saw (required for
    ``absolute_resized``). The result is clamped into the image so a model
    that overshoots by a pixel does not become an off-screen click.
    """
    if convention not in CONVENTIONS:
        raise ValueError(f"unknown coordinate convention: {convention!r}")
    width, height = _pair(image_size, "image_size")
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        raise ValueError("coordinates must be numeric") from None
    if fx != fx or fy != fy or fx in (float("inf"), float("-inf")) or fy in (float("inf"), float("-inf")):
        raise ValueError("coordinates must be finite")
    if convention == CONVENTION_ABSOLUTE:
        px, py = fx, fy
    elif convention == CONVENTION_ABSOLUTE_RESIZED:
        if resized_size is None:
            raise ValueError("resized_size is required for absolute_resized")
        rw, rh = _pair(resized_size, "resized_size")
        px, py = fx * width / rw, fy * height / rh
    elif convention == CONVENTION_RELATIVE_1000:
        px, py = fx * width / 1000.0, fy * height / 1000.0
    else:  # relative_unit
        px, py = fx * width, fy * height
    ax = min(max(int(round(px)), 0), width - 1)
    ay = min(max(int(round(py)), 0), height - 1)
    return ax, ay


def normalize_coords(elements: "list[dict]", *, convention: str, image_size,
                     resized_size=None) -> "list[dict]":
    """Return copies of ``elements`` with ``x``/``y`` (and ``rect``) in absolute pixels.

    Every element is annotated ``convention: "absolute"`` and keeps the source
    convention under ``emitted_convention`` so an audit can see what the model
    said and what was clicked. Elements whose coordinates cannot be converted
    are dropped rather than passed through half-normalized.
    """
    if convention not in CONVENTIONS:
        raise ValueError(f"unknown coordinate convention: {convention!r}")
    out: list[dict] = []
    for element in elements or []:
        if not isinstance(element, Mapping) or "x" not in element or "y" not in element:
            continue
        try:
            x, y = normalize_point(element["x"], element["y"], convention=convention,
                                   image_size=image_size, resized_size=resized_size)
        except ValueError:
            continue
        copy = dict(element)
        copy["x"], copy["y"] = x, y
        rect = element.get("rect")
        if isinstance(rect, Mapping):
            try:
                left, top = normalize_point(rect["left"], rect["top"], convention=convention,
                                            image_size=image_size, resized_size=resized_size)
                right, bottom = normalize_point(
                    float(rect["left"]) + float(rect["width"]),
                    float(rect["top"]) + float(rect["height"]),
                    convention=convention, image_size=image_size, resized_size=resized_size,
                )
                copy["rect"] = {"left": left, "top": top,
                                "width": max(right - left, 0), "height": max(bottom - top, 0)}
            except (KeyError, TypeError, ValueError):
                copy.pop("rect", None)
        copy["emitted_convention"] = convention
        copy["convention"] = CONVENTION_ABSOLUTE
        out.append(copy)
    return out


# ── a11y fusion ──────────────────────────────────────────────────────────────


def _rect_of(node: Mapping) -> Optional[tuple[int, int, int, int]]:
    rect = node.get("rect")
    try:
        if isinstance(rect, Mapping):
            left = int(rect.get("left", rect.get("x")))
            top = int(rect.get("top", rect.get("y")))
            width = int(rect.get("width", rect.get("w")))
            height = int(rect.get("height", rect.get("h")))
        elif isinstance(rect, Sequence) and not isinstance(rect, str) and len(rect) == 4:
            left, top, width, height = (int(v) for v in rect)
        else:
            return None
    except (TypeError, ValueError):
        return None
    if width < 0 or height < 0:
        return None
    return left, top, width, height


def _point_of(node: Mapping) -> Optional[tuple[int, int]]:
    """A node's click point: explicit x/y, else ``center``, else the rect centre."""
    try:
        if "x" in node and "y" in node:
            return int(node["x"]), int(node["y"])
        center = node.get("center")
        if isinstance(center, Mapping):
            return int(center["x"]), int(center["y"])
        if isinstance(center, Sequence) and not isinstance(center, str) and len(center) == 2:
            return int(center[0]), int(center[1])
    except (TypeError, ValueError, KeyError):
        return None
    rect = _rect_of(node)
    if rect is None:
        return None
    left, top, width, height = rect
    return left + width // 2, top + height // 2


def _close(a: dict, b: dict, tol: int = 24) -> bool:
    return abs(a["x"] - b["x"]) <= tol and abs(a["y"] - b["y"]) <= tol


def _inside(point: dict, rect: tuple[int, int, int, int]) -> bool:
    left, top, width, height = rect
    return left <= point["x"] <= left + width and top <= point["y"] <= top + height


def fuse_with_a11y(grounded: "list[dict]", a11y: "list[dict]", tol: int = 24) -> "list[dict]":
    """Merge VLM-grounded elements with accessibility-tree elements.

    An a11y node contributes its click point from ``x``/``y``, ``center`` or the
    centre of ``rect`` (the shape the desktop drivers emit). A grounded point
    that falls **inside** a node's rect is a match regardless of ``tol``; without
    a rect, proximity within ``tol`` pixels decides. Matched elements become
    ``source: "fused"`` and inherit the a11y label/role/rect (the precise half);
    unmatched a11y nodes are appended as ``source: "a11y"``.
    """
    fused = [dict(g) for g in grounded]
    for node in a11y or []:
        if not isinstance(node, Mapping):
            continue
        point = _point_of(node)
        if point is None:
            continue
        rect = _rect_of(node)
        probe = {"x": point[0], "y": point[1]}
        label = node.get("label", node.get("name", ""))
        match = next(
            (g for g in fused
             if (rect is not None and _inside(g, rect)) or _close(g, probe, tol)),
            None,
        )
        if match is not None:
            match["a11y_label"] = label
            match["role"] = node.get("role", "")
            match["source"] = "fused"
            if rect is not None and "rect" not in match:
                match["rect"] = {"left": rect[0], "top": rect[1],
                                 "width": rect[2], "height": rect[3]}
        else:
            entry = {"label": label, "x": point[0], "y": point[1],
                     "role": node.get("role", ""), "source": "a11y"}
            if rect is not None:
                entry["rect"] = {"left": rect[0], "top": rect[1],
                                 "width": rect[2], "height": rect[3]}
            fused.append(entry)
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
