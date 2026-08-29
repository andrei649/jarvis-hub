#!/usr/bin/env python3
"""Render a boundary verdict into GitHub Actions outputs and the run summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("verdict", type=Path)
    p.add_argument("--github-output", type=Path)
    p.add_argument("--step-summary", type=Path)
    args = p.parse_args(argv)

    v = json.loads(args.verdict.read_text(encoding="utf-8"))
    tier, direction = v["tier"], v["direction"]
    ok = v["auto_merge_eligible"]

    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as fh:
            fh.write(f"tier={tier}\n")
            fh.write(f"direction={direction}\n")
            fh.write(f"auto_merge={str(ok).lower()}\n")

    verdict_line = (
        "auto-merge eligible" if ok else "**held — requires @andrei649 approval**"
    )
    lines = [
        "### Boundary classification",
        "",
        f"**tier {tier} / {direction}** — {verdict_line}",
        "",
    ]
    lines += [f"- {reason}" for reason in v["reasons"]]
    if v["boundary_files"]:
        lines += ["", "<details><summary>Boundary files touched</summary>", ""]
        lines += [f"- `{path}`" for path in v["boundary_files"]]
        lines += ["", "</details>"]
    body = "\n".join(lines) + "\n"

    if args.step_summary:
        with args.step_summary.open("a", encoding="utf-8") as fh:
            fh.write(body)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
