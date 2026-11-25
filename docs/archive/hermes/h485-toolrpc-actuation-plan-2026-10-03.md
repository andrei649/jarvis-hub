# H485 same-invocation terminal review and actuation plan

**Goal:** Finish Task 3 of the synchronous-review plan: return the exact terminal verdict to its invoking model and execute an approved operation through the existing worker.

**Freshness:** Generated 2026-10-03; base/initial HEAD `08cb4430793eb3b74ec38bc1a0142d7c66bf760b`; local `codex/h277-provider-discovery-20261002`. No push, merge, deployment, paid calls or activation.

**Architecture:** Registration owns an async `gated_review(actor, args, task_id)` callback after synchronous intake. The terminal registrar re-reads the exact persisted tuple and joins its scheduled judgement, then consumes the persisted verdict. Named task selection feeds the existing worker claim/execute/receipt pipeline. Callback completion and approval alone never imply command success.

**Spec:** `h485-synchronous-review-plan-2026-10-03.md` Task 3; pinned Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. H277/H485 and the full 697-row objective remain open until all accepted requirements have evidence.

## Contracts, ownership and rollback

- Sol High worker owner: `agents/core/autonomy/queue.py`, `agents/core/autonomy/worker.py`, new `tests/test_h485_named_worker_execution.py`. Add `runnable(limit=10,max_tier=None,*,task_id:int|None=None)` and `tick(limit=10,max_tier=None,*,task_id:int|None=None)`. Omitted selector preserves batch behavior; supplied selector must be a strict positive integer and retain status, retry and tier predicates. No direct execution API.
- Sol High ToolRPC owner: `agents/core/tool_rpc.py`, new `tests/test_h485_toolrpc_review_seam.py`. Add registrar-only optional async `gated_review(actor:str,args:dict,task_id:int)->dict|None`, requiring custom gated intake and trusted execution. Await it before recording manual pending approval. None/error retains manual fallback; cancellation propagates. Callback arguments cannot be selected by model fields. Handler execution stays forbidden at intake.
- Coordinator owns `agents/core/autonomy_coordinator.py`, `agents/core/agent_runtime.py`, `agents/core/approval_outcomes.py` and real integration tests. Queue-owner-only additional exact chat projection changes require an explicit amended contract before edits.
- Contract amendment: coordinator owns new `agents/core/autonomy/terminal_review.py` and durable-answer integration in `agents/core/orchestrator.py`. Queue owner adds `chat_invocation_outcome(context,task_id)->dict|None` for only the authenticated originating turn, and permits matching current-origin revisions in existing explicit acknowledgment. Context-local bounded observed items are acknowledged only after successful durable answer persistence, alongside existing prior-turn observations.
- Before an approved execution, revalidate task birth, kind, actor, exact payload, current registration/turn, smart policy and sealed receipt. Then `await worker.tick(limit=1,task_id=id)` and re-read persisted outcome. Other approved tasks must remain unexecuted. A scheduler race loses gracefully and never reruns a claimed operation.
- DENY returns constant sanitized feedback and existing authenticated session tally; it must not create a pending-approval footer. Feedback stays unacknowledged until durable answer persistence. ESCALATE/off/unavailable/error retains manual handling.
- Owner edits, expiry, consent revocation, e-stop, taint, kernel/target/hardline floors and retry budget remain authoritative. Keep shipped smart defaults off.
- Rollback: revert one coherent local integration unit; no schema migration, dependency change or alternate executor is planned.

## Review focus and tests

1. A named operation cannot drain an older unrelated approved task; retry/tier/hold/halt constraints still apply.
2. Two SQLite connections or overlapping ticks can race a claim; exactly one transport execution occurs and the loser does not raise a stale transition error.
3. Re-registration, argument changes, caller cancellation and revoked consent while reviewing cannot produce stale actuation.
4. Completed/refused/failed/retrying outcomes must remain distinct; never turn a queued approval into a successful command result.
5. Same-turn DENY and its session breaker must reach both normal and streaming model loops, without raw policy/judge text and without premature observation acknowledgment.

## Tasks

- [x] Write/run red-first named selection, retry/tier filtering, halt/hold, race and existing receipt-path tests; implement selection using the unchanged execution pipeline.
- [x] Write/run red-first ToolRPC callback registration, ordering, exception/cancellation and pending collector tests; implement the registrar-only seam.
- [x] Integrate native mocked HTTP judge with actual coordinator, signed queue, kernel and synthetic command transport: two successive APPROVE commands, DENY/manual fallback, stale edits, consent revocation and scheduler races.
- [x] Integrate sanitized same-turn denial/session breaker and normal/streaming loop acceptance; retain existing durable acknowledgment behavior.
- [x] Review, meaningful focused regressions and isolated mutation faults, then serial full backend at the integrated milestone. Refresh Graft after source edits.
- [x] Update affected records truthfully, scan the exact staged set, commit locally, verify commit bytes and clean checkout. No equivalence promotion based on foundation seams alone. Closure is confirmed by the local commit/manifest check and clean status after this delivery transaction.

**Earlier checkpoint:** 66 new cases, 3,293 earlier focused regressions, 101 final compatibility checks and nine isolated faults pass. Independent review's synthetic-DONE and truncated-feedback findings were corrected and reproduced. Completion proof lives in existing task.result JSON; no schema migration/cache was added. Root re-read H277/H485; two Sol High reviewers re-read 42 other previously-current affected rows, preserving verdicts and correcting outdated completion/project-context prose. The first full backend was interrupted after 3,709 passing cases to preserve the public ToolRPC positional registration signature; the corrected full run and final local delivery were pending then.

**Full-suite correction:** The completed rerun returned 21,701 passed, two failed, 34 skipped and one xfailed. The failures reproduced: 14 existing binding callsites needed their +12-line position refresh, and clearing pytest.ini addopts had disabled its socket guard. With those positions corrected and the repository guards restored, the binding/socket/new-case union passes all 119 cases. No guard was weakened. A complete guarded rerun remains required.

**Final guarded backend:** 21,703 passed, 34 skipped, one existing xfailed, 67 warnings, 1,126.85 seconds, exit zero. The 21,738-case count guard and all 18 frozen hashes match after completion. Configured socket/timeout protections stayed active; Graft is fresh after the binding correction.

**Delivery:** Final record/doc gates, exact staged secret scan, local commit/manifest match and clean checkout complete this terminal slice; their terminal results are required before claiming delivery. No publication or activation.

**Next action after verified local delivery:** Correct Telegram owner-group identity, then implement context-bound DENY/once-only owner handling. Current isolated Docker/WASM code follows the pinned isolated-container script exception; nested terminal and scheduled-origin behavior still require explicit tests.
