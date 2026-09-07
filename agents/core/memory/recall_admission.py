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
    reasons = ", ".join(
        f"{name.removeprefix('rejected_')}: {count}"
        for name, count in counts["by_reason"].items()
        if name != "admitted" and count
    )
    return (
        f"{counts['admitted']} recalled fact(s) used, "
        f"{counts['withheld']} withheld ({reasons})"
    )


__all__ = [
    "ADMISSION_REASONS",
    "AUTHORITY",
    "MAX_DETAIL_CHARS",
    "REJECTIONS",
    "SCHEMA",
    "AdmissionError",
    "RecallAdmission",
    "abstain",
    "admit",
    "explain",
    "hit_ref",
    "reject",
    "summarise",
]
