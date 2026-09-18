# Specialist-route shared compaction implementation plan

Goal: bound shared history by the routes that will actually execute, while preserving local-only/model policy, request identity, usage accounting and atomic accepted-clock publication. Base 3dacf0fb77191f053425dd4edd4e1a546ddc337e. H673 frozen row and parent-approved bounded design are the specification. Execute inline with test-driven development; no delegation, protected edits, dependencies, global evidence, assets or live providers.

## Modules and contracts

- New agents/core/route_compaction.py: frozen PreparedRoute with actual raw backend/model/route, finite or dynamic completion reserve, immutable effective window and exact prompt; request-owned lifetime and session identity. Resolve via existing router, revalidate exact final routing before execution; never mutate router/backend state. Shared staged-history coordinator uses monotonically decreasing budget and at most three planning passes; instability refuses before main provider/tool calls.
- agents/core/orchestrator.py: opt-in compression path prepares target-specific enriched prompts, stages shared compaction against strictest input budget, commits accepted summary/clock once after final stable routes, and supplies records to both parallel Agent.process and SSE execution. Existing unmanaged compression callers remain compatible. No copying action authority.
- agents/core/agent.py: optional internal prepared route keyword, same managed policy check before dispatch; ordinary process(text, context) unchanged. Preserve residency, guardrail wrapping, usage scopes, tool runtime and failure behavior.
- agents/core/context_compressor.py only if a pure explicit shared-input-budget seam is needed; no new compression policy/threshold behavior.
- tests/test_route_compaction.py: actual route/window/reserve/dispatch tests and transactional/cancellation regressions. Existing compaction/clock/anchor/agent/stream suites remain guards.

## Budget and provenance

Each candidate route is selected from the actual enriched prompt using the existing router. Read window metadata from that raw backend; selected job window wins, selected Ollama resolves its own num_ctx, never router._backend. Invalid metadata refuses; unknown capacity uses the existing explicit conservative model estimate. Each explicit positive max_tokens reserves that actual value (provider finite capping may conservatively overreserve). Cloud auto uses existing cloud_cap. Local auto is dynamic remaining context, not an invented completion cap; existing hard85% input ceiling preserves estimated headroom without guaranteeing answer length. Nonpositive remaining finite budget refuses, never clamps to one token.

Shared history must fit every specialist after accounting for its fixed prompt/system/tool overhead. Stage once against the minimum allowance, rebuild prompts, and monotonically tighten if final routing changes capacity; bounded failure is safer than dispatch on unstable routes. Managed final execution rechecks exact backend/model/route and policy/selection lifetime; mismatch refuses rather than silently selecting another route.

Usage anchors lacking backend/model/prefix provenance cannot be called exact for a changed route. Conservatively invalidate those anchors for managed shared planning until a provenance-bound anchor is available; retain legacy/unmanaged meter and billing behavior. No global state or cross-session anchor reuse. Existing provider usage remains the best measurement when its provenance is valid.

## RED/GREEN units

- [x] Route budget RED: default128k versus actual specialist8k, distinct selected Ollama num_ctx, mixed finite/cloud-auto/local-auto reserves, invalid and unknown metadata, impossible budget. Implement immutable records/resolver only after RED.
- [x] Prepared Agent RED: exact prepared tuple reaches dispatch; policy/selection closure or changed model refuses before provider; legacy caller unchanged. Implement optional internal seam.
- [x] Shared coordinator RED: actual text/SSE fanout selects distinct models, tighter final routing replans monotonically, unstable route refuses, one clock commit, no publication on cancellation/CAS failure, two sessions independent. Implement staged history and dispatch integration.
- [x] Run guarded focused regressions, whole Ruff/Bandit and source-scoped Graft freshness, update this plan with evidence and actual limitations; source-only commit for independent review.

Verification uses product Python3.12 through /tmp/nerva-run-isolated.py with TMPDIR=/private/tmp and NERVA_PUBLIC_PROFILE=0, preserving pytest.ini socket/timeouts. No full backend until parent integration. No whole-H673 claim without final frozen-row reassessment.

## Completed source and verification

Implemented the three runtime modules above; context_compressor.py required no edits. Added 35 focused route-compaction cases. The final guarded integration selection collected 653 cases with zero failures/errors/skips (JUnit `/tmp/nerva-route-focused.xml`, log `/tmp/nerva-route-focused.log`). It includes existing anchors, compaction clocks, continuations, actual Agent/runtime, router, text usage, HTTP, concurrent sessions, invocation reasoning, xAI/OpenAI Responses, tool-loop and binding guards. No full backend was run in this source unit.

RED evidence includes `/tmp/nerva-route-orch-red.log` (actual text/SSE exceeded specialist capacity), `/tmp/nerva-route-history-race-red.log` (concurrent retained-history change), `/tmp/nerva-route-unmanaged-actual-red.log` (ordinary inherited background lifetime), `/tmp/nerva-route-generation-red.log` (untrusted generation anchor), and `/tmp/nerva-route-estimate-red.log` (unknown promoted to known and missing optional-tool reserve). Final source passes whole Ruff (`/tmp/nerva-route-ruff.log`) and baseline Bandit 1.9.4 (`/tmp/nerva-route-bandit.log`). Source-scoped Graft cache `/tmp/nerva-route-graft` was rebuilt for only the three runtime files and new test; wiring freshness passes (`/tmp/nerva-route-graft-check.log`), with no deep semantic/paid indexing or project instruction changes.

Final details and limits:

- PreparedRoute keeps actual EffectiveWindow(None) for unknown metadata. Separate `capacity` is only the existing model estimate used by planning; actual Agent execution is tested not to promote it to known metadata. Invalid/async metadata refuses.
- Local automatic output remains dynamic with max_tokens unchanged. If an attached optional tool runtime can use a known-window tools backend, planning conservatively reserves its existing quarter-window allowance without changing the direct provider parameter. Unlimited output still has no promised completion length. Responses' 32768 reserve is its existing product cap, not a vendor claim.
- Final prompt/system/tool-schema overhead includes a conservative schema superset and clock-line allowance. Three monotonic planning attempts are bounded. A staged summary publishes once only after final route checks, retained-history equality and existing clock CAS. SSE secondaries reuse the same accepted plan.
- Managed usage anchors are bounded to 256 session/agent entries and require a nonempty durable instance, identical backend/model and exact retained-prefix hash. Unknown provenance falls back to estimation; legacy billing and unmanaged anchors are unchanged.
- Compression-disabled ordinary callers create no new revocable route frame. Inherited managed ancestry remains revocable even if a later child disables compression. This compatibility repair passed the independent reviewer's original counterexample before final handoff.
- Existing Starlette/httpx deprecation and the existing router network-error test's blocked-socket warning remain. There were no live provider calls, dependency/policy changes, bundles, global metadata changes or whole-H673 equivalence assertion.

Exact final command (from this worktree):

```sh
TMPDIR=/private/tmp /usr/bin/python3 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_route_compaction.py tests/test_context_usage_anchor.py tests/test_context_compaction_policy.py tests/test_compaction_clock.py tests/test_session_continuation.py tests/test_agent_runtime_v2.py tests/test_hybrid_router.py tests/test_text_usage_context.py tests/test_chat_http.py tests/test_concurrent_session_isolation.py tests/test_invocation_reasoning.py tests/test_invocation_reasoning_http.py tests/test_xai_responses.py tests/test_openai_responses.py tests/test_tool_loop_compaction.py tests/test_orchestrator_bindings.py --junitxml=/tmp/nerva-route-focused.xml -q
```


## Integrated verification

Reviewed source ee2aa4cc was rebased as one owned commit onto the final toolsets tree 4af7cc52, producing c58de044dddd5712e4e89f160cccd6cefc1bbecc. Independent exact-source verification passed 264 guarded cases (/tmp/nerva-route-independent.xml, .log), including the original unmanaged-lifetime counterexample. Root combined verification passed 275 cases covering route planning, toolsets, pinned jobs, xAI, continued sessions, clocks and binding inventory (/tmp/nerva-route-integrated-focused.xml, .log). Actual guarded collection is 803 modules and 12,011 backend cases (+35). Frontend 1,329 / mobile 140 / routes 502 are unchanged; this unit changes no frontend source or API schema.

Whole Ruff and baseline Bandit 1.9.4 validation is recorded in /tmp/nerva-route-integrated-ruff.log and -bandit.log. The four-file explicit Graft cache /tmp/nerva-route-integrated-graft covers only the three runtime files and test module; build/check logs use the same prefix. No deep/paid indexing or tracked cache. The integrated full backend run collected 12,011 cases: 11,987 passed, 23 skipped and one expected failure, with zero failures or errors in 254.429 seconds (/tmp/nerva-route-full.xml and .log). The tracked diff SHA-256 was unchanged throughout the run. Final documentation and evidence hashes are updated after this completed run; no runtime source changed.

H673 remains partial. This closes actual specialist-route planning for the existing opt-in shared-compression flow, preserving disabled/unmanaged behavior. Planning estimates are never represented as provider-known runtime windows. Direct local auto output remains dynamic; known-window optional tool execution retains its existing quarter-window completion budget. Unknown-generation or mismatched backend/model/history usage anchors are untrusted. Remaining server-only context discovery, image estimates, explicitly unsupported usage frames and non-conversational attribution are separate obligations. No live provider, hardware or billing claim.
