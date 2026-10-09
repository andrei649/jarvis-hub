# H487 connected owner consent and terminal runtime

Generated: 2026-10-03, Europe/Bucharest. Goal: complete local parity with all
697 accepted pinned Hermes capabilities. Base/head at task start:
01191f70389208f20955a0e9729e8bfc7f2412c4. Working checkout:
`/Users/andrei649/Projects/nerva-pr-worktrees/consent`. Integration checkout retained its frozen baseline; the complete rerun passed
on 2026-10-04. No publication or activation.

This implements the existing owner/queue plan as one connected terminal path.
Terminal-only delivery cannot establish H487 equivalence. Telegram and all
other accepted producers remain required. No change to ordinary once/edit/
reject/defer, Smart DENY, B7 kernel floors, transport policy or hardline rules.

## Shared contracts and single writers

Root owns `consent_types.py`, worker, coordinator, target snapshots, orchestrator
wiring, owner routes/HUD, integration tests, records and documentation.
Implementer A (Sol High) owns queue, consent_sources, consent_ledger, optional
consent_tasks leaf, and new queue/witness tests. Implementer B (Sol High) owns
consent_execution, consent_dispatch, execution runner, local/SSH transports,
sandbox and new physical scope tests. Neither delegates or commits.

Queue constructor appends `consent_categories=()` and
`consent_head_anchor=None`. The latter is mandatory for usable reusable consent;
absent/unavailable signer or anchor preserves ordinary asks. Root supplies the
existing terminal category catalog and a separate consent head anchor. The
ledger shares the queue SQLite connection and transaction.

Root calls `bind_consent_resolver(resolve)` after real producer registration.
`resolve(task, captured_source_dict)` returns a `ConsentDescriptor` or None
from trusted current producer/origin/policy/target configuration, never model
authority. Source capture v2 signs that descriptor. Existing v1 evidence cannot
be silently upgraded into a grant. Keep the old read-only source wrapper and
add a transaction-safe current validator. Source validation for an approved or
running consent task must verify original immutable intent and private proof,
not insist that it remains pending or trust a reconstructed caller snapshot.

Queue APIs:

- `pending_consent_offer(task_id) -> ConsentOffer | None`
- `decide_reusable_consent(task_id, revision, *, choice, actor, reason=None)
  -> ConsentDecisionResult | None`
- `approve_with_current_consent(task_id) -> bool`
- `consent_task_marker(task_id) -> bool` classifies even a corrupt proof.
- `claim_consent(task_id, *, execution_id, live_check) -> ConsentClaim | None`
- `verify_consent_execution(task_id, claim, *, live_check) -> bool`
- `consent_dispatch_current(task_id, claim, *, live_check) -> bool`

Owner choices are session/always/deny. Actor is server-created after actual
authentication; its current callback is checked in the queue transaction.
Telegram actors additionally match the exact source principal. One atomic
decision grants/rejects the exact current pending group (at most 64); mixed,
stale, expired, edited or unauthenticated members fail all-or-none. Each task
retains its own B7 receipt. Genuine owner choices have distinct consent markers
and authentic human metadata. Future reuse has decided_by=consent and no
human_decision or acceptance preference. Generic transitions/claim cannot
manufacture or downgrade consent authority.

Ledger witnesses bind category, scope and decision ID. Regrant after revoke
cannot resurrect an already staged task; unrelated grant/head advancement
does not invalidate other current grants. Private task proofs bind captured
source hash, birth, immutable intent and exact witness. Claims bind actual B7
execution ID and queue instance/nonce. A spent dispatch cannot be retried under
the same proof. Missing/corrupt proof never becomes ordinary approval.

Physical APIs in `consent_execution.py`: `_worker_scope(queue, claim,
live_check, *, dispatch_check)`, `consent_current(task_id)`,
`consent_dispatch(task_id)`, `consent_scope_present()`. Verification calls the
queue APIs above. Scope lifetime and original worker task are independently
checked. Enforce mode retains its own consumed execution permit.

Runner appends `consent_approval_check` and `consent_kernel_check` constructor
callbacks. A separate `ConsentDispatchScope` binds exact handler asyncio task,
transport instance/backend, target, argv, cwd, timeout and live request check.
Adjacent physical gates on local/SSH/Docker refuse copied/closed/stale scopes,
changed requests, revoked grants and host fallback. Consent and owner-once
authority cannot be combined. No transport launch for passive metadata.

## Tests, dependencies and rollback

Baseline 736 focused tests passed on unchanged base. Owner route regression
first fails 404 instead of required authenticated 401; subsequent test cases
must exercise actual queue/producer/worker behavior, not just mocks. Queue
tests cover exact followers, races, scope downgrade, category AND, reopen,
revocation/regrant, corrupted source/head/proof and own B7 execution bindings.
Physical tests cover real gate callsites with mocked effect only, original
task/transport/one-use invariants and missing proof in mediation off/enforce.
Root then runs connected producer-owner-future-task-dispatch tests, ordinary
owner/queue/worker regressions, route/mobile/frontend gates and scoped scans.
Run expensive full suites once at frozen integrated milestones, serially.
Rebuild/check Graft after changed source. No live/device/cloud parity claim.

Root coordinator edits change trusted callback hashes: implementer tests use
standalone trusted resolver fixtures; real coordinator tests run after source
stabilizes. Every coordinator change also requires refreshing the literal AST
binding inventory and running its entire test module. Root reviews both diffs
before integration. Rollback is this localized source/test/doc diff; never
adopt previous grants after external anchor/database mismatch.

Next action at start: run RED/GREEN queue and physical implementations concurrently,
while root integrates the authenticated owner route and worker/runtime path.

## Current checkpoint — 2026-10-04

Base/head remains01191f70; changed source/test paths and exact hash snapshots are
in `docs/hermes/evidence/h487-connected-terminal-progress-2026-10-04.json`.
Queue/physical/root tasks are connected and tested; no live effects were run.
The separate baseline full-suite record does not cover this runtime. Root source
review and133 collateral test modules preserve42 existing capability verdicts;
H487 stays partial and no new equivalent credit is added. Next: current-runtime
full guarded suite completed with six collateral failures; auth/API snapshots
and the unconfigured queue double are corrected with52 focused passes. Scoped
Ruff/Bandit/gitleaks passed. Preserve locally, integrate real Telegram reusable
callbacks next, then rerun the full suite at that frozen milestone. Rollback remains the
localized source/test/doc diff, keeping task/chat history and external anchors.
