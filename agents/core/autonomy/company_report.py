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
  actionable; "in progress" is not.
* **Nothing is inferred.** Every number comes from the ledger. When the ledger
  has nothing — no runs at all — the brief says so rather than rendering a row
  of zeros under a confident heading.
* **No payloads, ever.** Step summaries are already bounded by the ledger; this
  builder emits them and the task ids, never task payloads or results. The day
  report (``day_report.py``) draws the same line for the same reason.

Pure and network-free, like ``digest.build_morning_brief``: the caller reads the
ledger and passes it in, so this stays testable without a database.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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


def _run_headline(snapshot: Mapping[str, Any]) -> str:
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


def build_run_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """One run, projected to what a person needs — never task payloads."""
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
        "headline": _run_headline(snapshot),
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
) -> dict[str, Any]:
    """The whole night, as a structured brief.

    ``snapshots`` is what ``WorkRunLedger.snapshot`` returned for each run the
    caller cares about. An empty sequence is reported as "nothing ran", which is
    a different statement from "everything succeeded" and must never render the
    same way.
    """
    runs = [build_run_summary(s) for s in snapshots]
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

    for run in brief.get("runs") or ():
        lines.append(f"*{run['title']}* — {run['headline']}")
        lines.extend(f"  {line}" for line in run["verdict_lines"])
        if run["recent"]:
            lines.append(f"  · last: {run['recent'][-1]['summary']}")
        lines.append(f"  · {run['steps']} step(s), {run['steps_left']} left")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["SCHEMA", "build_company_brief", "build_run_summary", "render_company_brief"]
