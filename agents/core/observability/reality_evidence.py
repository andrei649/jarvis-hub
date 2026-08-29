"""Durable evidence ledger for reality-harness runs (GAP-9).

The harness's verdicts previously lived only in an in-process registry — the
scheduled reality lane produced no artifact, so VERIFIED evidence evaporated
with the runner. This module records each run as one append-only JSONL line
(`nerva.reality.run.v1`) under ``data_path("reality")``, mirroring the
benchmark store / eval-nightly shape: evidence retention is deliberately
separate from promotion.

The V3 constraint stays intact by construction: nothing in the codebase reads
this ledger back — ``record_verification`` gains no caller, in-process green
runs remain the only VERIFIED path, and registry state still resets on boot.
``promotion_scope: in_process_only`` is stamped into every record so the
artifact itself says what it is: a transcript, never an authority.

CLI (the scheduled lane's evidence step)::

    python -m agents.core.observability.reality_evidence \
        --json-out reality-run.json --lane scheduled
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from agents.core.paths import data_path

from .runtime_log import _bounded_dict

SCHEMA = "nerva.reality.run.v1"
_RING_LIMIT = 30
_LEDGER_NAME = "runs.jsonl"
# The operator pack's raw event ledger is unbounded by design; evidence keeps
# its counters, not the transcript.
_DROPPED_METADATA_KEYS = {"events"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _bounded_case(result: dict, case=None) -> dict:
    metadata = {
        key: value
        for key, value in dict(result.get("metadata") or {}).items()
        if key not in _DROPPED_METADATA_KEYS
    }
    row = {
        "capability_id": result.get("capability_id"),
        "name": result.get("name"),
        "skipped": bool(result.get("skipped")),
        "passed": bool(result.get("passed")),
        "detail": str(result.get("detail") or "")[:500],
        "metadata": _bounded_dict(metadata),
    }
    if case is not None:
        row["ref"] = case.ref
        row["contract"] = str(case.contract)[:300]
        row["live"] = bool(case.live)
        row["promotable"] = case.metadata.get("promotable", True) is not False
    return row


class RealityEvidenceLedger:
    """Append-only JSONL run ledger with a bounded local ring."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else Path(data_path("reality"))
        self._path = self._root / _LEDGER_NAME
        if self._path.resolve().parent != self._root.resolve():
            raise ValueError("ledger path escapes its store root")

    @property
    def path(self) -> Path:
        return self._path

    def record_run(
        self,
        run: dict,
        cases=None,
        *,
        revision: str = "",
        runner_id: str = "",
        lane: str = "local",
        started_at: str = "",
        live_enabled: bool | None = None,
    ) -> dict:
        results = list(run.get("results") or [])
        paired = list(zip(results, cases, strict=True)) if cases is not None else [
            (result, None) for result in results
        ]
        record = {
            "schema": SCHEMA,
            "harness_id": run.get("harness_id"),
            "started_at": started_at or _now_iso(),
            "finished_at": _now_iso(),
            "revision": str(revision)[:64],
            "runner_id": str(runner_id)[:128],
            "lane": lane if lane in {"scheduled", "dispatch", "local"} else "local",
            "live_enabled": live_enabled,
            "totals": {
                "passed": run.get("passed"),
                "total": run.get("total"),
                "skipped": run.get("skipped"),
                "cases": len(results),
            },
            # The honesty fields: this artifact is a transcript, not authority.
            "promotion_scope": "in_process_only",
            "durable_promotion": False,
            "promoted_in_process": list(run.get("promoted") or []),
            "cases": [_bounded_case(result, case) for result, case in paired],
        }
        self._append(record)
        return record

    def _append(self, record: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        existing: list[str] = []
        if self._path.exists():
            existing = [ln for ln in self._path.read_text("utf-8").splitlines() if ln]
        existing.append(line.rstrip("\n"))
        if len(existing) > _RING_LIMIT:
            existing = existing[-_RING_LIMIT:]
        tmp = self._path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(existing) + "\n", encoding="utf-8")
        tmp.replace(self._path)

    def runs(self) -> list[dict]:
        if not self._path.exists():
            return []
        rows = []
        for line in self._path.read_text("utf-8").splitlines():
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # a torn line never poisons the readable history
        return rows


async def _run_and_record(args) -> dict:
    # Boot the same fixture the readiness tests use: a real orchestrator with
    # discovered skills, so the derived plugin/component/skill cases exist.
    from agents.core import skills as skill_registry
    from agents.core.config import JarvisConfig
    from agents.core.observability.reality_harness import (
        all_reality_cases,
        reality_enabled,
        run_reality,
    )
    from agents.core.orchestrator import Orchestrator

    started = _now_iso()
    orch = Orchestrator(JarvisConfig())
    skill_registry.discover()
    cases = all_reality_cases(orch)
    run = await run_reality(cases)
    ledger = RealityEvidenceLedger(Path(args.store_root) if args.store_root else None)
    return ledger.record_run(
        run,
        cases,
        revision=args.revision,
        runner_id=args.runner_id,
        lane=args.lane,
        started_at=started,
        live_enabled=reality_enabled(),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", default="", help="ledger directory (default: data root)")
    parser.add_argument("--json-out", default="", help="also write this run's record here")
    parser.add_argument("--revision", default="", help="source revision (e.g. $GITHUB_SHA)")
    parser.add_argument("--runner-id", default="", help="runner identity for provenance")
    parser.add_argument("--lane", default="local", choices=["scheduled", "dispatch", "local"])
    args = parser.parse_args(argv)
    record = asyncio.run(_run_and_record(args))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    totals = record["totals"]
    print(
        f"reality evidence: {totals['passed']}/{totals['total']} passed, "
        f"{totals['skipped']} skipped, {totals['cases']} cases -> recorded"
    )
    # The run is recorded either way; a red run is evidence too. Exit red so
    # CI surfaces it, matching the pytest lane's behavior.
    return 0 if totals["passed"] == totals["total"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
