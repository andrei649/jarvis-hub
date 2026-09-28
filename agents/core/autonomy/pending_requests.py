"""pending_requests.py — closing the loop between a night's ask and the owner's answer.

A company-mode run that needs something privileged does not do it: it hands the
action to the governed intake, gets back a durable task, records a ``queued``
step and **blocks**. Without this module that is where the story ends — the task
gets approved in the morning and the run stays blocked forever, because nothing
ever told it. This is the half that reads the answer and moves the run.

**There is no pending-request table here, on purpose.** The ledger already holds
the fact durably: a ``queued`` step carrying the durable task id. A second table
would be a second copy of one fact, and two copies drift — into a run blocked on
an ask nobody can find, or an ask that gets reconciled twice. So the outstanding
asks *are* :meth:`WorkRunLedger.outstanding_asks`, and this module is a
reconciler over them.

Every rule below exists against a specific way of faking an approval:

* **Silence is never a yes.** An undecided task leaves the ask open and the run
  blocked. Nothing here turns "nobody answered" into "approved" — the only thing
  a deadline may do is *end* the run, and that is the budget's job, not this
  module's. This is the rule the whole file exists to protect.
* **The decision is read from the task, every time.** Never from a cached copy
  and never from what the run believed when it queued: a cached "approved" is how
  an approval given for one thing gets spent on another.
* **A vanished task is not an approval.** A purged or unknown id resolves as
  ``lost`` and records a *failed* step, so the supervisor's repeat-failure rule
  can end a run whose asks keep evaporating. Treating it as "probably fine" would
  be the single most dangerous line in the codebase.
* **Who decided is recorded, and it is not hidden.** A run may legitimately be
  unblocked by a policy auto-approval — the owner authorised the goal, and the
  intake decides each action on its own terms. That is exactly why the brief has
  to be able to say "5 of 9 steps were auto-approved by policy": the split is a
  fact the owner is owed, not an embarrassment to smooth over.
* **A rejection is an answer.** It closes the ask, records a ``refused`` step and
  lets the run continue with something else — the planner's refusal fingerprint
  is what stops it proposing the same thing again.
* **Deferred is still waiting**, not an answer.
* **Reconciling is idempotent.** The same decision applied twice must not resume
  a run twice; the ledger refuses to resolve a step that is no longer
  outstanding, so the second application is a no-op rather than a second step.
* **A stop outranks an answer.** A resolution never resumes a run that is
  stopping or already terminal: the asks are still closed (the record should say
  what the answer was) but the run does not move.
* **A wait still open is observed here (H464d).** H487 credits the time the owner
  took to decide, and for an ask whose decision stamp cannot be used (the owner
  edited it before approving) only up to the last time the open wait was observed
  on the record. The report routes are read-only, so this reconcile — which reads
  every blocked run's asks on each sweep anyway — is the observer: a run still
  waiting gets one settling budget read, and the credit is the same whether or not
  anyone looked at the HUD.

Nothing here reads the environment and nothing here authorises: the reconciler
can unblock a run, which is strictly less than being able to start one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agents.core.autonomy.work_runs import FLAG as _FLAG
from agents.core.autonomy.work_runs import WorkRunError

logger = logging.getLogger("jarvis.pending_requests")

# Reconciling only matters where runs exist, and runs only exist under company
# mode. Re-exported from work_runs rather than re-spelled so the two can never
# gate on different strings.
FLAG = _FLAG

# How a queued step ended up. Each maps to one sentence in the brief; "waiting"
# is a first-class outcome rather than the absence of one, because "still waiting
# on you, since 11pm" is the most useful thing a morning report can say.
RESOLUTIONS = ("approved", "rejected", "waiting", "lost", "expired_unanswered")

# Task statuses that mean the owner (or policy) said yes. ``running`` and ``done``
# are included because a task can be decided and executed between two sweeps —
# missing that would leave the run blocked on work that already happened.
_APPROVED_STATUSES = frozenset({"approved", "running", "done"})
# ...and the ones that mean no. ``quarantined`` counts: the action was taken out
# of the queue's hands and will not run, which the run must not read as pending.
_REJECTED_STATUSES = frozenset({"rejected", "failed", "quarantined"})
# Everything else — ``proposed``, ``blocked``, ``deferred`` — is still waiting.

# Deciders that are not a person. Spelled the same way, and for the same reason,
# as permission_ledger, goal_contract and first_action.
MACHINE_DECIDERS = frozenset(
    {"policy", "system", "kernel", "auto", "worker", "scheduler", ""}
)


@dataclass(frozen=True)
class AskOutcome:
    """What one outstanding ask turned out to be."""

    run_id: str
    step_seq: int
    task_id: int | None
    resolution: str
    detail: str
    decided_by: str = ""
    by_machine: bool = False
    human_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_seq": self.step_seq,
            "task_id": self.task_id,
            "resolution": self.resolution,
            "detail": self.detail,
            "decided_by": self.decided_by,
            "by_machine": self.by_machine,
            **({"human_reason": self.human_reason} if self.human_reason else {}),
        }


@dataclass(frozen=True)
class ReconcileResult:
    """What one pass over a run's outstanding asks did."""

    run_id: str
    outcomes: tuple[AskOutcome, ...] = ()
    resumed: bool = False
    note: str = ""

    @property
    def still_waiting(self) -> int:
        return sum(1 for o in self.outcomes if o.resolution == "waiting")

    @property
    def answered(self) -> int:
        return sum(1 for o in self.outcomes if o.resolution != "waiting")

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "resumed": self.resumed,
            "note": self.note,
            "answered": self.answered,
            "still_waiting": self.still_waiting,
            "outcomes": [o.as_dict() for o in self.outcomes],
        }


@dataclass(frozen=True)
class SweepReport:
    """One pass over every blocked run."""

    results: tuple[ReconcileResult, ...] = ()
    errors: tuple[str, ...] = field(default=())

    @property
    def resumed(self) -> int:
        return sum(1 for r in self.results if r.resumed)

    @property
    def still_waiting(self) -> int:
        return sum(r.still_waiting for r in self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runs": len(self.results),
            "resumed": self.resumed,
            "still_waiting": self.still_waiting,
            "errors": list(self.errors),
            "results": [r.as_dict() for r in self.results],
        }


# A task whose read raised in this pass: never a decision, never re-read again.
_UNREADABLE = object()


def _status_of(task: Any) -> str:
    return str(getattr(task, "status", "") or "").strip().lower()


def _decision_of(task: Any) -> str:
    return str(getattr(task, "decision", "") or "").strip().lower()


def _decider_of(task: Any) -> str:
    return str(getattr(task, "decided_by", "") or "").strip().lower()


def classify(task: Any) -> tuple[str, str]:
    """What one durable task says about the ask that is waiting on it.

    Returns ``(resolution, detail)``. A task this cannot read confidently comes
    back as ``waiting`` rather than as anything that would let the run proceed:
    the failure direction here has to be "keep waiting", never "assume yes".
    """
    if task is None:
        return "lost", "the durable task is gone — it was never an approval"
    status = _status_of(task)
    if status == "expired":
        return "expired_unanswered", "approval deadline elapsed unanswered"
    if status in _APPROVED_STATUSES:
        decision = _decision_of(task) or "approved"
        return "approved", f"the task was {status} ({decision})"
    if status in _REJECTED_STATUSES:
        return "rejected", f"the task was {status}"
    if not status:
        # A task object with no readable status is not a decision. Saying
        # "waiting" costs a night; saying "approved" spends an authorisation
        # nobody gave.
        return "waiting", "the task has no readable status"
    return "waiting", f"the task is still {status}"


def _human_reason_of(task: Any) -> str | None:
    """Read only durable human metadata; executor result dictionaries never count."""
    from .decision_reasons import normalize_reason

    metadata = getattr(task, "human_decision", None)
    if not isinstance(metadata, dict):
        return None
    by = str(metadata.get("by") or "").strip().lower()
    if by in MACHINE_DECIDERS or metadata.get("action") not in {"accept", "edit", "reject", "defer"}:
        return None
    try:
        return normalize_reason(metadata.get("reason"))
    except ValueError:
        return None


class PendingRequests:
    """Reads the answers to a run's outstanding asks and moves the run.

    ``ledger`` is the :class:`WorkRunLedger`; ``read_task`` takes a durable task
    id and returns the task record (typically ``TaskQueue.get``) or ``None``.
    Both are injected, so this is testable without a queue or a database.
    """

    def __init__(
        self,
        ledger: Any,
        *,
        read_task: Callable[[int], Any],
    ) -> None:
        self._ledger = ledger
        self._read_task = read_task

    # ── one run ──────────────────────────────────────────────────────────

    def reconcile(self, run_id: str) -> ReconcileResult:
        """Close every answered ask on one run, and resume it if it can move."""
        run = self._ledger.get(run_id)
        if run is None:
            return ReconcileResult(run_id, note="unknown run")
        outcomes, expiry_resumed, settled_expiry = self._close_asks_with_expiry(run_id)
        if settled_expiry:
            # An expiry settled in this pass — found on the first read or on a re-read
            # after that read failed — has already decided, atomically, whether the run
            # resumes. No generic resume may follow it: for an unmarked (pre-v3) block
            # that would turn "nobody answered" into a resume (round-2 MINOR 1).
            return ReconcileResult(run_id, outcomes, resumed=expiry_resumed,
                                   note="expiry settled atomically" if expiry_resumed else "expiry settled; run held")
        if run.terminal:
            # The asks are still worth closing — the record should say what the
            # answer was — but a finished run is a record, never a resource to
            # reopen.
            return ReconcileResult(
                run_id, outcomes, note=f"run is already {run.status}"
            )

        if run.status == "stopping":
            return ReconcileResult(
                run_id, outcomes, note="the run is stopping; an answer does not restart it"
            )
        if run.status != "blocked":
            return ReconcileResult(
                run_id, outcomes, note=f"the run is {run.status}, not blocked"
            )
        if any(o.resolution == "waiting" for o in outcomes):
            waiting = sum(1 for o in outcomes if o.resolution == "waiting")
            self._observe_wait(run_id)
            return ReconcileResult(
                run_id, outcomes,
                note=f"still waiting on {waiting} decision(s)",
            )
        if not outcomes:
            # Blocked with nothing outstanding is a stuck run, not a licence to
            # proceed. Resuming would be inventing the ask that unblocked it.
            return ReconcileResult(
                run_id, outcomes,
                note="blocked with no outstanding ask — nothing here can unblock it",
            )
        try:
            if self._unmarked_block(run_id):
                # Review F5: a run blocked before migration v3 has no causal marker.
                # An answered ask resumes it on the pre-v3 contract plus the same
                # stop/barrier/outstanding/budget holds, atomically in the ledger;
                # expiry settlement (above) still holds such a run, and so does the
                # ledger when an ask of the block expired in an EARLIER pass (round 3,
                # item 6) — the hold is read from the block's asks, not from this pass.
                self._ledger.resume_unmarked_after_asks(run_id)
            else:
                self._ledger.resume_after_asks(run_id, answered_seqs=[o.step_seq for o in outcomes])
        except WorkRunError as exc:
            return ReconcileResult(run_id, outcomes, note=f"resume refused: {exc.reason}")
        return ReconcileResult(run_id, outcomes, resumed=True, note="every ask is answered")

    def _observe_wait(self, run_id: str) -> None:
        """Record, durably, that the run's approval wait is still open (H464d).

        The ledger's settling budget read extends each open wait source to now when
        — and only when — its task is still blocked on the owner with the intent it
        was queued with; a decided, edited or expired task is never extended. Best
        effort: a failed observation costs credit, never the reconcile."""
        observe = getattr(self._ledger, "budget_state", None)
        if not callable(observe):
            return
        try:
            observe(run_id)
        except Exception:
            logger.debug("could not observe the open approval wait of %s", run_id,
                         exc_info=True)

    def _unmarked_block(self, run_id: str) -> bool:
        """Whether the run's block carries no ``approval_block_seq`` (a pre-v3 block).
        A ledger without the marker accessor is treated as marked (the strict path)."""
        marker_of = getattr(self._ledger, "approval_block_seq", None)
        if not callable(marker_of) or not callable(getattr(self._ledger, "resume_unmarked_after_asks", None)):
            return False
        return marker_of(run_id) is None

    def _close_asks_with_expiry(self, run_id: str) -> tuple[tuple[AskOutcome, ...], bool, bool]:
        """Close every outstanding ask of one run.

        Returns ``(outcomes, resumed, settled_expiry)``: ``settled_expiry`` is True when
        any ask was settled as expired in this pass, and ``resumed`` when one of those
        settlements resumed the run atomically.
        """
        steps = self._ledger.outstanding_asks(run_id)
        # One authoritative read per source (a second only when the first raised);
        # expiry is terminal. The re-read happens here, before ordering, so an
        # expiry found only on the re-read is ordered like any other: normal answers
        # first, every expiry last, so the final expiry transaction can close the
        # epoch. A source unreadable twice stays queued and prevents atomic resume.
        prepared = [(step, self._read_or_unreadable(step)) for step in steps]
        prepared = [(step, self._read_or_unreadable(step) if task is _UNREADABLE else task)
                    for step, task in prepared]
        prepared.sort(key=lambda item: _status_of(item[1]) == "expired")
        outcomes: list[AskOutcome] = []
        settled_expiry = False
        resumed = False
        for step, task in prepared:
            outcome, expiry_resumed = self._close_one(run_id, step, task=task)
            if expiry_resumed is not None:
                settled_expiry = True
                resumed = resumed or expiry_resumed
            outcomes.append(outcome)
        return tuple(outcomes), resumed, settled_expiry

    def _read_or_unreadable(self, step: Any) -> Any:
        if step.task_id is None:
            return None
        try:
            return self._read_task(step.task_id)
        except Exception:
            # Preserve per-source ordinary reconciliation on read failures.
            return _UNREADABLE

    def _close_one(self, run_id: str, step: Any, *, task: Any) -> tuple[AskOutcome, bool | None]:
        """Close one ask, given what :meth:`_read_or_unreadable` read for it (the task,
        ``None``, or ``_UNREADABLE``). Returns ``(outcome, expiry_resumed)``: ``None``
        when this call settled no expiry, otherwise whether the ledger's expiry
        settlement resumed the run. This is the only place a reconcile pass settles an
        expiry, and it reports it, so the caller holds the run on the expiry's own
        decision instead of resuming it a second way (round-2 MINOR 1)."""
        task_id = getattr(step, "task_id", None)
        seq = int(getattr(step, "seq", 0))
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
            # A queued step with no durable task is a bug in whatever recorded it.
            # It is recorded as lost rather than silently waiting forever, so the
            # streak rule can end the run instead of the run hanging until dawn.
            return self._apply(run_id, seq, None, "lost", "the step carries no durable task"), None
        if task is _UNREADABLE:
            # A queue that cannot be read is not a queue that said yes. The source
            # remains queued and prevents atomic resume.
            logger.warning("could not read task %s while reconciling %s", task_id, run_id)
            return AskOutcome(
                run_id, seq, task_id, "waiting", "the task could not be read"
            ), None
        resolution, detail = classify(task)
        if resolution == "expired_unanswered":
            settlement = self._ledger.settle_expired_ask(run_id, seq, task_id=task_id,
                                                         expired_at=task.expired_at)
            return (AskOutcome(run_id, seq, task_id, resolution, detail, "system", True),
                    bool(getattr(settlement, "resumed", False)))
        decided_by = _decider_of(task) if task is not None else ""
        return self._apply(
            run_id, seq, task_id, resolution, detail, decided_by=decided_by,
            human_reason=_human_reason_of(task),
        ), None

    def _apply(
        self,
        run_id: str,
        seq: int,
        task_id: int | None,
        resolution: str,
        detail: str,
        *,
        decided_by: str = "",
        human_reason: str | None = None,
    ) -> AskOutcome:
        by_machine = decided_by in MACHINE_DECIDERS
        outcome = AskOutcome(
            run_id, seq, task_id, resolution, detail,
            decided_by=decided_by, by_machine=by_machine, human_reason=human_reason,
        )
        if resolution == "waiting":
            return outcome
        step_outcome = {"approved": "ok", "rejected": "refused", "lost": "failed"}[resolution]
        try:
            self._ledger.resolve_step(
                run_id, seq,
                outcome=step_outcome,
                detail={
                    "resolution": resolution,
                    "reason": detail,
                    "decided_by": decided_by,
                    "by_machine": by_machine,
                    **({"human_reason": human_reason} if human_reason else {}),
                },
            )
        except WorkRunError as exc:
            # Already answered by a concurrent sweep. Report what we found; the
            # ledger's refusal is what makes reconciling idempotent.
            logger.debug("step %s/%s not outstanding: %s", run_id, seq, exc.reason)
        return outcome

    # ── every blocked run ────────────────────────────────────────────────

    def sweep(self, *, limit: int = 50) -> SweepReport:
        """Reconcile every blocked run. Safe to call on a timer."""
        results: list[ReconcileResult] = []
        errors: list[str] = []
        for run in self._ledger.list_runs(active_only=True, limit=limit):
            if run.status not in {"blocked", "stopping"}:
                continue
            try:
                results.append(self.reconcile(run.id))
            except Exception as exc:  # one bad run must not stop the sweep
                logger.warning("reconcile failed for %s", run.id, exc_info=True)
                errors.append(f"{run.id}: {exc.__class__.__name__}")
        return SweepReport(tuple(results), tuple(errors))


def waiting_summary(report: SweepReport | ReconcileResult) -> str:
    """One honest sentence for the brief.

    "Still waiting on you" is the finding a morning report exists to deliver, so
    it is said in words rather than left as a count the reader has to interpret.
    """
    if isinstance(report, ReconcileResult):
        report = SweepReport((report,))
    if not report.results:
        return "no run is waiting on a decision"
    if report.still_waiting:
        return (
            f"{report.still_waiting} decision(s) still waiting on you; "
            f"{report.resumed} run(s) resumed"
        )
    if report.resumed:
        return f"{report.resumed} run(s) resumed — every ask is answered"
    return "every ask is answered; no run could resume"


def machine_share(outcomes: Mapping[str, Any] | SweepReport) -> dict[str, int]:
    """How many answered asks a person actually decided.

    The owner approved the *goal*; each action was decided on its own terms, and
    some of those decisions were made by policy. A brief that hides the split
    reads as "you approved nine things" when the owner approved one.
    """
    if isinstance(outcomes, SweepReport):
        flat = [o for r in outcomes.results for o in r.outcomes]
    else:
        flat = list(outcomes.get("outcomes", []))  # type: ignore[union-attr]
    answered = [o for o in flat if _resolution(o) != "waiting"]
    machine = sum(1 for o in answered if _by_machine(o))
    return {"answered": len(answered), "by_machine": machine, "by_person": len(answered) - machine}


def _resolution(outcome: Any) -> str:
    if isinstance(outcome, AskOutcome):
        return outcome.resolution
    return str(outcome.get("resolution", "") or "")


def _by_machine(outcome: Any) -> bool:
    if isinstance(outcome, AskOutcome):
        return outcome.by_machine
    return bool(outcome.get("by_machine"))


__all__ = [
    "FLAG",
    "MACHINE_DECIDERS",
    "RESOLUTIONS",
    "AskOutcome",
    "PendingRequests",
    "ReconcileResult",
    "SweepReport",
    "classify",
    "machine_share",
    "waiting_summary",
]
