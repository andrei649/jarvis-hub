#!/usr/bin/env python3
"""Query ``BACKLOG.md`` without loading it into an assistant's context.

``BACKLOG.md`` is ~957 KB — roughly 176K tokens measured with a real tokenizer
(``docs/AI_CONTEXT.md``), which is 73% of the whole project-state tier. Every
turn that answers "what is still open" by reading the file whole pays that,
repeatedly, to look at a few dozen lines. ``docs/AI_CONTEXT.md`` has always said
not to; it had no tool that made the advice followable, so under pressure the
file got read whole anyway.

This is that tool. Every subcommand answers one question and prints bounded
output — a row's id and first sentence, not its body, unless ``show`` is asked
for the body by name. Reach for the file itself only when *writing* to it, and
then open the one section ``sections`` points at.

    scripts/backlog.py counts              # done / open, and per-prefix
    scripts/backlog.py open                # the open rows, one line each
    scripts/backlog.py show HA-4i SEC-B5   # those rows in full
    scripts/backlog.py sections            # headings, line numbers, row counts
    scripts/backlog.py find "taint"        # matching rows, one line each

The grammar it parses is the file's own: a row starts at column 0 with
``- [ ]`` or ``- [x]``, its body is the indented lines that follow, and an id —
when the row has one — is the first ``PREFIX-123`` inside the leading bold span.
Rows without an id (owner credential lines, descriptive caveats written as
checkboxes) are kept and addressed by line number.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "BACKLOG.md"

#: One-line summaries are cut here. Long enough to identify a row, short enough
#: that listing every open row stays a rounding error against the file itself.
SUMMARY_CHARS = 150
#: ``find`` and ``open`` never print more than this many rows without --limit.
DEFAULT_LIMIT = 100

_ROW = re.compile(r"^- \[([ xX])\] (.*)$")
_HEADING = re.compile(r"^(#{2,4}) +(.*)$")
#: An id inside the row's opening bold span: **HA-5d — …**, **DRA-58 …**, and
#: the lettered families too (**SEC-B5**, **GAP-4**) — the segment after the
#: dash may lead with a letter, which an id pattern requiring a digit misses.
_ID = re.compile(r"\*\*\s*([A-Z][A-Z0-9]*-[A-Z]?[0-9]+[a-z]?)\b")
#: Markdown noise stripped from a one-line summary so the line reads as prose.
_NOISE = re.compile(r"[*`]|^[✅🔴🟠🟡🟢⬜🔨🌊]\s*")


@dataclass
class Row:
    """One checkbox row: where it is, whether it is done, and what it says."""

    line: int
    done: bool
    ident: str | None
    section: str
    text: str
    body: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """The row's own words: checkbox, status emoji and markdown all stripped."""
        flat = " ".join(_ROW.match(self.text).group(2).split())
        for _ in range(3):  # emoji then bold markers, in either order
            flat = _NOISE.sub("", flat).strip()
        return flat[:SUMMARY_CHARS]

    @property
    def label(self) -> str:
        return self.ident or f"L{self.line}"

    def render(self) -> str:
        head = f"{'[x]' if self.done else '[ ]'} {self.label}  (BACKLOG.md:{self.line})"
        return "\n".join([head, f"  section: {self.section}", "", self.text, *self.body])


def parse(path: Path = BACKLOG) -> list[Row]:
    """Every checkbox row in the file, in document order."""
    rows: list[Row] = []
    section = "(no section)"
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        heading = _HEADING.match(raw)
        if heading:
            section = " ".join(heading.group(2).split())
            continue
        match = _ROW.match(raw)
        if match:
            ident = _ID.search(match.group(2))
            rows.append(
                Row(
                    line=number,
                    done=match.group(1).lower() == "x",
                    ident=ident.group(1) if ident else None,
                    section=section,
                    text=raw,
                )
            )
            continue
        # An indented line right after a row is that row's body; a blank line is
        # kept only once a body has started, since a row can span paragraphs but
        # the blank lines *between* rows belong to neither.
        if rows and (raw.startswith("  ") or (not raw.strip() and rows[-1].body)):
            rows[-1].body.append(raw)
    for row in rows:
        while row.body and not row.body[-1].strip():
            row.body.pop()
    return rows


def cmd_counts(rows: list[Row], _ns: argparse.Namespace) -> int:
    done = [r for r in rows if r.done]
    todo = [r for r in rows if not r.done]
    print(f"rows: {len(rows)}  done: {len(done)}  open: {len(todo)}")
    prefixes: dict[str, list[Row]] = {}
    for row in todo:
        prefixes.setdefault(row.ident.split("-")[0] if row.ident else "(no id)", []).append(row)
    print("\nopen by prefix:")
    for prefix, group in sorted(prefixes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"  {len(group):3d}  {prefix}")
    return 0


def _print_rows(rows: list[Row], limit: int) -> int:
    shown = rows[:limit]
    for row in shown:
        print(f"{row.label:<10} L{row.line:<5} {row.summary}")
    if len(rows) > len(shown):
        print(f"\n… {len(rows) - len(shown)} more (raise --limit)")
    return 0


def cmd_open(rows: list[Row], ns: argparse.Namespace) -> int:
    todo = [r for r in rows if not r.done]
    if ns.section:
        needle = ns.section.lower()
        todo = [r for r in todo if needle in r.section.lower()]
    return _print_rows(todo, ns.limit)


def cmd_show(rows: list[Row], ns: argparse.Namespace) -> int:
    by_id = {r.ident.lower(): r for r in rows if r.ident}
    by_line = {f"l{r.line}": r for r in rows}
    missing: list[str] = []
    found: list[Row] = []
    for wanted in ns.ident:
        key = wanted.lower()
        row = by_id.get(key) or by_line.get(key)
        (found.append(row) if row else missing.append(wanted))
    for index, row in enumerate(found):
        if index:
            print()
        print(row.render())
    for wanted in missing:
        print(f"not found: {wanted}", file=sys.stderr)
    return 1 if missing else 0


def cmd_sections(rows: list[Row], _ns: argparse.Namespace) -> int:
    order: dict[str, list[Row]] = {}
    for row in rows:
        order.setdefault(row.section, []).append(row)
    for section, group in order.items():
        todo = sum(1 for r in group if not r.done)
        print(f"L{group[0].line:<6} {len(group):3d} rows  {todo:3d} open  {section[:90]}")
    return 0


def cmd_find(rows: list[Row], ns: argparse.Namespace) -> int:
    try:
        pattern = re.compile(ns.pattern, re.IGNORECASE)
    except re.error as exc:
        print(f"bad pattern: {exc}", file=sys.stderr)
        return 2
    hits = [r for r in rows if pattern.search(r.text) or pattern.search("\n".join(r.body))]
    if ns.open_only:
        hits = [r for r in hits if not r.done]
    return _print_rows(hits, ns.limit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backlog.py", description="Query BACKLOG.md without loading it whole."
    )
    parser.add_argument("--file", type=Path, default=BACKLOG, help=argparse.SUPPRESS)
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("counts", help="row totals, and open rows per id prefix")

    opened = subs.add_parser("open", help="the open rows, one line each")
    opened.add_argument("--section", help="only rows under a heading matching this text")
    opened.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    show = subs.add_parser("show", help="print named rows in full")
    show.add_argument("ident", nargs="+", help="row ids (HA-4i) or line refs (L1587)")

    subs.add_parser("sections", help="headings with line numbers and row counts")

    find = subs.add_parser("find", help="rows whose text or body matches a regex")
    find.add_argument("pattern")
    find.add_argument("--open-only", action="store_true")
    find.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser


_COMMANDS = {
    "counts": cmd_counts,
    "open": cmd_open,
    "show": cmd_show,
    "sections": cmd_sections,
    "find": cmd_find,
}


def _run(argv: list[str] | None) -> int:
    ns = build_parser().parse_args(argv)
    if not ns.file.is_file():
        print(f"no such file: {ns.file}", file=sys.stderr)
        return 2
    return _COMMANDS[ns.command](parse(ns.file), ns)


def main(argv: list[str] | None = None) -> int:
    """Run one query. ``| head`` closing the pipe early is a normal end, not a crash."""
    try:
        return _run(argv)
    except BrokenPipeError:
        # Silence Python's "Exception ignored" epilogue by pointing stdout at
        # devnull before interpreter shutdown flushes it.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    # The documents are Unicode; redirected Windows streams otherwise use a
    # legacy code page and can crash on a normal row. The CLI emits UTF-8.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    raise SystemExit(main())
