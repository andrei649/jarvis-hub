# Conservative Responses accounting availability

- Generated: 2026-10-09 UTC.
- Goal: accepted OpenAI/xAI Responses with partial or unsupported accounting
  categories must not become complete provider-cost observations.
- Base: 7cba013d78da7d4fda15c4dff9d76ea26c5ce1f6.
- Branch/worktree: codex/responses-counter-availability-20261009,
  /workspace/jarvis-hub-responses-counter-availability.
- Delivery: autonomous local development only; no inference or publication.
- Tested source: 5fb7e86d882076683d34225f5d56489822bbf593.
- State: local implementation, independent reviews and verification complete.
- Next action: retain this checkpoint and select the next verified local gap
  from a clean final head; no publication follows from this unit.

## Evidence and chosen contract

responses_dialect.usage currently returns an unflagged TokenUsage after strict
field-by-field normalization. A positive sibling can make absent output/input
look measured; unavailable later tool replies can leave an aggregate complete.
Actual text, tool and accepted terminal stream paths all use this parser.

OpenAI OpenAPI at 0ef225c4f701046f8fe88cae9d29d0df4d1a9fa9 documents inclusive
input/output counts and input/output detail objects. Input details contain both
cached_tokens and cache_write_tokens, required in that schema. Cache-write is
described as input tokens written to cache; no omission-as-zero rule follows.
Source URL:
https://raw.githubusercontent.com/openai/openai-openapi/0ef225c4f701046f8fe88cae9d29d0df4d1a9fa9/openapi.yaml
Whole source SHA-256:
06d914881ac7e73185739ce80bc3ad84bfcd5df022e6bab5527b87d938f67506.
Focused excerpt: /workspace/scratch/openai-responses-usage-schema-0ef225c.txt.
The official xAI Responses reference documents cached input but does not promise
the same cache-write field or universal OpenAI compatibility. Its fetched hash
and deployment ID are in /workspace/scratch/post-gemini-responses-availability-gap.md.

Only usage in agents/core/llm/responses_dialect.py changes runtime behavior.
Preserve its existing exact integer range 0..2**63-1 and numeric mapping:
input = inclusive input total minus a valid cached subset; cache_read = that
subset; output = reported output total; cache_write remains zero. Invalid or
oversized cached subsets fall back to no split, retaining inclusive input.
Never add detail/reasoning/total counts to inclusive totals or synthesize missing
totals. Do not add cache-write mapping or adjust pricing in this unit.

counts_complete=True requires all of:

1. Explicit input_tokens and output_tokens valid under the existing exact-int
   range (not bool, float, string, negative or over-limit).
2. An input_tokens_details dict with explicit valid cached_tokens <= input.
3. Explicit cache_write_tokens equal to exact integer zero.
4. If total_tokens is supplied, a valid exact integer in the same range equal
   to input_tokens + output_tokens. An absent redundant total is allowed.

Everything else is False, including absent/non-dict usage, absent cache details,
unknown/positive cache writes and contradictory supplied totals. Total equality
is a local consistency fence; schema descriptions/examples do not establish an
explicit universal equation or an exact invoice. All supported explicit zeros
remain observable. TokenUsage.reported/as_dict and aggregation stay unchanged.

The cache-write guard is conservative application accounting, not a requirement
to know inclusive token totals. Otherwise valid xAI replies that omit the field
will remain answers with estimated accounting. No omitted-field zero inference
or provider-specific exception is introduced. Existing incomplete accounting
retains input+cache_read and output floors without cache discount or cached-prefix
fallback. Inclusive input remains known independently of partition/output
availability and stays useful for prompt anchors. This flag does not measure
every physical attempt, retry, auxiliary call, server-side fee or whole-turn bill.

## Preserved boundaries and ownership

Do not change accepted response/output/tool-call shapes, fixed model allowlists,
request cache keys, xAI reasoning/replay identity or lifetime checks. Keep strict
completed terminal body matching, clean EOF/close, errors/trailers/cancellation
and single-observation gates unchanged. The original text/structured return
types remain intact; no transport, endpoint, route, client or setting changes.

- auth_audit (gpt-6-sol/high): only usage function plus NEW
  tests/test_responses_counter_availability.py. Direct strict types/range,
  absent/zero/cache-write/total consistency, preserved numeric split, actual cost
  source and floors/no discount, independent managed/unmanaged prompt anchors.
- mobile_session_transport (gpt-6-sol/high): NEW
  tests/test_responses_usage_propagation.py. Actual OpenAI and xAI text, tool
  runtime and validated terminal stream observations; full/zero/partial/unavailable,
  cache-write unknown/positive, contradictory total and later unavailable tool
  reply. Runtime fixtures must offer benign tools, reach mocked HTTP and answer.
  Preserve existing rejection/no-event controls. Existing test edits require
  root agreement on an actual changed expectation, not fixture broadening.
- wall_contracts (gpt-6-luna/medium): read-only exact-base pin/claim/citation
  inventory and public schema evidence, no code/tests or nested delegation.
- Root: contract, unchanged-source/failure-message RED verification, release,
  critical review, integration, documentation/status and local git. Max four active.

## Verification and rollback

Before production, both test writers report actual RED failure messages and
root verifies source hash. Include a real accounting record regression that
fails provider-versus-estimate before checking the availability flag. Preserve
known numeric siblings and both boolean/float zero traps. After source freeze,
run focused OpenAI/xAI/replay/usage tests and disjoint runtime/context/cost/parity
integration, then independent source and collateral review. The preceding full
backend milestone passed 21,502 with 37 skips at 28aa7dc; this one-function
follow-up uses targeted/integration evidence unless a new failure or broader
change justifies another expensive milestone. Collect canonical backend counts,
reuse unchanged clients, refresh only exact-base fresh pins and preserve every
row status and unrelated stale evidence. Roll back source, tests and proof as
one unit; no persistent-data migration or client build is involved.

## Execution checkpoint

Root inspected every final RED failure and verified the exact unchanged source
SHA-256 7959f78567953082004d08295efb7455973ee7622beb92880295f0a6604574de
before releasing production. Builder RED: 45 cases, 44 failures and one passing
anchor control, 1.464s; includes supplied null/list detail containers and an
actual provider-versus-estimate record regression before the marker assertion.
Consumer RED: 187 cases, 42 expected failures and 145 passes, 8.492s; every
OpenAI/xAI text/runtime/stream and replay fixture reached mocked HTTP/answers.
Zero errors/skips or fixture failures in either RED.

Seven-module focused union passes 295/295 (8.357s); root's disjoint ten-module
integration passes 221/221 (7.033s). Combined 516 distinct passing cases with
zero errors/skips. AST comparison confirms only usage changed; numeric mapping
and all other module code are preserved. Independent frozen-source review finds
no Critical/Important issue; Ruff/diff pass. Canonical collection is 21,626
backend (+87), with unchanged client counts 2,009/306 reused, 555 routes and
18 agents. No full-suite repeat is claimed for this follow-up after the preceding
full milestone; the current evidence is focused/integration plus collection.
Four formerly-current pins are refreshed and two new H673 tests pinned; eight
potential pins to unchanged existing test files remain untouched. All 226 row
statuses and unrelated stale evidence are preserved. Independent collateral
review, Hermes/status checks and frozen three-file hash comparison pass. Final
proof and limits: docs/project-responses-counter-availability-20261009.md.
