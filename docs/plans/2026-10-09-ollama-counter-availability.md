# Ollama response counter availability

- Generated: 2026-10-09 UTC.
- Goal: partial Ollama counters must not be treated as complete provider totals.
- Base: de70661489cd5c69b245de23186d77ece040629f.
- Tested source: 8363102c85a78e584aae9cce520def9e70c80607.
- Branch/worktree: codex/ollama-counter-availability-20261009,
  /workspace/jarvis-hub-ollama-counter-availability.
- Delivery: autonomous local development; no remote publication or live provider.
- Status: implementation, independent review, focused/integration verification
  and canonical evidence complete. No further action within this unit.

## Bounded contract

Only ollama_usage in agents/core/llm/tool_dialects.py changes production behavior.
It keeps each strict nonnegative integer prompt_eval_count/eval_count, replaces
invalid fields with zero, and sets counts_complete=True only when both fields
are valid. Missing/malformed/partial pairs are explicitly False, including an
unavailable all-zero pair. A supplied valid zero pair is True. Booleans, strings,
floats (including whole-valued and nonfinite values), negatives and containers
are not integers for this contract. Do not infer discounts from cache/total
fields. TokenUsage.reported and the four-field as_dict representation stay intact.

Existing observers/runtime forward flagged unavailable and valid-zero samples.
Existing accounting must use estimates with observed count floors for incomplete
pairs, and keep complete-zero observations distinct from absence. Prompt anchors
remain independent: positive valid input still anchors when output is missing;
output-only or absent input cannot create or erase an anchor. Actual tool-loop
aggregation with a later unavailable response must remain incomplete.

Preserve successful HTTP/JSON behavior of non-stream /api/generate and /api/chat;
this unit adds no done-validation gate. Streaming retains its existing literal
done-is-True, malformed-frame, error and transport/cancellation gates. Answers,
tool calls and thinking-exhausted replies are preserved. This flag describes
only counter availability for an observed parsed response, not all physical
attempts, retries, whole-turn cost or exact tokenization. No routes, schemas,
settings, prices, other providers or client code change.

## Ownership and verification

- auth_audit (gpt-6-sol/high): only production tool_dialects.py and new
  tests/test_ollama_counter_availability.py. Parser/normalization and direct
  accounting/anchor regressions. Tests first; wait for root RELEASE before code.
- mobile_session_transport (gpt-6-sol/high): new
  tests/test_ollama_usage_propagation.py and precise existing expectations in
  tests/test_text_usage_propagation.py and tests/test_stream_token_usage.py.
  Actual mocked text, tool/runtime and terminal stream propagation, unavailable
  later tool iteration, zero and partial controls. No production changes.
- wall_contracts (gpt-6-luna/medium): read-only exact-base pin and claim inventory
  for those paths plus docs/ARCHITECTURE.md. No repository edits or tests.
- Root: scope, source freeze, critical review, integration, docs/status and git.
  At most four active agents; no nested delegation.

Root verifies the production base hash before both RED runs are accepted. After
green, independent review checks the one-function scope and reachable consumer
semantics. Focused provider/usage/stream/protocol suites plus disjoint accounting,
runtime, context, compaction and route/OpenAPI checks cover this parser unit.
The immediately preceding full backend milestone already passed 21,372 cases
with 37 skipped at 42013de; do not relabel that historical result as this source.
Do not repeat the full suite unless new changes/failures or unresolved scope
justify it. Collect the current canonical count, reusing unchanged client counts.

Refresh only previously-current evidence pins after collateral claim review;
preserve pre-existing stale evidence and all unrelated capability statuses.
Rollback the parser, regressions and evidence as one local unit. No data migration.

## Implementation checkpoint

Root verified the unchanged production hash for builder RED: 26 cases, 22 failed
and 4 passing controls (2.381 seconds). Initial consumer RED: 87 cases, 17 failed
and 70 passed (3.512 seconds); four failures were caused by an empty tool registry
fixture and are not counted as production regressions. After a benign offered
tool fixed the fixture, root restored only the parser to the exact base and
confirmed those four actual runtime cases failed for missing availability flags
or missing zero events (1.169 seconds), then restored the candidate.

The final ten-module focused union passes 292/292 (5.389 seconds), and the root's
disjoint thirteen-module integration passes 344/344 (8.004 seconds): 636 distinct
passing cases, no errors/skips. Only ollama_usage changes production behavior;
the other 28 module functions and other module AST are identical. Canonical
collection is 21,450 backend cases (+41); client counts are reused. No new full
backend run is claimed for this parser-only unit after the preceding milestone.
Independent production and collateral-claim reviews have no Critical/Important
finding. Twelve previously-current pins are refreshed; two new H673 test pins
are added, all 226 capability statuses preserved. Hermes/status, Ruff and diff
checks pass. See [final evidence](../project-ollama-counter-availability-20261009.md).
