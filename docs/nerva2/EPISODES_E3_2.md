# E3.2 — a recall admission reason for every recall decision

> **Status:** delivered, not program-accepted.
> **Owner decision:** 2026-09-01, `CONTINUITY_CORE_RECONCILIATION.md` §7.
> **Closes:** B3 / #731 — E3 #761 taint/provenance reason per recall admission.
> **Authority:** `evaluation_only`. It records decisions; it makes none.

## The question this answers

Recall already decides things. A hit gets redacted because the injection scanner
flagged it; the turn gets escalated because something in the results was tainted.
What has never existed is a **record of the decision**.

The question that needs it is not "why did Nerva answer with that?" — it is:

> **Why did it not use the thing I told it?**

A dropped hit is invisible by construction. The answer just comes back thinner, and
a *missing* memory, a *stale* one and a *deliberately withheld* one look identical
from the outside. They are three different problems with three different fixes.

## The closed vocabulary

| reason | means | what a person does about it |
|---|---|---|
| `admitted` | it was used | nothing — but it is what makes the trail readable |
| `rejected_taint` | untrusted source or an injection flag | a security decision; check the source |
| `rejected_privacy` | the caller is not cleared for this privacy class | a policy decision; grant scope, or accept it |
| `rejected_stale` | superseded or invalidated by a later fact | usually what "why did it use the old number" means |
| `rejected_contradiction` | conflicts with another admitted fact, and neither can be preferred honestly | resolve the conflict; picking one silently is not an option |
| `abstained` | the check itself failed | fix the check — this is **not** a rejection |

Two of these distinctions do real work:

* **taint ≠ privacy.** One says "this might attack you"; the other says "this is not
  yours to see". Conflating them makes both unreadable.
* **abstained ≠ rejected.** "We decided no" and "we could not decide" call for
  different fixes. Folding the second into the first is how a broken check hides as
  a policy.

There is **no `rejected_other`**. A decision the vocabulary cannot name is a gap in
the vocabulary; an escape hatch is how a closed set stops being closed.

## Three properties

* **Evaluation-only.** Nothing here admits what was not already admitted or blocks
  what was not already blocked. A record that could also *grant* would be a second,
  quieter admission path — and the one nobody reviews, because it looks like logging.
* **`admitted` is a reason, not an absence.** A trail with entries only for refusals
  tells you what was blocked and never what was used.
* **An admission never carries the recalled text.** Only a short reference. A trail
  carrying the content would be a second copy of the memory, subject to none of the
  redaction the first copy just went through.

## Where it is wired

`MemorySearchTool.search` returns `admissions` and `admission_summary` alongside its
hits. A hit that is both tainted and redacted is recorded as `rejected_taint`: taint
is *why* it was withheld and redaction is *how*, and recording the how leaves the
reason — the part a person acts on — unstated.

`explain()` renders one sentence: *"3 recalled fact(s) used, 2 withheld (taint: 1,
stale: 1)"*.

## Checks

`tests/_nerva_e3_2_checks.py`, invoked from `tests/test_h14_1_bitemporal_kg.py`
(count-neutral). Twelve checks; `_there_is_no_escape_hatch` and
`_a_tainted_hit_is_recorded_as_taint_not_as_redaction` are red-proven.
