"""H688 — addressing a setting, and a place inside its value, by a dotted name.

A setting is ``category.key``; a ``json`` setting holds nested data, so a name may go on
below the key: ``appearance.preferences.ui.theme``. Keys may themselves contain dots
(``"ui.theme"`` as one key of the preferences object), so a dot is not always a boundary.
The grammar, the same for ``config get``, ``set`` and ``unset``:

* Segments are separated by ``.``.
* ``\\.`` is a literal dot inside a segment, ``\\\\`` a literal backslash, ``\\"`` a quote.
* A segment written in double quotes (``"ui.theme"``) is taken exactly as written.
* A segment that is quoted or carries an escape is *strict*: it is one key, never joined.
* Consecutive plain (unquoted, unescaped) segments are matched *greedily* against the keys
  that exist at that level: ``ui.theme`` finds the key ``"ui.theme"`` when it exists, else
  ``ui`` and then ``theme`` inside it. When more than one reading exists at a level (both
  ``"ui"`` and ``"ui.theme"``), the name is refused as ambiguous and the error spells out
  the quoted form of each reading — nothing is picked silently.

A write never invents a structure beside a dotted key: creating a plain key ``ui`` while
the same object holds ``"ui.theme"`` would leave a phantom ``ui`` object next to the key the
owner almost certainly meant, so :func:`set_in` refuses it loudly (quote the segment to
mean a new key ``"ui"`` on purpose, escape the dot to mean a new key ``ui\\.font``).

Pure functions over plain JSON values: no storage, no I/O. The CLI resolves the setting with
:func:`resolve_setting` and reads/writes the rest with :func:`get_in`, :func:`set_in`,
:func:`unset_in` before the whole new value goes through the ordinary validated write.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from typing import Any

_INDEX = re.compile(r"[0-9]+")


class PathError(ValueError):
    """A name that does not parse or does not lead anywhere."""


class AmbiguousPath(PathError):
    """More than one existing key matches a run of plain segments."""


class PhantomIntermediate(PathError):
    """A write would create a plain key beside an existing dotted key that starts with it."""


@dataclass(frozen=True)
class Segment:
    text: str
    strict: bool = False


def parse(name: str) -> list[Segment]:
    """Split *name* into segments, resolving quotes and escapes (see the module docstring)."""
    segments: list[Segment] = []
    i, n = 0, len(name)
    if not name:
        raise PathError("an empty setting name")
    while True:
        buf: list[str] = []
        strict = False
        if i < n and name[i] == '"':
            strict = True
            i += 1
            while True:
                if i >= n:
                    raise PathError(f"unterminated quote in {name!r}")
                ch = name[i]
                if ch == "\\" and i + 1 < n:
                    buf.append(name[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                buf.append(ch)
                i += 1
            if i < n and name[i] != ".":
                raise PathError(f"a quoted segment must end at a dot or the end of {name!r}")
        else:
            while i < n and name[i] != ".":
                ch = name[i]
                if ch == "\\":
                    if i + 1 >= n:
                        raise PathError(f"a trailing backslash in {name!r}")
                    buf.append(name[i + 1])
                    strict = True
                    i += 2
                    continue
                if ch == '"':
                    raise PathError(f"a quote may only open a whole segment in {name!r}")
                buf.append(ch)
                i += 1
            if not buf:
                raise PathError(f"an empty segment in {name!r} (quote it, \"\", to mean an empty key)")
        segments.append(Segment("".join(buf), strict))
        if i >= n:
            return segments
        i += 1  # the dot
        if i >= n:
            raise PathError(f"a trailing dot in {name!r}")


def quote(key: str) -> str:
    """The strict, quoted spelling of one key."""
    return '"' + key.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(segments: list[Segment]) -> str:
    """A spelling of *segments* that parses back to the same strict keys."""
    return ".".join(quote(s.text) if (s.strict or "." in s.text or not s.text) else s.text for s in segments)


def _readings(segments: list[Segment], start: int) -> Iterator[tuple[str, int]]:
    """Every key the segments from *start* could spell, longest first, with the next index."""
    if segments[start].strict:
        yield segments[start].text, start + 1
        return
    end = start
    while end < len(segments) and not segments[end].strict:
        end += 1
    for stop in range(end, start, -1):
        yield ".".join(s.text for s in segments[start:stop]), stop


def match(segments: list[Segment], start: int, existing: Collection[str]) -> tuple[str, int] | None:
    """The one existing key the segments from *start* spell, or None; refuses ambiguity."""
    found = [(key, stop) for key, stop in _readings(segments, start) if key in existing]
    if len(found) > 1:
        spelled = " or ".join(
            render([Segment(key, True)] + segments[stop:]) for key, stop in found)
        raise AmbiguousPath(f"{'.'.join(s.text for s in segments[start:])!r} matches more than one key "
                            f"({', '.join(quote(k) for k, _ in found)}); spell it as {spelled}")
    return found[0] if found else None


def resolve_setting(name: str, declared: Collection[tuple[str, str]]) -> tuple[str, str, list[Segment]] | None:
    """``(category, key, path below the key)`` for *name* against the *declared* settings.

    The category is the first segment; the key is matched greedily (it may contain dots).
    None when no declared key of that category matches.
    """
    segments = parse(name)
    if len(segments) < 2:
        raise PathError(f"setting names are category.key, got {name!r}")
    category = segments[0].text
    keys = {key for cat, key in declared if cat == category}
    found = match(segments, 1, keys)
    if found is None:
        return None
    key, stop = found
    return category, key, segments[stop:]


def _step(node: Any, segments: list[Segment], i: int, where: list[Segment]) -> tuple[Any, int] | None:
    """The child of *node* the segments from *i* name, and the next index; None if absent."""
    if isinstance(node, dict):
        found = match(segments, i, node.keys())
        if found is None:
            return None
        key, stop = found
        return key, stop
    if isinstance(node, list):
        seg = segments[i]
        # ASCII digits only: str.isdigit() accepts '²' or '٣', which int() then rejects or
        # reads as another number.
        if not _INDEX.fullmatch(seg.text):
            raise PathError(f"{render(where) or 'the value'} is a list; {seg.text!r} is not an index")
        index = int(seg.text)
        if index >= len(node):
            return None
        return index, i + 1
    raise PathError(f"{render(where) or 'the value'} is not an object or a list; nothing is inside it")


def get_in(value: Any, segments: list[Segment]) -> Any:
    """What *segments* address inside *value*; PathError when it is not there."""
    node, i, where = value, 0, []
    while i < len(segments):
        step = _step(node, segments, i, where)
        if step is None:
            raise PathError(f"no {render(segments[i:])} in {render(where) or 'the value'}")
        child, i_next = step
        where.append(Segment(str(child), True))
        node, i = node[child], i_next
    return node


def _check_phantom(node: dict, key: str, segments: list[Segment], i: int) -> None:
    if segments[i].strict:
        return
    beside = sorted(k for k in node if isinstance(k, str) and k.startswith(key + "."))
    if beside:
        raise PhantomIntermediate(
            f"refusing to create a key {key!r} beside the existing dotted key {quote(beside[0])}: "
            f"to write inside that key, spell its whole name; to create a separate key {key!r} on "
            f"purpose quote it ({quote(key)}); to create one dotted key escape its dots "
            f"({key}\\.…)")


def set_in(value: Any, segments: list[Segment], new: Any) -> Any:
    """A copy of *value* with *new* at *segments*, creating missing objects on the way.

    Raises PhantomIntermediate rather than create a plain key beside a dotted key that
    starts with it, and PathError for a list index out of range or a step into a scalar.
    """
    if not segments:
        return copy.deepcopy(new)
    root = copy.deepcopy(value)
    node, i, where = root, 0, []
    while True:
        step = _step(node, segments, i, where)
        if step is None:
            if isinstance(node, list):
                raise PathError(f"{render(where) or 'the value'} has no index {segments[i].text} "
                                f"(it holds {len(node)})")
            # Missing from here on: each remaining segment is one new key (plain ones are
            # never merged into a dotted key that does not exist yet — escape to mean that).
            for j in range(i, len(segments)):
                key = segments[j].text
                _check_phantom(node, key, segments, j)
                if j == len(segments) - 1:
                    node[key] = copy.deepcopy(new)
                else:
                    node[key] = {}
                    node = node[key]
            return root
        child, i_next = step
        if i_next == len(segments):
            node[child] = copy.deepcopy(new)
            return root
        where.append(Segment(str(child), True))
        node, i = node[child], i_next


def unset_in(value: Any, segments: list[Segment]) -> Any:
    """A copy of *value* without what *segments* address; PathError when it is not there."""
    if not segments:
        raise PathError("nothing to remove below the setting itself")
    root = copy.deepcopy(value)
    # The same greedy walk as get_in, so a dotted last key ("ui.theme") is removed whole
    # and an ambiguous one refused — never split at its dot.
    node, i, where = root, 0, []
    while True:
        step = _step(node, segments, i, where)
        if step is None:
            raise PathError(f"no {render(segments[i:])} in {render(where) or 'the value'}")
        child, i_next = step
        if i_next == len(segments):
            del node[child]
            return root
        where.append(Segment(str(child), True))
        node, i = node[child], i_next
