# H485 authenticated guardian denial feedback implementation plan

Goal: stop repeated terminal retry suggestions after committed smart DENY verdicts,
using the existing authenticated chat observation flow without changing authority.
Base / preceding HEAD: `802b3b4bd1d2f310a334794bddd0cf15ffbe2d38`.
Branch: `codex/h277-provider-discovery-20261002`. Generated 2026-10-03.
Pinned specification: Hermes 59b2aeef6c7a, tools/approval.py:58-109.
Architecture: queue-local observational tables count committed verdicts for the
server-created (session_id, session_instance, principal_key), never model fields.
A per-task exact-snapshot denial event supplies safe constant feedback to the
existing bounded next-turn prompt block. This is not synchronous tool-result
parity and cannot grant approval or physically stop tools.

Global constraints: local only; Python 3.12; no new dependencies, runtime flag
activation, provider calls, publication, kernel changes or receipt shape changes.
One Sol/high implementer owns queue.py and queue tests; the coordinator owns
rendering, real chat integration tests, records and critical review. No delegation
by the implementer. Source changes remain localized and incremental.

## Task 1: transactional queue feedback

Files: agents/core/autonomy/queue.py and tests/test_h485_denial_feedback_queue.py.
- [x] Reproduce absent guardian feedback with red-first tests.
- [x] Count only successful store_smart_terminal_judgement DENY CAS writes for a
  ready, birth-checked original chat association. Duplicate/stale writes, ESCALATE,
  missing context and unavailable provider do not count. Changed exact task
  revisions may count as distinct committed denials, but stale event feedback
  must disappear until a verdict binds the new revision.
- [x] Use at most 256 recently denied consumer keys; saturate counts at 1,000,000.
  Trusted JARVIS_SMART_DENIAL_BREAKER_THRESHOLD defaults to 3, malformed values
  fall back to 3, <=0 disables warnings and positive values cap at 1,000,000.
- [x] Reset the consumer tally atomically on signed smart APPROVE or explicit
  recorded human accept/edit approval. Reject/defer/execution completion do not
  reset. Same principal/session-instance identity is mandatory.
- [x] Add optional guardian object only to observations of an exact current DENY:
  {decision: "deny", consecutive_denials: integer, breaker: boolean}. The count
  is the committed event's count; breaker additionally requires an active tally
  and current trusted threshold so an older event cannot revive a reset warning.
  Each tally sequence has a unique epoch; only events in that epoch can carry
  an active breaker after a reset, eviction or session replacement.
  No raw command, rationale, target, prompt or principal is projected.
- [x] Prioritize one latest validated active breaker observation before remaining
  FIFO items, preserving the eight-item/4 KiB budget and exact acknowledgement.
  An older waiting backlog must not hide the next-turn stop warning.
- [x] Purge on session-instance deletion and retention; preserve restart, backup
  of observation metadata, acknowledgement revision and <=4 KiB output budget.
- [x] Verify races/duplicates, restart, reset, isolation, changed intents,
  zero/default/invalid thresholds, 256-key eviction, purge and rollback.

## Task 2: model-facing feedback through existing turn flow

Files: agents/core/approval_outcomes.py; new
 tests/test_h485_denial_feedback_integration.py; .env.example; bounded records.
- [x] Add constant stop-retrying guidance only when a validated included guardian
  object has breaker=true. Fences/header remain in the same 4 KiB byte budget.
- [x] Real chat tests cover normal/streamed next authenticated owner turn, third
  distinct denial, successful persisted-answer acknowledgement, failed-answer
  retry, and no execution/replay or cross-identity disclosure.
- [x] Verify focused smart/observation/channel regressions, source mutations for
  feedback boundaries, global Ruff/Bandit, generated records and secret scan.
  Run complete backend serially at this authority-adjacent integration milestone.
  Frontend is unchanged; previous frontend result is not a new run.

Review focus: async CAS races; old denials after an owner approval; deleted/reused
sessions; edited tasks revealing a stale verdict; malformed stored metadata.
The observed DENY annotation must match the full canonical stored result shape,
not merely the decision/advisory fields. Review reproduced both this corruption
case and the FIFO warning delay; focused corrections are required before full tests.
Use a SQLite transaction for observation metadata updates alongside each verdict.
No consumer context means omit feedback, not infer a shared session.
Rollback: revert this additive observational increment; existing task/receipt
execution bytes and grants remain identical. Hooks and same-turn shell/script
placement are subsequent slices. H485 stays partial and earns no equivalence.
Next action: run the complete backend suite against frozen corrected sources; then
finish truthful records and a local-only checkpoint.


## Source-frozen interim verification

Initial focused union: 282 cases, zero failures/errors/skips. New H485 coverage is
49 cases (34 queue, 15 actual in-process chat/stream integration with mocked
provider HTTP). Seven isolated feedback mutants are assertion-killed; none
survives or is invalid, and the restored 49-case baseline passes with unchanged
live-source hashes. Bandit 1.9.4 over agents/scripts with the unchanged workflow
baseline has zero findings and zero scan errors. Complete-suite verification
remains pending at this interim record. No Python coverage instrumentation or
threshold is configured; case counts are not coverage percentages.

History: initial queue probes were red before implementation. Root integration
was 4 failed/9 passed, then rendering alone left only the two native-flow failures.
Review reproduced four malformed-annotation variants and FIFO warning starvation;
five added cases were red before correction. Backup SQL triggered one B608 finding
and was replaced with fixed literal queries and bound values, without baseline
weakening. The first isolated mutation copy lacked public agents.yaml (40 passes,
4 setup errors); it is invalid and earns no mutation credit. The corrected copy
includes and hashes that public config. A second Sol/high read-only reviewer
confirmed canonical metadata, priority/exact ack, and no new severity issue.

Task/TaskStatus, execution_fingerprint, verify_smart_terminal_approval,
_smart_terminal_mediation_valid_locked, claim_mediated and reap_stuck_running ASTs
are identical to parent 802b3b4b. Ordinary owner transitions add only the bounded
observational reset call; smart CAS adds count/reset within its existing write
transaction. The extracted unsigned-hold validator retains canonical supersession
rules and is reused by the observation projection. Existing signing bytes and
capability/kernel checks remain unchanged.

The five previously-current source-affected Hermes reviews are refreshed: H277,
H288, H468, H472, H485. Existing verdicts are retained; inherited stale H487 is
not restamped or promoted. Native mobile labels/configuration/device acceptance,
synchronous shell/script placement and forced-redacted hooks remain open.


Central env correction: the first completed backend run passed 21,563 cases,
with 34 skipped and one xfailed, but failed test_raw_env_reads_do_not_grow
(118 raw reads versus the unchanged 117 cap). Reproduced that test red isolated;
replaced only the new os.environ read with the stateless existing env_str helper
and removed the unused os import. Sorted that narrow import with Ruff. No guard
or baseline was weakened. Corrective union passes 327 cases, including the
entire existing env-config suite; global unchanged-baseline Bandit is clean.
The source-bound seven-mutant campaign was rerun successfully after import
sorting; the overlapping attempt detected source drift and is not final evidence.
A second full backend run is required and pending. H504's current TLS verdict is
also retained after reviewing the three commented env-example lines; TLS source,
configuration fields and all other prior H504 evidence are unchanged.


## Final checkpoint verification

Second complete backend: **21,564 passed, 34 skipped, one xfailed**, 67 warnings,
1,119.03 seconds, exit zero. All seven frozen source/test/harness hashes match
after completion. Corrective focused union: 327 passed; seven feedback mutants
killed with the restored 49-case baseline passing. Global unchanged-baseline
Bandit has zero findings and zero scan errors. Explicit Graft build/check passes;
the local wiring graph is current and no semantic layer was built.
See [complete verification report](evidence/h485-denial-feedback-verification-2026-10-03.md).
All checklist items describe this bounded next-turn slice only. H485 remains
partial; next are forced-redacted observers and synchronous flagged shell/script
coverage with independent acceptance. No publication or runtime activation.
