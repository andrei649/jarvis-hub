#!/usr/bin/env python3
"""Query the Hermes absorption ledger without loading 1.4 MB of JSON.

``docs/research/2026-09-07-hermes-absorption-ledger.json`` is the machine-readable
half of ``docs/HERMES_ABSORPTION.md``: 697 capabilities inventoried from Hermes
v2026.8.31, each with a decision (``copy`` / ``update`` / ``keep`` / ``skip``), a
rationale, a governance note and an effort estimate. At ~1.4 MB it is roughly
355K tokens — over a third of a 1M window for a file nobody needs whole. One
``cat`` of it costs more than every other document in this repo combined.

So: ask it questions instead.

    scripts/ledger.py stats                        # the totals, as recorded
    scripts/ledger.py clusters                     # work rows per cluster
    scripts/ledger.py list --cluster cli           # rows, one line each
    scripts/ledger.py list --decision copy --effort S
    scripts/ledger.py show "nerva doctor"          # one row in full

"Work" throughout means ``copy`` + ``update`` — the rows that imply a change.
``keep`` and ``skip`` are recorded decisions, not a queue.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "docs" / "research" / "2026-09-07-hermes-absorption-ledger.json"

#: Decisions that mean "there is work here".
WORK = ("copy", "update")
#: One-line summaries are cut here.
SUMMARY_CHARS = 90
DEFAULT_LIMIT = 60


def load(path: Path = LEDGER) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(data: dict[str, Any], ns: argparse.Namespace) -> list[dict[str, Any]]:
    rows = list(data.get("capabilities", []))
    if getattr(ns, "decision", None):
        rows = [r for r in rows if r.get("decision") == ns.decision]
    elif getattr(ns, "work_only", False):
        rows = [r for r in rows if r.get("decision") in WORK]
    if getattr(ns, "cluster", None):
        needle = ns.cluster.lower()
        rows = [r for r in rows if needle in str(r.get("cluster", "")).lower()]
    if getattr(ns, "effort", None):
        rows = [r for r in rows if str(r.get("effort", "")).upper() == ns.effort.upper()]
    return rows


def cmd_stats(data: dict[str, Any], _ns: argparse.Namespace) -> int:
    caps = data.get("capabilities", [])
    decisions = Counter(r.get("decision") for r in caps)
    work = [r for r in caps if r.get("decision") in WORK]
    print(f"generated: {data.get('generated')}   upstream: {data.get('upstream')}")
    print(f"capabilities: {len(caps)}   clusters: {len(data.get('clusters', []))}")
    print("\ndecisions:")
    for name, count in decisions.most_common():
        mark = "  <- work" if name in WORK else ""
        print(f"  {count:4d}  {name}{mark}")
    print(f"\nwork rows (copy + update): {len(work)}")
    print(f"effort of work rows: {dict(Counter(r.get('effort') for r in work).most_common())}")
    return 0


def cmd_clusters(data: dict[str, Any], _ns: argparse.Namespace) -> int:
    caps = data.get("capabilities", [])
    work = Counter(r.get("cluster") for r in caps if r.get("decision") in WORK)
    total = Counter(r.get("cluster") for r in caps)
    print(f"{'work':>5} {'all':>5}  cluster")
    for cluster, count in work.most_common():
        print(f"{count:5d} {total[cluster]:5d}  {str(cluster)[:70]}")
    return 0


def cmd_list(data: dict[str, Any], ns: argparse.Namespace) -> int:
    rows = _rows(data, ns)
    for row in rows[: ns.limit]:
        name = str(row.get("name", "?"))[:56]
        print(f"{row.get('decision','?'):<7} {str(row.get('effort','?')):<3} {name}")
    if len(rows) > ns.limit:
        print(f"\n… {len(rows) - ns.limit} more of {len(rows)} (raise --limit)")
    else:
        print(f"\n{len(rows)} rows")
    return 0


def cmd_show(data: dict[str, Any], ns: argparse.Namespace) -> int:
    needle = ns.name.lower()
    hits = [r for r in data.get("capabilities", []) if needle in str(r.get("name", "")).lower()]
    if not hits:
        print(f"no capability matching: {ns.name}", file=sys.stderr)
        return 1
    for index, row in enumerate(hits[: ns.limit]):
        if index:
            print("\n" + "-" * 60 + "\n")
        for key in ("name", "cluster", "decision", "effort", "hermes", "nerva_state",
                    "nerva_evidence", "rationale", "governance", "depends_on"):
            value = row.get(key)
            if value not in (None, "", [], {}):
                print(f"{key}: {value}")
    if len(hits) > ns.limit:
        print(f"\n… {len(hits) - ns.limit} more matches (narrow the name or raise --limit)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger.py", description="Query the Hermes absorption ledger without loading it whole."
    )
    parser.add_argument("--file", type=Path, default=LEDGER, help=argparse.SUPPRESS)
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("stats", help="totals, decisions and the work-row effort mix")
    subs.add_parser("clusters", help="work rows per cluster")

    listing = subs.add_parser("list", help="rows, one line each")
    listing.add_argument("--cluster")
    listing.add_argument("--decision", choices=["copy", "update", "keep", "skip"])
    listing.add_argument("--effort", choices=["S", "M", "L", "XL", "s", "m", "l", "xl"])
    listing.add_argument("--all", dest="work_only", action="store_false",
                         help="include keep/skip rows (default: work rows only)")
    listing.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    listing.set_defaults(work_only=True)

    show = subs.add_parser("show", help="one capability in full, matched by name substring")
    show.add_argument("name")
    show.add_argument("--limit", type=int, default=3)
    return parser


_COMMANDS = {"stats": cmd_stats, "clusters": cmd_clusters, "list": cmd_list, "show": cmd_show}


def _run(argv: list[str] | None) -> int:
    ns = build_parser().parse_args(argv)
    if not ns.file.is_file():
        print(f"no such file: {ns.file}", file=sys.stderr)
        return 2
    return _COMMANDS[ns.command](load(ns.file), ns)


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
    # Match the UTF-8 ledger even when Windows redirects output through a
    # legacy code page. Imported query helpers leave their caller's I/O alone.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    raise SystemExit(main())
