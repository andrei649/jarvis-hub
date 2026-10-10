# H277 shared local auxiliary model routing

Update 2026-10-10: H413 now defaults session titles directly to the declared
small local `DEFAULT_LOCAL_MODEL` (`qwen3:7b`), independently of the active chat
model. The explicit title override remains available. If that model is
unavailable, the instant first-words title stays; no chat-model or cloud retry
is introduced. The other task selectors retain the active-model fallback
described in this original plan. See the [current closure plan](../plans/2026-10-10-hermes-closure-02.md).

Generated 2026-10-02; base `614602123902391ccb5b30ba21c4ce900147b9c6`.
Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Previous goal turn made progress: approved primary video retry passed 20,450
backend tests and an exact-source bounded mutation campaign. This next increment
advances the common task-aware auxiliary selection gap; H277 remains partial.

## Source evidence and scope

The [source map](h277-auxiliary-routing-map-2026-10-02.md) identifies four real
orchestrator consumers that each select the active local model independently:
session titles, recall rewriting, conversation review and context compression.
Hermes resolves task-specific auxiliary provider/model configuration through
`agent/auxiliary_client.py:_resolve_task_provider_model` and its shared clients;
its title generator calls the shared API with `task="title_generation"`.

Nerva already has a shared physical-request policy guard in
`auxiliary_request_scope`; it has no common task-aware invocation/model selection
for these producers. Add a shared invocation seam and four independent model-only
overrides. Adopt all four consumers together, retaining their existing output,
streaming, timeout and offline fallback contracts. This is a functional model
selection feature, not a claim of full Hermes routing/discovery parity.

## Contract

- Fixed task keys and fixed environment names:
  `session_title` / `JARVIS_AUX_SESSION_TITLE_MODEL`,
  `query_rewrite` / `JARVIS_AUX_QUERY_REWRITE_MODEL`,
  `review` / `JARVIS_AUX_REVIEW_MODEL`,
  `compression` / `JARVIS_AUX_COMPRESSION_MODEL`.
  Unknown or non-string tasks refuse with a sanitized configuration error.
- Read at invocation time using `env_config.env_str`, or an explicitly injected
  mapping for pure resolver tests. No prefix enumeration or environment snapshot.
  Unset or ASCII-space-only values preserve the active local model, else the
  existing fallback: `DEFAULT_LOCAL_MODEL` for titles/rewrite/compression and
  `google/gemma-4-31b-a4b` for review. Do not alter active model selection globally.
- Explicit overrides must be strings of at most 256 raw characters, consisting
  of printable Unicode characters (`str.isprintable()`). Trim surrounding ASCII spaces only;
  preserve internal spaces and punctuation as opaque model IDs. Controls/nonprintable characters,
  oversized values and invalid types refuse before dispatch, without
  echoing the input. An invalid override cannot silently use a different model.
  This validation applies to new explicit overrides, not legacy active-model data.
- Select only `router.local_backend`. Never select `.backend`, a cloud fallback,
  a new provider/base URL/key or a live discovered model. The accessor and existing
  H513 policy retain their established locality/consent semantics. A configured
  identifier is not evidence that the backend has that model installed.
- Reject an active job model pin before model/backend selection or generation.
  Keep independent task calls isolated; never mutate router/backend configuration.
  Capture the selected model for the call and pass that exact value to both the
  policy scope and generator. Do not re-resolve to a different model during a call.
- Reuse `auxiliary_request_scope(router, backend, model, role=task)` around the
  entire awaited operation. Retain physical-request policy rechecks and scope
  lifetime; do not implement a second consent layer or inherit interactive consent.
- Titles/rewrite still append `/no_think` only for selected Qwen3 models and keep
  their existing 24/96 token, zero-temperature contracts and output parsers.
  Review keeps its bounded learning token setting, temperature 0.2, JSON system
  prompt and current output handling; it receives no new no-think suffix.
- Compression still calls the existing `compaction_hold.stream_summary` inside
  the policy scope, with the current normalized inactivity setting, token setting,
  temperature 0.2 and system prompt. Preserve streamed activity, cancellation,
  late-scope denial, unusable-response rejection, hold and deterministic digest.
- No retries, new feature activation, API/schema, frontend or dependency changes.
  Existing producers still return None without a router where they do so today;
  their surrounding fallback behavior handles configuration/provider failures.

## Implementation and verification

One new `agents/core/llm/auxiliary_text.py` supplies a pure fixed-task resolver and
an async invocation helper. Change only the four producer methods in
`agents/core/orchestrator.py`. Add focused tests in
`tests/test_h277_local_auxiliary.py`; retain existing producer and H513 regressions.

Write behavioral failing tests through the actual producer methods before helper
implementation: four independent overrides leave the active model untouched;
unset behavior is identical; changes apply to the next invocation; errors are
sanitized and dispatch nothing; Qwen behavior uses the selected model; job pins
and cloud-only routers cannot generate; concurrent tasks retain their own model
and request guard. Test actual request hooks with policy revocation and compression
stream lifetime/cancellation, not only mocks of the authorization function.

Run the relevant producer, H513, router-role and compression/learning suites, then
one full backend at the coherent integration milestone. Reuse source-matched
frontend evidence if its source/schema remain unchanged. Record reviewed evidence
truthfully: do not silently restamp unrelated stale Hermes rows.

## Decisions, limits and rollback

Owner autonomy authorizes local implementation and delegation; no push, merge,
deployment, live/paid model call or credentials/profile import. Use one Sol High
implementer; the parent owns contracts, review, docs and commits.
The four consumers share a contract, so adopt them in one increment instead of
leaving identical selectors split across multiple rounds; the cost is a larger
focused regression surface, covered by their existing suites.

Broader adapters, automatic provider discovery, recovery, acquisition/presence
callers and shared routing beyond these four consumers remain in the full goal.
Rollback the helper adoption and flags to restore active-model-only selection;
no persistent data migration or change to existing approvals is required.
