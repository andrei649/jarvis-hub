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
        expected_seam: set[str] | frozenset[str] | None = None,
    ) -> dict:
        results = list(run.get("results") or [])
        seam_ids = set(expected_seam or ())
        # A SEAM capability (registered, but with no runtime behind it) is *expected*
        # to fail its probe — the pytest lane pins exactly that contract
        # (tests/test_reality_harness.py). Count those separately so the exit
        # verdict can distinguish "the seam is still a seam" from a real regression.
        expected_failures = sorted(
            str(result.get("capability_id"))
            for result in results
            if not result.get("passed")
            and not result.get("skipped")
            and result.get("capability_id") in seam_ids
        )
        paired = list(zip(results, cases, strict=True)) if cases is not None else [
            (result, None) for result in results
        ]
        # Owner-hardware cases (case metadata mode "owner-live") can only pass on
        # the owner's box: anywhere else their probe reports the opt-in / config /
        # credential as missing. Off-box that is "not exercised", not a
        # regression — the pytest lane skips them for the same reason.
        owner_live_not_exercised = sorted(
            str(result.get("capability_id"))
            for result, case in paired
            if not result.get("passed")
            and not result.get("skipped")
            and case is not None
            and dict(getattr(case, "metadata", None) or {}).get("mode") == "owner-live"
            and str(dict(result.get("metadata") or {}).get("reason") or "").startswith("owner_live_")
        )
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
                "expected_seam_failures": len(expected_failures),
                "owner_live_not_exercised": len(owner_live_not_exercised),
            },
            "expected_seam_failures": expected_failures,
            "owner_live_not_exercised": owner_live_not_exercised,
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
            existing = [ln for ln in self._path.read_text(encoding="utf-8").splitlines() if ln]
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
        for line in self._path.read_text(encoding="utf-8").splitlines():
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
    from agents.core.config import JarvisConfig
    from agents.core.observability.reality_harness import (
        all_reality_cases,
        reality_enabled,
        run_reality,
    )
    from agents.core.orchestrator import Orchestrator

    started = _now_iso()
    orch = Orchestrator(JarvisConfig())
    # Discovery lives on the orchestrator's SkillLoader (the package exposes no
    # module-level ``discover``) — the same call the readiness fixture makes
    # and that ``Orchestrator.initialize`` would make on a real boot.
    orch.skills.discover()
    cases = all_reality_cases(orch)
    run = await run_reality(cases)
    from agents.core.observability import capability_registry as cr

    seam_ids = {record.id for record in cr.build_records(orch) if record.state == cr.SEAM}
    ledger = RealityEvidenceLedger(Path(args.store_root) if args.store_root else None)
    return ledger.record_run(
        run,
        cases,
        revision=args.revision,
        runner_id=args.runner_id,
        lane=args.lane,
        started_at=started,
        live_enabled=reality_enabled(),
        expected_seam=seam_ids,
    )


def explain_verdict(record: dict) -> dict:
    """Name the cases a red verdict did not excuse.

    The verdict is arithmetic (`passed + expected_seam + owner_live >= total`),
    so a red run could report its counts and exit 1 without saying *which* case
    broke it.

    Both excusals are counted per CASE, but the record stores them as
    capability-id lists and an id is shared by a capability's offline and
    owner-live rows. The owner-live excusal therefore only applies to a row that
    is itself `live`: an offline sibling failing under the same id would be a
    regression wearing its twin's excuse. `expected_seam_failures` has no such
    ambiguity - a SEAM capability has no runtime behind it either way.

    Returns `{"unexcused": [...], "lines": [...]}`: the rows the verdict did not
    excuse, and a printable listing of *every* failing row with its tag, so a
    mis-tagged excusal is visible rather than silently swallowed.
    """
    seam = set(record.get("expected_seam_failures") or ())
    owner_live = set(record.get("owner_live_not_exercised") or ())
    unexcused: list[dict] = []
    lines: list[str] = []
    for row in record.get("cases") or ():
        if row.get("passed") or row.get("skipped"):
            continue
        cid = row.get("capability_id")
        if cid in seam:
            tag = "expected-seam"
        elif cid in owner_live and row.get("live") is True:
            tag = "owner-live-not-exercised"
        else:
            tag = "UNEXCUSED"
            unexcused.append(row)
        lines.append(f"    [{tag}] {cid} -> {row.get('name')}")
    return {"unexcused": unexcused, "lines": lines}


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
    expected = int(totals.get("expected_seam_failures") or 0)
    off_box = int(totals.get("owner_live_not_exercised") or 0)
    print(
        f"reality evidence: {totals['passed']}/{totals['total']} passed, "
        f"{totals['skipped']} skipped, {expected} expected seam failures, "
        f"{off_box} owner-live cases not exercised on this host, "
        f"{totals['cases']} cases -> recorded"
    )
    # The run is recorded either way; a red run is evidence too. Exit red so
    # CI surfaces it, matching the pytest lane's contract: every failing case
    # must be a SEAM capability the harness test already expects to fail, or
    # an owner-hardware case that reported itself un-exercisable off the owner
    # box; anything else is a regression.
    passed = int(totals.get("passed") or 0)
    total = int(totals.get("total") or 0)
    if passed + expected + off_box >= total:
        return 0
    verdict = explain_verdict(record)
    # Report the LISTING's own count, not the arithmetic shortfall: the two are
    # computed by different rules (the shortfall from the excused-row tallies,
    # the listing per row with the `live` check above), so a header taken from
    # one and a body from the other could disagree. They agree on every record
    # record_run produces today; if that ever stops being true, say so rather
    # than printing a number the listing below contradicts.
    shortfall = total - passed - expected - off_box
    print(f"  {len(verdict['unexcused'])} failing case(s) the verdict did not excuse. "
          f"Every failing case, tagged:")
    if len(verdict["unexcused"]) != shortfall:
        print(f"  NOTE: the exit verdict's arithmetic makes that {shortfall}; the two "
              f"disagree, which should not be possible - trust the listing.")
    for line in verdict["lines"]:
        print(line)
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
