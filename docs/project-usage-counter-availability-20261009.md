# Compatible response counter availability

- Generated: 2026-10-09 UTC.
- Base: 999c942efc4a72c62b79efcdb31b67267f531417.
- Production commit: a0e427299f9cb278949180746ccfc162dbd3f1c2.
- Full-suite source/test commit: 93c386e909bebd46e9888428a654d071071899be.
- Branch: codex/usage-counter-availability-20261009.
- Worktree: /workspace/jarvis-hub-usage-counter-availability.
- Delivery: local. PR #1247 is the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-usage-counter-availability.md).

## Result and limits

A compatible response containing prompt_tokens=100000 but no completion_tokens
was previously treated as provider totals with zero output. Replacing the whole
value with a short-message estimate would also discard its known prompt cost.
The fix labels that record estimated and keeps at least the observed input and
output counts. It uses max(observed, estimate), never adds the two estimates.
Incomplete observations do not invent a cache discount.

TokenUsage now has an optional internal counts_complete marker. LM Studio and
explicitly declared OpenAI-compatible responses set it True only when both
canonical prompt and completion counters are exact nonnegative integers. Valid
zero is distinct from missing, invalid or partial metadata. Valid siblings are
retained. Other adapters keep None and their existing behavior. The reported
property remains the nonzero predicate and as_dict still contains four numbers.

Text observers and tool runtime retain explicit complete/incomplete observations,
including zero. A clean LM Studio stream terminal without usage supplies an
incomplete observation; interrupted/error/malformed streams retain their prior
no-event gates. Latest malformed snapshots cannot revive earlier counters.
Aggregation preserves numeric sums and is complete only for all explicitly
complete observations. Mixed legacy/explicit observations are incomplete.
A positive prompt counter still anchors context independently of output presence.

This is availability of counters in received parsed responses. It does not prove
provider truth, every physical dispatch or a complete turn bill. Failed attempts
without observations, retries, synthesis/compression/background work, legacy
provider availability, cache-write prices, API/CLI receipts and client readouts
remain outside this unit. Request bodies, tool authority and public response
schemas are unchanged. No live provider, device or GPU was used.

## Verification

Both writers ran their final RED suites before either changed production; root
verified the six source-file hashes still matched the base. Foundation RED:
39 failures of 107 cases. Consumer RED: 14 failures of 14. No errors or skips.
The runtime flag-filter and lazy-estimation refinements also reproduced in two
existing cases before correction. An initial integration run had one old
ToolTurn equality expectation for absent compatible usage; it was corrected to
expect the explicit incomplete marker while preserving answer/wire assertions.

Final focused checks are disjoint:

- Foundation: 107/107, 2.997 seconds. Canonical pairs, observer scopes, actual
  mocked text/tool/stream transport, retries and terminal gates.
- Consumer/runtime: 251/251, 4.187 seconds. Actual partial HTTP response through
  accounting, a two-request tool loop with missing final usage, legacy/zero/mixed
  aggregation, observed floors and existing runtime/provider/anchor behavior.
- Downstream integration: 345/345, 11.855 seconds. Other adapters, context
  anchors/compaction, caching, cost measurement/caps and route/OpenAPI guards.

The initial full run exposed two more old equality expectations in the LM Studio
protocol tests, with 21,347 passing, 2 failing and 37 skipped in 283.211 seconds.
Only their expected incomplete marker changed; production stayed identical.
The corrected protocol module passed 44/44 in 1.252 seconds. Combined focused
coverage is 747 distinct cases passed, zero errors or skips. The partial HTTP test
checks the arguments delivered to cost_tracker.record, not a provider invoice.
The accounting regression includes a 100,000-token observed input lower bound.
Ruff passes all twelve changed Python files; whitespace checks pass.

The repeated full backend milestone at 93c386e passed: **21,349 passed,
37 skipped, zero failures/errors; 21,386 total**, 291.509 seconds, process exit 0.
The 37 skipped IDs exactly match the preceding session-ID milestone. Executed
and collected counts agree. The initial failed run remains separate evidence.
All twelve production/test file hashes match the frozen manifest. Canonical collection
records 21,386 backend cases (+50), unchanged frontend/native 2,009 and mobile
306, 555 routes and 18 agents. Client counts are reused because their sources
are unchanged; no new client test run is claimed.

## Review and evidence freshness

auth_audit and mobile_session_transport (gpt-6-sol/high) own disjoint foundation
and consumer files and cross-reviewed the frozen implementation. Root owns the
integration, corrected old expectation, documentation and git. wall_contracts
(gpt-6-luna/medium) made the read-only exact-base inventory. No Critical or
Important source finding remains. Root additionally qualified the TokenUsage
docstring's prompt-occupancy claim before the full-suite source commit.

Exactly 45 previously-current evidence pins are refreshed after bounded named
claim review; 67 already-stale pins remain untouched. H673 gains the two new
test pins. H363/H673 wording distinguishes the compatible improvement from
remaining legacy and whole-turn limits. Every capability status is unchanged.
H557 Gemini schema references move by nine lines, H315/H507/H661 runtime
references by four, and H686's numeric fields by five. Known pre-existing bad
coordinates in H296/H368/H674 remain outside this review. Their narrow behavior
claims are preserved, not promoted into a full reassessment.

Production SHA-256 at the tested source:

- tool_protocol.py: dc80089517889fa45b47d7e52847abb0d5cc1293e8ab4bd51bd24aed68332399
- tool_dialects.py: 5f678101a1fc356dd584008a3b6af9175a65c8b18c316d4ec1a31e783c847cbe
- usage_context.py: d45298bac222004865d24331f49d21e3599a661ea12650af47570fed2a4db498
- base.py: a0a8eebd9c28540f2bb090727dd9d8e743739fc6271f837b52492df50be37788
- agent_runtime.py: 442e1650d741e4ec21051199c78ed92fd4eea77054613dced2c84446b21a9372
- orchestrator.py: 30bda671b2208996df4d677d4eabc96d9eb0e347b8a46cbf44e6c6d1381697c8

Scratch files under /workspace/scratch use the usage-counter-availability prefix:
foundation-red, consumer-red, refinement-red, foundation-focused,
consumer-union-final, integration, protocol-final, backend-initial and
backend-final XML/log pairs;
source-manifest.json, ast-review.json, pin-inventory.json/md, pin-refresh.json,
foundation-review.md, consumer-review.md and status-sync.log.
