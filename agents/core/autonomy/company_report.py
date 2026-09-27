"""company_report.py — what the night shift actually did, told honestly.

A run that worked all night is worth very little if the morning summary is
generous about it. This builder exists to make the *unflattering* facts the
hardest ones to leave out:

* **The headline is the verdict, not the effort.** A run with forty steps and no
  judge verdict is reported as unfinished, never as "40 steps completed".
* **Unauthorised steps lead.** If any step changed something without naming the
  durable approved task behind it, that is the first line of the run's summary,
  above whatever it achieved.
* **A blocked run says what it is waiting for.** "Waiting on your approval" is
  actionable; "in progress" is not. A *parked* run (H464) says what it is waiting
  on too — a task, a process, a webhook, a time — and the latest it can hold. Only
  while the barrier is in force, though: past its cap (or, for a clock, past its
  time) the run reads as it would without one, even when no sweep has run to
  clear the stale record. That is a plain clock comparison, never a probe.
* **Nothing is inferred.** Every number comes from the ledger. When the ledger
  has nothing — no runs at all — the brief says so rather than rendering a row
  of zeros under a confident heading.
* **No payloads, ever.** Step summaries are already bounded by the ledger; this
  builder emits them and the task ids, never task payloads or results. The day
  report (``day_report.py``) draws the same line for the same reason.

Pure and network-free, like ``digest.build_morning_brief``: the caller reads the
ledger and passes it in, so this stays testable without a database. The caller
passes its clock (``now``) too — the ledger's, so a barrier is read against the
same time it was stamped with; without one the wall clock is used.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

from agents.core.autonomy.run_barriers import describe, until

SCHEMA = "nerva.company.brief.v1"

# How each terminal (and non-terminal) status reads to a person. The wording is
# deliberately plain: "exhausted" is a machine word, "ran out of budget" is not.
_STATUS_TEXT: Mapping[str, str] = {
    "planning": "opened, no work started yet",
    "working": "in progress",
    "blocked": "waiting on your approval",
    "stopping": "stopping",
    "succeeded": "met its goal",
    "failed": "did not meet its goal",
    "exhausted": "ran out of budget",
    "stopped": "you stopped it",
}

_BUDGET_TEXT: Mapping[str, str] = {
    "steps": "it used every step it was allowed",
    "seconds": "it ran out of time",
    "deadline": "it passed its deadline",
    "interrupts": "it had no interruptions left",
}

_MAX_LINE = 300


def _clip(value: Any, limit: int = _MAX_LINE) -> str:
    return str(value or "").strip()[:limit]


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _in_force(barrier: Mapping[str, Any], now: float) -> bool:
    """Whether a stored barrier still holds at ``now`` by the clock alone: before
    its cap, and — for a clock wait — before its own time. Never probes; a record
    without a readable cap is not reported as holding."""
    cap = _finite(barrier.get("cap_at"))
    if cap is None or now >= cap:
        return False
    if barrier.get("kind") == "deadline":
        end = _finite(barrier.get("target"))
        return end is not None and now < end
    return True


def _waiting_on(run: Mapping[str, Any], now: float) -> str | None:
    """What a live run is parked on, read from the record — never probed. A barrier
    on a run that is not planning or working is not reported: the ledger clears it
    on every stop and settle, and the report does not rely on that alone. Nor is
    one whose time is up: with company mode off, or between sweeps, nothing has
    cleared the record yet, but it no longer holds (H464 review F2/F7)."""
    barrier = run.get("barrier")
    if not barrier or run.get("status") not in {"planning", "working"}:
        return None
    if not _in_force(barrier, now):
        return None
    return describe(barrier)


def _run_headline(snapshot: Mapping[str, Any], now: float) -> str:
    """One sentence: what happened to this run, worst news first."""
    run = dict(snapshot.get("run") or {})
    status = str(run.get("status") or "")
    unauthorised = list(snapshot.get("unauthorised_steps") or ())
    if snapshot.get("tampered"):
        return "its record does not match its own fingerprint — treat every claim below as unverified"
    if unauthorised:
        count = len(unauthorised)
        return (
            f"{count} step{'s' if count != 1 else ''} changed something without an "
            "approved task behind it"
        )
    waiting_on = _waiting_on(run, now)
    if waiting_on:
        # A clock's own time is its limit: "(at most until …)" would repeat it or,
        # when capped earlier, contradict it.
        cap = until(run.get("barrier")) if run["barrier"].get("kind") != "deadline" else ""
        return f"parked — waiting on {waiting_on}" + (f" (at most until {cap})" if cap else "")
    text = _STATUS_TEXT.get(status, status or "in an unknown state")
    if status == "exhausted":
        limit = str(run.get("stop_reason") or "").removeprefix("budget:")
        detail = _BUDGET_TEXT.get(limit)
        return f"{text} — {detail}" if detail else text
    if status == "stopped" and run.get("stop_reason"):
        return f"{text} ({_clip(run['stop_reason'], 120)})"
    return text


def _verdict_lines(snapshot: Mapping[str, Any]) -> list[str]:
    """The graders' words, or the absence of them stated plainly."""
    verdicts = {v["role"]: v for v in snapshot.get("verdicts") or ()}
    lines: list[str] = []
    judge = verdicts.get("judge")
    verifier = verdicts.get("verifier")
    if judge is None and verifier is None:
        lines.append("· nobody has graded it yet")
        return lines
    if verifier is not None:
        mark = "held" if verifier.get("passed") else "did not hold"
        lines.append(f"· the evidence {mark}: {_clip(verifier.get('reason'), 200)}")
    else:
        lines.append("· the evidence was never verified")
    if judge is not None:
        mark = "accepted" if judge.get("passed") else "rejected"
        lines.append(f"· the goal was {mark}: {_clip(judge.get('reason'), 200)}")
    return lines


def build_run_summary(
    snapshot: Mapping[str, Any], *, now: float | None = None
) -> dict[str, Any]:
    """One run, projected to what a person needs — never task payloads.

    ``now`` is the caller's clock (the ledger's); the wall clock when omitted."""
    now = time.time() if now is None else float(now)
    run = dict(snapshot.get("run") or {})
    budget = dict(snapshot.get("budget") or {})
    steps = list(snapshot.get("steps") or ())
    outcomes: dict[str, int] = {}
    for step in steps:
        key = str(step.get("outcome") or "")
        outcomes[key] = outcomes.get(key, 0) + 1
    return {
        "run_id": run.get("id"),
        "title": _clip(run.get("title")),
        "status": run.get("status"),
        "headline": _run_headline(snapshot, now),
        "waiting_on": _waiting_on(run, now),
        "steps": len(steps),
        "outcomes": outcomes,
        "steps_left": budget.get("steps_left"),
        "interrupts_used": run.get("interrupts_used"),
        "unauthorised_steps": list(snapshot.get("unauthorised_steps") or ()),
        "verdict_lines": _verdict_lines(snapshot),
        # The most recent few, oldest last — enough to see what it is doing without
        # turning a brief into a log.
        "recent": [
            {"summary": _clip(s.get("summary"), 160), "outcome": s.get("outcome"),
             "task_id": s.get("task_id")}
            for s in steps[-3:]
        ],
    }


def build_company_brief(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    company_mode_enabled: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """The whole night, as a structured brief.

    ``snapshots`` is what ``WorkRunLedger.snapshot`` returned for each run the
    caller cares about. An empty sequence is reported as "nothing ran", which is
    a different statement from "everything succeeded" and must never render the
    same way. ``now`` is the caller's clock (the ledger's, so a barrier is read
    against the time it was stamped with); the wall clock when omitted.
    """
    now = time.time() if now is None else float(now)
    runs = [build_run_summary(s, now=now) for s in snapshots]
    by_status: dict[str, int] = {}
    for run in runs:
        key = str(run["status"] or "")
        by_status[key] = by_status.get(key, 0) + 1
    needs_you = [r for r in runs if r["status"] == "blocked"]
    unauthorised = [r for r in runs if r["unauthorised_steps"]]
    return {
        "schema": SCHEMA,
        "enabled": bool(company_mode_enabled),
        "empty": not runs,
        "reason": (
            "" if runs
            else ("no work runs have been opened"
                  if company_mode_enabled
                  else "company mode is off, so no run was opened")
        ),
        "counts": {"runs": len(runs), "by_status": by_status},
        "needs_you": [r["run_id"] for r in needs_you],
        # Parked on real async work (H464): not stuck, not needing you — waiting.
        "parked": [r["run_id"] for r in runs if r.get("waiting_on")],
        "unauthorised": [r["run_id"] for r in unauthorised],
        "runs": runs,
    }


def render_company_brief(brief: Mapping[str, Any]) -> str:
    """The brief as plain text for a channel message. No markdown tables."""
    if brief.get("empty"):
        return f"🏢 *Company mode*\n\n{brief.get('reason') or 'nothing to report'}."

    lines = ["🏢 *Company mode — what ran*", ""]
    unauthorised = list(brief.get("unauthorised") or ())
    if unauthorised:
        # Above everything else, including successes: this is the one finding that
        # changes what the owner should do next.
        lines += [
            f"⚠️ {len(unauthorised)} run(s) changed something with no approved task "
            "behind it — check these first:",
            "  " + ", ".join(str(rid) for rid in unauthorised),
            "",
        ]
    needs_you = list(brief.get("needs_you") or ())
    if needs_you:
        lines += [f"⏳ {len(needs_you)} run(s) are waiting on your approval.", ""]
    parked = [r for r in brief.get("runs") or () if r.get("waiting_on")]
    if parked:
        lines += [f"⏸ {r['title']} is parked, waiting on {r['waiting_on']}." for r in parked]
        lines.append("")

    for run in brief.get("runs") or ():
        lines.append(f"*{run['title']}* — {run['headline']}")
        lines.extend(f"  {line}" for line in run["verdict_lines"])
        if run["recent"]:
            lines.append(f"  · last: {run['recent'][-1]['summary']}")
        lines.append(f"  · {run['steps']} step(s), {run['steps_left']} left")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["SCHEMA", "build_company_brief", "build_run_summary", "render_company_brief"]
