# H485 exact-attempt waiting and notification checkpoint

Base: `d5e957637424faf8e04816b0d4f19cb6971daf51`.
Branch: `codex/h277-provider-discovery-20261002`.
Generated: 2026-10-03. Local only; no publication, provider spend or activation.

**Execution Plan:**

Task 1 of `../h485-synchronous-review-plan-2026-10-03.md` joins the existing
runner's exact persisted task/revision across asyncio loops. An attempt owns a
finite monotonic deadline, thread-safe completion and a distinct shared capacity
reservation. Cancellation invalidates its live request and store guards before
asking the owning loop to stop. Resistant tasks retain capacity until actual
completion; an old callback cannot release a replacement attempt.

Task 2 orders opted-in terminal card delivery after that bounded review, with
fresh pending-leader/deadline/notifier checks and persisted card payloads.
APPROVE removes the obsolete push. ESCALATE, unavailable capacity, error and
timeout retain manual handling. A wait result grants no authority. DENY still
leaves an owner card available until Task 3 integrates same-invocation feedback.

**Files Modified:**

| Path | Rationale |
|---|---|
| `agents/core/autonomy/advisory_judgements.py` | Bounded exact-attempt lifecycle, cross-loop joins, cancellation and capacity ownership. |
| `agents/core/autonomy/task_approval_judge.py` | Typed exact task/revision join and attempt-bound queue CAS; owner cleanup invalidates work. |
| `agents/core/autonomy/worker.py` | Opted-in terminal notification wait; fresh card, deadline and notifier guards. |
| `tests/test_h485_judgement_waiting.py` | Seventeen lifecycle cases, including resistant work, pre-spawn timeout and replacement cleanup. |
| `tests/test_h485_smart_review_waiting_integration.py` | Six actual native HTTP/SQLite cases; no command executes. |
| `tests/test_h485_smart_review_notifications.py` | Twelve actual worker/queue/delivery-broker ordering and fallback cases. |
| `docs/hermes/h485-synchronous-review-plan-2026-10-03.md` | Interfaces, ownership, review focus and still-required ToolRPC integration. |
| `docs/hermes/evidence/h485-synchronous-review-mutations-2026-10-03.py` | Isolated nine-fault campaign; live source is never mutated. |
| `docs/hermes/evidence/h485-synchronous-review-mutations-2026-10-03.json` | Campaign outcomes, source/test hashes and restored baseline. |
| `docs/hermes/evidence/h485-synchronous-review-verification-2026-10-03.md` | This checkpoint and its limitations. |
| `BACKLOG.md` | Record waiting/delivery behavior without completion credit. |
| `docs/hermes/assessment.json` | Reread six parent-current affected rows while retaining verdicts. |
| `HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md` | Regenerated assessment projection. |
| `project-status.json`, `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md` | Regenerated collected backend count; frontend/mobile counts reused. |

**Verification Results:**

- Initial native integration: six missing-interface failures. Initial delivery
  integration: five ordering/stale-card failures and one existing default-off
  behavior pass. Two independent review findings reproduced red: expired cards
  after a wait and consumed delivery retry after notifier removal. Both fixed.
- Seventeen implementer lifecycle cases and eighteen coordinator native/delivery
  cases pass. Thirty-five new cases in total.
- Final frozen 33-module focused union: **1,022 passed**, one existing Starlette
  deprecation warning, exit zero. It includes task/action judging, worker,
  grouping, expiry, mediation, physical consent and speak/Media Director collateral.
  Log/JUnit: `/tmp/nerva-h485-wait-final-focused-20261003.{log,xml}`.
- [Isolated mutation receipt](h485-synchronous-review-mutations-2026-10-03.json):
  **9/9 killed**, no survivor/invalid case, 35-case baseline restored, live source
  hashes unchanged. Proof covers omitted wait, stale/expired card, removed
  notifier, missing timeout/caller invalidation, premature capacity release,
  replacement cleanup and missing no-waiter deadline timer.
- Independent Sol High read-only review found the two corrected notification
  issues and no bounded lifecycle defect. Task 1 implementer is Sol High; root
  owns notification/integration tests and corrections. No agent delegation.
- Repository Ruff and whitespace pass. Bandit 1.9.4 against the unchanged global
  baseline: zero findings or scan errors. Seven frozen source/test/harness hashes
  are in `/tmp/nerva-h485-wait-frozen-hashes-20261003.json`.
- Backend collection is **21,672**. Frontend/mobile counts **1,884/142** are reused,
  not newly executed. Python test counts are not coverage percentages; no Python
  coverage instrumentation/threshold is configured.
- Complete frozen backend: **21,637 passed / 34 skipped / one xfailed**, zero
  failures/errors, exit zero, 1,116.25 seconds, 21,672 collected. The backend
  result-count guard agrees with tracked status. All seven frozen hashes match
  after completion. Log/JUnit:
  `/tmp/nerva-h485-wait-full-backend-20261003.{log,xml}`. Existing deprecation,
  asyncio fixture and blocked-external-socket warnings remain; no live provider
  acceptance is inferred. No attempt-wait/guardian warning was reported.
- Final record/document/count gates: **106 passed** at the frozen checkpoint.
  Five unchanged worker citation relocations were reread and remapped after the
  first restamp was refused; all six affected reviews retain their verdicts.
  Documented equivalence remains **182/697 (26.1%)**: 74 reread equivalents and
  108 inherited audit verdicts. No stale row was promoted without review.
- Graft rebuilt its wiring cache (48,019 nodes); explicit freshness check passes.
  No hooks, instruction-file changes or semantic/provider pass were requested.

**Remaining Risks:**

H277/H485 remain partial. Required Task 3 still includes server-owned synchronous
ToolRPC verdicts, same-turn denial breaker/feedback, named approved-task execution
waiting through existing claims/receipts, normal/streaming integration, broader
shell/script placement, native controls and live model/channel/device acceptance.
Observer context expansion and other lifecycle hooks remain in the full backlog.
The 697-row objective is unchanged; no new equivalence credit is claimed here.

If the hub loop is forcibly closed with resistant work outstanding, its bounded
reservations remain until adapter disposal; no shutdown API was added here.
Invalidated work cannot send/store, but a previously committed decision is never
rolled back by waiter cancellation. A dropped notifier before broker admission
does not consume retry; notifier changes after broker admission retain the broker's
existing ambiguous-delivery handling. Shipped smart defaults remain off.

Next action: complete Task 3's exact terminal post-intake review and sealed
execution contract, then extend the actual shell/script producers and required
native surfaces. Keep local evidence, live acceptance and GitHub CI separate.
