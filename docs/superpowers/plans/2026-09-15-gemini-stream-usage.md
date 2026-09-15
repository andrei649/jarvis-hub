# Conservative Gemini streaming usage implementation plan

> Execute sequentially with TDD and independent review; no extra agents.

Goal: report trustworthy terminal-local Gemini usage once after natural clean HTTP exhaustion. Base/head before implementation eed3a16faf41f95cd27e6f6dda4c491a9275725c. Generated 2026-09-15. Branch codex/backlog-gemini-stream-usage. Implementation complete; next action independent source review.

## Primary evidence and conservative scope

https://ai.google.dev/api/generate-content defines candidate finishReason as stopped generation, promptFeedback.blockReason as prompt blocking without candidates, and request-level usageMetadata: inclusive promptTokenCount, candidatesTokenCount plus separate thoughtsTokenCount. No stream snapshot summation.

Official SDK inspected revision b88fded4adda37fcc8d1cc4bf49ef3fc11ecfec4: https://github.com/googleapis/python-genai/blob/b88fded4adda37fcc8d1cc4bf49ef3fc11ecfec4/google/genai/_api_client.py iterates to HTTP EOF, closes in finally, and parses raw JSON errors alongside SSE frames; it has no OpenAI [DONE] terminal. https://github.com/googleapis/python-genai/blob/b88fded4adda37fcc8d1cc4bf49ef3fc11ecfec4/google/genai/tests/client/test_async_stream.py tests HTTP200 content followed by raw JSON error, including async paths. models.py yields individual response objects rather than an aggregated usage total.

Only existing mapped finish reasons are supported for one candidate. Explicit known prompt block reasons with absent/empty candidates are also recognized. Terminal usage must be a mapping on that same final response with exact nonnegative promptTokenCount and candidatesTokenCount; optional thoughtsTokenCount must be exact nonnegative if present. For prompt blocking, explicit generated counts must be zero. Existing gemini_usage performs the final mapping, with caches/details/totals not added.

Require natural stream exhaustion and clean response close. A [DONE] compatibility marker preserves current text behavior but does not prove accounting completion. Malformed JSON, error objects, conflicting response IDs or unrecognized/raw body trailers invalidate accounting. Valid SSE comments/metadata remain harmless. Later usage-only or non-terminal frames replace staged eligibility with none rather than reusing earlier metadata. Multi-candidate streams, unknown finish/block reasons and missing final count fields remain unreported. Empty/blocked text remains unchanged.

All staged state lives inside _stream_once, so cache rejection/auth rotation retry starts empty. No public signatures, requests, text extraction/callback behavior, guardrails, pricing, dependencies or global evidence changes. Publish through existing closed observer after successful text extraction/clean response exit only. No live calls or whole H673 closure.

## TDD steps and owned files

- [x] Add tests/test_gemini_stream_usage.py using injected raw async HTTP streams and actual Agent/adapter entry. Observe RED.
- [x] Add private terminal-local validation and attempt-local staging in agents/core/llm/gemini.py only.
- [x] GREEN terminal text/empty/blocked, cumulative snapshots, missing/malformed usage, unsupported/multiple candidates, raw/SSE error trailers after terminal, cancellation/close failures, [DONE], response identity changes, cache/auth retry isolation, concurrent observer isolation and unchanged callbacks/requests.
- [x] Focused Gemini/request-context/usage/abort regressions, whole Ruff and exact Bandit1.9.4 baseline; source commit and independent review. No full backend or global metadata.

## Verification evidence

- Initial actual-adapter RED: 4 failures / 21 passes, `/tmp/nerva-gemini-stream-red.log` (supported completions lacked usage).
- Boundary RED: 3 failures / 31 passes, `/tmp/nerva-gemini-stream-boundary-red.log` (SSE error-event spacing and earlier multi-candidate ambiguity).
- Final focused command: isolated launcher with `pytest tests/test_gemini_stream_usage.py tests/test_stream_token_usage.py tests/test_text_usage_propagation.py tests/test_text_usage_context.py tests/test_gemini_request_context.py tests/test_cloud_token_usage.py tests/test_stream_abort_no_persist.py`; 172 passed, `/tmp/nerva-gemini-stream-final.log`. Added 34 Gemini stream cases. All pytest.ini restrictions retained.
- Whole `ruff check agents scripts tests` passed, `/tmp/nerva-gemini-stream-ruff.log`.
- Exact Bandit 1.9.4 `-r agents scripts -q -b .bandit-baseline.json` passed, `/tmp/nerva-gemini-stream-bandit.log`; no baseline changes.
- No live provider traffic or billing proof. Usage-only final frames, absent terminal-local counts, unknown semantics and ambiguous multi-candidate streams deliberately keep estimates. Shared token/billing semantics unchanged.

## Independent review correction: candidate identity

Candidate.index identifies alternatives even when separate frames contain singleton candidate arrays. Accounting now rejects any supplied index except exact integer zero across the entire attempt; absent index remains supported. This preserves existing text/callback extraction while keeping ambiguous multi-candidate streams unreported. Nine actual-adapter regressions added, including index zero then one across frames, invalid earlier index followed by valid zero, and accepted explicit zero.

RED: 8 failed / 35 passed (`/tmp/nerva-gemini-index-red.log`). GREEN: 181 focused passed (`/tmp/nerva-gemini-index-green.log`), including 43 Gemini streaming cases total. Whole Ruff and exact Bandit baseline passed (`/tmp/nerva-gemini-index-ruff.log`, `/tmp/nerva-gemini-index-bandit.log`). No shared normalizer or response extraction changes.
