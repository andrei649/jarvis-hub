# H277 next auxiliary routing map (read-only)

Snapshot reviewed: Nerva integration base `414978c1` (listed producer/guard files unchanged during review) and pinned Hermes source `hermes-agent-59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. This report intentionally excludes the active video-retry implementation.

## Contract state

The H277 row in `docs/hermes/assessment.json` is still `partial`. It already records the role table, H513 dispatch guards, advisory judge coverage, and video consumer/provider work. The row's remaining field says: “Additional auxiliary adapters and shared routing, pinned upstream automatic provider discovery, same-provider retries and SDK credential recovery remain unfinished.” `docs/handoff/h277/README.md` likewise says broader auxiliary routing remains unfinished. This is a routing/configuration gap beyond video; it does not imply the role table is absent.

## What Nerva already has

`agents/core/llm/model_roles.py:ROLES` defines `main`, `deep`, `vision`, `video`, and `approval_judge`. `resolve()` and `describe()` provide common role configuration and introspection. Consumers are uneven by design: vision goes through `vlm.resolve_vlm_config`; video through the registered `VideoAnalysisTool.execute()` consumer in `video_analysis.py`; judge through `ApprovalJudge` wired to both `ActionApprovalQueue` and the persisted BLOCKED Decision Inbox task adapter (`TaskApprovalJudge`); deep only exposes `model_config.get_deep_model()` / `is_deep_model_configured()` for the router's local deep slot. `main` remains settings-selected and guarded.

There is already a shared **policy/dispatch guard seam**, `agents/core/llm/data_handling.py:auxiliary_request_scope()`. It captures a concrete router/backend/model and rechecks policy at physical requests. Existing producers use it with individual purpose strings; it does not select a model/provider or create a reusable auxiliary client/route. Thus adding another generic selector beside it would duplicate policy plumbing, while routing remains genuinely unshared.

Current exact producer seams include:

- Async, strict-local calls in `agents/core/orchestrator.py`: `_session_titler()` returns async `_generate` (role `session_title`, consumed by `session_titles.model_title`); `_query_rewriter()` returns async `_generate` (`query_rewrite`, consumed by memory query rewrite); `_compression_summarizer()` returns async `_summarize` (`compression`, consumed by compaction); `_review_llm()` is async (`review`, called by background/on-demand review). Each independently selects `router.local_backend` and `router.active_model`/fallback, then scopes `backend.generate()`.
- Async, strict-local acquisition producers in `agents/core/acquisition/llm_synth.py`: `generate_capability()` and `draft_plan()` each make up to two `backend.generate()` attempts under scopes `acquisition_capability` and `acquisition_draft`.
- Async optional local explanation in `agents/core/house/presence.py:LocalPresenceExplainer.explain()`; its `from_router()` constructor pins `local_backend` and active model, and it checks router/backend identity before scoped generation.
- The video role is its own approved ToolRPC consumer. The approval-judge role is likewise already routed and policy-guarded. Neither is the next generic auxiliary consumer.

The inspected eligible calls are async. The sync and async distinction matters because H513's context-managed guard covers both only while actual backend dispatch occurs; a candidate should preserve request-level scope and job-selection exclusions. There is no Nerva `get_text_auxiliary_client`/`call_llm`-style shared consumer that takes a task name and resolves its model/provider. `HybridRouter` is the main router; `model_roles` is configuration/introspection rather than a general auxiliary invocation API.

## Hermes comparison

Hermes centralizes auxiliary call execution in `agent/auxiliary_client.py`: `get_text_auxiliary_client(task, main_runtime=...)` (line ~5489), `call_llm(task, ...)` (~7849), and `async_call_llm(task, ...)` (~8146), with `get_async_text_auxiliary_client()` (~8234). The sync/async dispatch paths share task config resolution, concurrency limits, validation, same-provider retries and recovery/fallback handling. Task-specific `auxiliary.<task>.*` configuration is resolved in `_resolve_task_provider_model()` (searchable in the same module); examples include `auxiliary.compression`, `auxiliary.background_review`, `auxiliary.title_generation`, `auxiliary.curator`, and `auxiliary.side_question`. This is a canonical task-aware auxiliary funnel, not merely a fixed role list.

Concrete Hermes callers include `agent/context_compressor.py` and `agent/micro_compaction.py` using sync `call_llm()`, `agent/plugin_llm.py` exposing sync and async calls, plus async workflows such as title generation and background review. The key transferable contract is task-keyed shared routing/execution with common provider behavior; copying Hermes's broad provider/recovery implementation would exceed a narrow next increment.

## Candidate next seams (ranked)

1. **One shared strict-local async auxiliary invocation seam, first adopted by `_session_titler()` and `_query_rewriter()`.** These two are the smallest pair with identical mechanics: choose local backend/model, reject active job-model pins, apply Qwen no-think behavior, scope the physical request, call `generate()`. A shared task-aware resolver/dispatcher can make their selection common while preserving strict-local semantics, H513 `auxiliary_request_scope`, per-task token/temperature/system settings, and their separate output parsers. This adds a real common auxiliary consumer without adding another selector for video or judge.
2. **Extend the same seam to `_compression_summarizer()` and `_review_llm()`.** Both are raw-conversation consumers that intentionally fail closed to local inference and have independent bounded output behavior. They are the strongest next integrations after the first pair, but streamed compression and its hold/degraded-response rules make compression a larger first slice.
3. **Shared route application for `generate_capability()` / `draft_plan()` in `llm_synth.py`.** Both repeat the two-attempt strict-local request loop and differ mainly in task and output schema. This is bounded and clean, but acquisition is narrower and may not demonstrate broad auxiliary routing as clearly as the orchestrator producer pair.

## Remaining H277 requirements after such an increment

Even a shared local async selector/consumer would leave H277 partial. Remaining explicit inventory items include additional auxiliary adapters and shared routing beyond the adopted callers; pinned upstream automatic provider discovery, same-provider retries, and SDK credential recovery; native Gemini large-video upload/lifecycle and live video-model acceptance. The current H277 row already records advisory judging for action approvals and persisted BLOCKED Decision Inbox tasks; this report does not treat historic kernel/ToolRPC handoff text as an open judge gap. Keep these separate: the candidate above establishes shared Nerva routing at actual auxiliary producer call sites, but it does not establish Hermes parity or live/provider acceptance.

## Source pointers

- Nerva role configuration: `agents/core/llm/model_roles.py:ROLES`, `resolve()`, `describe()`.
- Nerva existing guard: `agents/core/llm/data_handling.py:auxiliary_request_scope()`.
- Nerva candidate producers: `agents/core/orchestrator.py:_session_titler`, `_query_rewriter`, `_review_llm`, `_compression_summarizer`; `agents/core/acquisition/llm_synth.py:generate_capability`, `draft_plan`; `agents/core/house/presence.py:LocalPresenceExplainer.explain`.
- Nerva current consumers: `agents/core/llm/vlm.py:resolve_vlm_config`; `agents/core/video_analysis.py:VideoAnalysisTool.execute`; `agents/core/autonomy/approval_judge.py:ApprovalJudge` plus `task_approval_judge.py:TaskApprovalJudge`; `agents/core/llm/model_config.py:get_deep_model`.
- Hermes shared funnel: `agent/auxiliary_client.py:get_text_auxiliary_client`, `_resolve_task_provider_model`, `call_llm`, `async_call_llm`, `get_async_text_auxiliary_client`; selected callers `agent/context_compressor.py`, `agent/micro_compaction.py`, `agent/plugin_llm.py`, `agent/title_generator.py`, `agent/background_review.py`.

## Source fingerprints

Read-only Luna Medium investigation with parent verification of the producer names
and current judge integration; no tests or model calls. File SHA256 values:

- `agents/core/llm/model_roles.py`: `d96eeef6a8a07b526143e873365645d299860c75e975919fa064367fa8a8815e`
- `agents/core/llm/data_handling.py`: `93fd8f550218a2248dbc30bb9659335a317e53ba6d919cc476209b7450035166`
- `agents/core/orchestrator.py`: `4e31f75e9907e53f37935a72c474223b8933dd560f41133327bd2fd402193513`
- `agents/core/acquisition/llm_synth.py`: `6d77c923d70999836ea75ab5a6d77bdbbdb9844a6b56c000b766efb02f200565`
- `agents/core/house/presence.py`: `c0948190a773116a7ffe3f0b6b5a823e658085c729cfc70dbae11b3510f02fa6`
