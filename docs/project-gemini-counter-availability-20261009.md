# Conservative Gemini accounting availability

- Generated: 2026-10-09 UTC.
- Base: d780d5372b0d5ef27ae98bf58912badac771137d.
- Tested source: 28aa7dc3d2b88ad01f22ed121038909331bba8fa.
- Branch/worktree: codex/gemini-counter-availability-20261009,
  /workspace/jarvis-hub-gemini-counter-availability.
- Delivery: local. PR #1247 is the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-gemini-counter-availability.md).

## Behavior and source evidence

Gemini's parser already preserved strict valid prompt, candidate and thought
counts, but lacked an availability marker. A positive partial observation could
therefore make missing categories look like measured zero in cost accounting.
A missing later tool response could also leave an aggregate apparently complete.

The official Gemini API Discovery revision 20261008, retrieved 2026-10-09 from
https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta,
defines totalTokenCount as prompt + tool-use prompt + thoughts + candidates.
It identifies cached content as part of promptTokenCount. Tool-use prompt is a
separate input category, not an already-included cache/detail breakdown. The
full discovery document SHA-256 is
bc75ec1dc53bb3e20ace03d17704fde8bc0ef4ec35cd7c2340618c70e44a42fb;
the relevant schema snapshot is /workspace/scratch/gemini-usage-discovery.json.
This official schema is the primary evidence; no omission-as-zero rule is inferred
from optional SDK types.

Only gemini_usage changes runtime behavior. Its numeric mapping stays input =
strict valid promptTokenCount and output = strict valid candidatesTokenCount +
thoughtsTokenCount. Valid siblings survive invalid fields. Positive tool-use
input remains unmapped; adding it would also alter context anchors and requires
a separate contract. Cache, total and modality details are not added twice.

counts_complete is True only when the three mapped counters are explicit exact
nonnegative integers, toolUsePromptTokenCount is explicitly exact integer zero,
and totalTokenCount, if supplied, is an exact nonnegative integer equal to the
documented sum. An absent redundant total is allowed, but does not synthesize
missing categories. Booleans and fractions cannot satisfy the exact-zero check.
Every other observation is incomplete, including unknown/positive tool-use
input, contradictory totals and absent/non-mapping metadata. Supported explicit
all-zero observations remain available. The nonzero reported predicate and
four-count as_dict serialization are unchanged.

This is a conservative accounting rule, not an API validity rule. An otherwise
valid response missing optional fields remains an answer with estimated cost.
Existing text observers and tool runtime forward the marker; later unavailable
tool observations make the observed aggregate incomplete. Existing accounting
keeps estimates with mapped input/output floors and grants no cache discount or
cached-prefix fallback to incomplete observations. Those floors do not include
the known positive tool-use category that this mapping deliberately omits.

## Preserved boundaries

Text/tool acceptance, retries, tool calls, callbacks and blocked-prompt behavior
are unchanged. The existing stream helper still requires supported terminal
candidate/block semantics, strict prompt/candidate counters and strict thoughts
when supplied. Missing/invalid core counts or malformed supplied thoughts still
produce no event. An accepted terminal lacking thoughts, with unknown/positive
tool-use input or a contradictory total carries an incomplete observation.
Candidate identity/index, terminal-local snapshot replacement, clean exhaustion
and response close, trailer/error and cancellation gates are preserved.

AST comparison confirms all module code outside gemini_usage is unchanged in
tool_dialects.py. The other two source changes only qualify the docstrings of
gemini.py:_stream_terminal_usage and tool_protocol.py:TokenUsage. Their executable
AST, fields and methods are identical to base. Positive inclusive prompt anchors
remain useful independently of output/accounting availability; missing or zero
input does not erase an earlier anchor. This unit does not establish exact full
context occupancy or aggregate tool-use input.

## Verification

Root verified all three production base hashes and every RED failure message
before releasing implementation. Builder RED: 29 cases, 28 failures and one
passing anchor control, 1.231 seconds. The accounting regression reaches the
actual interaction record and reproduces provider instead of estimate; numeric
assertions precede the flag checks. Strict-zero cases include False and 0.0 for
tool-use and 140.0 for the supplied total. Consumer RED: 171 cases, 28 expected
failures and 143 passes, 4.017 seconds. All runtime fixtures offer a benign tool
and reach mocked HTTP and the accepted answer; there are no fixture failures.
Both RED runs have zero errors/skips.

- Nine-module focused union: **272/272**, 5.096 seconds. Direct availability,
  actual text/tool/runtime/stream propagation, cloud dialects, scoped observers,
  accounting, Gemini request context and context anchors.
- Root's disjoint eighteen-module integration: **430/430**, 11.853 seconds.
  Protocol/runtime, compaction and prompt anchors, cost records, Gemini cache,
  prior provider availability, stream usage and route/OpenAPI guards.

Combined: **702 distinct passing cases**, zero failures/errors/skips. Ruff and
diff checks pass. Canonical collection is **21,539 backend cases** (+54),
frontend/native 2,009, mobile 306, 555 routes and 18 agents. Client counts are
reused; no new client test run is claimed.

The single serial full backend milestone on the frozen source passes:
**21,502 passed, 37 skipped, zero failures/errors**, 295.954 seconds, exit 0.
All 21,539 cases match the canonical collected count; the executed-count guard
passes. The 37 skipped case IDs exactly match the earlier persona-dispatch
milestone, with no new skip. This run covers the cumulative Ollama, Anthropic
and Gemini availability follow-ups. No source/test edits followed the frozen
commit. Hermes and generated status checks pass.

## Review, metadata and limits

auth_audit (gpt-6-sol/high) owns the parser/direct tests and independently reviews
root's collateral metadata. mobile_session_transport (gpt-6-sol/high) owns the
actual propagation tests and independently reviews frozen production.
wall_contracts (gpt-6-luna/medium) inventories exact-base evidence; root owns
the contract, critical review, integration, docs and git. Frozen production and
collateral reviews find no Critical/Important issue.

Thirty-three affected evidence pins were current at base and are refreshed only
for their bounded changed claims. Two new H673 test pins are added; all 226
capability statuses and unrelated stale pins remain unchanged. H363/H673 and the
architecture inventory describe Gemini's conservative mapping and its unmapped
tool-use limit. H557's same-target Gemini schema coordinates move by fourteen
lines without a schema behavior change; its earlier Anthropic/ToolSpec pointers
stay unchanged. H686's cache-field citation now points to lines 77-78 of
tool_protocol.py; its missing live chat readout remains open. Immutable inventory
and row identity hashes continue to bind the same research ledger.

The marker covers only parsed observations, not every physical attempt, failed
request, retry, auxiliary model call or a complete-turn bill. No live inference,
model server, billing service, device or GPU was used. The public discovery fetch
is a schema read only. No routes, prices, settings, client contracts or persistent
data change. The independent Anthropic partial-prompt anchor limitation and
legacy availability in other producers remain open.

## Frozen evidence

- tool_dialects.py: 99900b780dc7b264c2ef0432e8692cac1d326d920fc12e149de7f906019f169d.
- gemini.py: 564d5dd61db4a0f4fffd025bc9ae7698c4b1d0630356f068a5452a884af059da.
- tool_protocol.py: 6e57a8bb97728bdd3859376b1fbbb658221b975eabe26143c38fd9267109e936.
- New direct tests: 808bb8ba95346889c62238ac05f7c4986427fe70ca45992e923c1fd4db685c40.
- New propagation tests: 153a238ba067663b6a8eaf905eee4d193a63c267c7e66d628dbe342bf6708f02.

Scratch artifacts in /workspace/scratch use the gemini-counter-availability
prefix: builder-red, consumer-red, builder-focused, integration and backend-final
XML/log pairs; base-hashes.json, source-manifest.json, ast-review.json,
pin-inventory.json/md, pin-refresh.json, consumer-review.md, claim-review.md,
status-sync.log and pr1247-readonly.json. The eight-file manifest includes every
changed source and test. The design note is
gemini-availability-conservative-design-review.md; the official schema snapshot
is gemini-usage-discovery.json. final-result.json records the full-suite counts
and unchanged skip comparison. Read-only GitHub verification shows PR #1247
still OPEN/DRAFT/CLEAN at da7c8a222c2cd0cb658b192c967194bc9c88efa3, with seven
successful executed checks and four conditional skips. This local unit was not
pushed to that PR.
