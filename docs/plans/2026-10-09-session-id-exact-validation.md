# Exact shared session ID validation

- Generated: 2026-10-09 UTC.
- Goal: reject a final newline in a session ID at every existing shared-validator
  call site, preserving the documented ASCII alphabet and 1–128 character bound.
- Base / HEAD before edits: 19128484c4c2aabd893a0831151152481323434f.
- Branch/worktree: codex/session-id-exact-validation-20261009,
  /workspace/jarvis-hub-session-id-validation.
- Scope: autonomous local bug fix; no publication or live providers.
- Next action: focused and collateral checks are green at frozen source; finish
  canonical count refresh, then run the serial full backend milestone.

## Contract and scope

The shared validator documents an exact inert identifier, but Python's dollar
anchor can match before a final newline. A value such as session_A followed by
LF currently passes and reaches session selection and persistence. Require the
entire original string to match: no stripping, normalization, type coercion or
fallback. Existing ASCII letters, digits, underscore and hyphen remain valid
at lengths 1 through 128; other whitespace, separators and nonstrings remain
invalid. Change only is_valid_session_id's match operation in production.

Exercise persistence read, write and deletion guards before directory lookup,
and HTTP request validation before downstream session/memory work. Newline IDs
must fail with the existing invalid-ID responses (400 for resume/path routes,
422 for typed request bodies). Valid request and persistence paths must retain
their behavior. Existing malformed legacy files are neither renamed nor deleted;
their names no longer qualify as valid session identifiers.

No new routes, schema, authentication, session generation, channel normalization,
KG-token validation, CLI receipt fields, client UI or dependencies. Do not infer
that other regex languages share Python's anchor semantics. Review client
validation separately before making any cross-client claim.

## Ownership and tests

- auth_audit (gpt-6-sol/high): only agents/core/validation.py and
  tests/test_session_traversal.py. Write meaningful failing regressions first;
  capture RED, make the minimal fix, then run the focused boundary module and
  adjacent persistence/HTTP consumers. Preserve valid 1/128 character boundaries
  and verify invalid inputs do not reach downstream operations.
- mobile_session_transport (gpt-6-sol/high): read-only design and independent
  frozen-code review, including HTTP/client compatibility and side-effect tests.
- wall_contracts (gpt-6-luna/medium): read-only affected evidence-pin inventory.
- Root: plan, integration, backlog/parity/proof and generated metadata, git.
  At most four active agents; no nested delegation or overlapping file writers.

After focused RED/GREEN, run relevant session lifecycle, continuation, channel,
vision and KG collateral suites. The shared helper has broad callers, so run
one serial full backend milestone at the frozen source if focused checks pass.
No JS source change is planned; retain earlier client evidence with its original
scope. Update canonical collected counts; refresh only formerly current pins
after named claim review and preserve stale pins. Report actual run counts and
unresolved limitations without promoting unrelated backlog completion.

## Rollback

Revert the shared-helper fix, regressions and supporting evidence together.
No data migration or environment changes require rollback. Existing valid
session IDs and their stored files remain unchanged.

## Focused verification complete

The boundary module produced nine expected failures before the fix, then passed
all 36 cases. The writer's seven-module union passed 178/178 (5.566 seconds), and
root's disjoint 15-module union passed 273/273 (7.310 seconds): 451 distinct
passing cases with zero skips, errors or failures. Portable persistence traps
verify refusal before directory access without requiring newline filenames.
Frozen independent review has no Critical/Important findings. Ruff, whitespace
and exact text/AST scope checks pass. Production changes one matching operation;
no assessment pins refer to either changed Python file. Full milestone pending.
