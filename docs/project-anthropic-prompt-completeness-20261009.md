# Complete Anthropic prompt anchors

- Generated: 2026-10-09 UTC.
- Base: aa4ca99ea22bd72be134c03e4b46fb367bade0b0.
- Tested source: 5538f559b81ff2793f08e6b592686271ea848871.
- Branch/worktree: codex/anthropic-prompt-completeness-20261009,
  /workspace/jarvis-hub-anthropic-prompt-completeness.
- Delivery: local; PR #1247 remains the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-anthropic-prompt-completeness.md).

## Repaired behavior

Anthropic's input, cache-read and cache-creation counts form disjoint prompt
categories. Missing categories already stayed unknown for cost accounting, but
both context-anchor writers accepted any positive subtotal. A received 23 input
plus 90 cache-read tokens with unknown cache-write could overwrite a prior
complete 28,000-token anchor. The visible transcript floor cannot recover hidden
system/tool overhead, so compaction could be deferred by that lower subtotal.

TokenUsage now has a separate optional prompt_counts_complete marker after its
existing fields. Only the Anthropic parser sets it from provider metadata:
True requires all three prompt categories to be explicit exact nonnegative
integers; missing/non-mapping usage or any invalid/absent prompt category is
False. Output availability is independent. A full prompt with unknown output
can therefore remain anchorable while cost accounting stays estimated. Valid
numeric siblings, the all-four counts_complete accounting rule, reported and
four-number as_dict remain unchanged.

Both _record_context_anchor and remember_usage decline literal False before
creating or replacing a value. An earlier anchor retains its tokens, covered
prefix/count, identity and recency; without one, the existing estimate fallback
remains. Positive True or legacy None raw observations keep their prior behavior.
Complete zero prompt counts still leave the old anchor, following the existing
positive-count policy. Managed numeric validation and session/route/model/
instance/prefix freshness checks are unchanged.

The first _sum_usage observation remains the original object. Every subsequent
multi-observation accounting sum is explicitly prompt-incomplete: totals across
requests cannot describe one request prefix, even when every constituent has a
complete prompt. This also applies to legacy multi-observation sums. Numeric
accumulation and accounting availability conjunction are unchanged. Existing
live anchor callbacks already use raw per-response samples separately from
their accounting aggregate.

This is an Anthropic-only producer migration. Other raw adapters retain None,
including Gemini. Its additional tool-use prompt counts do not establish exact
initial-prefix or peak physical-window semantics, and this unit neither adds
those counts to anchors nor changes their existing eligibility.

## Verification

Root verified all four unchanged production base hashes and inspected every RED
failure before releasing source edits. Builder RED: **24/24 failures**, 2.034s,
including actual high-to-low overwrite, unwanted initial creation and managed
recency changes. Consumer RED: **22 cases, four failures and 18 passes**, 1.565s.
All four consumer failures reach actual anchor values after mocked HTTP/answers:
text 113 instead of 28,000, an unwanted initial anchor, managed tool-loop
(113,2) instead of (28,000,1), and accepted stream overwrite. There are no
fixture failures, constructor errors, collection errors or skips.

The consumer path uses real Agent/ToolRuntime observers with sinks calling the
real anchor writers. It does not claim to exercise the entire orchestrator
conversation lifecycle. A high-then-partial text sequence also reaches the real
ContextCompressor: plain short transcript estimation yields no compaction,
whereas the retained complete anchor preserves the summarize decision. Partial
usage still records estimated cost with known floors and no cache discount.
Managed tool-loop controls retain the original prefix after appended rows and
reject changed instance/prefix. Stream callbacks and accepted answers remain.

- Thirteen-module focused union: **342/342**, 6.630 seconds. Both new modules,
  Anthropic normalization/availability/propagation, protocol, both anchor paths,
  route compaction, accounting, cloud tools and text/stream publication.
- Root's disjoint twenty-module integration: **449/449**, 9.992 seconds.
  Prepared persona/context guards, model and turn leases, clocks, guardrails,
  Gemini cache, cost records, runtime, other provider anchor controls and parity.

Combined: **791 distinct passing cases**, zero failures/errors/skips. Two final
source docstrings clarify the three prompt-marker states and non-anchorable
aggregates; they change no executable behavior. Independent production review
binds final hashes. AST review confirms one new TokenUsage field/documentation,
anthropic_usage, _sum_usage, _record_context_anchor and remember_usage only;
other functions/providers remain unchanged. Ruff/diff pass.

Canonical collection is **21,654 backend cases** (+28), frontend/native 2,009,
mobile 306, 555 routes and 18 agents. Client counts are reused without a new run.
The single serial full backend milestone on the frozen source passes:
**21,617 passed, 37 skipped, zero failures/errors**, 297.802 seconds, exit 0.
All 37 skipped case IDs exactly match the preceding Gemini milestone, and the
executed-count guard agrees with the canonical 21,654. This run also covers the
intervening Responses availability follow-up. Hermes/generated status checks
pass. No source/test changes follow the frozen source commit.

## Review and evidence scope

auth_audit (gpt-6-sol/high) owns the four source files/direct tests and reviews
root's collateral metadata. mobile_session_transport (gpt-6-sol/high) owns
consumer regressions and independently reviews final production. wall_contracts
(gpt-6-luna/medium) inventories exact-base evidence; root owns the contract,
critical review, integration, docs and git. Frozen production and collateral
reviews find no Critical/Important issue.

Eighteen affected pins were current at base and are refreshed after bounded
review. Forty-six already-stale orchestrator pins remain untouched; only H063
and H277 had fresh orchestrator pins, and their session/authority mechanisms are
unchanged. Two new H673 test pins are added, with all 226 statuses and unrelated
stale evidence preserved. H673 narrows the formerly documented Anthropic
partial-anchor gap to the actual repaired path; H363 cost semantics remain.
H557's same-target Gemini schema coordinates move four lines without behavior
changes; H686's fresh protocol cache-field citation moves to 83-84. Existing
citations bound to stale orchestrator pins are not presented as newly reassessed.
Inventory and row identity hashes still bind the unchanged research ledger.

The existing Anthropic anchor control now tests a complete three-category prompt
with missing output (123 tokens), preserving output independence. The new tests
separately require partial-prompt rejection. This is a deliberate replacement
of the old partial-positive anchor expectation, not a claim that behavior stayed
unchanged. No other existing test file was edited.

## Limits

A preserved older anchor still describes only its original covered prefix under
existing freshness rules. It does not remeasure changed system, tool or persona
material, prove exact wire tokenization or physical context occupancy, or make
unknown first-request overhead measurable. The plain estimator, compressor
algorithm and independent final managed dispatch guard are unchanged. The
regression demonstrates lost anchor/compaction pressure, not a proven bypass of
that guard or universal over-window dispatch. Other providers' legacy prompt
eligibility remains outside this unit.

No live provider, model server, billing service, device or GPU was used. No
routes, settings, prices, client contracts, persistence, request authorization
or external publication change. Prompt and accounting markers remain per-observed
response metadata, not proof of all attempts, retries or complete-turn spend.

## Frozen artifacts

- tool_protocol.py: f8c6c0bd1dd9306226df8ef44b76f01a3d747ccfb7f84235b4e59fead8943137.
- tool_dialects.py: 16e07bcab892b370e7a256932b5fc814e094830dd7b2b64b149a3e4774850a4a.
- orchestrator.py: c4dfe0e242dc260c76e864f45fee201c4bd97b52ee869a98f32d094b54c39ab4.
- route_compaction.py: d392f80c15fae2d7cc1fe948cbc83b55d5f5818af8d77ee57ae293297cdb80aa.

Scratch artifacts under /workspace/scratch use the anthropic-prompt-completeness
prefix: builder-red, consumer-red, focused, integration and backend-final XML/log
pairs; base-hashes.json, source-manifest.json, ast-review.json, pin-inventory.json/md,
pin-refresh.json, consumer-review.md, claim-review.md and status-sync.log. The
manifest covers all seven changed source/test files. Design review:
anthropic-prompt-anchor-completeness-design-review.md; initial research:
post-responses-prompt-anchor-gap.md, including root's scope cautions.
final-result.json records executed counts and the unchanged skip comparison.
