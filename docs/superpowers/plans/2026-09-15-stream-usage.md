# Terminal streaming usage implementation plan

> Execute sequentially with TDD; no additional agents or live provider requests.

Goal: publish one complete usage measurement after verified stream termination for Ollama, LM Studio and Anthropic. Base/head before implementation: 8c76332d95305476231745e9f6b7b2637ab9009b. Generated 2026-09-15. Branch codex/backlog-stream-usage. Next action: RED fixtures before implementation.

## Contracts and scope

Ollama: https://docs.ollama.com/api/generate and https://docs.ollama.com/api/streaming define done=true completion. Only literal boolean true qualifies; capture terminal prompt_eval_count/eval_count through existing strict normalizer. Intermediate counts do not become a completed measurement.

LM Studio: https://lmstudio.ai/docs/developer/openai-compat/chat-completions delegates response schema to OpenAI. https://developers.openai.com/api/reference/resources/chat documents an optional usage-only final chunk with choices:[] before [DONE]; interrupted streams may lack it. Handle empty choices without crashing; retain final usage snapshot, require [DONE], add no stream_options or other request fields.

Anthropic: https://platform.claude.com/docs/en/build-with-claude/streaming specifies message_start, cumulative message_delta usage (replace, never add), and message_stop. Preserve disjoint input/cache categories from message_start; later supplied fields replace earlier values. Require start and stop, suppress reporting after error events even within HTTP200. Keep thought filtering and existing text behavior intact.

All providers: attempt-local counters, no global/backend mutable usage. Report via existing report_text_usage only after finalization and clean stream exit. Cancel, HTTP/transport error, malformed frame, or missing terminal yields no measurement; existing estimates remain. LM Studio unloaded retry resets staged counters. Existing text callbacks/public signatures/guardrails unchanged. Gemini and generic native OpenRouter SSE implementation deferred; no live/billing proof or full H673 closure.

## Paths and test-first steps

- [x] Add tests/test_stream_token_usage.py with injected raw async streams through actual adapters/Agent entry: valid terminal once, cumulative replacement, cache-only Anthropic, usage-only LM choices, literal Ollama boolean, missing terminal, SSE error, malformed metadata/frame, transport failure/cancel, retry reset, thinking filters and unchanged payload. Observe RED.
- [x] Implement bounded staged accounting in agents/core/llm/base.py and anthropic.py, adding a small pure parser module only if necessary. No protected edits or dependencies.
- [x] GREEN focused stream/text/structured/retry/abort tests, whole Ruff and Bandit1.9.4 baseline. Record exact results and commit source/plan only; controller independently reviews and owns metadata/full backend.


## Verification and review handoff

Implementation complete 2026-09-15; next action independent review. Baseline RED: six failures / eighteen passes in `/tmp/nerva-stream-red-bounded.log`, proving missing measurements, cumulative/cache retention, and LM Studio usage-only parsing. Initial RED cancellation fixture waited for a stream that had already failed on empty choices and hit the timeout; bounded the readiness race, reran original source, then restored implementation. Initial adjacent GREEN: 107 passed (`/tmp/nerva-stream-green.log`).

Final: 258 passed in 2.48s (`/tmp/nerva-stream-final.log`), including 34 new stream cases. Whole agents/scripts/tests Ruff passed (`/tmp/nerva-stream-ruff.log`); exact CI Bandit1.9.4 baseline passed (`/tmp/nerva-stream-bandit.log`, existing comment warnings only). git diff --check passed. No full suite, global status/assessment, dependency, protected guardrail, request-signature or live-provider changes.

Command: `/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_stream_token_usage.py tests/test_text_usage_context.py tests/test_text_usage_propagation.py tests/test_lmstudio_model_unloaded_retry.py tests/test_cloud_tool_turns.py tests/test_stream_abort_no_persist.py tests/test_local_token_usage.py tests/test_cloud_token_usage.py tests/test_complete_prompt_anchor.py tests/test_context_usage_anchor.py`.

Runtime scope is only base.py and anthropic.py. Counts from incomplete streams remain unknown, not free. Token field validation and disjoint cache mapping reuse reviewed normalizers; no new pricing claims. Gemini terminal usage is deliberately deferred.

## Independent review repair

P2 reproduced: malformed final Anthropic usage retained intermediate output, and missing message_delta retained message_start output; malformed start containers could also appear as complete requests. Added 12 actual-adapter regressions, including valid final zero output with independently malformed input and preserved cache counts. RED: 11 failed / 35 passed (`/tmp/nerva-stream-review-red.log`). Repair requires mapping start usage and an exact nonnegative integer output_tokens supplied by the final message_delta; every delta refreshes this readiness, so a missing/malformed final update cannot reuse earlier output. Malformed supplied start/delta containers invalidate the staged measurement. This validates streaming completeness only: existing global normalizers, TokenUsage and billing semantics are unchanged. Other independently valid fields retain their existing per-field normalization.

Final repaired suite: 270 passed in 2.20s (`/tmp/nerva-stream-review-green.log`), 46 new stream cases total. Whole Ruff and exact CI Bandit1.9.4 baseline passed (`/tmp/nerva-stream-review-ruff.log`, `/tmp/nerva-stream-review-bandit.log`); diff clean. Reviewer must clear this finding against the final repair commit. No rebase or global metadata changes.

## Integration preparation

Verified exactly two owned commits and byte-identical touched source between text base 8c76332d and gallery base cb0b9b872a0cfbbbf9245c3e3410951fc12c11b0 before replay. Rebased source commits: f2d3f0b4 and b45fcce8. Refreshed only 11 matching source-evidence references and H673 partial prose; inventory unchanged. Fresh backend collection 11,229; unchanged frontend/mobile 1,262/137; routes 500.

Integrated runtime/status/Hermes suite: 338 passed in 4.49s (`/tmp/nerva-stream-integrated-tests.log`). Whole Ruff and exact Bandit1.9.4 baseline passed (`/tmp/nerva-stream-integrated-ruff.log`, `/tmp/nerva-stream-integrated-bandit.log`). Status/Hermes generated checks and diff checks passed. No full backend execution or publication; controller owns final integration. Gemini actual streaming accounting remains deferred.
