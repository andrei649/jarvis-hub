# H277 enforcing smart terminal approvals

Goal: implement the pinned Hermes guardian's actual one-operation command
approval behavior in Nerva's governed terminal path. Generated 2026-10-03;
base and preceding committed head `326d21ed`, branch
`codex/h277-provider-discovery-20261002`. This document describes the uncommitted
successor smart-terminal increment. Streaming temperature recovery is committed
and separately verified at that base.

Reference: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`tools/approval_smart.py:_smart_approve` and `tools/approval.py:_smart_gate`.
Hermes asks the named approval model for APPROVE, DENY or ESCALATE. Operator
policy is trusted system text; proposed commands are untrusted. APPROVE covers
one operation, DENY cannot create persistent permission and an interactive
owner may override it once. Empty, malformed, failed or uncertain results
escalate. Hardline and owner deny rules precede the guardian.

Observed gap: Nerva's separate approval model only produces advisory risk
scores. Both action cards and Decision Inbox tasks ignore those scores for
authorization. ToolRPC terminal commands use the task queue, not the standalone
action-card queue. Updating the latter alone would not deliver this behavior.

Design constraints:

- Keep advisory mode and all current defaults. Introduce explicit trusted
  owner opt-in for smart terminal review and optional trusted operator policy.
  Action arguments, model text and persisted advisory annotations cannot enable
  that mode or become policy.
- Separate strict tri-state verdict parsing from risk-score parsing. Reuse the
  existing named-role transport, independent data consent, timeout, physical
  request checks and configuration revocation checks. Check the smart policy
  revision before dispatch, after generation and at the decision CAS.
- Start with the real terminal ToolRPC task end to end. Full task/action
  automation outside the pinned command/script behavior is separate work;
  human-only goal and permission approval are not silently broadened.
- Bind the verdict to the exact persisted pending task revision. Apply a
  single-operation approval in one SQLite write transaction after rechecking
  pending status, deadline, action digest and applicable mediation evidence.
  Record `smart-approve` and the judge identity; do not forge a human accept/edit
  or populate human decision metadata.
- Persist authenticated machine decision evidence with the existing detached
  signer, including both the reviewed preapproval digest and approved execution
  fingerprint. Terminal execution must verify that evidence and current owner
  opt-in instead of trusting a risk annotation or machine-looking row fields.
  Missing signing authority must escalate, never manufacture authority.
- Keep kernel refusal, target policy, source binding, budgets, e-stop and the
  normal execution permit checks. DENY and ESCALATE retain a decision card;
  an explicit owner accept remains one operation and grants no broad allowlist.
- Preserve default advisory rendering. Expose the actual smart result and
  machine attribution on applicable decision cards, with mobile/HUD parity
  recorded. No automatic activation in this development workspace.

Likely paths: new `agents/core/autonomy/smart_approvals.py`, the existing
approval judge/runner/task adapter, a localized task-queue CAS and signed
verification helper, worker decision side effects, terminal approval check,
focused tests and inspected parity documentation. Keep one writer per file.
Settle helper interfaces and storage ownership before delegating implementation.

Verification: red-first tests for actual terminal enqueue -> review -> durable
approval -> governed execution, DENY/ESCALATE/invalid/failure, trusted operator
policy placement, unchanged advisory mode, owner override, edits and concurrent
owner decisions, expiration, revocation while waiting/generating/cleaning up,
forged or replayed machine evidence, missing signer, kernel refusal and target
policy. Run focused existing H277/H513/task mediation/terminal regressions,
relevant frontend checks if changed, mutation probes for authority checks,
Graft freshness, derived Hermes status and staged secret scan. Full suites run
serially at the completed integration milestone.

Rollback: revert this opt-in smart terminal increment as one coherent local
commit; existing advisory judging remains. No push, merge, deployment, provider
spend, live-provider claim or full H277/parity completion claim.

Implemented paths: `autonomy/smart_approvals.py`, `approval_judge.py`,
`advisory_judgements.py`, `task_approval_judge.py`, `queue.py`, `worker.py`,
`autonomy_coordinator.py`, `environments/execution.py`, Decision Inbox JSX and
tests, environment example and associated architecture/mobile/parity records.

Verification checkpoint: the corrected 137 new backend cases pass, as do 725
focused existing/new kernel, mediation, task, judge, ToolRPC and terminal cases.
Eleven isolated authority mutants are assertion-killed; restored baseline and
copied/live source hashes match. The original mode-off-only revision probe
survived because an independent enabled guard still refused execution; the
final probe covers policy-text drift at the physical request as well. The
refreshed campaign includes the real kernel callback, AUTO-mode and taint gates
and worker forwarding. All 1,884 frontend tests across 207 files, TypeScript and
HUD build pass offline. The existing legacy HUD suite passes 233 tests and its
69.75% line coverage exceeds that suite’s configured 60% threshold. No Python
coverage threshold or instrumentation is configured in the current test runtime;
these test/mutation results do not claim Python line/branch coverage. Final full backend
verification exits zero: 21,509 passed, 34 skipped and one expected failure. See
`evidence/h277-smart-terminal-mutations-2026-10-03.json`.

Review corrections were reproduced red before fixing: preserve the reviewed
agent at target/kernel authorization; reject a machine row changed to unsigned
human accept; permit only unsigned DENY/ESCALATE supersession on a fresh exact
digest. Execution also rechecks request, actor, current owner policy, transport
flags and Docker backend/timeout after an awaited kernel grant.

Limits: opt-in terminal ToolRPC only; action-card scoring stays advisory. The
legacy manually approved Docker path still lacks a `terminal.exec` kernel hop;
this increment adds it only to the new smart path. Owner-edited/reblocked tasks
remain manual. Same-digest prior nonapproval is retained rather than repeatedly
judged after a policy-only change. Static shell detection/comment projection is
bounded and not a complete shell interpreter. Native mobile verdict rendering,
Hermes broader pre-escalation shell/script placement, denial-breaker behavior,
and live local/cloud model acceptance remain open. No development flag is enabled.

Next action: commit this verified local checkpoint after the final staged scan;
then fix the three pre-existing Nous Bandit findings and continue H485 session
denial feedback/observer hooks. Broader same-turn shell/script integration remains
a separate dependency. No remote integration.

Real-kernel correction before checkpoint: an inline actual Action Kernel probe
found that its default irreversible policy returns QUEUE again after the signed
guardian approval. Recording-sandbox tests with injected GRANT did not expose
this. The first full backend run was interrupted for the necessary correction;
its partial pass count is not a complete-suite result.

Add an optional trusted terminal-approval callback at the kernel's policy gate,
threaded explicitly through the existing worker/mediation bridge. It may satisfy
only terminal.exec's ordinary ASK in AUTO mode, after capability/e-stop/budget/
loop gates and before the existing taint escalation. ASK/OFF modes, malformed
or missing proof, other action kinds, and arbitrary injected QUEUE decisions
remain holds. The runner's callback must match its exact Action and re-read the
signed task/current configuration, never read an approval flag from model args.
The final kernel audit includes the approved task identifier and a sealed-approval
reason. Actual-kernel integration covers two distinct operation receipts, e-stop,
ASK/OFF and untrusted-source refusal. Typed terminal intake reauthorizes the exact
toolrpc.terminal_run Action and lets the production bridge consume that exact
handoff once, preserving current model-request and project/session association.
A red-first regression preserves manually approved Docker execution when the
kernel is disabled. The corrected sources are included in the refreshed mutation
manifest. No blanket QUEUE-to-GRANT wrapper.

Additional changed paths: `agents/core/kernel/__init__.py`,
`agents/core/kernel/binding.py`, `tests/test_h277_smart_kernel.py` and the actual
kernel integration tests. Generated project-status counts and their dependent
Markdown now match 21,544 collected backend tests and 1,884 frontend tests; the
unchanged mobile count is reused, not a new mobile-suite claim.

Resource plan: two gpt-6-sol/high implementation agents with one writer per file;
coordinator integrates and verifies shared authority. The queue agent performed
bounded read-only review after its storage changes. Neither agent delegated.
Graft wiring was rebuilt and checked after the final correction: 47,798 nodes
and 2,715 files, in sync. The optional deep semantic layer was not built.


Final inventory/lint correction: the first completed corrected-source backend run
reported 21,508 passed, 34 skipped, one expected failure and one failure in the
exact orchestrator writer-location inventory. The 14 existing coordinator calls
all moved +89 lines; names and columns were unchanged. The isolated gate failed
again before updating those positions. The 148-case corrective inventory/vision
union now passes, as does repository-wide Ruff after four import-only hygiene
fixes in previous H277 vision work. Function/class bodies and mutation selectors
are unchanged. The fresh final backend run exits zero with 21,509 passed, 34 skipped and one
expected failure (1,126.01 seconds); the earlier failed run remains recorded as
failed. All 21 frozen source/test hashes match after this run.


Security scan boundary: Bandit 1.9.4, matching the repository workflow and its
unchanged baseline, scanned agents/scripts with zero scan errors. It reports
three pre-existing findings only in unchanged `agents/core/llm/nous_auth.py`:
B101 at 452 and 584 (asserts) and B105 at 506 (public boolean status). No finding
is on this increment’s changed authority paths. The global Bandit gate therefore
remains red; this report does not describe it as passing. No baseline was
weakened. Exact staged gitleaks scanning is repeated after final records.
