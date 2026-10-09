# Responses accounting availability

- Generated: 2026-10-09 UTC.
- Base: 7cba013d78da7d4fda15c4dff9d76ea26c5ce1f6.
- Tested source: 5fb7e86d882076683d34225f5d56489822bbf593.
- Branch/worktree: codex/responses-counter-availability-20261009,
  /workspace/jarvis-hub-responses-counter-availability.
- Delivery: local; PR #1247 remains the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-responses-counter-availability.md).

## Behavior and deliberate compatibility tradeoff

The shared OpenAI/xAI Responses parser normalized each strict count separately
but returned unflagged usage. A valid positive sibling could label missing
categories provider-measured zero. An unavailable later tool reply could leave
the observed aggregate apparently complete. All accepted text, tool and validated
terminal stream paths use this parser.

Only responses_dialect.usage changes runtime behavior. It keeps exact integers
in the existing 0..2**63-1 range, normalizes invalid fields to zero and preserves
valid siblings. Inclusive input is split once into uncached input plus a valid
cached subset; malformed/oversized cache details retain the full input with no
split. Output is inclusive. Cache-write remains zero; no reasoning, write or
total detail is added twice, and no missing total is reconstructed.

counts_complete is True only when input/output totals and the cached subset
are explicit valid counters, cached_tokens <= input_tokens, cache_write_tokens
is explicitly exact integer zero, and total_tokens, if supplied, is valid and
equals input+output. An absent redundant total is allowed. Booleans/fractions
cannot satisfy the exact-zero requirement. All other observations are False,
including absent/non-dict metadata or details, missing/positive writes and
contradictory totals. Supported explicit all-zero usage stays observable;
TokenUsage.reported and four-number serialization remain unchanged.

This marker serves conservative application accounting, not merely inclusive
token-total availability. Ordinary valid xAI Responses payloads can omit the
cache-write field that its published schema does not promise. They still produce
answers and retain known input/output counts, but are deliberately estimated
under this shared accounting rule. There is no added API validity requirement
or provider-specific omission-as-zero exception. A separate partition/pricing
availability contract would be needed to express that distinction more finely.

Existing cost recording keeps input+cache_read and output as estimate floors,
without a cache discount or cached-prefix fallback for incomplete observations.
A known inclusive prompt remains useful for anchors independently of output or
cache-write availability. Positive write counts are not separately added to
inclusive input. Neither availability nor the local total-consistency check
establishes an exact invoice, cache-write pricing or every chargeable category.

## Evidence and preserved boundaries

OpenAI OpenAPI is pinned at
0ef225c4f701046f8fe88cae9d29d0df4d1a9fa9:
https://raw.githubusercontent.com/openai/openai-openapi/0ef225c4f701046f8fe88cae9d29d0df4d1a9fa9/openapi.yaml.
Whole downloaded source SHA-256:
06d914881ac7e73185739ce80bc3ad84bfcd5df022e6bab5527b87d938f67506.
The input details are a breakdown containing required cached_tokens and
cache_write_tokens; write tokens are described as input tokens written to cache.
The field descriptions do not prove omission means zero or an explicit universal
input-plus-output invoice equation. The published example is locally consistent.
The official prompt-caching guide supports cached input as a subset. The official
xAI Responses reference documents its own usage shape and does not promise
universal OpenAI detail-field compatibility. Fetched URLs, hashes and xAI
deployment ID are recorded in the scratch research supplement.

AST comparison confirms all module code outside usage is identical to base.
Responses/XAI transport code is untouched: fixed models, request cache keys,
response/output validation, function identities, encrypted replay and lifetime
checks remain. Streaming still requires one completed terminal with matching
body, bounded clean exhaustion/close, no error or contradictory trailer, and
unchanged cancellation behavior. Existing observers forward explicit complete
or incomplete zero samples; a later unavailable tool sample marks the observed
aggregate incomplete. No request or response shape is added.

## Verification

Root verified the unchanged production hash and inspected every final RED
failure before releasing implementation. Builder RED: **45 cases, 44 failures,
one passing anchor control**, 1.464 seconds. It checks exact types/range, zero
traps, null/list detail containers and numeric preservation. Its actual cost
record regression fails provider-versus-estimate before asserting the new flag.
Consumer RED: **187 cases, 42 failures, 145 passes**, 8.492 seconds. Registered
runtime tools reach mocked HTTP/answers; the xAI second request retains its
ciphertext and call ID. All failures are contract failures, with no fixture,
HTTP/replay or terminal-validation failure. Both runs have zero errors/skips.

- Seven-module focused union: **295/295**, 8.357 seconds. Both new modules,
  existing OpenAI/xAI request/stream/replay suites, accounting, scoped usage
  context and tool protocol.
- Root's disjoint ten-module integration: **221/221**, 7.033 seconds. Runtime,
  compaction and anchors, cost recording/estimation, text propagation and
  route/OpenAPI guards.

Combined: **516 distinct passing cases**, zero errors/skips. Ruff/diff checks,
Hermes and generated status checks pass. Canonical collection is **21,626 backend
cases** (+87), frontend/native 2,009, mobile 306, 555 routes and 18 agents.
Client counts are reused without a new run. No source/test edits follow the
frozen tested source.

No new full backend run is claimed for this one-function follow-up. The latest
historical full milestone remains **21,502 passed, 37 skipped**, 295.954 seconds,
at 28aa7dc3d2b88ad01f22ed121038909331bba8fa. That result precedes this parser
change; current verification is the focused/integration evidence above.

## Review and metadata

auth_audit (gpt-6-sol/high) owns the source/direct tests and independently reviews
root's collateral metadata. mobile_session_transport (gpt-6-sol/high) owns actual
propagation tests and independently reviews frozen production. wall_contracts
(gpt-6-luna/medium) inventories evidence; root owns the contract, critical review,
integration, docs and git. Independent frozen production and collateral reviews
find no Critical/Important issue.

Four affected previously-current evidence pins are refreshed: three source pins
and one architecture pin. Eight potential pins to the existing OpenAI/xAI test
files remain byte-identical and unchanged. Two new H673 test pins are added;
all 226 statuses and unrelated stale evidence remain unchanged. H363/H673 and
the architecture inventory explain the conservative write/total criteria and
the valid-xAI-response tradeoff. H364 reasoning and H670 identity behavior are
untouched. No relevant inline source citation shifts in those row claims.
Immutable inventory and row identity hashes retain the same ledger.

No live provider, model server, billing service, device or GPU was used; schema
reads are public documentation only. No route, setting, price, client contract,
persistent data, request authorization or external publication changes. The
marker covers received observations, not silent retries, failed requests without
usage, auxiliary calls, vendor-specific fees or a complete-turn bill. Existing
partial-disjoint prompt-anchor behavior remains a separate documented gap.

## Frozen evidence

- Source: 97b9f45f9fb9d27956e005a009df1ac57e172a1ff82539e8683671bcf3a20e06.
- Direct tests: f253c1e9b703ef22d050119c311a6fb8970c432130341335676e03fc2aa78e9e.
- Propagation tests: a7db7f763b8b31bd894960499139e63fdea069f18e57d61108c2f8d16a525c3c.

Scratch artifacts under /workspace/scratch use the responses-counter-availability
prefix: builder-red, consumer-red, focused and integration XML/log pairs;
base-hashes.json, source-manifest.json, ast-review.json, pin-inventory.json/md,
pin-refresh.json, consumer-review.md, claim-review.md and status-sync.log.
Design review: responses-availability-conservative-design-review.md. Pinned
schema excerpt: openai-responses-usage-schema-0ef225c.txt. Research supplement:
post-gemini-responses-availability-gap.md.
