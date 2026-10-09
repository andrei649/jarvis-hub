# Conservative Anthropic counter availability

- Generated: 2026-10-09 UTC.
- Goal: partial disjoint Anthropic usage categories must not become measured zeros.
- Base/HEAD: 1c1f5ccb4821beebc42b7e1c1309fead256c2edd.
- Branch/worktree: codex/anthropic-counter-availability-20261009,
  /workspace/jarvis-hub-anthropic-counter-availability.
- Delivery: autonomous local development; no publication or live model calls.
- Next action: frozen parser and focused/integration checks pass; finish
  independent collateral review and the local evidence commit.

## Contract and tradeoff

Only anthropic_usage in agents/core/llm/tool_dialects.py changes production.
Set counts_complete=True only when all four fields input_tokens, output_tokens,
cache_read_input_tokens and cache_creation_input_tokens are supplied as exact
nonnegative integers. A valid all-zero set is complete. Otherwise use False,
including absent/malformed usage, missing/null fields and invalid counters.
Preserve each valid sibling through existing strict normalization; no type
coercion, numeric inflation, new discounts or change to reported/as_dict.

The pinned Anthropic SDK Usage schema requires input/output but allows optional
cache categories. Optionality does not establish that omission or null proves
zero cache use. This availability rule is deliberately conservative: a valid
API response lacking optional cache details remains a valid answer with estimated
accounting. The current billing consumer uses all four disjoint categories, so
a required-pair-only flag would incorrectly elevate unknown cache partitions.
No new authoritative omission rule is claimed; the public documentation fetch
was unavailable. SDK shape evidence remains pinned at
50b78d17a8a73bef97c3884102310344ac00f056.

Existing observers/runtime forward explicit unavailable and complete-zero
observations. Existing accounting uses estimates floored at observed input plus
cache and output, and grants no cache discount for incomplete observations.
All-four-complete behavior and existing write-premium approximation stay intact.
A later tool response without counters must make the observed aggregate
incomplete. This is parsed-category availability, not coverage of physical
attempts, retries, whole-turn cost or live billing.

Text/tool response acceptance, tool calls and errors are unchanged. Streaming
still requires start, stop, a valid final output delta and no error/malformed
transport; preserve cumulative replacement and last-field semantics. Missing
input/cache with a valid terminal output emits an incomplete observation, while
invalid/missing final output keeps the existing no-observation gate. No new
response validation or retry behavior. No provider outside Anthropic changes.

Both legacy and managed prompt anchors still accept positive partial prompt
sums independently of counts_complete. This unit preserves that behavior and
does not claim exact occupancy or complete system/tool/cache measurement. A
zero/absent prompt sum must not erase an existing anchor. Anchor completeness
is a separate contract, not an incidental accounting change.

## Ownership and checks

- auth_audit (gpt-6-sol/high): production tool_dialects.py ONLY anthropic_usage;
  NEW tests/test_anthropic_counter_availability.py for strict availability,
  optional-omission tradeoff, accounting floors/no-discount and anchor controls.
- mobile_session_transport (gpt-6-sol/high): NEW
  tests/test_anthropic_usage_propagation.py and exact Anthropic unavailable-event
  expectation in tests/test_text_usage_propagation.py. Actual mocked text,
  structured/runtime, tool-loop aggregation and terminal streaming regressions.
  Every runtime fixture must offer a benign tool and reach its HTTP assertion.
- wall_contracts (gpt-6-luna/medium): read-only exact-base affected-pin inventory
  and claim/coordinate list including optional docs/ARCHITECTURE.md update.
- Root: interfaces, meaningful RED verification, source freeze, critical review,
  integration, docs/status and local git. At most four active; no nested agents.

Both writers add tests first and await root RELEASE before production. Root
checks failure reasons and exact production base hash, not only test counts.
After implementation, run focused Anthropic/provider/publication suites and
disjoint accounting/runtime/context/route guards. No automatic repeat of the
full backend milestone for one parser; expand only for failures or unresolved
scope. Latest full backend is the historical persona guard source 42013de,
21,372 passed and 37 skipped; do not relabel that as this candidate's evidence.
Collect current backend count and reuse unchanged client counts.

Review frozen production and collateral claims independently. Refresh only
previously-current file pins after review; preserve unrelated stale evidence
and capability statuses. Roll back the parser, tests and proof as one unit.
There are no new routes, settings, prices, client contracts or data migrations.

## Implementation checkpoint

Root verified the exact production base and each failure message before release.
Builder RED: 18 cases, 17 failures and one passing anchor control, 1.248 seconds.
One case reaches actual accounting and fails because partial cache data is
labeled provider rather than estimate; the others lack the availability flag.
Consumer RED: 42 cases, 18 expected failures and 24 passes, 2.265 seconds. All
runtime fixtures reach HTTP and their accepted answer; none fails on fixture
setup. These runs have zero errors/skips.

Final focused eight-module union: 264/264, 4.506 seconds. Root's disjoint
fifteen-module integration: 333/333, 8.646 seconds. Combined: 597 distinct passing
cases, zero failures/errors/skips. A test-file blank-line Ruff fix after the
focused run changes no test behavior. Independent frozen production review has
no Critical/Important finding. Only anthropic_usage changes; the other 28
functions and all other module AST are identical. Canonical collection is
21,485 backend cases (+35); unchanged client counts are reused. No new full
backend run is claimed for this parser-only unit.
