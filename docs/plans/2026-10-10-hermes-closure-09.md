# Hermes full-contract closure — batch 09

Generated 2026-10-10 UTC. Goal: repair clarification registration at fresh startup
and restore typed choice coercion after Other, then re-review the whole frozen
H067 pending-input contract. Initial base/head:
`16bfdc1282554ada805968383ced004046173b2c`, the frozen H456 source checkpoint.
Branch `codex/hermes-closure-09-20261010`. Next action: fresh-start red regression.
This isolated worktree will incorporate final batch08 metadata before its own
integration milestone. H067 currently needs_review, not accepted-complete credit.
Local only; no push, remote merge, deployment, live accounts or paid providers.

## Design and scope

The fresh app builds ToolRPC before loading runtime settings. The guarded
register_clarify_tool therefore sees an empty cache and omits the opted-in tool;
the later enabled service cannot make a missing registration available. Repair
this once immediately after initial load_runtime_settings, on the existing
server and only if clarify is not already registered. Use the effective cached
setting via the existing helper. Preserve default-off, restart-to-apply and
handler-time revocation; do not rebuild executor or move all settings loading.
No changes to permissions, pairing, confirmation policy, model routing or APIs.
Rollback is this small boot-composition unit and its regression.

Read-only source/clause review is in batch08/next-h067-contract-review.json and
next-clarify-startup.json. Frozen donor commit remains
59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e, MIT; original reviewed native mapping is
recorded in docs/hermes/pending-input-plan-2026-10-05.md. The whole H067 acceptance
requires per-chat numeric/label/multiselect/free-text clarification; native and
typed once/always/cancel interception; confirmed new/reset/undo with governed
persistent opt-out; and safe deletion of ephemeral bot notices. Existing native
mechanisms appear to implement these clauses; re-review stale evidence and run
meaningful clause integration suites before renewing credit. Fix alone earns no
whole-contract promotion. Wider CLI/email work belongs to other contracts.

## Ownership and verification

repair_1247 (gpt-6-sol/high) owns agents/core/orchestrator.py and new
 tests/test_h067_clarify_startup.py. Root owns plan, review, donor/evidence,
collateral coverage, generated reports and integration. Optional read-only
reviewer may inspect clauses/deltas; no subdelegation or overlapping writers.

Show the regression red against the actual isolated fresh app lifespan with a
persisted enabled setting, then green after repair. Also prove default/stored
false remains absent; effective settings are the authority; handler disable and
same-instance channel restart remain fail-closed; preserve an existing tool
spec rather than replacing it. Use disposable synthetic state and blocked network
with no provider invocation. Exercise actual registered clarification dispatch
under a verified live-human turn when the fixture permits, with typed ingress
resuming the waiting call. Run existing pending-input/session-command/ephemeral
integration suites; no new endpoint means existing route guards suffice. Full
backend milestone runs serially after batch08 and after this source is frozen.

## Additional confirmed clause gap

Review against exact donor tools/clarify_gateway.py:162-184 found that valid
numeric/label/multiselect replies must still coerce to the existing choice after
Other is selected. Native parse_clarify returned all awaiting_text responses raw
before matching choices. Restore choice matching first; only unmatched text falls
back to raw Other text, including invalid selection-shaped input. Keep existing
command fallthrough, size bounds, whole-reply matching and first-writer behavior.
No new permissions or transport behavior. This belongs to the same H067 typed
answer contract and is verified before full equivalence.

review_1233 (gpt-6-sol/high) owns agents/core/channels/pending_input.py and
 tests/test_pending_input_other_choice.py (new), independently of startup files.
Show red for numeric, exact label and multiselect after Other; green for these,
free prose fallback, invalid selection fallback and actual pending-state delivery.
Root owns integration, no overlapping writers. Donor SHA manifest and exact
cached files are in batch09/donor-files.json and the shared frozen donor cache.

## Frozen source and current verification

The startup regression failed before repair: one of two actual fresh-app cases
found persisted/effective true but no clarify registration. The eight-line
post-load reconcile now passes shipped/stored-off, enabled, restart-to-apply,
effective-setting narrowing, preserved existing spec, and live handler disable.
The core clause selection ran 316 cases: 302 passed and 14 optional-SDK skips.
Final startup/same-instance-restart selection passed 7/7.

Other-choice coercion failed five of ten regression cases before repair; the
final parser/runtime/native/completion selection passed 116/116. Exact known
choices now coerce before the unmatched-text fallback, including multi-select;
commands and size bounds retain their existing handling. No authority change.

Root installed Slack/Discord SDKs and dependencies under scratch batch09 only,
without mutating the shared environment running batch08. All 18 cases in the two
formerly-skipped modules pass, including all 14 prior skips. Exact versions are
recorded in optional-deps-versions.json; these are offline adapter tests, not live
platform accounts. Changed Python Ruff and whitespace checks pass.

Read-only clause reports cover typed parsing, route/owner/receipt identity,
Once/Always/Cancel, durable session history and permission.grant opt-out, plus
safe bot-owned ephemeral deletion. The initial stable report's Other mismatch
is resolved by the parser red/green evidence; it is not left as an open blocker.
Root reviewed both small production diffs. Fresh actual app/model/HTTP smoke and
the serial frozen integration milestone are required before whole H067 credit.

The final actual fresh-app HTTP/model smoke passes without injecting a registration
helper: the live tool loop emits clarify, authenticated polling discovers it, and
a valid answer resumes the same turn. Anonymous/other-principal discovery, wrong
principal answers, invalid choices and replay refuse. It used two tool-loop HTTP
responses plus one synthetic naming response, blocked two unrelated boot probes,
and removed temporary state. Source digests were unchanged during the run.
A pre-existing nonstream context-anchor warning was observed; usage is recorded
before that callback, so turn totals remain. The separate H673 issue is recorded
in next-context-anchor.json and is not represented as repaired by this batch.
