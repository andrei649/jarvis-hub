# H517 speech-provider authority prerequisite

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013,
with the existing local sprint preserved. Goal: make the existing owner-approved
speech command registration usable under strict task mediation before extending
it to multiple named providers. H517 remains partial.

## Global constraints

Local only: no commit, push, merge, deployment, paid/live provider calls or
changes to unrelated modules. Preserve dirty state. At most two Sol High
implementers; no subdelegation; single writer per file. Focused TDD first,
then integration and serial full backend tests for the milestone. Keep socket
and timeout guards. Existing approval, safe-mode, arming, file-content checks,
local-only semantics and TTS/STT fallbacks remain intact.

Decision: fix the concrete authority prerequisites first. A common interface
alone would not repair the unusable strict-mode registration path. Multiple
named providers and a shared media registry remain the next implementation,
not replaced by this prerequisite.

## Task 1: strict mediation registration

Own agents/core/kernel/registry.py, agents/core/voice/command_settings.py,
agents/core/autonomy/irreversible.py (docstring only),
tests/test_action_auth_matrix.py, tests/_snapshots/action_auth.json and new
tests/test_h517_voice_kernel.py. Register only settings.voice_command as a
kernel-mediated kind; enumerate its broker constant. Prove the actual
command request -> AutonomyWorker/TaskQueue -> recorded human decision ->
execution -> protected setting path under enforce. Hold must continue refusing
classified enqueue, as the existing mode intends. Kernel DENY, unavailable
kernel/receipt, machine decision and edited/forged requests must not write.
Irreversible risk remains at the human-approval floor even on kernel GRANT.
Do not register settings.retention or a settings wildcard. Keep compatibility
for the existing off mode. The queue supports off, enforce and
hold; there is no separate observe mode. If execution requires an additional kernel/worker change,
report the exact blocker before touching unowned shared files. Update stale
comments only after tests demonstrate the path. Save RED and focused GREEN
JUnit reports in /tmp/h517-voice-kernel-*.xml. Report to
/tmp/h517-voice-kernel-report.md with files, tests, evidence and limitations.

Execution ruling: preserve the worker's existing signed-decision contract. The
real execution boundary validates the receipt, current policy/scope and global
halt; it does not re-call kernel authorization. Prove those revocation paths
and the executor's private claim guard. Changing only an injected kernel hook
is not a supported revocation mechanism and must not be reported as one. No
second execution-authority path is introduced inside the settings handler.

## Task 2: approval identity after slot wait

Own agents/core/voice/local_providers.py and new
tests/test_h517_voice_revision.py. Strengthen the existing Ready/_recheck
contract so an invocation initially validated against one approved command
cannot execute after that command was replaced or reapproved while waiting,
even if argv remains identical. Bind initial approved task/revision and bound
file identities; compare fresh approved state at the existing post-slot check.
Legacy approved records remain usable; do not introduce settings migrations.
Prove real TTS and STT bounded-run paths: unchanged approval succeeds, revoked
or changed approval refuses, identical argv with changed executable/script
identity plus a newly approved value refuses the original queued invocation,
and arming/safe-mode changes still refuse. Preserve public signatures and
fallback/sentinel behavior. No extra authorization or filesystem writes in
status. Save RED and focused GREEN JUnit reports in
/tmp/h517-voice-revision-*.xml. Report to
/tmp/h517-voice-revision-report.md with files, tests, evidence and limitations.

## Task 3: join the two production paths

After Tasks 1 and 2 freeze, the Task 2 implementer owns only new
tests/test_h517_voice_authority_integration.py. Reuse Task 1's strict signed
worker/executor fixture and real temporary speech programs. For TTS and STT,
register through command_settings.request, approve through the worker, tick
to install, hold the real command runner slot, then register/approve/install
the identical argv again. The old pending invocation must refuse without
spawning; a fresh invocation under the replacement approval must succeed.
This joins strict approved registration to real bounded speech execution;
do not mock the queue, approval store, process or final checks. Run only these
two new cross-task cases and append evidence to the Task 2 report.

## Integration, verification and rollback

Parent reviews incremental diffs against /tmp/nerva-h517-voice-baseline,
checks cross-task real approval-to-run integration, refreshes only relevant
documentation/evidence and truthful status. Run existing H613/STT/voice/kernel
tests, action matrix, strict mediation regressions, full backend milestone,
doc/status checks and applicable security checks. No frontend behavior changes
are intended in this prerequisite. Rollback only this slice's changed hunks;
disable JARVIS_VOICE_COMMANDS to stop command execution without deleting data.

Tasks 1-3 and their manifest/inventory corrections are verified. Next action:
settle named-provider storage/registry interfaces using h517-named-provider-next.md
and implement the next production slice; H517 and H613 remain partial.

## Full-suite correction

The first full backend run found two manifest-coverage failures: the exact new
action registry entry must also have a product capability manifest. Task 1's
writer additionally owns agents/core/capability_manifests.py and a focused
regression in its new voice-kernel test module. Add the exact voice entry with
irreversible risk, the real apply handler, required recorded-request inputs,
and truthful clear/revoke semantics (future runs stop; prior effects are not
undone). Preserve confidence zero and the existing human floor; no wildcard or
new authorization registry. Run the H27 manifest suite and strict voice/matrix
focus, then parent repeats the full backend suite. No unrelated manifest edits.

The second full run exposes the companion executable-case counts and readiness
snapshot (three failures). Task 1 additionally owns
tests/test_h27_capability_verification.py and
tests/_snapshots/capability_readiness.json: add exactly the new wired action,
update expected inventories by one and prove its matching real harness case.
Keep existing readiness states, escape sets and proof requirements unchanged.
Run the complete H27/capability registry/readiness group before a full rerun.
