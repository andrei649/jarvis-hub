# Durable compaction clock implementation plan

Goal: freeze session birth/current-date prompt lines between accepted compactions.
Base: 546a50d83a29c48a082f994647a681326be3e972 (same tree as main d3caec90).
Generated: 2026-09-15. Head: this source unit. Next: independent exact-source review.

H671 remains partial: there is no cross-ID continuation caller. No inferred roots,
rotated IDs, new routes, global metadata, providers or authority changes.

## Approved design

Checkpoint SQLite owns session_clock(session_id PK, birth_at, revision, rebuilt_at,
compaction_sha256). Birth stays sessions.started_at, with existing records lazily
seeded at revision zero/birth time. Immutable ClockSnapshot carries session ID,
birth, rebuild time, revision. A compare-and-swap transaction records accepted
compaction hash and clock time together. Summary/transcript publication follows
success, never a failed/stale commit. No-op or exhausted compression does not commit.
No cross-database atomicity is claimed; accepted compaction identity is durable,
while existing transcript rendering/cache remains in process.

Capture once before async history preparation. Pass the immutable snapshot explicitly
to each Agent request, with a scoped context for the actual tool runtime child task.
A competing commit cannot rewrite a running request's snapshot. Tool compaction
operates on copies, verifies fit, commits synchronously, then publishes without an
await between commit and publication. No-op stays byte-identical. If committing
fails/stales, history raises a typed refusal caught by real text/stream/process entry points; tool runtime stops via
its existing context safety response. Missing checkpoint/snapshot keeps legacy
compaction available but never fabricates a durable clock/commit. Known captured
clock remains frozen when storage later fails. Fresh conversations seed fresh birth.

## Steps and validation

- [x] RED durable snapshot/restart/CAS/failure tests; implement store and formatting.
- [x] RED actual Agent midnight frozen snapshots; implement request binding.
- [x] RED actual history accepted/no-op/failed/cancelled/racing commit; implement seam.
- [x] RED actual tool-loop midnight/failed commit; copy before commit/publication.
- [x] Guarded focused suite, whole Ruff/Bandit baseline, explicit scoped Graft build/check.

Owned paths: checkpoint.py, conversation_clock.py, agent.py, agent_runtime.py,
orchestrator.py, focused tests and this plan. No dependencies. Rollback: revert
source commit; additive session_clock table is ignored by prior versions. Existing
session rows and dates remain unchanged. Migration is idempotent, missing/corrupt
birth remains unknown, and no speculative parent relation is introduced.

## Verification evidence

Initial store RED: 3 failures; Agent RED: 2 failures; history/tool seams RED:
4 failures; legacy Z timestamp/recreated-session RED: 1 failure; refreshed-clock
budget RED: 1 failure. Logs `/tmp/nerva-clock-{red,agent-red,seams-red,migration-red,race-red}.log`.

Guarded product Python focused run: **271 passed**, including 18 new cases (15
clock/store/history/Agent, 3 actual tool-runtime cases), in 8.51 seconds:
`/tmp/nerva-clock-focused.log` and `/tmp/nerva-clock-focused.xml`.
Existing Agent generation-seam fixture now asserts the explicit unknown clock
snapshot argument; its remaining exact request contract stays intact. Binding
inventory passes without any coordinate changes.

Command uses `/tmp/nerva-run-isolated.py` and the product Python3.12 executable,
`TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0`, original pytest.ini/addopts/socket and
timeout guards. Test paths: test_compaction_clock, test_tool_loop_compaction,
test_conversation_clock, test_session_birth_persistence, test_context_compaction_policy,
test_context_compressor_h20_3, test_context_compressor_salvage, test_agent_runtime_v2,
test_orchestrator_bindings, test_orchestrator_process_record, test_orchestrator_gemini_cache.

Whole `ruff check .` passes. Bandit1.9.4 baseline over relative `agents scripts`
passes (existing comment warnings); logs `/tmp/nerva-clock-{ruff,bandit}.log`.
Scoped Graft wiring build/check covers only the five owned runtime sources and
three tests copied to `/tmp/nerva-compaction-clock-graph-source`, cache outside repo;
478 nodes/1201 edges, fresh. No secrets/dependencies/deep provider calls indexed.

No full backend, live provider, frontend or native run is claimed. Session lineage
is still absent; this is the accepted compaction-clock boundary increment only.
Compaction identity/hash and revision are durable; full summary/transcript storage
and cross-ID continuation are not introduced. Known failed/stale commits cannot
publish or send an oversized raw-history fallback, while missing durable snapshots retain legacy compaction without a new clock.

Additional existing checkpoint/index/shutdown/performance guards: **26 passed** in 1.22 seconds (`/tmp/nerva-clock-checkpoint-adjacent.log`). Total bounded verification: **297 passed**.

## Independent review repairs

Review reproduced two P2 failures: failed CAS leaked raw oversized history to
text/stream calls, and an inherited child could commit after its Agent owner exited.
The current design supersedes the initial raw-history fallback: CompactionClockRefused
stops history publication, and actual text/stream/process boundaries return a bounded
context refusal. No provider request receives unaccepted raw history.

ClockFrame snapshots remain immutable/request-local. A separately shared lifetime
is revoked in the owner scope's finally, and inherited/nested frames consult it.
Child CAS replaces only its own frame, retaining the SAME lifetime, so sibling
snapshots do not move and even an already-updated child loses commit authority after
owner exit. Closed scopes refuse instead of turning into unmanaged legacy compaction.
Direct Agent capture still records agent_id for a newly created session.

Two added review regressions reproduced RED, plus creator metadata RED. Four new
cases verify actual entrypoint refusal, late-child refusal, updated-child revocation
with parent snapshot isolation, and preserved creator metadata. Total new tests:22.

Final repaired verification: **301 guarded focused tests passed in8.90seconds**,
`/tmp/nerva-clock-repaired.xml`/`.log`, including the earlier271+26 plus4new.
Whole Ruff and baseline Bandit pass again; scoped Graft check detected changed
source, explicit rebuild and final freshness check passed. Logs
`/tmp/nerva-clock-repair-{ruff,bandit}.log` and `/tmp/nerva-clock-graft-{stale,rebuild,fresh}.log`.

Final compatibility repair: wholly unmanaged clock_scope (no snapshot, no managed
ancestor) creates no revocable frame, preserving existing late background Agent
calls. A closed managed ancestor still refuses before an unmanaged scope can be
minted. Actual unmanaged-child regression reproduced RED; both this case and the
closed-managed-to-unmanaged case now pass. **303 guarded focused tests passed in
8.74 seconds**, total24new; `/tmp/nerva-clock-final.xml`/`.log`. WholeRuff/Bandit
and manual Graft stale→build→fresh passed again. No further scope changes.

## Independent review and integration

Final source d0e3b08081a3d176c54d0129a5032bbeafe54acd was independently cleared:
281 guarded cases including the original external counterexamples, metadata creator
preservation, unmanaged compatibility and inverse managed-scope revocation.
Evidence /tmp/nerva-clock-review-cleared.log and .xml. Root source review agreed.
The three implementation commits were rebased onto actual cache integration main
131359e7beaa8066f9cd03afa75131850647fa36, producing 7b42e1e4d01a5ce177940dbda579efe6851c7d7f.

The first full run found one stale exact-context fixture: test_reasoning_timeout
expected only session_id/wall_seconds, omitting the deliberate _clock_snapshot=None.
Its shared dictionary assertion passed and is retained verbatim. Test-only commit
347259b5f037194196a44480eb9e700c8a1fc0b1 synchronizes the exact expected contract;
46 reasoning/clock/tool-compaction cases pass in /tmp/nerva-clock-context-fix.log
and .xml. Runtime source and collection count are unchanged. First-run evidence
is retained at /tmp/nerva-clock-full-first.log and .xml: 11,635 passed, 23 skipped,
one expected failure and this one failure (257.43 seconds). A fresh full run follows.

Assessment refresh is gated on ALL evidence in the prior row matching base131,
not merely an individual file hash. H362/H386/H391/H392/H678 retain their previously
stale evidence verbatim. Only 35 previously-current matching references changed;
/tmp/nerva-clock-evidence-refresh.json records retained/restored paths. H671 adds
specific new clock/runtime tests and retains partial status for cross-ID lineage.

Fresh final full backend: **11,636 passed, 23 skipped, one expected failure,
zero unexpected failures**, 246.38 seconds; 11,660 collected. Actual evidence:
/tmp/nerva-clock-full.log and /tmp/nerva-clock-full.xml. Socket restrictions and
all repository pytest addopts remained enabled; no live/provider proof is claimed.

Exact full command:
`/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 PATH=/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest --junitxml=/tmp/nerva-clock-full.xml`

Final metadata suite (test_hermes_sprint_status, test_status_sync, test_release_gate)
passes 81 cases, /tmp/nerva-clock-metadata.log and .xml. Whole Ruff and Bandit1.9.4
baseline pass after the test repair: /tmp/nerva-clock-integrated-ruff.log and
/tmp/nerva-clock-integrated-bandit.log. `status_sync --verify-test-count backend
--test-result /tmp/nerva-clock-full.xml` confirms11660. Generated counts reuse
frontend1326/mobile140/routes501; no frontend/native rerun for this backend unit.
Hermes totals remain121 equivalent/327 partial/94 missing/107 excluded/48 needing
review. H671 remains partial, with unknown birth and absent cross-ID lineage explicit.
