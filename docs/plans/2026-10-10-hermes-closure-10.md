# Hermes contract closure — batch 10

Generated 2026-10-10 UTC. Goal: complete H673's provider-measured context-pressure
contract, starting with reproducible flaws; no partial slice earns whole credit.
Initial base/head: `f925c3d3637fbf09aec2e5a0c568bf42aad0b977`, batch09 frozen source.
Branch `codex/hermes-closure-10-20261010`. Next action: settle rendered-prefix
binding from the actual native and frozen donor flows, then red/green regressions.
Batch09 is independently frozen and running its full suite; no batch10 edits go
there. Incorporate its final metadata before this batch's integration milestone.
Local only: no push, merge, deployment, paid providers or external messages.

## Contract and diagnosis

The frozen H673 row requires the last main-loop response's provider prompt
occupancy for system/schema/history, estimating only appended messages and
replacing the measurement on each eligible response. Companion behavior includes
the 85% hard limit, selected Ollama num_ctx resolution, and Gemini default output
reserve. Unknown or invalid provider usage/window remains explicitly unknown.
Frozen donor commit: 59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e (MIT). Cached
agent/usage_anchor.py checks the complete priced prefix and falls back when it
was truncated, spliced or otherwise changed; no permission to trust stale counts.

Confirmed fresh-app nonstream issue: when compression is off, a legacy usage
callback reads an uninitialized anchor coverage field. H002 records usage before
this callback, so billing is not lost. The managed route store already supports
session/model/backend/instance and full-prefix matching, but is lazily initialized
and unsynchronized across session threads. Its exact pressure/rendered-view
association needs review before extending it.

Correction to the initial read-only design: checkpoint.commit_clock changes clock
and compaction metadata only, not raw ConversationMemory rows. Therefore the
pre-CAS raw row snapshot is not inherently stale after publication. Sliding
last_n invalidation is a truthful fallback, also permitted by the donor. Do not
rewrite retained transcript to make an incorrect diagnosis true.

Confirmed image-accounting issue: after dropping a previously measured image,
ContextCompressor._used subtracts a guessed flat 1500 from a provider measurement.
The actual removed cost was not reported. Retain the measurement as a conservative
upper bound until a new response reanchors; estimate unmeasured appended images
as before. This may compress earlier but does not pretend the guessed subtraction
is observed occupancy. Keep the fallback estimate when no usable measurement
exists. The raw-estimate floor/rendered-view decision is a separate part of this
same contract and will be settled before its implementation.

## Ownership and verification

Root owns scope, shared interfaces, docs, evidence and critical integration.
repair_1247 (gpt-6-sol/high) investigates actual rendered-prefix binding read-only
until root assigns production paths. review_1233 (gpt-6-sol/high) owns only
agents/core/context_compressor.py and tests/test_context_usage_anchor.py for the
measured-image subtraction repair. No subdelegation or overlapping writers.

For the image repair, show a regression where removing an image from the measured
prefix cannot justify lowering pressure by an invented cost; show actual compact
behavior across a threshold as well as no-anchor and unmeasured-image controls.
Update old tests that expressly required the wrong subtraction, documenting the
behavior change; do not weaken unrelated safeguards. Run focused compressor and
usage-anchor tests, Ruff and whitespace validation. Root runs broader integration
serially once the full H673 behavior is complete and reviewed. No new route or
frontend is currently planned. Rollback is this single context-pressure unit.

## Refined implementation boundary

The refined source review retracts the false post-CAS row-mutation theory. It
also shows raw-row equality does not establish equality of an ephemeral summary,
changed system/tool scaffolding or transient in-turn tool messages. Whole H673
therefore needs a priced-view binding/representation decision; do not promote the
row based on the bounded repairs below. Full inventory remains unchanged.

repair_1247 now owns agents/core/orchestrator.py, agents/core/route_compaction.py,
and new tests/test_h673_anchor_lifecycle.py for two confirmed lifecycle repairs:
initialize one bounded synchronized managed anchor store per real orchestrator;
and omit the unusable unmanaged legacy anchor callback while preserving measured
billing and managed route publication. No new guessed coverage, no transcript
mutation, no change to provider selection or generation behavior. Prove fresh
nonstream usage no longer logs a sink error; managed replacement, distinct
sessions, bounded retention, concurrent access and closed observation stay safe.
The raw-prefix match remains conservative and is not newly described as a proof
of the actual rendered request. Root will settle the larger view-binding gap
before any equivalent verdict. The earlier standalone _record_context_anchor
helpers may remain for compatibility but cannot be the production unmanaged sink.

## Focused repair evidence (not whole acceptance)

Image red proof: 19 cases with three expected failures; final four-module
selection passes 85/85, with the refined actual-strip regression 19/19. The
measured 27,250-token request remains above the 85% hard threshold of a 32k
window after an image is removed. A new response can later replace this bound.
Lifecycle red proof: five cases fail before the fix, including the actual fresh
nonstream gather's usage-sink AttributeError. Final lifecycle/route/usage
selection passes 97/97. Plain helper compatibility and usage totals remain;
closed observers cannot publish late measurements. Ruff and diff checks pass.

Root inspected both production diffs and the behavior regressions. The actual
disposable fresh-app HTTP/model/ToolRPC clarification smoke, reused to exercise
two physical tool-loop replies plus auxiliary naming, now passes with no usage
sink warning or AttributeError in its completed log. It did not inject a
registration helper or mutate provider/accounts; source hashes stayed unchanged
and temporary state was removed. This verifies the known lifecycle defect,
not the still-open exact provider-view association. Artifacts are under scratch
batch10/core, batch10/images and batch10/live-clarify-smoke.*.

Companion-clause review confirms production managed nonstream/SSE compaction
uses selected-route budgets, resolves Ollama num_ctx after selection, and reserves
Gemini's default output cap. Unknown metadata stays estimated. No live physical
window or billing proof is claimed. The earlier suspected active-local-model
Gemini gap was ruled out by the enabled production call graph.
