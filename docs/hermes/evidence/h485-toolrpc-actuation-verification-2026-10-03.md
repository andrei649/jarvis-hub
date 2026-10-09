# H485 same-invocation terminal review and worker execution

Base/initial HEAD: `08cb4430793eb3b74ec38bc1a0142d7c66bf760b`.
Branch: `codex/h277-provider-discovery-20261002`. Generated 2026-10-03.
Local only; no publication, paid provider calls, deployment or activation.

**Execution Plan:**

The registrar owns an async continuation after governed intake. Terminal review
joins the existing exact task/revision attempt and re-reads the durable verdict.
An APPROVE uses a named selector in the existing worker pipeline; retry/tier,
halt/hold, kernel, target and signed receipt checks remain. A concurrent scheduler
claim is observed rather than run again. Successful DONE results also require a
worker-signed proof binding birth, operation, original approval, kernel evidence
and exact result. A queue transition with a success-shaped dictionary is insufficient.

DENY returns constant sanitized feedback without a pending-approval footer.
Authenticated session tallies stop further gated operations at the configured
breaker, including a fourth call in the same provider batch. The next model
request receives no tool offer. Feedback revisions are acknowledged only after
a successful durable answer and exact denial facts surviving result budgeting
in the actual model request. Truncated feedback remains for a later turn.

**Files Modified:**

| Path | Rationale |
|---|---|
| `agents/core/tool_rpc.py` | Registrar-only review continuation, detached args, cancellation and registration checks. |
| `agents/core/autonomy/queue.py` | Named SQL selection, current-origin observations/CAS acknowledgment and signed completion validation. |
| `agents/core/autonomy/worker.py` | Named tasks use the ordinary claim/execution pipeline; smart successful results gain completion proof. |
| `agents/core/autonomy/terminal_review.py` | Exact native review, sealed execution, scheduler observation and bounded truthful results. |
| `agents/core/autonomy_coordinator.py` | Wire the actual terminal registrar to this continuation. |
| `agents/core/approval_outcomes.py` | Bounded context-local revisions and model-visible feedback confirmation. |
| `agents/core/agent_runtime.py` | Session breaker in serial gated calls and withdrawal of the model's tool offer. |
| `agents/core/orchestrator.py` | Acknowledge delivered current-turn observations after successful answer persistence. |
| `agents/core/orchestrator_bindings.py` | Refresh only the 14 existing coordinator callsite positions after the 12-line integration insertion. |
| `tests/test_h485_named_worker_execution.py` | Real SQLite selector/claim races, retry/tier, halt/hold and mediation. |
| `tests/test_h485_same_turn_queue_feedback.py` | Exact turn/session/principal/birth and acknowledgment guards. |
| `tests/test_h485_toolrpc_review_seam.py` | Callback registration, detached arguments, collector ordering and cancellation. |
| `tests/test_h485_smart_execution_completion.py` | Missing/forged/tampered completion and original approval proofs. |
| `tests/test_h485_toolrpc_actuation_integration.py` | Actual coordinator/HTTP/queue/kernel/worker and normal/streaming chat with synthetic command transport. |
| `tests/test_h277_smart_terminal_integration.py` | Preserve explicit queued approval inspection fixtures; synchronous tests rewire the actual continuation. |
| `docs/hermes/h485-toolrpc-actuation-plan-2026-10-03.md` | Contracts, ownership, verification and rollback. |
| `docs/hermes/h485-synchronous-review-plan-2026-10-03.md` | Reconcile the four delivered Task 3 items with remaining producer and owner-context work. |
| `docs/hermes/evidence/h485-toolrpc-actuation-mutations-2026-10-03.{py,json}` | Isolated faults and exact frozen hashes. |
| `docs/hermes/assessment.json`, `HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md` | Re-read affected parent-current claims; preserve verdicts. |
| `project-status.json`, `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md` | Regenerate backend collected count; frontend/mobile counts reused. |
| `BACKLOG.md` | Record delivered terminal slice and outstanding H277/H485 scope. |

**Verification Results:**

- Red-first selector, callback and completion tests exposed the missing interfaces.
  Actual native integration first failed for immediate approval-required instead
  of same-invocation approval/refusal. Review found synthetic DONE could falsely
  report execution; signed completion proof closes that reporting gap.
- Review also found premature acknowledgment when budget truncation omits denial
  facts. Two normal/streaming regressions reproduced the loss and now pass.
- Actual terminal integration: **23 passed**, including two successive real-kernel
  operations, scheduler claim, no transport for fake DONE, cancellation, revocation,
  owner reject, registration/turn expiry, failed transport and both chat modes.
- Broader 131-module focused union: **3,293 passed / one skipped**, one existing
  Starlette deprecation warning, 79.84 seconds, exit zero. JUnit/log:
  `/tmp/nerva-h485-actuation-focused-20261003.{xml,log}`.
- Final compatibility correction preserves every old positional registration
  parameter by appending the optional review argument. A regression first failed
  at registration; after correcting its initially invalid synthetic class label,
  the current ToolRPC/runtime/classification/native union passes **101 cases**.
  This signature-only correction follows the broader focused run; that earlier
  run is not described as a final byte freeze. The isolated restored baseline is
  now **66 new cases**, all passing with current source hashes.
- [Isolated fault campaign](h485-toolrpc-actuation-mutations-2026-10-03.json): nine
  faults. Initial pass killed eight; skipping completion-signature verification
  survived, exposing a missing direct signature corruption case. Added that
  regression; final campaign kills all nine with no survivor or invalid case.
  Live source is never mutated. Final freeze restoration is recorded in the JSON.
- Sol High implementers owned disjoint worker/queue and ToolRPC files. Read-only
  review and collateral claim re-reading were also Sol High. No subagent delegation.
- Generated backend collection: **21,738**. Frontend/mobile **1,884/142** are
  reused counts, not new executions. Record/doc gates passed **228 cases** at the
  earlier checkpoint. Bandit unchanged baseline: zero findings/errors. Graft was
  rebuilt and checked after the signature and binding-inventory corrections.
- The first full backend run was deliberately interrupted for the positional
  compatibility correction: **3,709 passed / four skipped**, exit two. It is not
  full-suite evidence.
- The subsequent complete backend run finished with **21,701 passed / two failed /
  34 skipped / one xfailed**, 49 warnings, 1,128.22 seconds, exit one. The exact
  callsite inventory retained 14 coordinator positions from before the 12-line
  insertion. The invocation also mistakenly cleared pytest.ini addopts, disabling
  its socket guard and timeout backstop. Both failures reproduced in a focused
  run. Updating only those 14 inventory positions and restoring the configured
  pytest guards yields **119 passed** across the binding contract, socket guard
  and all 66 new cases. No socket-guard code or assertion was weakened.
  That failed run is retained as diagnostic evidence.
- The final complete guarded backend passes **21,703 tests / 34 skipped / one
  existing xfailed**, 67 warnings, 1,126.85 seconds, exit zero. The configured
  socket and 30-second per-test timeout protections are retained. JUnit/log:
  `/tmp/nerva-h485-actuation-full-backend-guarded-20261003.{xml,log}`.
  The JUnit count matches **21,738** tracked cases; all 18 frozen source/test/
  configuration hashes match after terminal completion. This supersedes the
  failed full invocation, without hiding it. Corrected record/doc gates pass
  228 cases; final delivery will recheck them after this report refresh and scan
  the exact staged bytes. Local commit and clean-checkout confirmation follow
  those checks; no GitHub CI or live-service acceptance is claimed.

**Remaining Risks:**

H277/H485 remain partial. Broader shell producers and nested/unattended policy,
context-aware DENY notifications, native mobile/configuration and live model/channel/
device acceptance remain required. Action approvals and other task kinds remain
advisory; owner-edited/reblocked terminal rows remain manual. Smart defaults stay
off. A mediated approval expiring during a long execution can conservatively
make its completed result unverified. Cancellation after physical execution
begins cannot undo the operation; existing worker state/reaper remains authoritative.
No Python coverage threshold is configured; case counts are not coverage percentages.
The full 697-row objective is unchanged; no new equivalence credit is claimed.
The pinned Hermes smart gate permits an interactive owner to override DENY once,
with session/permanent persistence disabled; unattended DENY returns immediately.
The next notification slice must preserve that distinction rather than suppress
every smart-denied card. This source reread grants no additional parity credit.
Physical-launcher inspection also confirms that current Nerva model code uses
isolated Docker/WASM, with no general writable project mount. Pinned Hermes
omits whole-script approval for comparable isolated containers; adding that
prompt is not a demonstrated current-backend gap. Nested terminal calls and
scheduled terminal origins still need explicit behavioral evidence. Telegram
owner-group identity with an empty sender allowlist needs a separate bounded
security correction before synchronous owner override is extended.
