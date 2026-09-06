"""``python scripts/operator_bench.py`` — run the S1 operator benchmark.

NERVA_VISION S1 asks whether Nerva can actually do a spread of real computer tasks
and prove it. This runs the twenty-task pack and writes the result where the HUD
and the release gate read it.

It prints two numbers, never one:

    19/19 hermetic; nothing confirmed on a real host yet

The hermetic rate says the governed *route* works end to end against in-process
twins. It says nothing about a real desktop, and a single blended number would let
one claim borrow the other's credibility. The live column stays ``not_run`` until
someone runs each task's live twin on their own machine — ``--pack`` prints those
twins, one per task, as the instructions they are.

The pack also carries a negative control: one task that produces a correct result
via an ungoverned action, and is therefore expected to FAIL. Its failure is what
proves the governance rule is load-bearing rather than decorative, so it is scored
separately and a green run reports it as expected.

Usage::

    python scripts/operator_bench.py            # run and persist
    python scripts/operator_bench.py --pack     # print the questions and live twins
    python scripts/operator_bench.py --check    # exit 1 unless the stored run is clean

Exit status: 0 when the run is governance-clean and every scored task passed;
1 otherwise. Governance outranks the rate — a single ungoverned action fails the
whole pack regardless of how many tasks passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))

from agents.core.observability.operator_benchmark import (  # noqa: E402
    load_report,
    run_pack,
    save_report,
)
from agents.core.observability.operator_pack import (  # noqa: E402
    NEGATIVE_CONTROLS,
    TASKS,
    scored_tasks,
)


def print_pack() -> int:
    """The questions and their live twins — what a person runs on a real box."""
    for task in TASKS:
        marker = " (negative control — expected to fail)" if task.id in NEGATIVE_CONTROLS else ""
        print(f"\n{task.id}  [{task.surface}]{marker}")
        print(f"  {task.describe}")
        print(f"  live: {task.live_twin}")
    print(f"\n{len(scored_tasks())} scored task(s), {len(NEGATIVE_CONTROLS)} negative control(s).")
    return 0


def _print(report: dict) -> None:
    print(report["headline"])
    herm = report["hermetic"]
    print(
        f"  hermetic: {herm['passed']} passed, {herm['failed']} failed, "
        f"{herm['skipped']} skipped"
    )
    print(f"  governance clean: {report['governance_clean']}")
    for surface, counts in sorted(report["by_surface"].items()):
        print(
            f"    {surface:<9} {counts['passed']} passed, {counts['failed']} failed, "
            f"{counts['skipped']} skipped"
        )
    failures = [r for r in report["results"] if r["outcome"] == "failed"]
    if failures:
        print("  failed:")
        for row in failures:
            print(f"    {row['task_id']}: {row['detail']}")


async def _run(*, persist: bool) -> int:
    report = await run_pack(scored_tasks())
    _print(report)

    # The negative control runs separately: folding an expected failure into the
    # scored pack would make a healthy run look 19/20 forever.
    control = await run_pack([t for t in TASKS if t.id in NEGATIVE_CONTROLS])
    control_ok = control["governance_clean"] is False
    print(
        f"  negative control: {'as expected — an ungoverned action failed the task' if control_ok else 'DID NOT FAIL — the governance rule is not load-bearing'}"
    )

    if persist:
        path = save_report(report)
        print(f"  written: {path}")
    clean = report["governance_clean"] and report["hermetic"]["failed"] == 0
    return 0 if (clean and control_ok) else 1


def check() -> int:
    """Exit 1 unless a stored run exists, is current, and is clean."""
    report = load_report(tasks=scored_tasks())
    if report is None:
        print("no stored operator benchmark — run: python scripts/operator_bench.py")
        return 1
    if report.get("stale"):
        print(
            "the stored benchmark was measured against a different pack — "
            "re-run: python scripts/operator_bench.py"
        )
        return 1
    _print(report)
    return 0 if report.get("governance_clean") and report["hermetic"]["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the S1 operator benchmark pack.")
    parser.add_argument("--pack", action="store_true", help="print the questions and live twins")
    parser.add_argument("--check", action="store_true", help="verify the stored run")
    parser.add_argument("--no-persist", action="store_true", help="run without writing the result")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    if args.pack:
        return print_pack()
    if args.check:
        return check()
    if args.json:
        report = asyncio.run(run_pack(scored_tasks()))
        print(json.dumps(report, indent=2))
        return 0 if report["governance_clean"] and report["hermetic"]["failed"] == 0 else 1
    return asyncio.run(_run(persist=not args.no_persist))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
