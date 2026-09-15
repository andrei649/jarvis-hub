# Complete text-response usage implementation plan

> Execute sequentially with TDD and verification-before-completion; no subagents.

Goal: retain successful non-stream provider usage through existing agent meters and complete-prefix anchors without changing public string/stream signatures. Base/head before implementation: 041b507309c7b014c44ce3ba71f88ffa5e853dd0. Generated 2026-09-15. Branch codex/backlog-text-usage. Next action: RED tests.

Architecture: a new llm/usage_context.py contains two request-local scopes: the caller observer, and a provider-publication scope enabled only for legacy generation. Both close their callable lifetime and restore ContextVars in finally. ToolRuntime remains the sole publisher of ToolTurn usage. No shared backend state, new request parameters, callback-bearing prompt context or protected guardrails edits.

## Verified source contracts

Agent.generate_response forwards usage only to the tool runtime. _call_agents_parallel supplies none and clears its usage map after gather, so non-stream channels also lose structured measurements. Bind an observer per _run_agent around the awaited process, capture agent ID and local per-turn usage map, and install that map after gather. Scope provider publication only inside Agent's legacy call: synthesis, compression and background direct calls remain outside it. Existing streaming orchestrator observer continues to work.

Text adapters reuse established strict normalizers for Ollama /api/generate, LM Studio usage, Gemini usageMetadata, explicit openai-compatible totals; Anthropic uses its existing disjoint normalizer. Publish after successful response parsing/finalization, once per accepted response. Errors/missing counts keep estimates. Existing Gemini cache/auth and LM Studio unloaded retries are preserved; unsuccessful attempts publish nothing. OpenRouter's inherited generate_stream calls generate and thus may publish once. Actual Ollama/LM Studio/Gemini/Claude stream terminal accounting is explicitly deferred.

Official contracts: https://docs.ollama.com/api/generate; https://lmstudio.ai/docs/developer/openai-compat/tools; https://ai.google.dev/api/generate-content; https://openrouter.ai/docs/cookbook/administration/usage-accounting; https://platform.claude.com/docs/en/build-with-claude/prompt-caching. Input/cache categories and billing unchanged from prior reviewed cloud unit.

## Sequential increments

- [x] Write scope and Agent/non-stream caller regressions; watch RED. Implement usage_context.py, agent.py and orchestrator.py bounded wiring; GREEN and scoped Ruff/Bandit.
- [x] Write complete-response provider integration regressions; watch RED. Instrument generate only in llm/base.py, gemini.py, anthropic.py, openrouter.py. GREEN and scoped Ruff/Bandit.
- [x] Combined focused adjacent tests, whole Ruff and exact Bandit1.9.4 baseline; commit source/evidence. No full backend/global status or assessment.

## Test matrix

Nested observer restoration, cancellation, callback errors and late child-task rejection; unchanged strings/callback behavior; tools report once despite potential ambient publication; inherited OpenRouter stream once; actual non-stream gather meter/anchor with tools on/off; per-agent/session concurrency and next-turn reset; direct synthesis/background calls unreported; successful provider text and missing/malformed metadata; reasoning-exhaustion returns; explicit profile guard; model-unloaded retry and Gemini cache rejection/auth rotation; failed responses do not report; protected guardrails input blocks prevent requests and output policy unchanged. Test files: test_text_usage_context.py and test_text_usage_propagation.py. Existing local/cloud token usage, cloud tools, context anchors, reasoning timeout, taint, abort, Gemini request context and LM Studio retries are adjacent checks.


## Verification and handoff

Source complete 2026-09-15; next action independent review. Context RED: 5 failures from absent scoped wiring, `/tmp/nerva-text-context-red.log`. Nested tool-publication RED: 1 failure, `/tmp/nerva-text-nested-red.log`; corrected by masking inherited publisher at Agent.generate_response entry. Context/timeout/taint/abort GREEN: 43 passed, `/tmp/nerva-text-context-green.log`. Provider RED: 9 failed, 11 passed, `/tmp/nerva-text-providers-red.log`; GREEN plus cache/model retry suites: 47 passed, `/tmp/nerva-text-providers-green.log`.

Final guarded focused suite: 274 passed in 7.45s, `/tmp/nerva-text-final.log`. Thirty new cases (5 context, 25 provider/caller cases). Whole agents/scripts/tests Ruff passed (`/tmp/nerva-text-ruff.log`); exact CI Bandit 1.9.4 baseline over agents/scripts passed (`/tmp/nerva-text-bandit.log`, existing comment warnings only). Incremental scoped Ruff/Bandit passed too. git diff --check clean. No full backend run, source status/assessment refresh, dependencies, live provider calls or protected guardrails edits.

Final command: `/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_text_usage_context.py tests/test_text_usage_propagation.py tests/test_local_token_usage.py tests/test_cloud_token_usage.py tests/test_cloud_tool_turns.py tests/test_context_usage_anchor.py tests/test_complete_prompt_anchor.py tests/test_reasoning_timeout.py tests/test_tool_result_taint.py tests/test_stream_abort_no_persist.py tests/test_lmstudio_model_unloaded_retry.py tests/test_gemini_request_context.py tests/test_session_birth_persistence.py`.

Remaining: actual streaming-provider terminal usage frames are deliberately not counted. OpenRouter's inherited stream obtains one complete generate response and reports that once. Synthesis/background calls are outside provider-publication scope. Billing/pricing representation and heterogeneous-route context limits are unchanged; no whole H673 closure.

## Integration preparation

Replayed only source commit 29a82ab3 onto H139 local base f123446cfc61355b9e08b92cf0b17cac8d0f8460, producing source head ea3a800a. The original local base is not an ancestor after squash integration; all six modified existing source files were verified byte-identical between 041b5073 and H139 before evidence refresh. Adjacent VLM changes preserved. Updated only 30 matching inspected source-hash references, leaving older mismatches and the frozen inventory unchanged. H673 remains partial.

Fresh collection: backend 11,149; frontend/mobile reused unchanged at 1,257/137; routes 500. Integrated runtime/status/Hermes suite: 342 passed (`/tmp/nerva-text-integrated-tests.log`). Whole Ruff and exact Bandit1.9.4 baseline passed (`/tmp/nerva-text-integrated-ruff.log`, `/tmp/nerva-text-integrated-bandit.log`); generated status/Hermes and diff checks passed. No full backend execution. Controller will replay the source and metadata commits onto actual H139 merge 96651993, whose tree matches the tested local base.
