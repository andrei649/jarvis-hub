# Conservative Gemini accounting availability

- Generated: 2026-10-09 UTC.
- Goal: partial or unsupported Gemini counter categories must remain estimated.
- Base: d780d5372b0d5ef27ae98bf58912badac771137d.
- Branch/worktree: codex/gemini-counter-availability-20261009,
  /workspace/jarvis-hub-gemini-counter-availability.
- Delivery: autonomous local development, no publication or live inference.
- Tested source: 28aa7dc3d2b88ad01f22ed121038909331bba8fa.
- State: local implementation, independent review and full milestone complete.
- Next action: retain this checkpoint; select the next verified local software
  gap from a clean final head. No publication follows from this unit.

## Evidence and bounded accounting contract

Official Gemini API Discovery revision 20261008, retrieved 2026-10-09 from
https://generativelanguage.googleapis.com/$discovery/rest?version=v1beta,
defines totalTokenCount as prompt + tool-use prompt + thoughts + candidates.
The relevant schema is saved in /workspace/scratch/gemini-usage-discovery.json;
the whole discovery document SHA-256 is
bc75ec1dc53bb3e20ace03d17704fde8bc0ef4ec35cd7c2340618c70e44a42fb.
Prompt counts include cached content. Tool-use prompt is a separate category,
not a cache/detail subset. A three-field flag alone would overlook that input.

Keep the current numeric mapping: strict valid promptTokenCount goes to input;
strict valid candidatesTokenCount plus thoughtsTokenCount goes to output.
Valid siblings survive invalid fields; cache/total/modality fields are never
added twice. Positive toolUsePromptTokenCount remains outside this mapping.
Adding it to input would also alter context anchors and is a separate contract.

Only gemini_usage changes runtime behavior. Set counts_complete=True only when:

1. All three mapped counters are explicit exact nonnegative integers.
2. toolUsePromptTokenCount is explicitly an exact integer zero.
3. If totalTokenCount is supplied, it is an exact nonnegative integer equal to
   the documented sum. An absent total is allowed because it is redundant once
   the category counters are explicit; do not reconstruct missing categories.

Otherwise mark False, including non-mapping/missing metadata, unknown or
positive tool-use input, invalid counters and contradictory supplied totals.
Fully explicit supported zero counts remain observable. This is conservative
application accounting, not an API validity rule: otherwise valid responses
may lack fields and stay estimated. The four-number as_dict and nonzero
reported predicate remain unchanged.

Existing observers/runtime forward the marker. Incomplete accounting keeps
mapped prompt/output floors and grants no cache discount/prefix fallback.
Unmapped positive tool-use tokens are not added to those floors by this unit;
do not claim every known input category is accounted for. The flag is neither
exact spend nor coverage of every physical attempt, retry or complete turn.

## Preserve accepted responses and stream gates

Non-stream text/tool parsing and blocked-prompt responses retain their behavior.
The existing _stream_terminal_usage already validates supported terminal
candidate/block semantics, strict prompt/candidate counters and strict thoughts
if present, then calls gemini_usage. Keep those gates byte-for-byte in behavior:
missing/invalid core counters or malformed supplied thoughts still mean no
event. A terminal accepted under those existing rules but missing thoughts,
with unknown/positive tool-use input or conflicting total stays an observation
with False. Preserve clean EOF/close, error trailers, cancellation, candidate
identity, retries and terminal-local snapshot replacement. No gate is loosened.

Two source docstrings may be qualified: _stream_terminal_usage describes
terminal/core-counter validation, and TokenUsage.counts_complete describes
counters usable under the adapter's accounting contract, not merely presence.
No other behavior outside gemini_usage changes. Prompt anchors still use valid
inclusive prompt counts independently of output completeness; absent/zero input
does not erase an anchor. No exact occupancy or tool-use aggregation is claimed.

## Ownership, regressions and evidence

- auth_audit (gpt-6-sol/high): only gemini_usage behavior in tool_dialects.py,
  the two docstrings in gemini.py/tool_protocol.py, and NEW
  tests/test_gemini_counter_availability.py. Parser, total/tool-use fence,
  actual accounting source/floors/no-discount and independent anchor controls.
- mobile_session_transport (gpt-6-sol/high): NEW
  tests/test_gemini_usage_propagation.py; exact existing expectations in
  tests/test_text_usage_propagation.py, tests/test_cloud_token_usage.py and the
  blocked/no-usage ToolTurn equality in tests/test_cloud_tool_turns.py.
  Actual text, structured/runtime, blocked prompt, later unavailable tool
  response and accepted terminal stream markers. Runtime fixtures must offer a
  benign tool and reach HTTP. Keep existing no-event terminal controls.
- wall_contracts (gpt-6-luna/medium): read-only exact-base pin/claim/citation
  inventory for those paths and optional architecture update.
- Root: contract, failure-message/base-hash verification, source freeze,
  critical review, integration, docs/status and local git. At most four active;
  no nested delegation. Tests first; no production before root RELEASE.

The existing cloud-token no-double-count fixture has positive tool-use input
and an inconsistent total. Keep its numeric mapping assertion but make Gemini
accounting incomplete; add an explicit zero-tool-use consistent/absent-total
control for complete accounting. Do not rewrite other provider expectations.

Run focused Gemini, provider usage, stream/cache and accounting tests, plus
disjoint runtime/context/cost/route guards. Run a full backend milestone after
this provider-availability batch is frozen: the last full suite predates the
Ollama/Anthropic follow-ups, and Gemini adds a consistency/unsupported-category
fence. Run it once serially unless failures justify a correction and repeat.
Collect canonical counts, reusing unchanged client counts. Independently review
source and collateral claims, refresh only formerly-current evidence pins and
preserve all unrelated statuses/stale evidence. Roll back code, tests and proof
as one unit; no routes, settings, prices, client contracts or data migration.

## Execution checkpoint

Root verified all three production base hashes and every RED failure before
releasing production. Builder: 29 cases, 28 failures and one passing anchor
control, 1.231s. Its accounting regression reaches provider-versus-estimate
behavior, and strict-zero tests distinguish False/0.0 from integer zero.
Consumer: 171 cases, 28 failures and 143 passes, 4.017s; actual HTTP/runtime
fixtures reached accepted answers, with no fixture failures. Zero errors/skips.

The nine-module focused union passes 272/272 (5.096s); root's disjoint
eighteen-module integration passes 430/430 (11.853s). Combined 702 distinct
passing cases, zero errors/skips. Independent frozen-source review finds no
Critical/Important issue. AST comparison confirms only gemini_usage changes
runtime behavior; both other source changes are docstrings. Ruff/diff pass.
The source/test SHA-256 manifest and review reports are in /workspace/scratch
with the gemini-counter-availability prefix. One serial full backend milestone
passes on the frozen source: 21,502 passed and 37 skipped, zero failures/errors,
295.954s, exit 0. All 37 skip IDs match the preceding persona milestone.
Canonical and executed totals agree at 21,539 (+54); unchanged client counts
2,009/306 are reused. Hermes/status checks and independent collateral review
pass. Thirty-three formerly-current pins are refreshed, two H673 tests added,
and all 226 statuses/unrelated stale pins retained. Final proof and limitations
are in docs/project-gemini-counter-availability-20261009.md.
