"""todo_tree.py — a flat list with parent links, read as an indented tree (H666).

Hermes nests the agent's subtasks with one optional ``parent`` on each item (the id of
another item) instead of a nested array, so merge-by-id keeps working, and every front
end renders the list through the same defensive builder. Nerva does the same for the
``todo`` tool's items (``parent`` is another item's id) and for mission plan steps
(``parent`` is another step's ``idx``); ``nerva todo`` reads the tree here and the HUD
through its twin, ``frontend/src/todo-tree.ts``. Both suites read one shared set of
cases (``frontend/src/test/todo-tree-cases.json``) so the twins cannot drift apart.

The builder never drops an item and never raises on what it is given:

* items come back in depth-first order, children in list order under their parent;
* depth stops at :data:`MAX_DEPTH`: a deeper item renders at that depth, under its parent;
* an item whose parent is missing, itself, or not an id at all renders at depth 0 in its
  place. When two items share an id, the first one holds it, so a later duplicate that
  names that id as its parent sits under the first;
* the members of a cycle (and anything under them) are reached from no root, so they are
  appended at the end, flat, at depth 0, in list order.

Stdlib only: the CLI imports it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

#: How deep an item is drawn. A deeper one is drawn at this depth.
MAX_DEPTH = 4


def ref(value: Any) -> str | int | None:
    """A usable id: text or a whole number (a bool is not one). Anything else is none.

    A whole-valued float is the number it holds: JSON's ``1.0`` is ``1`` to the HUD's
    twin (``Number.isInteger``), so it must be ``1`` here too, or the two draw
    different trees from the same reply."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, (str, int)):
        return value
    return None


def tree(
    items: Iterable[Any],
    key: Callable[[Any], Any],
    parent: Callable[[Any], Any],
) -> list[tuple[Any, int]]:
    """``[(item, depth), ...]`` in depth-first order; every item exactly once. Anything
    that is not a list or tuple of items is an empty list, as the HUD's twin reads it."""
    rows = list(items) if isinstance(items, (list, tuple)) else []
    first: dict[Any, int] = {}
    for pos, item in enumerate(rows):
        own = ref(_safe(key, item))
        if own is not None and own not in first:
            first[own] = pos
    children: list[list[int]] = [[] for _ in rows]
    roots: list[int] = []
    for pos, item in enumerate(rows):
        above = first.get(ref(_safe(parent, item)))
        if above is None or above == pos:
            roots.append(pos)
        else:
            children[above].append(pos)
    out: list[tuple[Any, int]] = []
    placed = [False] * len(rows)
    for root in roots:
        stack = [(root, 0)]
        while stack:
            pos, depth = stack.pop()
            placed[pos] = True
            out.append((rows[pos], min(depth, MAX_DEPTH)))
            stack.extend((child, depth + 1) for child in reversed(children[pos]))
    out.extend((rows[pos], 0) for pos in range(len(rows)) if not placed[pos])
    return out


def _safe(getter: Callable[[Any], Any], item: Any) -> Any:
    try:
        return getter(item)
    except Exception:
        return None


__all__ = ["MAX_DEPTH", "ref", "tree"]
