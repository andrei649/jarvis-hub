# Preserve complete Anthropic prompt anchors

- Generated: 2026-10-09 UTC.
- Goal: a partial Anthropic prompt subtotal must not create or replace a
  single-request context anchor; retain complete prompt counts when output
  accounting is unavailable.
- Base: aa4ca99ea22bd72be134c03e4b46fb367bade0b0.
- Branch/worktree: codex/anthropic-prompt-completeness-20261009,
  /workspace/jarvis-hub-anthropic-prompt-completeness.
- Delivery: autonomous local development, no publication or live inference.
- Tested source: 5538f559b81ff2793f08e6b592686271ea848871.
- State: local implementation, independent reviews and full milestone complete.
- Next action: retain this checkpoint and select the next verified local gap
  from a clean final head; no publication follows from this unit.

## Evidence and contract

Anthropic input, cache-read and cache-creation are disjoint prompt categories.
The parser already keeps valid siblings and treats absent optional categories
as unknown for accounting. Both unmanaged _record_context_anchor and managed
remember_usage nevertheless replace a stored anchor on any positive sum. A
partial 23 input + 90 cache-read with unknown cache-write can overwrite a prior
28,000-token complete observation. The compressor floors at transcript estimates,
which cannot recover hidden system/tool overhead and may then defer compaction.
This is not proof of bypassing the independent final managed dispatch guard.

Add TokenUsage.prompt_counts_complete: bool | None = None at the end of the
dataclass. It describes whether mapped prompt categories constitute a complete
single-response prompt count, independently of output/accounting availability.
It does not prove exact wire tokenization, peak physical context occupancy or
freshness of system/tool/persona material. Preserve numeric fields, reported,
four-number as_dict and existing counts_complete behavior.

Only the Anthropic producer is migrated in this unit:

- True iff input_tokens, cache_read_input_tokens and
  cache_creation_input_tokens are all explicit exact nonnegative integers,
  including zero. Output availability is irrelevant to this prompt flag.
- False for missing/non-mapping usage or any missing/invalid prompt category.
  Keep all valid siblings and the existing four-category accounting flag.
- Other producers remain None with their current behavior, including Gemini.
  Gemini tool-use prompt aggregates do not establish initial-prefix/physical
  occupancy semantics; do not add them to anchors or migrate that contract here.

Both anchor writers decline literal prompt_counts_complete=False before any
replacement. With a prior anchor, preserve its value, covered prefix/count,
identity and eviction order; without one, retain no anchor and the existing
estimate fallback. True or None positive prompt sums follow the existing path;
zero retains the old anchor. Do not gate on counts_complete: full prompt with
unknown output remains anchorable. Keep managed counter validation, route/model/
session/instance/prefix checks, compressor behavior and final dispatch bounds.

_sum_usage(None, incoming) continues to return the original observation. A sum
of two or more observations sets prompt_counts_complete=False, regardless of
the two prompt flags, because a sum over requests is not one prompt prefix.
Preserve numeric accumulation and accounting availability conjunction exactly.
Existing live anchor callbacks receive the raw per-response observation, not
this accounting aggregate. Legacy raw None observations remain compatible;
legacy multi-observation sums are deliberately non-anchorable too.

## Ownership and meaningful regressions

- auth_audit (gpt-6-sol/high): tool_protocol.py new field/documentation only;
  tool_dialects.py only anthropic_usage; orchestrator.py only _sum_usage and
  _record_context_anchor; route_compaction.py only remember_usage. NEW
  tests/test_prompt_counter_completeness.py for strict prompt flags independent
  of output, legacy serialization, both anchor writers' retain/no-create/update
  controls and aggregate non-anchorability. Do not change retrieval/freshness,
  other provider parsers, stream gates or compressor/dispatch behavior.
- mobile_session_transport (gpt-6-sol/high): NEW
  tests/test_anthropic_prompt_anchor.py for actual mocked text, structured/tool
  and accepted stream observations reaching real anchor writers. Text sequence
  complete-high then partial-low must retain the high anchor and the real
  compressor's summarize decision; accounting retains partial count floors and
  stays estimated. Managed tool sequence preserves original covered prefix and
  route identity as later rows arrive. Runtime fixtures must offer benign tools
  and reach HTTP/answers. Own only the old anchor-control function in
  tests/test_anthropic_counter_availability.py: change its fixture to complete
  three-field prompt with unavailable output (123), preserving the intended
  output-independent control. New partial-rejection regressions cover the old
  behavior being removed. No other existing test edits without root review.
- wall_contracts (gpt-6-luna/medium): exact-base read-only pin/claim/citation
  inventory. Root: contract, failure/hash checks, critical review, integration,
  metadata, documentation and git. At most four active; no nested delegation.

Tests first. Root verifies every failure message and unchanged four production
hashes before releasing source edits. Regression failures must reach the anchor
overwrite or wrong compressor decision, not stop only at a missing new field.
Use getattr for testing a new field against old code when appropriate. Direct
constructor TypeError alone is not meaningful bug reproduction. Include both
complete-high-to-partial-low and no-prior-anchor cases plus complete-prompt/
missing-output, zero, legacy inclusive and managed freshness controls.

## Verification, metadata and rollback

After freeze, run focused protocol/Anthropic/anchor/usage tests and disjoint
runtime, compaction/clock/prepared-dispatch, cost and route guards. Independent
production and collateral reviews follow. Run one serial full backend milestone
on the frozen source: this changes the common usage value, both context-anchor
writers and aggregate provenance. Repeat only for a discovered failure/change.
Collect canonical backend counts and reuse unchanged clients. Refresh only
exact-base fresh evidence pins, map affected same-target citations and preserve
every row status and unrelated stale pin. The old Anthropic partial-anchor limit
can be narrowed to the actual repaired path; do not claim every provider's
prompt metadata or physical occupancy is now proven.

Rollback source, tests and proof as one unit. No routes, settings, prices, client
contracts or persistent-data migration. A retained older anchor keeps only its
original covered prefix and existing freshness semantics; it is not a new
measurement of changed instructions or tool schemas. Unknown initial prompt
data still uses estimates. The existing final prepared guard remains separate.

## Execution checkpoint

Root verified all four production base hashes and every RED failure message
before release. Builder: 24 cases, all 24 fail, 2.034s, including genuine
overwrite/no-create/recency failures rather than constructor errors. Consumer:
22 cases, four expected anchor failures and 18 passes, 1.565s; actual mocked
text, tool loop and accepted terminal streams reached answers before assertions.
Both runs have zero errors/skips and no fixture failures.

Thirteen-module focused union passes 342/342 (6.630s); root's disjoint
twenty-module integration passes 449/449 (9.992s), totaling 791 distinct cases
with zero errors/skips. Two final source docstrings were clarified after focused
verification; executable behavior is unchanged and the full run binds final
bytes. Independent production review, Ruff/diff and precise AST scope pass:
one new TokenUsage field/documentation, anthropic_usage, _sum_usage,
_record_context_anchor and remember_usage only. Other providers and methods
remain unchanged. Seven source/test hashes are frozen in the scratch manifest.
Canonical collection is 21,654 backend (+28), with unchanged client counts
2,009/306 reused, 555 routes and 18 agents. One serial full milestone passes:
21,617 passed, 37 skipped, zero failures/errors, 297.802s, exit 0. The 37 skip
IDs are identical to the preceding Gemini milestone; executed-count, Hermes
and generated status guards pass. Eighteen formerly-current pins are refreshed,
46 preexisting-stale orchestrator pins preserved, two H673 tests added and all
226 statuses retained. Independent collateral review confirms bounded claims
and same-target citations. Final proof: docs/project-anthropic-prompt-completeness-20261009.md.
