"""operator_benchmark.py — the 20-task pack that measures the computer operator.

NERVA_VISION S1 asks for execution breadth: can Nerva actually do a spread of real
computer tasks, and can it prove it? A pass rate is easy to produce and easy to
inflate, so the whole design of this module is about the ways a benchmark lies:

* **A hermetic pass is never reported as a live pass.** Every task has a *live
  twin* — the same task on a real host — and its result starts as ``not_run`` and
  stays there until someone runs it there. The report carries both columns and a
  headline that names the hermetic rate as hermetic. A single "pass rate" number
  would be the lie; there are two numbers because there are two claims.
* **Governance is scored, not assumed.** A task that got the right answer by
  taking an ungoverned action FAILS, however correct its output. ``ungoverned``
  is counted per task and any non-zero count fails the whole pack, because a
  benchmark that rewards the result and ignores the route trains exactly the wrong
  behaviour.
* **A skipped task is not a passed task.** Tasks the host cannot support are
  ``skipped`` with the host probe's reason, and skips are reported separately —
  never folded into the denominator to flatter the rate.
* **The rate is persisted, and what it was measured against travels with it.**
  A stored result carries the pack fingerprint; a rate quoted against a different
  pack is not comparable and the loader says so rather than pretending.

The pack is declarative so it can be reviewed as data. Each task names what it
does, the capability it exercises, and how a run is judged — no task judges itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.operator_benchmark")

SCHEMA = "nerva.operator-benchmark.v1"
_DEFAULT_FILE = "operator_benchmark.json"

# Outcomes. `skipped` is deliberately distinct from both: the host could not
# support the task, which is a fact about the host, not a score either way.
OUTCOMES = ("passed", "failed", "skipped")

# What a task exercises. Used to report breadth — 19 passes all in one surface is
# a different result from 19 spread across the operator's real range.
SURFACES = ("desktop", "browser", "terminal", "files", "vision")


class BenchmarkError(RuntimeError):
    """A bounded benchmark failure. ``reason`` is a public code."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "benchmark_error")
        super().__init__(self.reason)


@dataclass(frozen=True)
class Task:
    """One benchmark task, declared as data.

    ``run`` drives the hermetic twin and returns a result mapping; ``judge`` says
    whether that result counts as a pass. They are separate on purpose — a task
    that judged itself could not be reviewed, and "did the right thing" is a
    different question from "did something".
    """

    id: str
    surface: str
    describe: str
    run: Callable[[], Any] | None = None
    judge: Callable[[Any], bool] | None = None
    live_twin: str = ""
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.id or "").strip():
            raise BenchmarkError("task_id_required")
        if self.surface not in SURFACES:
            raise BenchmarkError(f"unknown_surface:{self.surface}")
        if not str(self.describe or "").strip():
            raise BenchmarkError("task_describe_required")
        if not str(self.live_twin or "").strip():
            # A task with no live twin can only ever be a hermetic claim, and the
            # pack exists to make the live gap visible. Naming the twin is how the
            # gap stays countable.
            raise BenchmarkError(f"live_twin_required:{self.id}")

    def identity(self) -> dict[str, Any]:
        return {
            "id": self.id, "surface": self.surface, "describe": self.describe,
            "live_twin": self.live_twin, "requires": list(self.requires),
        }


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    surface: str
    outcome: str
    detail: str = ""
    ungoverned: int = 0
    live: str = "not_run"
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "surface": self.surface, "outcome": self.outcome,
            "detail": self.detail, "ungoverned": self.ungoverned,
            "live": self.live, "duration_ms": self.duration_ms,
        }


@dataclass
class GovernanceLedger:
    """Counts actions and how many bypassed governance.

    A task hands this to its twin; the twin records every actuation and whether a
    kernel decision preceded it. Any ungoverned action fails the task outright.
    """

    attempted: int = 0
    governed: int = 0
    ungoverned_ids: list[str] = field(default_factory=list)

    def act(self, action_id: str, *, governed: bool) -> None:
        self.attempted += 1
        if governed:
            self.governed += 1
        else:
            self.ungoverned_ids.append(str(action_id))

    @property
    def ungoverned(self) -> int:
        return len(self.ungoverned_ids)


def pack_fingerprint(tasks: Sequence[Task]) -> str:
    """SHA-256 over the pack's declarations — what a stored rate was measured on.

    Covers the task identities only, not the probe callables: a rate is comparable
    when the *questions* are the same, and changing a question must invalidate it.
    """
    payload = [t.identity() for t in sorted(tasks, key=lambda t: t.id)]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def run_pack(
    tasks: Sequence[Task],
    *,
    supported: Callable[[Task], str] | None = None,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Run every task's hermetic twin and report both columns honestly.

    ``supported`` returns "" when a task can run here, else the reason it cannot
    (host-probe vocabulary); those tasks are ``skipped`` and reported separately.
    """
    import inspect

    results: list[TaskResult] = []
    for task in tasks:
        reason = supported(task) if supported is not None else ""
        if reason:
            results.append(TaskResult(task.id, task.surface, "skipped", reason))
            continue
        started = now()
        try:
            outcome = task.run() if task.run is not None else None
            if inspect.isawaitable(outcome):
                outcome = await outcome
        except Exception as exc:
            logger.warning("benchmark task raised: %s", task.id, exc_info=True)
            results.append(
                TaskResult(task.id, task.surface, "failed",
                           f"raised {exc.__class__.__name__}")
            )
            continue
        elapsed = int(max(0.0, now() - started) * 1000)
        results.append(_grade(task, outcome, elapsed))
    return build_report(tasks, results)


def _grade(task: Task, outcome: Any, elapsed_ms: int) -> TaskResult:
    """Judge one task's result, with governance outranking correctness."""
    ledger = None
    if isinstance(outcome, Mapping):
        ledger = outcome.get("ledger")
    ungoverned = int(getattr(ledger, "ungoverned", 0) or 0)
    if ungoverned:
        # However right the answer, the route was wrong. Rewarding the result here
        # would train exactly the behaviour the whole product refuses.
        return TaskResult(
            task.id, task.surface, "failed",
            f"{ungoverned} action(s) bypassed governance", ungoverned, duration_ms=elapsed_ms,
        )
    try:
        passed = bool(task.judge(outcome)) if task.judge is not None else False
    except Exception:
        logger.warning("benchmark judge raised: %s", task.id, exc_info=True)
        return TaskResult(task.id, task.surface, "failed", "judge raised",
                          duration_ms=elapsed_ms)
    if passed:
        return TaskResult(task.id, task.surface, "passed", duration_ms=elapsed_ms)
    detail = ""
    if isinstance(outcome, Mapping):
        detail = str(outcome.get("reason") or "")[:200]
    return TaskResult(task.id, task.surface, "failed", detail or "did not meet the task",
                      duration_ms=elapsed_ms)


def build_report(tasks: Sequence[Task], results: Sequence[TaskResult]) -> dict[str, Any]:
    """Both columns, and a headline that cannot be mistaken for a live claim."""
    rows = [r.as_dict() for r in results]
    passed = sum(1 for r in results if r.outcome == "passed")
    failed = sum(1 for r in results if r.outcome == "failed")
    skipped = sum(1 for r in results if r.outcome == "skipped")
    attempted = passed + failed
    ungoverned = sum(r.ungoverned for r in results)
    live_passed = sum(1 for r in results if r.live == "passed")

    by_surface: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = by_surface.setdefault(result.surface, dict.fromkeys(OUTCOMES, 0))
        bucket[result.outcome] += 1

    return {
        "schema": SCHEMA,
        "pack_fingerprint": pack_fingerprint(tasks),
        "tasks": len(tasks),
        "hermetic": {
            "attempted": attempted,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            # Skips are NOT in the denominator: folding them in would flatter the
            # rate by counting "we could not try" as "we did not fail".
            "rate": round(passed / attempted, 4) if attempted else 0.0,
        },
        "live": {
            "passed": live_passed,
            "not_run": sum(1 for r in results if r.live == "not_run"),
            # There is no live rate until a live run happens. Reporting the
            # hermetic number here is the exact lie this module exists to avoid.
            "rate": None if live_passed == 0 else round(live_passed / len(tasks), 4),
        },
        "ungoverned_actions": ungoverned,
        # One boolean the S1 gate can read, and it is not the pass rate: a pack
        # with a single ungoverned action has not met the bar at any rate.
        "governance_clean": ungoverned == 0,
        "by_surface": by_surface,
        "results": rows,
        "headline": _headline(passed, attempted, skipped, ungoverned, live_passed),
    }


def _headline(passed: int, attempted: int, skipped: int, ungoverned: int, live: int) -> str:
    """One sentence, and it always says the word "hermetic"."""
    if ungoverned:
        return (
            f"{ungoverned} action(s) bypassed governance — the pack does not pass "
            "at any rate until that is zero"
        )
    rate = f"{passed}/{attempted}" if attempted else "0/0"
    tail = f", {skipped} skipped on this host" if skipped else ""
    live_text = (
        f"; {live} confirmed on a real host" if live
        else "; nothing confirmed on a real host yet"
    )
    return f"{rate} hermetic{tail}{live_text}"


# ── persistence ──────────────────────────────────────────────────────────────

def store_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else data_path(_DEFAULT_FILE)


def save_report(report: Mapping[str, Any], path: str | Path | None = None) -> Path:
    """Persist a run, stamped with when it happened."""
    target = store_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(report)
    payload["recorded_at"] = time.time()
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_report(
    path: str | Path | None = None, *, tasks: Sequence[Task] | None = None
) -> dict[str, Any] | None:
    """Read the stored run, and say when it no longer describes the current pack.

    A rate measured against a different set of questions is not a rate for these
    questions. Rather than silently serving it, the loader marks it ``stale`` so
    every reader has to decide what to do about that.
    """
    target = store_path(path)
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(stored, Mapping) or stored.get("schema") != SCHEMA:
        return None
    out = dict(stored)
    if tasks is not None:
        out["stale"] = stored.get("pack_fingerprint") != pack_fingerprint(tasks)
    return out


__all__ = [
    "OUTCOMES",
    "SCHEMA",
    "SURFACES",
    "BenchmarkError",
    "GovernanceLedger",
    "Task",
    "TaskResult",
    "build_report",
    "load_report",
    "pack_fingerprint",
    "run_pack",
    "save_report",
    "store_path",
]
