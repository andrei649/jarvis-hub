# Local structured-turn usage normalization

Base: de17ba32a23e5d202de497125d61ae1ee468e5d1. Scope: H673 local usage gap only; row remains partial.

## Design

LMStudioBackend and OllamaBackend already return structured ToolTurn responses but discard token counts. Add pure normalizers in tool_dialects.py and attach TokenUsage to their successful generate_tool_turn results. Existing AgentToolRuntime usage_sink and orchestrator context anchors carry the measurement. Do not add mutable last-response state, requests, authority, dependencies or change Anthropic normalization.

Official protocol evidence reviewed 2026-09-15:
- https://docs.ollama.com/api/chat and https://docs.ollama.com/api/usage: top-level prompt_eval_count is total prompt tokens; eval_count is generated tokens. Cached prompt tokens are already part of the total, never add them.
- https://lmstudio.ai/docs/developer/openai-compat/tools: tool-only /v1/chat/completions response contains usage.prompt_tokens and usage.completion_tokens alongside choices.

Accept only nonnegative Python integers excluding bool; other values independently become zero. Preserve existing TokenUsage.reported semantics (all-zero means unavailable). Do not derive missing input from total_tokens or cache counters, infer billing/cache savings, or change provider request bodies. No stream/string-return API changes.

## TDD steps

1. Write failing normalization and actual HTTP-mocked backend tests for ordinary/tool-only output, zero/missing/malformed counts and sibling preservation.
2. Add pure ollama_usage and lmstudio_usage helpers; wire both successful structured response paths without changing tool-call parsing or finish reasons.
3. Prove backend measurements pass the runtime sink to context anchors: last input replaces rather than sums, output-only/no usage preserves prior input, distinct sessions remain isolated and transcript-prefix coverage stays unchanged. Concurrent calls share a backend without response-state leakage.
4. Run one focused pytest process with repository guards, isolated JARVIS_HOME, TMPDIR=/private/tmp, JARVIS_TESTING=1, NERVA_PUBLIC_PROFILE=0 and dotenv disabled. Run scoped Ruff/diff. Commit scoped paths, parent owns global evidence/counts and review.

## Limits and rollback

No paid/live provider calls. Evidence proves request/response normalization with mock HTTP, not vendor acceptance, cache hits or billing. H671 lineage/compaction timing and other cloud usage gaps are outside this unit. Rollback is one commit revert; no storage migration.

## Verification

Implemented and locally verified; independent review remains parent-owned.

- RED: tests/test_local_token_usage.py: 34 failures before runtime edits, all from missing normalizers/usage. /tmp/nerva-local-usage-red.log.
- Initial GREEN: all 34 new tests passed. Added four runtime/malformed-backend acceptance cases; fixed empty-allowlist test fixture after the real runtime correctly refused it.
- Final: 215 passed, 0 failed in 2.83s; /tmp/nerva-local-usage-final.log. New collected-test delta: +38.
- Command (through /tmp/nerva-run-isolated.py with the isolated environment above): python3.12 -m pytest tests/test_local_token_usage.py tests/test_provider_context_limits.py tests/test_context_usage_anchor.py tests/test_agent_runtime_v2.py tests/test_cloud_tool_turns.py tests/test_lmstudio_model_unloaded_retry.py.
- Scoped Ruff and git diff --check passed. No frontend, full-backend, or live-provider claim.
- Runtime diff is two normalizers, one strict count helper, and usage attachment at the two existing structured-return sites. Anthropic parser and protected authority code unchanged.

