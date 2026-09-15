# H673 cloud structured-turn usage and complete prompt anchors

Goal: preserve reported Gemini/explicit OpenAI-compatible structured-turn counts and correct cached Anthropic context occupancy. Base: 4376780dd38cf3604852d5084fcd564832f8d7e2. Head: pending. Generated: 2026-09-15. Next action: RED focused tests, minimal implementation, GREEN regression suites, independent review.

## Verified contracts

https://ai.google.dev/api/generate-content defines promptTokenCount inclusive of cached content, candidatesTokenCount across candidates, thoughtsTokenCount separately, and totalTokenCount as prompt + candidates + thoughts. Map prompt total to input and candidates + thoughts to output. Ignore total, modality breakdowns and toolUsePromptTokenCount rather than inventing additions.

https://openrouter.ai/docs/cookbook/administration/usage-accounting reports usage.prompt_tokens and completion_tokens plus nested breakdowns. https://platform.openai.com/docs/api-reference/chat/create counts reasoning within completion totals. Use only standard totals with explicit openai-compatible backend_kind. No usage request options, inferred vendor mappings or network calls.

https://platform.claude.com/docs/en/build-with-claude/prompt-caching defines total input as input_tokens + cache_creation_input_tokens + cache_read_input_tokens. Current anthropic_usage preserves these disjoint categories; current context anchor reads only input, undercounting cache and ignoring cache-only requests. Sum those three categories for occupancy; billing stays unchanged. Local/Gemini/compatible totals carry zero cache categories, so the same sum never duplicates their cached subset. Document TokenUsage's existing disjoint contract explicitly.

## Implementation units and boundaries

1. Correct _record_context_anchor with cached and cache-only regressions, preserving latest-request replacement and zero/unreported behavior. No Anthropic normalizer or billing changes.
2. Add strict cloud normalizers in tool_dialects, wire Gemini and OpenRouter tool turns; preserve content/tool parsing, thought signatures, routing, requests and per-session isolation. Only nonnegative exact ints count; booleans, floats, strings, negative/nonmapping fields become zero independently. No synthesis from totals. Missing usage retains estimates. Malformed metadata must not discard valid content.

Paths: agents/core/orchestrator.py, agents/core/llm/tool_protocol.py, tool_dialects.py, gemini.py, openrouter.py; focused new tests and this plan only.

## Tests before implementation

- Anchor from actual Anthropic normalizer includes ordinary input, cache reads and writes; cache-only requests update; latest prompt replaces instead of accumulates; empty usage preserves prior anchor; output never contributes; billing tuple unchanged.
- Normalizer valid, malformed, absent, zero and inconsistent breakdown cases; Gemini thoughts added exactly once; compatible details never added; explicit/unknown profile guard.
- Injected HTTP adapters preserve text/tool-only responses, blocked Gemini usage and unchanged request parameters. Runtime sink receives measurements; concurrent requests remain independent; all normalized mappings anchor complete prefix once.
- Run focused cloud/local usage, existing cloud tool turns and context anchor tests with isolated launcher and pytest.ini intact; scoped Ruff/diff check. No full suite, paid/live provider calls, dependencies, authority changes or global metadata. H673 remains partial: cache discounts, billing premiums, string/stream usage, and provider-specific undocumented semantics are outside this unit.

## Verification

Implemented and locally verified 2026-09-15. Anchor RED: 3 failures / 2 passes, proving mixed/read-only/write-only cache omissions; `/tmp/nerva-cloud-anchor-red.log`. Anchor GREEN with existing context/local cases: 60 passed, `/tmp/nerva-cloud-anchor-green.log`. Cloud RED: 42 failures / 1 pass for absent normalizers/adapter usage, `/tmp/nerva-cloud-usage-red.log`; initial combined GREEN exposed a test-only cleanup mismatch (Gemini has no aclose method), corrected to close injected client. Final: 181 passed in 2.07s, `/tmp/nerva-cloud-usage-final.log`; 56 added cases (51 cloud, 5 anchor). Scoped Ruff and git diff --check passed. Independent review is next; no whole-row H673 closure or live-provider billing proof.

Command (pytest.ini retained): `/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_cloud_token_usage.py tests/test_complete_prompt_anchor.py tests/test_context_usage_anchor.py tests/test_local_token_usage.py tests/test_cloud_tool_turns.py`.

## Integration preparation

Verified original base ancestry and replayed only the two cloud commits onto URL head `af033f6d0a5d49d49ca541f523d9fd083fe59a00`; rebased source head `32af93b6` (anchor `2032bec0`). Runtime diff unchanged. Fresh backend collection: 11,092; unchanged frontend/mobile counts reused at 1,247/137; 498 routes. Integrated focused runtime/status/Hermes tests: 249 passed in 2.26s (`/tmp/nerva-cloud-integrated-tests.log`). Whole agents/scripts/tests Ruff passed; exact CI Bandit 1.9.4 baseline scan passed with existing comment warnings (`/tmp/nerva-cloud-integrated-bandit.log`). Status and Hermes generated checks and git diff --check passed. Updated only 23 evidence references whose old hashes matched inspected URL-base source; older mismatches remain untouched. Full backend execution is reserved for controller integration, not claimed here.
