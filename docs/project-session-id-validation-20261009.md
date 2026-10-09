# Exact shared session ID validation

- Generated: 2026-10-09 UTC.
- Base: 19128484c4c2aabd893a0831151152481323434f.
- Tested source / integration HEAD: 30e0e53d4c65a435317048f0ee61fb05acf2d5a1.
- Branch/worktree: codex/session-id-exact-validation-20261009,
  /workspace/jarvis-hub-session-id-validation.
- Goal: make the shared session validator enforce its complete-input contract.
- Delivery: local; PR #1247 is the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-session-id-exact-validation.md).

## Behavior and compatibility

Python's dollar anchor permits a match before a final LF. The shared validator
therefore accepted an ID such as session_A followed by a newline, despite its
documented ASCII-only identifier alphabet. This could select a distinct session
or reach a newline-named file; it is not evidence of traversal outside the data
directory. Use fullmatch in is_valid_session_id so the complete original value
must satisfy the existing alphabet and 1–128 character length checks.

No ID is stripped or coerced into a different ID. Ordinary valid identifiers
keep their exact value. Existing callers inherit the correction: persistence,
session routes, typed chat/stream and selected-image request validation, session
continuation, session-file discovery and channel key validation. Existing invalid
ID errors retain their route-specific response shape and status. Preexisting
newline-named files are neither renamed nor deleted by this change; their names
no longer qualify as valid session identifiers.

Only the session helper's matching operation changes in production. KG identifier
validation, channel metadata normalization, authentication, schemas, routes and
session generation remain unchanged. The mobile JavaScript patterns already
reject terminal LF, confirmed in Node; Python's anchor exception does not apply
there. No new client control or dependency is needed. Existing device/live-Hub
acceptance remains separate.

## Verification

The boundary module first ran with **9 failures and 27 passes** before the
production fix (36 cases, 1.618 seconds). The failures cover the ordinary and
length-boundary terminal LF, persistence load/save/delete, resume, chat, stream
and continuation. Persistence traps directory lookup rather than creating a
literal newline-named file, so these regressions are portable to Windows.

The writer's seven-module focused suite then passed **178/178**, zero failures,
errors or skips (5.566 seconds), including all 36 boundary cases. Root's disjoint
15-module integration suite passed **273/273**, zero failures, errors or skips
(7.310 seconds): channel routing, native session transitions, session persistence/
refresh, purge/retention, archived chats, KG collateral and route/OpenAPI/lifespan
guards. Together these are **451 distinct passing cases**.

Ruff passes both changed Python files. Root's text and AST comparison confirms
the only production edit is the session helper's match-to-fullmatch operation;
all other module code is identical. Independent review reports no Critical or
Important finding at the frozen hashes below.

The full backend suite at **30e0e53d4c65a435317048f0ee61fb05acf2d5a1** passed:
**21,277 passed, 37 skipped, zero failures or errors, 21,314 total** in
**286.005 seconds**, exit 0. It ran through the subreaper with four workers,
loadfile distribution and a 90-second test timeout. The 37 skipped test IDs are
identical to the preceding full model-generation-lease run; no live test was
enabled. No production or test file changed after source freeze.

Canonical collection records **21,314 backend cases** (+14), unchanged
frontend/native 2,009 and mobile 306 inventories, 555 routes and 18 agents.
Hermes and generated-status checks pass. Client source is unchanged and no
frontend/mobile suite is rerun for this backend fix; prior client evidence
retains its original source and scope. No live model/provider or device is used.

Frozen SHA-256 values:
- agents/core/validation.py: dd8be708d2dc45c2293e7c2683223ded602bbf5e0e137d071d38138c86ceb094
- tests/test_session_traversal.py: bd4eb9e1ecdfaa3e5e8243fb02621c0ff439265390b13ca62fd81f26e2641b52

Scratch evidence: session-id-validation-{red,focused,integration}.{xml,log},
session-id-validation-{design-review,code-review}.md,
session-id-validation-pin-inventory.{json,md},
session-id-validation-ast-review.json, session-id-validation-status-sync.log and
session-id-validation-backend-final.{xml,log}. The full run's executed count
matches the tracked backend inventory.

## Review and evidence freshness

auth_audit (gpt-6-sol/high) owns the helper and boundary tests;
mobile_session_transport (gpt-6-sol/high) independently reviews the contract and
frozen code; wall_contracts (gpt-6-luna/medium) inventories existing evidence.
Root owns integration, documentation, status and git. No nested delegation.

There are no assessment evidence pins for either changed Python file. No Hermes
row needs a hash refresh or capability promotion. AUD-5 records this additional
edge case; its original traversal protection is retained. Client parity notes
describe the common server correction without claiming new device acceptance.
