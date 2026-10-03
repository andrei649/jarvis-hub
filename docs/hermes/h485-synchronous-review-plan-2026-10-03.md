# H485 synchronous guardian review implementation plan

> **For agentic workers:** Execute owned tasks with red-first regressions; the coordinator owns integration and review. No subagent delegation.

**Goal:** Let a governed terminal tool invocation receive its exact guardian verdict before human escalation, and continue approved operations through existing sealed execution.

**Architecture:** Join the existing capacity-bounded runner by persisted task id and approval snapshot digest. A server-owned async ToolRPC seam will await that attempt; notification release and the model's feedback will consume fresh durable state, never a waiter return value as authority. Existing signed receipts, kernel/taint floors and owner decisions remain authoritative.

**Tech Stack:** Python 3.12, asyncio, thread-safe completion futures, existing SQLite queue and HTTPX native transport tests. No new dependency.

**Spec:** Pinned Hermes guardian behavior; `h277-smart-terminal-plan-2026-10-03.md`, `h485-smart-observers-plan-2026-10-03.md`, and the verified source gap in ToolRPC's immediate approval-required return.

## Freshness and constraints

- Generated: 2026-10-03; base and initial HEAD `d5e957637424faf8e04816b0d4f19cb6971daf51`.
- Local branch `codex/h277-provider-discovery-20261002`; no push, merge, deploy, live provider calls or runtime activation.
- Full objective remains all 697 capability rows. This plan does not close H485/H277 by introducing a waiting primitive.
- At most two Sol High implementers; single writer per file. Coordinator retains shared interface, integration and final review.
- Preserve 32 pending / two concurrent shared judge limits, fresh contexts, live consent checks at native dispatch, and exact queue CAS.
- Timeout covers slot waiting as well as inference. Caller cancellation invalidates only the exact scheduled attempt; a completed queue decision cannot be rolled back by cancelling a waiter.
- A wait result means the attempt completed, not that a verdict exists, an operation is authorized or execution succeeded.
- No completion cache or unbounded waiter registry. Offline/capacity-refused/not-scheduled attempts return promptly.
- Rollback: revert this coherent local change; persisted queue schema and signed receipt format remain unchanged.

## Review focus

1. Hub-loop jobs joined from a different caller loop must not leak work or deadlock.
2. A timeout before hub spawn or while waiting for a slot must prevent late native dispatch.
3. A backend swallowing cancellation must not store or send after attempt invalidation.
4. A previous callback must never release or settle a replacement attempt sharing the same key.
5. Payload edit, owner decision, expiry and judge revocation must preserve manual control and refuse stale verdicts.

## Task 1 — exact-attempt wait and cancellation lifecycle

Owned files: `agents/core/autonomy/advisory_judgements.py`, `agents/core/autonomy/task_approval_judge.py`, `tests/test_h485_judgement_waiting.py` (Sol High implementer).
Coordinator tests: `tests/test_h485_smart_review_waiting_integration.py`.

Interfaces:
- `AdvisoryJudgements._wait_judgement(action_id: str, *, timeout: float) -> bool` joins only an existing exact attempt. Missing/invalid-timeout/timed-out/invalidated work returns False; natural completion returns True. Caller CancelledError propagates after synchronous invalidation and thread-safe cancellation request.
- `AdvisoryJudgements._cancel_judgement(action_id: str) -> None` invalidates the exact attempt before scheduling its cancellation. No authority is derived from it.
- `TaskApprovalJudge.wait_for_review(task_id: int, snapshot_sha256: str, *, timeout: float) -> bool` validates typed id and lowercase SHA256, then joins the exact existing attempt. It does not schedule, score, promote or execute.
- Preserve existing `schedule`, projections and shared capacity contracts. `clear_pending` must invalidate exact task attempts as well as UI pending markers.

- [x] Write failing tests for natural completion, no scheduling, prompt unavailable return, slot timeout, caller cancellation, cross-loop ownership, cancellation-resistant work, duplicate joiners and exact-key replacement cleanup.
- [x] Run the new tests against the parent implementation and record expected missing-interface failures.
- [x] Implement bounded attempt bookkeeping, identity-checked cleanup, completion signalling and live attempt guard inside native request scope and before durable store.
- [x] Run focused existing H277/H513/H485 action/task/smart/native regressions and independent coordinator integration tests.
- [x] Review lifecycle and freeze source hashes; refresh Graft and record truthful evidence. No equivalence promotion.

## Task 2 — notification ordering for the exact pending task

Owned next: coordinator `agents/core/autonomy/worker.py` plus focused actual delivery-broker tests.
Consumes Task 1 `wait_for_review`; produces notification hold/release after trusted bounded guardian review.

- [x] Derive eligible smart terminal wait duration from live trusted judge configuration; capture persisted digest before awaiting.
- [x] Revalidate pending leader, revision, owner decision and notifier registration before release. Refresh the card from queue rather than sending pre-await payload bytes.
- [ ] Native APPROVE suppresses obsolete approval push; ESCALATE/error/capacity/timeout resumes manual handling. DENY is coordinated with Task 3 same-turn feedback, while the durable owner decision remains available.
- [x] Prove notification ordering, edits, owner decisions, revoked consent and unrelated pending approvals with actual worker/queue/broker tests.

## Task 3 — same-turn ToolRPC verdict and sealed operation execution

Owned next: coordinator shared contracts `agents/core/tool_rpc.py`, `agents/core/autonomy_coordinator.py`, `agents/core/agent_runtime.py`, `agents/core/approval_outcomes.py`; split implementation only after contract review.

- [ ] Add server-owned async post-intake review seam for terminal_run; model arguments cannot select callbacks, timeout or authority.
- [ ] Return bounded DENY feedback in the same invocation, including existing birth-checked session breaker; preserve feedback until the answer is durably persisted.
- [ ] Wait/execute named APPROVE task through existing worker claims, signed one-operation receipt, kernel and actual handler. Never report command success merely because it was approved or queued.
- [ ] Prove two successive exact operations, normal/streaming loop behavior, cancellation/expiry/edit/revocation, and no duplicate execution or receipt reuse.
- [ ] Extend shell/script entry points only through their actual governed intake and hardline/taint/irreversibility floors.

## Milestone verification and records

- [x] Isolated mutation checks for the newly changed authority/lifecycle boundaries.
- [x] Serial full backend suite at the integrated milestone; frontend/mobile only when touched. Separate reused prior test evidence from newly run checks.
- [x] Refresh only affected assessment evidence, preserve partial verdicts until whole contracts are proved, regenerate status/count artifacts and run record/doc gates.
- [ ] Exact staged secret scan, local commit and clean checkout. No publication.

## Execution ledger

Initial ruling: stage the shared waiting lifecycle before notification and ToolRPC integration. Those paths depend on an exact bounded attempt handle; polling the queue or creating an independent judge would violate the existing cancellation/capacity boundary. Tasks 2/3 remain required.

Checkpoint: Task 1 and notification ordering are verified locally with 35 new cases, 1022 focused cases, nine killed isolated faults and the complete backend (21637 passed, 34 skipped, one xfailed). Independent review findings for expired cards and removed notifiers were reproduced red and fixed. Task 3, coordinated DENY notification handling, broader producers/native/live acceptance remain required. Source/test/harness freeze matches after full suite. Base d5e95763; no publication or activation.
