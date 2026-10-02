# H277 Local Auxiliary Routing Implementation Plan

> Use superpowers:subagent-driven-development. One Sol High implementation writer;
> the parent owns contracts, review, documentation, records and commits.

**Goal:** Select independent local models for four real auxiliary tasks through
one shared guarded invocation path.
**Architecture:** Fixed task-to-model-setting table and pure resolver, consumed by
one async helper. Reuse H513 scope and the existing compression streaming adapter.
**Tech Stack:** Existing Python 3.12, HTTPX and pytest; no new dependencies.
**Spec:** [Local auxiliary design](../../hermes/h277-local-auxiliary-design-2026-10-02.md).
**Base:** `614602123902391ccb5b30ba21c4ce900147b9c6`.

## Global constraints

Local only: no push, merge, deploy, external provider calls or credential imports.
Preserve unrelated work, all existing output/fallback contracts and the full Hermes
objective. New selectors cover local model IDs only, never provider/URL/key routing.

## Review focus

1. Model identity passed to the actual policy check must match generation.
2. Compression child tasks retain guarded lifetime after cancellation/idle cutoff.
3. Concurrent task overrides never mutate shared router state.
4. New invalid settings do not silently select another model or leak their values.
5. Review's legacy fallback and compression's streaming behavior stay distinct
   from title/rewrite defaults and Qwen suffixing.

### Task 1: Shared local invocation and four consumers

Own only new `agents/core/llm/auxiliary_text.py`, the four methods
`_session_titler`, `_query_rewriter`, `_review_llm`, `_compression_summarizer` in
`agents/core/orchestrator.py`, and new `tests/test_h277_local_auxiliary.py`.
Do not edit existing tests or policy/stream/router code without a concrete finding
and ownership transfer from the parent. No commit/stage/full-suite/subdelegation.

Interfaces:
- `AuxiliaryConfigError(ValueError)` with sanitized text only.
- `resolve_auxiliary_model(task: str, active_model: str | None, *,
  env: Mapping[str, str] | None = None) -> str`.
- `async generate_local_auxiliary(router, task: str, *, system: str, prompt: str,
  max_tokens: int, temperature: float, summary_idle: float | None = None) -> str`.
  Compression invokes `stream_summary` (default existing DEFAULT_IDLE if None);
  other tasks invoke `backend.generate`. Keep Qwen behavior task-specific.
Read the design for exact task keys, flags, validation, fallback and guard contract.

- [x] Write behavioral red tests through real orchestrator producers for all four
  overrides, independent from the active model. Capture actual assertion failures;
  a missing module/collection error alone is not red behavior evidence.
- [x] Implement resolver/helper and localized producer changes. Preserve settings
  bounds/system prompts/token budgets/None behavior/streaming. Use a fixed immutable
  task table and env_config reads; no provider discovery or global mutation.
- [x] Add configuration, call-time updates, unknown task, invalid types/controls/
  size, sanitized error, default compatibility and task-specific Qwen cases.
- [x] Verify real H513 guards and job exclusions; concurrent models/scopes, policy
  change before a physical send, and compression child cancellation/late send.
- [x] Run focused tests and scoped Ruff/diff checks. Required selection:
  `tests/test_h277_local_auxiliary.py`, `tests/test_h413_session_titles.py`,
  `tests/test_query_rewrite.py`, `tests/test_h513_auxiliary*.py`,
  `tests/test_h513_data_handling.py`, `tests/test_background_review.py`,
  `tests/test_h674_compaction_hold.py`, `tests/test_context_compression*.py`,
  `tests/test_h277_model_roles.py`, `tests/test_h277_role_routes.py`.
  Use `/tmp/nerva-pr-python-20261001/bin/python`, repository timeout/socket guards,
  and JUnit in this plan's ignored workspace. Report exact red/green and limitations.

### Task 2: Review, records and local integration

Parent owns `.env.example`, `docs/FLAGS.md`, BACKLOG/parity/count/status records,
implementation report and continuation. No runtime overlap with Task 1.

- [x] Review the complete increment against the five focus points; obtain a
  bounded independent read-only review. Fix concrete findings red-first.
- [x] Document four optional model IDs and preserved behavior. Re-read affected
  Hermes evidence and keep H277 partial; never promote unrelated stale rows.
- [x] Commit coherent source, regenerate truthful records/counts, freeze a clean
  commit and run the full backend once. Reuse frontend evidence only with source
  and schema equality. Record exact warnings/skips/expected failures separately.
- [x] Run documentation/status checks, exact-index secret scans and save a local
  checkpoint with next action. Preserve reports before deleting only this plan's
  ignored workspace; the full parity goal remains active.

Implementation verified locally; owner-authorized publication is tracked in the PR integration continuation. The full Hermes goal remains active. Source/test evidence and
remaining work are recorded in [the continuation](../../hermes/local-continuation-2026-10-01.md).
