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
    scripts/backlog.py tables counts         # work-item table status rollup
    scripts/backlog.py tables list --open-only --limit 20
    scripts/backlog.py tables show H18.1

The grammar it parses is the file's own: a row starts at column 0 with
``- [ ]`` or ``- [x]``, its body is the indented lines that follow, and an id —
when the row has one — is the first ``PREFIX-123`` inside the leading bold span.
Rows without an id (owner credential lines, descriptive caveats written as
checkboxes) are kept and addressed by line number.

The separate ``tables`` commands count only structurally recognized work-item
tables. Unclassified task-shaped tables and repeated IDs are reported explicitly
so a checkbox-only count cannot be mistaken for whole-backlog completion.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __package__:
    from .status_sync import classify_row
else:
    from status_sync import classify_row

REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "BACKLOG.md"

#: One-line summaries are cut here. Long enough to identify a row, short enough
#: that listing every open row stays a rounding error against the file itself.
SUMMARY_CHARS = 150
#: ``find`` and ``open`` never print more than this many rows without --limit.
DEFAULT_LIMIT = 100

_ROW = re.compile(r"^- \[([ xX])\] (.*)$")
_HEADING = re.compile(r"^(#{2,4}) +(.*)$")
_TABLE_HEADING = re.compile(r"^(#{1,6}) +(.*)$")
#: An id inside the row's opening bold span: **HA-5d — …**, **DRA-58 …**, and
#: the lettered families too (**SEC-B5**, **GAP-4**) — the segment after the
#: dash may lead with a letter, which an id pattern requiring a digit misses.
_ID = re.compile(r"\*\*\s*([A-Z][A-Z0-9]*-[A-Z]?[0-9]+[a-z]?)\b")
#: Markdown noise stripped from a one-line summary so the line reads as prose.
_NOISE = re.compile(r"[*`]|^[✅🔴🟠🟡🟢⬜🔨🌊]\s*")
_TABLE_ID = re.compile(
    r"^\s*[*_`~\[]*\s*(?:[✅🟢🔨🔴⬜🟡⏳]\s*)?"
    r"(?P<id>O\d+-P\d+(?:\.\d+)*|H\d+\.[A-Z]\d*[a-z]?|Gate\s+[A-Z]|"
    r"H\d+(?:\.\d+)+[a-z]?|T-\d+(?:\.\d+)+[a-z]?|"
    r"[A-Z]{1,5}-\d+(?:\.\d+)*[a-z]?|[A-Z]{1,3}\d+(?:\.\d+)*[a-z]?)"
    r"(?![A-Za-z0-9_.-])"
)
_TABLE_ID_MENTION = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:O\d+-P\d+(?:\.\d+)*|H\d+\.[A-Z]\d*[a-z]?|Gate\s+[A-Z]|"
    r"H\d+(?:\.\d+)+[a-z]?|T-\d+(?:\.\d+)+[a-z]?|"
    r"[A-Z]{1,5}-\d+(?:\.\d+)*[a-z]?|[A-Z]{1,3}\d+(?:\.\d+)*[a-z]?)"
    r"(?![A-Za-z0-9_.-])"
)
_TABLE_DIVIDER = re.compile(r"^:?-{3,}:?$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_NON_WORK_SECTION = re.compile(
    r"^(?:(?:project|release|status)\s+)?(?:history|historical|metrics?|evidence|snapshots?|changelog)\b",
    re.IGNORECASE,
)
MAX_TABLE_LIMIT = 500
DIAGNOSTIC_LIMIT = 20
SHOW_CHARS = 500


@dataclass(frozen=True)
class TableWorkItem:
    ident: str
    section: str
    line: int
    status: str
    summary: str
    text: str

    def metadata(self) -> dict[str, str | int]:
        return {"id": self.ident, "section": self.section, "line": self.line,
                "status": self.status, "summary": self.summary}


@dataclass(frozen=True)
class TableDiagnostic:
    section: str
    line: int
    header: str
    unclassified_rows: int
    sample_key: str = ""
    sample_number: str = ""
    mentioned_ids: tuple[str, ...] = ()
    status_hints: tuple[int, int, int, int] = (0, 0, 0, 0)

    def metadata(self) -> dict[str, str | int]:
        return {"section": self.section, "line": self.line,
                "header": self.header[:SUMMARY_CHARS], "unclassified_rows": self.unclassified_rows,
                "sample_key": self.sample_key, "sample_number": self.sample_number,
                "mentioned_ids": list(self.mentioned_ids),
                "status_hints": dict(zip(("done", "delivered", "blocked", "open"), self.status_hints, strict=True))}


@dataclass(frozen=True)
class ExcludedTable:
    section: str
    excluded_by: str
    line: int
    header: str
    rows: int

    def metadata(self) -> dict[str, str | int]:
        return {"section": self.section, "excluded_by": self.excluded_by,
                "line": self.line, "header": self.header[:SUMMARY_CHARS], "rows": self.rows}


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _table_id_column(cells: list[str]) -> int | None:
    header = [re.sub(r"[*_`~]", "", cell).strip().casefold() for cell in cells]
    first = header[0] if header else ""
    identifies = first in {"id", "task id", "work id", "item id", "work item", "task", "gate", "horizon", "project"}
    describes = any(any(term in cell for term in ("task", "item", "status", "state", "summary", "description", "scope", "name", "capability", "deliverable", "gate", "project")) for cell in header[1:])
    if identifies and describes:
        return 0
    if first in {"#", "no.", "nr.", "number"}:
        for index, name in enumerate(header[1:4], 1):
            if name in {"item", "task", "work item", "gate"}:
                return index
    return None


def _tasklike_header(cells: list[str]) -> bool:
    names = [re.sub(r"[*_`~]", "", cell).strip().casefold() for cell in cells]
    has_item = any(name in {"item", "task", "work item", "task id", "work id"} for name in names)
    has_state = any(name in {"status", "state", "s"} for name in names)
    return has_item and has_state


def _non_work_heading(title: str) -> bool:
    label = re.sub(r"^[^\w]+", "", title).strip()
    return bool(_NON_WORK_SECTION.match(label))


def _status_hints(rows: list[list[str]]) -> tuple[int, int, int, int]:
    counts = dict.fromkeys(("done", "delivered", "blocked", "open"), 0)
    for cells in rows:
        counts[classify_row(cells)] += 1
    return tuple(counts[key] for key in ("done", "delivered", "blocked", "open"))


def _table_summary(cells: list[str], header: list[str], id_column: int, match: re.Match[str]) -> str:
    after_id = re.sub(r"^[\s*_`—–:-]+", "", cells[id_column][match.end('id'):])
    after_id = re.sub(r"^[✅🟢🔨🔴⬜🟡⏳]\s*", "", after_id)
    after_id = re.sub(r"^[\s*_`—–:-]+", "", after_id)
    if after_id:
        cell = after_id
    else:
        indexes = [i for i, name in enumerate(header) if i != id_column
                   and not any(word in name.casefold() for word in ("status", "state", "owner", "date", "evidence", "proof"))
                   and name.strip() not in {"#", "S", "P"}]
        cell = cells[indexes[0]] if indexes and indexes[0] < len(cells) else cells[id_column]
    clean = re.sub(r"[*_`]", "", cell).strip()
    clean = re.sub(r"^[✅🟢🔨🔴⬜🟡⏳]\s*", "", clean)
    return " ".join(clean.split())[:SUMMARY_CHARS]


def _parse_table_work_items(text: str) -> tuple[list[TableWorkItem], list[TableDiagnostic], list[ExcludedTable]]:
    lines = text.splitlines()
    items: list[TableWorkItem] = []
    diagnostics: list[TableDiagnostic] = []
    excluded: list[ExcludedTable] = []
    section = "(no section)"
    excluded_by: str | None = None
    headings: list[tuple[int, str, str | None]] = []
    fence_char = ""
    fence_length = 0
    index = 0
    while index < len(lines):
        raw = lines[index]
        fence = _FENCE.match(raw)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char, fence_length = "", 0
            index += 1
            continue
        if fence_char:
            index += 1
            continue
        heading = _TABLE_HEADING.match(raw)
        if heading:
            level = len(heading.group(1))
            section = " ".join(heading.group(2).split())
            while headings and headings[-1][0] >= level:
                headings.pop()
            excluded_by = (headings[-1][2] if headings else None) or (section if _non_work_heading(section) else None)
            headings.append((level, section, excluded_by))
            index += 1
            continue
        header = _table_cells(raw)
        divider = _table_cells(lines[index + 1]) if index + 1 < len(lines) else None
        if not (header and divider and len(header) == len(divider)
                and all(_TABLE_DIVIDER.fullmatch(cell) for cell in divider)):
            index += 1
            continue
        table_line = index + 1
        index += 2
        rows: list[tuple[int, list[str]]] = []
        while index < len(lines):
            cells = _table_cells(lines[index])
            if not cells:
                break
            rows.append((index + 1, cells))
            index += 1
        if excluded_by:
            if rows and (_table_id_column(header) is not None or _tasklike_header(header)):
                excluded.append(ExcludedTable(section, excluded_by, table_line, " | ".join(header), len(rows)))
            continue
        id_column = _table_id_column(header)
        if id_column is None:
            if rows and _tasklike_header(header):
                names = [re.sub(r"[*_`~]", "", cell).strip().casefold() for cell in header]
                item_column = next(i for i, name in enumerate(names) if name in {"item", "task", "work item", "task id", "work id"})
                sample = rows[0][1]
                sample_cell = sample[item_column] if item_column < len(sample) else ""
                sample_key = (sample_cell.lstrip(" *_`").split(maxsplit=1) or [""])[0][:30]
                mentioned = tuple(dict.fromkeys(_TABLE_ID_MENTION.findall(sample_cell)))[:5]
                diagnostics.append(TableDiagnostic(
                    section, table_line, " | ".join(header), len(rows), sample_key,
                    sample[0][:30], mentioned, _status_hints([cells for _, cells in rows]),
                ))
            continue
        unclassified = 0
        unclassified_cells: list[list[str]] = []
        sample_key = ""
        sample_number = ""
        mentioned_ids: list[str] = []
        for number, cells in rows:
            if not cells:
                continue
            candidate_columns = (0, id_column) if id_column != 0 and header[0].strip() == "#" else (id_column,)
            found = None
            row_id_column = id_column
            for column in candidate_columns:
                if column < len(cells):
                    found = _TABLE_ID.search(cells[column])
                    if found:
                        row_id_column = column
                        break
            if not found:
                unclassified += 1
                unclassified_cells.append(cells[id_column:])
                if not sample_key and id_column < len(cells):
                    key_cell = cells[id_column].lstrip(" *_`")
                    sample_key = (key_cell.split(maxsplit=1) or [""])[0][:30]
                    sample_number = cells[0][:30]
                if id_column < len(cells):
                    for mention in _TABLE_ID_MENTION.findall(cells[id_column]):
                        if mention not in mentioned_ids and len(mentioned_ids) < 5:
                            mentioned_ids.append(mention)
                continue
            ident = found.group("id")
            row_text = " | ".join(cells)
            marker_cell = cells[row_id_column][:found.start("id")] + cells[row_id_column][found.end("id"):]
            marker_cell = re.sub(r"\[\]\([^)]*\)", "", marker_cell)
            items.append(TableWorkItem(
                ident=ident, section=section, line=number,
                status=classify_row([f"WORKID {marker_cell}", *cells[row_id_column + 1:]]),
                summary=_table_summary(cells, header, row_id_column, found),
                text=row_text if len(row_text) <= SHOW_CHARS else row_text[:SHOW_CHARS - 1] + "…",
            ))
        if unclassified:
            diagnostics.append(TableDiagnostic(section, table_line, " | ".join(header), unclassified, sample_key, sample_number, tuple(mentioned_ids), _status_hints(unclassified_cells)))
    return items, diagnostics, excluded


def parse_table_work_items(text: str) -> list[TableWorkItem]:
    """Recognized work-item rows only; table diagnostics are exposed by the CLI."""
    return _parse_table_work_items(text)[0]


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


def _table_totals(items: list[TableWorkItem]) -> dict[str, int]:
    totals = dict.fromkeys(("total", "done", "delivered", "blocked", "open"), 0)
    for item in items:
        totals["total"] += 1
        totals[item.status] += 1
    totals["open_or_blocked"] = totals["open"] + totals["blocked"]
    return totals


def _table_filter(items: list[TableWorkItem], diagnostics: list[TableDiagnostic], section: str | None) -> tuple[list[TableWorkItem], list[TableDiagnostic]]:
    if not section:
        return items, diagnostics
    needle = section.casefold()
    return ([item for item in items if needle in item.section.casefold()],
            [diagnostic for diagnostic in diagnostics if needle in diagnostic.section.casefold()])


def _table_limit(value: int) -> int:
    if not 1 <= value <= MAX_TABLE_LIMIT:
        raise ValueError(f"--limit must be between 1 and {MAX_TABLE_LIMIT}")
    return value


def cmd_tables(path: Path, ns: argparse.Namespace) -> int:
    items, diagnostics, excluded = _parse_table_work_items(path.read_text(encoding="utf-8"))
    items, diagnostics = _table_filter(items, diagnostics, getattr(ns, "section", None))
    if getattr(ns, "section", None):
        needle = ns.section.casefold()
        excluded = [table for table in excluded
                    if needle in table.section.casefold() or needle in table.excluded_by.casefold()]
    if ns.table_command == "counts":
        totals = _table_totals(items)
        grouped: dict[str, list[TableWorkItem]] = {}
        by_id: dict[str, list[TableWorkItem]] = {}
        for item in items:
            grouped.setdefault(item.section, []).append(item)
            by_id.setdefault(item.ident.casefold(), []).append(item)
        sections = [{"section": section, **_table_totals(group)} for section, group in grouped.items()]
        duplicates = [group for group in by_id.values() if len(group) > 1]
        payload = {"totals": totals, "section_count": len(sections),
                   "sections": sections[:DEFAULT_LIMIT],
                   "duplicate_ids": len(duplicates),
                   "duplicate_examples": [{"id": group[0].ident, "lines": [item.line for item in group[:5]]}
                                          for group in duplicates[:DIAGNOSTIC_LIMIT]],
                   "unclassified_tables": len(diagnostics),
                   "diagnostics": [d.metadata() for d in diagnostics[:DIAGNOSTIC_LIMIT]],
                   "excluded_tables": len(excluded),
                   "excluded_diagnostics": [table.metadata() for table in excluded[:DIAGNOSTIC_LIMIT]]}
        if ns.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print("table work items: {total}  done: {done}  delivered: {delivered}  blocked: {blocked}  open: {open}  open or blocked: {open_or_blocked}".format(**totals))
            for section in sections[:DEFAULT_LIMIT]:
                print("  {total:4d} total  {done:4d} done  {delivered:4d} delivered  {blocked:4d} blocked  {open:4d} open  {section}".format(**section))
            if len(sections) > DEFAULT_LIMIT:
                print(f"… {len(sections) - DEFAULT_LIMIT} more sections")
            print(f"duplicate ids: {len(duplicates)}")
            for group in duplicates[:DIAGNOSTIC_LIMIT]:
                print(f"  {group[0].ident}: lines {', '.join(str(item.line) for item in group[:5])}")
            print(f"unclassified task-like tables: {len(diagnostics)}")
            for diagnostic in diagnostics[:DIAGNOSTIC_LIMIT]:
                print(f"  L{diagnostic.line}  {diagnostic.section[:90]}  ({diagnostic.unclassified_rows} unclassified rows; sample key: {diagnostic.sample_key}; mentions: {','.join(diagnostic.mentioned_ids)}; header: {diagnostic.header[:SUMMARY_CHARS]})")
            if len(diagnostics) > DIAGNOSTIC_LIMIT:
                print(f"… {len(diagnostics) - DIAGNOSTIC_LIMIT} more diagnostics")
            print(f"excluded task-shaped tables: {len(excluded)}")
            for table in excluded[:DIAGNOSTIC_LIMIT]:
                print(f"  L{table.line}  {table.section[:90]}  (under {table.excluded_by[:70]}; {table.rows} rows)")
            if len(excluded) > DIAGNOSTIC_LIMIT:
                print(f"… {len(excluded) - DIAGNOSTIC_LIMIT} more excluded tables")
        return 0

    if ns.table_command == "list":
        try:
            limit = _table_limit(ns.limit)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if ns.open_only:
            items = [item for item in items if item.status in {"open", "blocked"}]
        shown = items[:limit]
        if ns.json:
            print(json.dumps({"total": len(items), "rows": [item.metadata() for item in shown],
                              "unclassified_tables": len(diagnostics),
                              "diagnostics": [d.metadata() for d in diagnostics[:DIAGNOSTIC_LIMIT]],
                              "excluded_tables": len(excluded),
                              "excluded_diagnostics": [table.metadata() for table in excluded[:DIAGNOSTIC_LIMIT]]}, ensure_ascii=False))
        else:
            for item in shown:
                print(f"{item.ident:<12} {item.status:<9} L{item.line:<6} {item.section[:50]} — {item.summary}")
            if len(items) > len(shown):
                print(f"… {len(items) - len(shown)} more (raise --limit)")
            if diagnostics:
                print(f"unclassified task-like tables: {len(diagnostics)} (use tables counts for diagnostics)")
            if excluded:
                print(f"excluded task-shaped tables: {len(excluded)} (use tables counts for diagnostics)")
        return 0

    if ns.table_command == "show":
        if len(ns.ident) > 20:
            print("show accepts at most 20 ids", file=sys.stderr)
            return 2
        by_id: dict[str, list[TableWorkItem]] = {}
        for item in items:
            by_id.setdefault(item.ident.casefold(), []).append(item)
        found: list[TableWorkItem] = []
        error_code = 0
        for wanted in ns.ident:
            matches = by_id.get(wanted.casefold(), [])
            if not matches:
                print(f"not found: {wanted}", file=sys.stderr)
                error_code = max(error_code, 1)
            elif len(matches) > 1:
                print(f"ambiguous id: {wanted} ({len(matches)} table rows)", file=sys.stderr)
                error_code = 2
            else:
                found.append(matches[0])
        if ns.json:
            print(json.dumps({"rows": [dict(item.metadata(), text=item.text) for item in found]}, ensure_ascii=False))
        else:
            for item in found:
                print(f"{item.ident}  {item.status}  (BACKLOG.md:{item.line})")
                print(f"  section: {item.section}")
                print(f"  {item.text}")
        return error_code
    return 2


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

    tables = subs.add_parser("tables", help="bounded work-item table queries")
    table_subs = tables.add_subparsers(dest="table_command", required=True)
    table_counts = table_subs.add_parser("counts", help="work-item table totals and unclassified-table diagnostics")
    table_counts.add_argument("--section")
    table_counts.add_argument("--json", action="store_true")
    table_list = table_subs.add_parser("list", help="bounded work-item table rows")
    table_list.add_argument("--open-only", action="store_true")
    table_list.add_argument("--section")
    table_list.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    table_list.add_argument("--json", action="store_true")
    table_show = table_subs.add_parser("show", help="named work-item table rows")
    table_show.add_argument("ident", nargs="+")
    table_show.add_argument("--section")
    table_show.add_argument("--json", action="store_true")
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
    if ns.command == "tables":
        return cmd_tables(ns.file, ns)
    return _COMMANDS[ns.command](parse(ns.file), ns)


def main(argv: list[str] | None = None) -> int:
    """Run one query. ``| head`` closing the pipe early is a normal end, not a crash."""
    try:
        result = _run(argv)
        sys.stdout.flush()
        return result
    except BrokenPipeError:
        # Silence Python's "Exception ignored" epilogue by pointing stdout at
        # devnull before interpreter shutdown flushes it.
        with open(os.devnull, "w", encoding="utf-8") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    # The documents are Unicode; redirected Windows streams otherwise use a
    # legacy code page and can crash on a normal row. The CLI emits UTF-8.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    raise SystemExit(main())
