# Effective tool window implementation plan

**Goal:** Bound ordinary tool turns by configured/cached backend capacity, preserving guarded generation and recoverable tool output.
**Base:** 61c657c2f4c629ebd0b022dc33bedf60522f1532. **Generated:** 2026-09-15. **Head:** source commit containing this plan (parent includes root-owned shape capture). **Next:** independent review and parent integration.
**Architecture:** Immutable per-turn metadata snapshot resolved before guardrail binding at Agent.process and Orchestrator's direct agent path; explicit forwarding to AgentToolRuntime. Direct raw runtime callers resolve locally. No wrapper introspection, network metadata probes, shared mutation, or job-selection scope synthesis.
**Spec:** Frozen H298 actual-window scaling requirement and controller-approved repair design; preceding model-pin plan governs pinned behavior.
**Constraints:** No protected files, provider parameters beyond existing completion limit, dependencies, global reports, or live calls. Root owns code_tools shape-capture changes in this shared worktree.

## Metadata and budget contract

`EffectiveWindow(tokens: int | None, valid: bool)` is immutable. Resolve selected job window first, otherwise synchronous `backend.context_window(model)` once. Absent/None means unknown and retains model-table estimate; supplied bool/nonpositive/noninteger, throwing property/call, or awaitable means invalid and refuses the tool turn. Never await metadata or discover remote capacity. A coroutine result is closed to avoid leakage. Opaque direct wrappers without metadata use the documented estimate; production callers explicitly forward raw metadata.

Known capacity bounds both transcript and tool-output scaling. `llm.tool_loop_context_tokens` remains a transcript cap; `llm.tool_result_context_window` remains a result-scaling override, each may only tighten known capacity. Reserve positive explicit max_tokens; auto/nonpositive gets one-quarter of known capacity. Refuse an explicit reserve consuming all 85% occupancy allowance. Do not raise tiny available capacity to the legacy minimum. Check initial and subsequent transcripts including estimated tool-schema overhead, compact existing result envelopes or refuse before generating. Unknown capacity retains legacy estimation semantics, without claiming measured safety. File-read infinity is preserved; the transcript boundary handles large reads without recursive persistence.

## Task 1: snapshot and production forwarding

Files: new agents/core/llm/effective_window.py; agents/core/agent.py; narrow agents/core/orchestrator.py call site; tests/test_effective_tool_window.py.
- [x] Add RED tests for configured, absent, invalid, throwing and asynchronous metadata, single snapshot and concurrent distinct models.
- [x] Implement immutable resolver and optional `effective_window` forwarding before bind_guardrails, preserving the wrapped generation backend.
- [x] Verify real Agent.process→GuardrailsEngine→runtime flow and Orchestrator forwarding with existing fixture; ordinary text behavior stays unchanged.

## Task 2: per-turn runtime budgets

Files: agents/core/agent_runtime.py; same focused test module; existing tool-loop spill/pin tests.
- [x] RED actual ordinary 4096-token backend with 30KB result must spill/compact before next request; concurrent 4K/32K requests must stay independent.
- [x] Pass snapshot through run/_run_loop, context compaction and spent result budgets; clamp owner overrides against known capacity. Preserve finite threshold precedence and file_read infinity.
- [x] Test excessive reserve and initial prompt/schema rejection before backend calls; auto reserve becomes explicit bounded completion; unknown retains estimate.
- [x] Test fitting and oversized file_read output with zero re-spill, bounded compaction/refusal, and guarded generation remains active.
- [x] Run focused runtime/spill/pins/Agent/orchestrator tests, whole Ruff and baseline Bandit. Commit only owned paths and record exact evidence/count delta for independent review.

Token occupancy is an estimate, not a provider tokenizer guarantee. LM Studio without cached metadata remains unknown; no loaded-capacity or whole H298 equivalence claim follows from that fallback.

## Verification and handoff

28 new parametrized cases in `tests/test_effective_tool_window.py`; one existing exact-seam assertion updated to assert the explicit unknown snapshot. Initial runtime RED: `/tmp/nerva-window-red.log`; structured-argument RED: `/tmp/nerva-window-args-red.log`. Both preserve generated-answer behavior except deliberate pre-request capacity refusal.

Final isolated pytest (repository pytest.ini unchanged) passed **307 tests** in `/tmp/nerva-window-final-focused.log`:

```sh
/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_effective_tool_window.py tests/test_agent_runtime_v2.py tests/test_tool_loop_result_spill.py tests/test_job_model_pins.py tests/test_tool_result_store.py tests/test_agents_integration.py tests/test_orchestrator_bindings.py
```

Whole Ruff and Bandit1.9.4 baseline scan passed (`/tmp/nerva-window-ruff.log`, `/tmp/nerva-window-bandit.log`). Scoped Graft graph built for `agents/core/llm` with no deep/network pass or ignore/instruction edits; freshness check passed. The local graph is excluded from this commit. No live provider, full backend suite, assets or global metadata touched.

Known-window transcript checks now include tool schemas and retained structured assistant call arguments; generic estimator still provides heuristic content/role counts. Invalid supplied metadata returns a validation failure rather than pretending occupancy was measured. Source ownership: this commit owns only helper/Agent/runtime/narrow Orchestrator forwarding/test modules/this plan; root owns `code_tools.py`, its tests and shape plan.

## Integrated verification

Root integration on the scheduled-media baseline passed the full backend suite: 11,460 collected, 11,436 passed, 23 skipped, one expected failure, no unexpected failures (`/tmp/nerva-window-integrated-full.xml`, 271.290 seconds). Independent review passed 151 effective-window cases and 53 code-tool cases. The combined changes add 32 backend cases; frontend and native sources are unchanged by this unit. No live provider calls or production deployment. H298 reassessment covers both reviewed repairs and retains explicit unknown-capacity and filesystem limitations in its contract summary.
