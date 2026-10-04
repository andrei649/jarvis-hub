# H487 owner-once root integration

Generated2026-10-04; goal remains all697 pinned Hermes capabilities.
Base/head:`31a1d193`; prototype base:`4f265c6c`. Root is the sole real writer.

Apply only new tests first, observe meaningful missing-outcome RED, then apply
three source files and three narrow obsolete test expectations. Re-read the
process-local observation identity, immutable hard deadline, exact durable offer
reconciliation and claim-only execution branch; run focused and adjacent native
queue/consent/terminal regressions. Preserve genuine cancellation/pre-delivery
behavior and no physical effects for every observational ending.

Read-only review found a post-CAS/pre-publication race, reproduced and corrected
in the disposable prototype with an actual SQLite queue and cross-loop barrier.
Root integration must retain that exact test. Outcomes are not capabilities and
never mint kernel proof, queue grant or terminal effects. Queue/kernel/proof code
is unchanged. Rollback: reverse the seven-path patch and regenerate records.
No live Telegram/provider/device acceptance, push, merge or deploy. Next action:
apply the new14-case module before source, then record actual RED/GREEN.

# H487 Owner-Once Outcome Parity Implementation Plan

> **For agentic workers:** Use test-driven development and native execution in this disposable snapshot. The parent task explicitly forbids delegation and real-checkout edits.

**Goal:** Preserve distinct owner-once wait endings for a delivered native prompt: unanswered expiry, live-source withdrawal, authenticated owner denial, and an accepted choice held before handoff.

**Architecture:** Add a frozen nonauthority outcome value beside `OwnerOnceClaim`. The prompts coordinator publishes a queue-committed reply process-locally before scheduling an async wake, then records the exact returned observation for terminal review. Terminal review validates observation identity and durable owner-denial state and never sends any outcome object to the signed execution path.

**Tech Stack:** Python 3.12, asyncio/threading, SQLite-backed real queue, httpx MockTransport, pytest, Ruff.

**Spec:** Parent handoff dated 2026-10-04, pinned Hermes `tools/approval.py:872-902`, source baseline `4f265c6cdbe8d04d905230919bd0e717d6a3c5c4`, `/tmp/nerva-h277-openrouter-video-full-20261004-frozen.json`.

## Global Constraints

- Production edits only in `agents/core/autonomy/owner_once.py`, `owner_once_prompts.py`, and `terminal_review.py`.
- Add `tests/test_h487_owner_once_outcomes.py`; narrow old assertions only where the new result type or terminal reason necessarily replaces a former `None`/`guardian_denied` expectation.
- No queue, kernel, proof, grant, or Telegram authority change. Only exact `OwnerOnceClaim` enters `_run_owner_once`.
- Pre-delivery unavailability remains `None`; cancellation propagates. Observations cannot mint claims or physical effects.
- Preserve the hard offer deadline and `native_human_wait_window` only for a verified delivered prompt.
- No real checkout/index/docs edits, network/provider call, install, publication, or delegation.

## Review Focus

- A delivered hard expiry returns `timeout` even if the queue later settles the guardian denial.
- A channel/source/generation or registration withdrawal settles promptly as `withdrawn`, without waiting for hard expiry.
- A denied result requires the exact callback, queue CAS, durable human decision, offer, and prompt-local publication; a forged object or later offer cannot qualify.
- A committed accepted choice whose waiter dies returns `held`, and cannot dispatch or revive a grant.
- A delayed cross-loop wake cannot erase a committed denial; cancellation and pre-delivery failure retain their former behavior.

---

### Task 1: Wait result semantics

**Files:** `owner_once.py`, `owner_once_prompts.py`, new `tests/test_h487_owner_once_outcomes.py`, narrow `tests/test_h485_owner_once_prompts.py` updates.

**Interfaces:** `OwnerOnceWaitOutcome(state, task_id, nonce, decision_id)` is frozen and nonauthority. `OwnerOncePrompts.request(...) -> OwnerOnceClaim | OwnerOnceWaitOutcome | None`; `consume_outcome(outcome, task) -> str | None` confirms process-local identity, exact offer and durable denial.

- [ ] Write RED real-queue/MockTransport tests for delivered timeout, stop/withdrawal, denial, pre-delivery failure, cancellation, delayed cross-loop wake, forged/later offer, and accepted-but-held with no effects.
- [ ] Run focused new tests and record expected failures.
- [ ] Implement process-local committed-result publication before async wake; poll a delivered wait until answer, source withdrawal, or hard deadline. Record observational outcome identity separately from claims.
- [ ] Run new and existing prompt tests green.

### Task 2: Terminal handback

**Files:** `terminal_review.py`, new `tests/test_h487_owner_once_outcomes.py`, authorized narrow `tests/test_h485_owner_once_actuation.py` update.

- [ ] Add RED real terminal review tests for timeout/withdrawn/denied and held result; keep guardian provenance and zero physical effects.
- [ ] Map verified observations to `approval_timed_out` / `expired_unanswered`, `approval_withdrawn` / `withdrawn`, `owner_denied` / `denied`, and `terminal_execution_held` / `approved`. Reject forged observation fields.
- [ ] Run owner-once actuation/continuation and H487 native-runtime regressions green.

### Task 3: Verify and hand off

- [ ] Run affected owner-once/H487/H277 runtime tests with XML and Ruff, avoiding the concurrent full suite.
- [ ] Create an exact owned-path unified patch from hash-verified baseline, prove `git apply --check` in a fresh baseline copy, and record RED/GREEN evidence and limitations.

**Generation time:** 2026-10-04. **Next action:** write RED tests before production code.

Root terminal checkpoint: integrated source commits `48e911ed` and `c479790b`, verified head `e84f0922b230a2349933c67d8511cd3684c17e1a`. Frozen full backend: 22,465 total, 22,430 passed, 34 ordinary skips, 1 existing expected failure, zero failures/errors; all 3,020 input hashes unchanged. See [separate full receipt](evidence/h487-auxiliary-outcomes-full-2026-10-04.json). Implementation and root verification steps above are delivered; prototype checklist is retained as its pre-code historical plan. H277/H487 remain partial. Next action: reviewed next source units and remaining all697 work.
