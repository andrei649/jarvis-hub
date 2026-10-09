# H487 reusable consent and bounded human waiting

Goal: complete all 697 accepted Hermes capabilities locally, including H487's
real owner decision, identical pending followers and future category consent.
This design advances that goal; a storage primitive alone is not H487 completion.
Generated: 2026-10-03. Base/head: `7b6c08c5558f44a69af6743435face28650b9375`.
Standing owner authorization permits autonomous local design/implementation and
at most two Sol High implementers. No push, merge, deployment or activation.

## Reference and architectural choice

Pinned Hermes `59b2aeef6c7a`: `tools/approval.py::_persist_choice` grants each
detected pattern key for session/always; content-level Tirith findings cap at
session. `tools/approval_gateway_wait.py` shares identical pending requests'
session/always/deny outcomes, including denial reason, but never their once.
`tools/approval_human_wait.py` clamps a union window to timeout + 60 seconds.

Do not repurpose the process-boot PermissionLedger: its identity, resources and
default-off compatibility posture do not establish chat/tool consent. Do not
make notification grouping a grant or clone a mediated task receipt. Choose an
adjacent signed consent ledger, then integrate verified enqueue provenance,
owner choices and independently governed execution. Exact-request-only standing
consent would miss Hermes category semantics and is not the final design.

The first storage step accepts only server-defined category keys; it cannot
classify commands or authorize execution. Principal, surface, stable tool
registration key, policy revision and target scope are bound. Session choices
also bind session id/instance. Always survives reopening with the same signer,
stable registration and policy; a process-random epoch is not its identity.
Future producer integration must derive registration keys from reviewed server
registrations, never model payload. No permanent grant for content-only findings.

## Ledger contract and boundaries

`consent_ledger.py` uses a caller-owned SQLite connection and existing
`DetachedHMACSigner`, with distinct purpose/version and private namespace.
Frozen `ConsentContext(principal, surface, session_id, session_instance,
registration_key, policy_revision, target_scope)` binds lookup/grant identity.
`ConsentCategory(key, permanent=True)` is a server-owned risk category.
`ConsentLedger(connection, signer, *, categories)` requires an explicit trusted
category catalog; request categories must match its definitions, including the
permanent flag. Missing catalog grants nothing. Decision origins are the exact
internal labels `owner` and `admin`, assigned only after owner authentication;
the ledger itself cannot authenticate an external caller.
`ConsentLedger.initialize()` creates only its own tables.
`grant(context, categories, *, choice, decision_id, decided_by)` returns a bool;
only session/always and a nonempty authenticated human decision may persist.
Machine deciders, malformed categories/context, missing signer refuse. An always
choice stores nonpermanent categories with session scope. All keys must be
covered for `lookup(context, categories)` to return true. Empty categories grant
nothing. `revoke(context)` removes matching authority across that context's
session and always scope, without affecting other principals/targets.

Persist used decision identities: an old decision id cannot widen its context,
choice or categories, or recreate revoked authority on replay. HMAC verifies row
integrity, not rollback of the entire database; integration must not claim a
rollback-resistant revocation anchor until that is implemented and tested.

Use savepoints to preserve a caller's surrounding transaction and all-or-nothing
multi-category decisions. Store signed canonical bytes; verify purpose, namespace,
identity and exact category against every lookup. Tampering, invalid or unreadable
state never becomes approval. This is owner-decision evidence distinct from B7;
it neither transitions tasks nor skips kernel/target/e-stop/taint/budget checks.
Queue integration must use the same transaction for grants and row decisions,
and fresh dispatch checks must make revocation effective before physical effects.

## Human-wait accounting

Existing CompanyMode union windows are durable and limited to proven real queue
asks. Preserve raw wall time, no double counting, no retrospective window creation,
no renewal by a follower, and no weakening of the absolute goal deadline.
For a newly created epoch, freeze its ceiling from initial verified sources:
largest `(approval_deadline_at - epoch.start) + 60` when explicit; otherwise
360 seconds. Actual source credit still ends at its actual deadline or first
human decision. Later sources cannot increase the frozen epoch ceiling.
Persist the initial source sequence ids and validate the ceiling formula against
that fixed set, including on read-only and follower attachment paths. A fabricated
larger ceiling is invalid even if its metadata checksum was recomputed. The
existing checksum is not HMAC protection against a privileged whole-store rewrite.
Legacy epochs without a ceiling remain capped at 360; reopening cannot infer a
larger ceiling from mutable task state. Finite numeric validated fields only;
corrupt metadata gives zero credit. Read-only and settlement paths share bounds.

## Remaining end-to-end integration (required, not excluded)

Capture verified model/terminal/browser producer identity privately at enqueue;
offer explicit once/session/always/deny only for reusable-eligible requests.
Smart DENY retains once/reject. Apply exact immutable follower decisions under
queue CAS with their own B7 receipts; once promotes followers, timeout grants
nothing. Deliver choices and bounded denial reasons through owner HTTP/HUD and
authorized Telegram, plus other accepted channels. Future matching categories
reuse only current consent and current governance. Revoke/update identity/policy
and target checks at the actual effect boundary. Reassess H487 only after these
flows and accepted broader producers are tested, including live-surface limits.

## Implementation plan and verification

1. Sol High writer A owns only `agents/core/autonomy/consent_ledger.py` and
   `tests/test_h487_consent_ledger.py`. TDD persistence/reopening, category AND,
   principal/target/policy/registration/session isolation, content downgrade,
   tamper/missing signer, revocation and caller transaction rollback.
2. Sol High writer B owns only `agents/core/autonomy/work_runs.py`,
   `tests/test_h487_human_wait_budget.py` and
   `tests/test_h487_human_wait_integration.py`. TDD long deadline (>360) at real
   ledger/runtime boundary; first decision/expiry cutoffs, frozen union, legacy
   reopening, malformed metadata, read-only reporting and goal deadline.
3. Coordinator reviews both diffs and integration, runs guarded relevant unions
   and Ruff. Fix failures before recording results; no new equivalent verdict
   from primitive-only work. Then implement producer/queue/owner/dispatch/UI steps
   with explicit shared contracts and focused RED/GREEN integration proofs.
4. Rebuild/check Graft after source changes. Expensive full suite runs serially
   only at integrated milestones. Existing 7b6 full-suite receipt remains evidence
   for its own frozen bytes, not changed source.

Rollback: revert this coherent consent increment; leave ordinary queue/task/chat
history intact. Its new tables are inert without integration. Human-wait metadata
has explicit legacy interpretation. No provider calls or service restart required
for these offline tests. Plan self-review: storage and wait interfaces are disjoint;
unimplemented producer/owner/dispatch/UI tasks remain explicit and cannot support
a completion claim. Next action: RED tests, then localized implementation.
