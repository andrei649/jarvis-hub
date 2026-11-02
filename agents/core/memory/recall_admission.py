"""recall_admission.py — E3.2: why each recalled fact was let in, or was not.

Recall already decides things. A hit gets redacted because an injection scanner
flagged it; the turn gets escalated because something in the results was tainted.
What has never existed is a *record of the decision* — so "why did Nerva answer
with that?" and, worse, "why did it NOT use the thing I told it?" have had no
answer at all.

That second question is the one this is really for. A dropped hit is invisible by
construction: the answer just comes back thinner, and nobody can tell whether the
memory was missing, stale, or deliberately withheld. Those are three different
problems with three different fixes, and an unexplained absence looks the same as
all of them.

So every recall decision produces a :class:`RecallAdmission` with one reason from
a **closed** vocabulary. Three properties make it worth having:

* **Evaluation-only.** This module changes no floor and admits nothing that was
  not already admitted. It records what the existing rules decided. A record that
  could also *grant* would be a second, quieter admission path — and it would be
  the one nobody reviews, because it looks like logging.
* **Every outcome has a reason, including the boring one.** ``admitted`` is a
  reason, not the absence of one. An admission trail with entries only for
  refusals tells you what was blocked and never what was used, which is the half
  a person actually asks about.
* **The vocabulary is closed and the reasons do not overlap.** "It was dropped"
  is not an explanation; "it was dropped because the source is untrusted" is. A
  free-text reason drifts into prose nobody can aggregate, and overlapping reasons
  make a count meaningless.

There is deliberately no ``rejected_other``. A decision this module cannot name is
a decision the vocabulary is missing, and adding an escape hatch is how a closed
set stops being closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA = "nerva.recall-admission.v1"
AUTHORITY = "evaluation_only"

# The closed set. Ordered from "used" outward, and each names a *different*
# reason a person would act on differently:
#
#   admitted              — it was used. The reason a trail is readable at all.
#   rejected_taint        — the content is untrusted or carries an injection
#                           flag. A security decision.
#   rejected_privacy      — the caller is not cleared for this privacy class. A
#                           policy decision, and NOT the same as taint: one says
#                           "this might attack you", the other "this is not
#                           yours to see", and conflating them makes both
#                           unreadable.
#   rejected_stale        — superseded or invalidated by a later fact. A recency
#                           decision, and the one an owner most often means by
#                           "why did it use the old number".
#   rejected_contradiction— it conflicts with another admitted fact and neither
#                           can be preferred honestly. Withholding both is the
#                           right answer; picking one silently is not.
#   abstained             — the decision could not be made at all (the check
#                           itself failed). Distinct from every rejection above,
#                           because "we decided no" and "we could not decide"
#                           call for different fixes, and folding the second into
#                           the first is how a broken check hides as a policy.
ADMISSION_REASONS: tuple[str, ...] = (
    "admitted",
    "rejected_taint",
    "rejected_privacy",
    "rejected_stale",
    "rejected_contradiction",
    "abstained",
)

REJECTIONS = frozenset(r for r in ADMISSION_REASONS if r.startswith("rejected_"))

MAX_DETAIL_CHARS = 300
MAX_REF_CHARS = 200


class AdmissionError(ValueError):
    """A reason outside the closed vocabulary."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = str(reason)
        self.detail = str(detail or "")
        super().__init__(self.detail or self.reason)


@dataclass(frozen=True)
class RecallAdmission:
    """One recall decision, and the reason for it.

    Frozen: an admission that could be edited after the fact is a record of
    whatever someone last wanted it to say.
    """

    ref: str
    reason: str
    detail: str = ""
    redacted: bool = False
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.reason not in ADMISSION_REASONS:
            # No escape hatch. A decision the vocabulary cannot name is a gap in
            # the vocabulary, and `rejected_other` is how a closed set stops
            # being closed.
            raise AdmissionError("unknown_reason", f"{self.reason!r} is not an admission reason")
        object.__setattr__(self, "ref", str(self.ref or "")[:MAX_REF_CHARS])
        object.__setattr__(self, "detail", str(self.detail or "")[:MAX_DETAIL_CHARS])

    @property
    def admitted(self) -> bool:
        return self.reason == "admitted"

    @property
    def rejected(self) -> bool:
        return self.reason in REJECTIONS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ref": self.ref,
            "reason": self.reason,
            "detail": self.detail,
            "redacted": self.redacted,
        }


def hit_ref(hit: Any) -> str:
    """A short, stable handle for a hit — never its text.

    An admission trail that carried the content would be a second copy of the
    memory, subject to none of the redaction the first copy just went through.
    """
    if not isinstance(hit, Mapping):
        return ""
    for key in ("id", "fact_id", "observation_id", "entity_id", "source", "name"):
        value = hit.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:MAX_REF_CHARS]
    return ""


def admit(hit: Any, *, redacted: bool = False) -> RecallAdmission:
    """The boring outcome, recorded like every other one."""
    return RecallAdmission(ref=hit_ref(hit), reason="admitted", redacted=redacted)


def reject(hit: Any, reason: str, detail: str = "") -> RecallAdmission:
    if reason not in REJECTIONS:
        raise AdmissionError("not_a_rejection", f"{reason!r} is not a rejection reason")
    return RecallAdmission(ref=hit_ref(hit), reason=reason, detail=detail)


def abstain(hit: Any, detail: str = "") -> RecallAdmission:
    """The check itself failed. NOT a rejection — "could not decide" and "decided
    no" call for different fixes, and folding one into the other hides a broken
    check as a policy."""
    return RecallAdmission(ref=hit_ref(hit), reason="abstained", detail=detail)


def summarise(admissions: list[RecallAdmission] | tuple[RecallAdmission, ...]) -> dict[str, Any]:
    """Counts per reason, with every reason present.

    Missing keys would make a caller write ``.get(reason, 0)`` and a zero
    indistinguishable from a reason that was never evaluated — which is exactly
    the ambiguity this module exists to remove.
    """
    counts = dict.fromkeys(ADMISSION_REASONS, 0)
    for row in admissions or ():
        counts[row.reason] = counts.get(row.reason, 0) + 1
    total = sum(counts.values())
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "total": total,
        "admitted": counts["admitted"],
        "withheld": total - counts["admitted"],
        "by_reason": counts,
    }


def explain(admissions: list[RecallAdmission] | tuple[RecallAdmission, ...]) -> str:
    """One sentence a person can read.

    Says what was withheld and why, because an answer that is thinner than
    expected with no explanation looks identical to a missing memory.
    """
    counts = summarise(admissions)
    if not counts["total"]:
        return "nothing was recalled"
    if not counts["withheld"]:
        return f"{counts['admitted']} recalled fact(s) used, none withheld"
    return (
        f"{counts['admitted']} recalled fact(s) used, "
        f"{counts['withheld']} withheld ({_reasons(counts['by_reason'])})"
    )


def _reasons(by_reason: Mapping[str, int]) -> str:
    """``taint: 1, stale: 2`` — the withheld reasons in vocabulary order, never a zero."""
    return ", ".join(
        f"{name.removeprefix('rejected_')}: {by_reason[name]}"
        for name in ADMISSION_REASONS
        if name != "admitted" and by_reason.get(name)
    )


# ── H430: the per-turn recall indicator ────────────────────────────────────────
#
# Hermes renders each memory provider's last prefetch as one deterministic status line
# (``🧠 Provider — recalled 3 memories``) so the owner can see that memory was used this
# turn whether or not the model mentions it. Nerva's line is built the same way and from
# the same kind of state — what the recall path itself injected, never the model's text —
# plus the half Hermes leaves out: what the guard withheld, under which closed reason.
#
# A status carries counts and closed words only. No ref, no detail, no text: the line is
# shown beside a reply, and a line that quoted a memory would be a second, unfenced copy
# of it.

INDICATOR_GLYPH = "🧠"
RECALL_STATUS_SCHEMA = "nerva.recall-status.v1"
#: Every source that puts memory into a turn's prompt, in the order the lines are shown,
#: and the label each line names it by. Each reports its own last prefetch:
#:
#: * ``long_term_memory`` — the orchestrator's pre-turn recall (vector ⊕ graph,
#:   ``Orchestrator._recall_block``), shared by every agent the turn runs;
#: * ``message_archive`` — the owner's imported message archive, which Howard's prompt
#:   recalls as few-shot examples (``Agent.build_prompt``, ``search_similar(only_me=True)``).
RECALL_PROVIDERS: Mapping[str, str] = {"long_term_memory": "Long-term memory",
                                       "message_archive": "Message archive"}
#: ``this_turn`` — the turn's own recall ran and its result was used; ``previous_recall``
#: — it could not run in time and this session's previous recall stood in (H428);
#: ``unavailable`` — neither: the turn went on without that provider's memory.
RECALL_BASES: tuple[str, ...] = ("this_turn", "previous_recall", "unavailable")
#: The guard's per-snippet verdicts (``rag_guard.WrappedMemory.verdicts``): ``clean`` and
#: ``untrusted`` reached the prompt, ``redacted`` was withheld behind the redaction marker.
GUARD_VERDICTS: tuple[str, ...] = ("clean", "untrusted", "redacted")
_WITHHELD_REASONS = tuple(r for r in ADMISSION_REASONS if r != "admitted")
MAX_RECALL_COUNT = 10_000


def recall_status(
    admissions: list[RecallAdmission] | tuple[RecallAdmission, ...] = (),
    *,
    basis: str = "this_turn",
    untrusted: int = 0,
    counted: bool = True,
    provider: str = "long_term_memory",
) -> dict[str, Any]:
    """One provider's state after one prefetch: what reached the prompt, what was withheld.

    ``recalled`` is how many memories the prompt received with their content; ``None``
    when content was injected but could not be counted (the line then says "recalled
    relevant memory", never a guessed number). ``withheld`` names only the reasons that
    occurred. ``untrusted`` is how many of the recalled came from an untrusted source
    (used, datamarked, and why the turn's actions queue for approval). ``unavailable``
    carries no counts: nothing reached the prompt.
    """
    if provider not in RECALL_PROVIDERS:
        raise AdmissionError("unknown_provider", f"{provider!r} is not a recall provider")
    if basis not in RECALL_BASES:
        raise AdmissionError("unknown_basis", f"{basis!r} is not a recall basis")
    status: dict[str, Any] = {"schema": RECALL_STATUS_SCHEMA, "provider": provider, "basis": basis,
                              "recalled": 0, "withheld": {}, "untrusted": 0}
    if basis == "unavailable":
        return status
    if not counted:
        status["recalled"] = None
        return status
    counts = summarise(admissions)
    status["recalled"] = min(counts["admitted"], MAX_RECALL_COUNT)
    status["withheld"] = {name: min(count, MAX_RECALL_COUNT)
                          for name, count in counts["by_reason"].items() if name != "admitted" and count}
    if type(untrusted) is int and untrusted > 0:
        status["untrusted"] = min(untrusted, status["recalled"])
    return status


def guarded_recall_status(wrapped: Any, *, basis: str = "this_turn",
                          provider: str = "long_term_memory") -> dict[str, Any] | None:
    """The status of one prefetch whose snippets went through ``rag_guard.wrap_memory``,
    read from the guard's own per-snippet verdicts: ``redacted`` is withheld for taint (its
    body never reached the prompt), ``clean`` and ``untrusted`` were recalled. It never
    re-reads or re-scans a snippet.

    When the verdicts do not account for the rendered block, the status says "recalled
    relevant memory" if content went in and nothing at all if none did — never a guessed
    number. ``basis="unavailable"`` reports that the provider could not run.
    """
    if basis == "unavailable":
        return recall_status(basis="unavailable", provider=provider)
    verdicts = getattr(wrapped, "verdicts", ())
    verdicts = tuple(verdicts) if isinstance(verdicts, (tuple, list)) else None
    if (verdicts is None or len(verdicts) != getattr(wrapped, "n_items", None)
            or any(v not in GUARD_VERDICTS for v in verdicts)):
        injected = getattr(wrapped, "block", "")
        return (recall_status(basis=basis, counted=False, provider=provider)
                if type(injected) is str and injected.strip() else None)
    return recall_status(
        [reject({}, "rejected_taint", "injection-flagged") if v == "redacted" else admit({})
         for v in verdicts],
        basis=basis, untrusted=verdicts.count("untrusted"), provider=provider)


def _count(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_RECALL_COUNT


def valid_recall_status(status: Any) -> bool:
    """Whether *status* is a :func:`recall_status` shape: known keys, closed words, bounded
    counts and nothing else — so no caller can carry text through it."""
    if type(status) is not dict or set(status) != {"schema", "provider", "basis", "recalled",
                                                    "withheld", "untrusted"}:
        return False
    recalled, withheld, untrusted = status["recalled"], status["withheld"], status["untrusted"]
    if (status["schema"] != RECALL_STATUS_SCHEMA or status["provider"] not in RECALL_PROVIDERS
            or status["basis"] not in RECALL_BASES
            or not (recalled is None or _count(recalled)) or not _count(untrusted)
            or type(withheld) is not dict
            or any(name not in _WITHHELD_REASONS or not _count(count) or not count
                   for name, count in withheld.items())):
        return False
    if recalled is None:
        return not withheld and not untrusted
    return untrusted <= recalled and (status["basis"] != "unavailable"
                                      or (not recalled and not withheld))


def describe_recall(status: Any) -> str:
    """The one-line indicator for a :func:`recall_status`, or ``""`` when there is nothing
    to say (nothing recalled, nothing withheld). Deterministic: the same status always
    renders the same line, and a malformed status renders nothing rather than a guess.

    ``recalled 1 memory`` / ``recalled 3 memories`` / ``recalled relevant memory`` (content
    injected without a discrete count) are Hermes' three phrasings; a zero is never
    "0 memories". The HUD's renderer (``frontend/src/turn-outcome.tsx``) is pinned to this
    one by the shared cases in ``frontend/src/test/recall-line-cases.json``.
    """
    if not valid_recall_status(status):
        return ""
    label, basis = RECALL_PROVIDERS[status["provider"]], status["basis"]
    if basis == "unavailable":
        return f"{INDICATOR_GLYPH} {label} — unavailable this turn, no memory used"
    recalled, withheld, untrusted = status["recalled"], status["withheld"], status["untrusted"]
    parts: list[str] = []
    if recalled is None:
        parts.append("recalled relevant memory")
    elif recalled:
        parts.append("recalled 1 memory" if recalled == 1 else f"recalled {recalled} memories")
    if parts and basis == "previous_recall":
        parts[0] += " from this session's previous recall"
    if parts and untrusted:
        parts[0] += f" ({untrusted} from an untrusted source)"
    total = sum(withheld.values())
    if total:
        parts.append(f"{total} withheld ({_reasons(withheld)})")
    if not parts:
        return ""
    return f"{INDICATOR_GLYPH} {label} — " + ", ".join(parts)


def describe_recalls(statuses: Any) -> list[str]:
    """One line per provider that has something to say, in :data:`RECALL_PROVIDERS`
    order — the indicator for a whole turn, which may have recalled from several sources.
    A malformed entry, a repeated provider and a silent status render no line."""
    if not isinstance(statuses, (list, tuple)):
        return []
    by_provider: dict[str, str] = {}
    for status in statuses:
        if valid_recall_status(status) and status["provider"] not in by_provider:
            by_provider[status["provider"]] = describe_recall(status)
    return [by_provider[p] for p in RECALL_PROVIDERS if by_provider.get(p)]


__all__ = [
    "ADMISSION_REASONS",
    "AUTHORITY",
    "GUARD_VERDICTS",
    "INDICATOR_GLYPH",
    "MAX_DETAIL_CHARS",
    "MAX_RECALL_COUNT",
    "RECALL_BASES",
    "RECALL_PROVIDERS",
    "RECALL_STATUS_SCHEMA",
    "REJECTIONS",
    "SCHEMA",
    "AdmissionError",
    "RecallAdmission",
    "abstain",
    "admit",
    "describe_recall",
    "describe_recalls",
    "explain",
    "guarded_recall_status",
    "hit_ref",
    "recall_status",
    "reject",
    "summarise",
    "valid_recall_status",
]
