# H388 upstream operating guidance integration

Goal: full H388 within the all697 Hermes objective. Base/head `dba0fb56`;
generated 2026-10-04. Previous goal turn made progress via owned checkpoint
storage and604 affected tests. Keep local; no push/merge/deploy or providers.

Reuse pinned Hermes `59b2aeef6c7a`, prompt_builder/system_prompt guidance and
selectors with its MIT notice. The prepared external adapter contains copied
task-completion/tool-enforcement/session-search texts plus bounded adaptations;
its10 pure tests are preparation evidence, not runtime acceptance or full H388.

1. Integrate the reviewed pure adapter and its meaningful RED/GREEN tests.
2. Wire the real tool runtime after its profile/registry resolves the exact
   offered schemas. Bind actual routed model, authenticated channel and trusted
   per-agent flags. No capability is inferred from a model or user input.
   At an existing compaction boundary rebuild guidance against the new offer,
   removing feature-specific advice when its tool disappears.
3. Bind presentation/env/profile guidance at the real Agent generation seam,
   synthesis and streamed cache material before cache acquisition. Preserve
   persona/identity, clock/session isolation, prefix equality and routed models.
   Only supply observed execution facts; do not fabricate an OS, cwd or shell.
4. Port the remaining model/tool/profile/help/steer/HUD/provider guidance and
   wire their actual existing Nerva capabilities. Preserve tool schema names;
   role swaps belong at the wire adapter. Independently config-toggled blocks
   and model-family choices must match the pinned contract, not just four blocks.
5. Focused RED/GREEN and affected runtime/prompt/cache tests per step; full suites
   serially at a frozen completed batch. H388 stays partial while explicit
   requirements remain; record functionality separately from pure prototypes.

Likely paths: agents/core/operating_guidance.py (new), agent_runtime.py, agent.py,
orchestrator.py or their existing wiring helpers, focused H388/runtime tests and
Hermes records. Root owns shared integration; at most two Sol High implementers
may prepare disjoint external files without children. No new dependencies.

Rollback removes guidance wiring while leaving existing prompt/ToolRPC authority
and stored settings intact. Neither guidance nor a toggle grants execution or
overrides kernel policy. Unknown/unreadable guidance settings omit optional
advice; the existing tool authorization remains authoritative.

Implemented batch at base/head dba0fb56 (working changes, 2026-10-04):
- Copied three Hermes blocks and the two model selectors, with its MIT notice;
  adapted parallel/execution/Google/surface/environment/profile advice.
- Real AgentToolRuntime calls bind the actual routed model and profiled tools.
  Committed compaction folds rebuild the advice when a tool is withdrawn.
- AutonomyCoordinator binds the authenticated principal's channel and live
  `llm.operating_guidance` JSON settings, registered in the existing admin store.
  Unknown/unreadable settings omit advice. No OS or execution host is guessed.
- Changed paths: operating_guidance.py, agent_runtime.py, autonomy_coordinator.py,
  settings_db.py, orchestrator_bindings.py, three H388 test modules and Hermes
  records. Binding callsite coordinates were updated after insertion.
- Tests: 10 pure +10 actual-runtime +4 product wiring/persistence pass. Affected
  integration run: 284/285 pass, with one stale callsite-coordinate failure;
  after correction all50 tests of that module pass. No current full-suite claim.
  Final combined runtime/settings/profile/compaction/binding/image/code/kernel
  integration run: all502 cases pass with no skips, failures or errors.
  Token estimation in the synthetic compacting fixture follows the existing
  deterministic compaction tests; production compaction itself is exercised.
- Next action: continue the remaining H388 blocks and direct/synthesis/stream
  prompt/cache seams from pinned Hermes. This batch leaves H388 partial.
