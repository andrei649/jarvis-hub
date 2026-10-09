# Anthropic counter-category availability

- Generated: 2026-10-09 UTC.
- Base: 1c1f5ccb4821beebc42b7e1c1309fead256c2edd.
- Tested source: de64dacc824c49e126ce8d378338e29425350f03.
- Branch/worktree: codex/anthropic-counter-availability-20261009,
  /workspace/jarvis-hub-anthropic-counter-availability.
- Delivery: local. PR #1247 remains the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-anthropic-counter-availability.md).

## Behavior and deliberate conservatism

Anthropic's input, cache-read and cache-write counts are disjoint. The parser
already retained strict integer siblings, but missing categories normalized to
zero without an availability marker. A positive partial observation could
therefore be labeled provider usage and receive a cache discount despite an
unknown prompt category. A missing later tool observation could leave an earlier
aggregate looking complete.

Only anthropic_usage changes production. counts_complete is True only when
input_tokens, output_tokens, cache_read_input_tokens and
cache_creation_input_tokens are all explicit exact nonnegative integers.
Missing/null/malformed categories make it False while valid siblings survive.
Fully supplied zero counters remain observable. Non-mapping or missing usage
is explicitly incomplete. The four-field as_dict and legacy nonzero reported
predicate are unchanged; no new cache details are added to totals.

This is an application accounting rule, not an API validity requirement. The
pinned SDK Usage schema at 50b78d17a8a73bef97c3884102310344ac00f056 requires
input/output and permits optional cache categories. That shape alone does not
prove absent/null cache fields are measured zero. Consequently an otherwise
valid response lacking optional cache details remains an answer with estimated
accounting. No authoritative omission rule or live-provider claim is introduced.

Existing observers and tool runtime now forward explicit unavailable and zero
observations. Existing accounting keeps estimates floored at known input plus
cache and output, and suppresses cache discounts and cached-prefix fallback for
incomplete observations. A later unavailable tool response marks the observed
aggregate incomplete. Fully observed categories retain existing pricing,
including its documented cache-write premium approximation.

Text/tool acceptance and stream start/stop/final-output gates are unchanged.
Streaming still needs valid final output and no usage/transport failure; missing
input/cache categories with valid terminal output produce an incomplete sample.
Cumulative updates replace prior fields, including later malformed fields;
earlier values are not resurrected. Existing errors, retries, callbacks and
tool calls are preserved. The other 28 functions and all other module AST are
identical to base.

## Verification

Root verified the exact production base hash and every RED failure message
before releasing implementation. Builder RED: 18 cases, 17 failures and one
passing anchor control, 1.248 seconds. The accounting regression reaches
_record_interactions and reproduces provider instead of estimate for missing
cache creation; the other cases lack the availability marker. Consumer RED:
42 cases, 18 expected failures and 24 passes, 2.265 seconds. Every runtime fixture
offers a benign tool and reaches HTTP and its accepted answer; there are no
fixture failures. Both RED runs have zero errors/skips.

- Eight-module focused union: **264/264**, 4.506 seconds. Both new modules,
  prior Anthropic normalization, text/stream publication, cloud usage/tool
  dialects and counter accounting.
- Root's disjoint fifteen-module integration: **333/333**, 8.646 seconds.
  Claude cache requests, protocol/runtime, compaction and prompt anchors,
  scoped observers, cost records, Ollama/compatible availability and route guards.

Combined: **597 distinct passing cases**, zero failures/errors/skips. A blank
line removed from the new direct test file after the focused run satisfies Ruff
and changes no behavior. Ruff and diff checks pass. Canonical collection is
**21,485 backend cases** (+35), frontend/native 2,009, mobile 306, 555 routes and
18 agents. Hermes/status checks pass; client counts are reused without a new run.

This parser-only unit uses the focused/integration evidence above. No new full
backend run is claimed. Latest historical full backend remains 21,372 passed
and 37 skipped, 312.491 seconds, at 42013de7435c08f7bee91257d7c7f7fd2091366c.
That historical result is not this candidate's full-suite verification.

## Review and limits

auth_audit (gpt-6-sol/high) owns the parser/direct tests and independently checks
root's collateral metadata. mobile_session_transport (gpt-6-sol/high) owns actual
propagation regressions and independently reviews the frozen parser.
wall_contracts (gpt-6-luna/medium) inventories exact-base pins; root owns scope,
critical review, integration, docs and git. No Critical/Important finding remains.

Ten affected pins were current at base and are refreshed after bounded claim
review. Two new H673 test pins are added; all 226 capability statuses and
unrelated stale pins remain unchanged. H363/H673 and the architecture inventory
describe the conservative four-category rule. H557's same-target Gemini
coordinates move by seven lines, without changing its schema behavior.

Counter availability covers only an observed parsed response, not all physical
attempts, retries, silent failures, auxiliary calls or a whole-turn bill. No
live provider, model server, billing service, device or GPU was used. No routes,
settings, prices, client contracts or persistent-data behavior change.

Prompt occupancy remains a separate limit: unmanaged and managed anchors still
accept a positive sum of supplied prompt categories independently of output or
counts_complete. An incomplete partition can therefore replace an earlier
anchor with a lower bound. Zero/absent prompt sums leave an existing anchor
intact. This fix does not establish exact system/tool/cache occupancy or repair
that independent anchor-completeness contract.

## Frozen evidence

- Production SHA-256: 9545ec35b9654b03f036986a3f37c495802f57c7d6b7d1e18098c01c934f2569.
- New direct tests: 85adcf68d121ab4ef00e4ee2ba401c8002577106fd8d858a38bcacdf9f627f0d.
- New propagation tests: cc45b634814fe1d536d138e0cce1b2c32dd5b60852b0873fd52f1d97a79ecca3.

Scratch artifacts under /workspace/scratch use the anthropic-counter-availability
prefix: builder-red, consumer-red, builder-focused and integration XML/log pairs;
source-manifest.json, base-hashes.json, ast-review.json, pin-inventory.json/md,
pin-refresh.json, consumer-review.md, claim-review.md and status-sync.log.
Design review: anthropic-availability-conservative-design-review.md; pinned
SDK type: anthropic-usage-upstream.txt.
