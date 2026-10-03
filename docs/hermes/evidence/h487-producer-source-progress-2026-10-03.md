# H487 live producer and signed pending-source progress

Goal: complete all 697 accepted Hermes capabilities locally. Generated 2026-10-03.
Base/head before this increment: `27bf6cb043a029bf2cee1e6c777a0ef38cc3263c`.
Design: [producer plan](../h487-consent-producer-plan-2026-10-03.md).
Exact implementation/test hashes and local artifacts: [receipt](h487-producer-source-progress-2026-10-03.json).

## Delivered behavior

Ported the complete pinned Hermes terminal warning detector, with its MIT notice.
The closed catalog contains 116 warning descriptions plus one unknown category.
First-warning priority is preserved. Malformed/parser-limit/unknown categories
are session-max; classification itself grants nothing. Homes are explicit caller
arguments and the Hermes-specific gateway lifecycle predicate is optional and
trusted. No installed Hermes runtime or private configuration is required. The
pinned quoted-prose false positive is intentionally preserved and tested.

ToolRPC supports an explicit registrar-owned `consent_revision`. A stable private
key binds the declared schema/flags/capability and readable callback code/module
bytes, while the existing random grouping epoch continues to detect live
replacement. A separate fresh-descriptor verifier cannot break ordinary grouping
if it fails. The actual terminal registration declares `nerva.terminal_run.v1`
and exports verified owner-turn provenance only inside its real enqueue scope.
No provenance key is placed in a public task, payload or model answer.

The real governed BLOCKED enqueue now captures a bounded signed private source.
It binds a distinct purpose/version, persistent queue namespace, task ID/birth,
approval snapshot, exact deadline, existing ready chat association, producer
semantics and server policy. Numeric risk-tier policy keys are serialized as
strings for canonical JSON. Capture cannot borrow an older same-arguments task
from another turn, re-sign an existing source, or commit a caller's transaction.
Metadata/signing failure leaves the ordinary persisted ask intact.

Private read verifies canonical bytes/signature, current pending intent and exact
association; taint, expiration, a human decision or canonical Smart DENY refuses
the source. Reopening the same DB with its signer preserves valid provenance.
Session-instance/session purge deletes matching private sources in the same
transaction. Settled acknowledged retention deletes its source and preserves
pending sources; orphan cleanup is bounded by the existing batch limit.

## Verification and review

Two disjoint implementers used `gpt-6-sol` High; neither delegated or committed.
Their reports retain RED/GREEN evidence. The coordinator reviewed the complete
changed modules and ran the guarded integration union on the frozen final source:

```text
/tmp/nerva-pr-python-20261001/bin/python -m pytest tests/test_h487*.py tests/test_h277*.py tests/test_h485*.py tests/test_company*.py tests/test_pending_requests.py tests/test_h464*.py tests/test_tool_rpc*.py tests/test_autonomy_queue*.py tests/test_autonomy_worker*.py -q --junitxml=/tmp/nerva-h487-producer-source-final-integrated-20261003.xml
```

Exit 0: **3,135 cases, zero failures, errors or skips**, 74.285 seconds. The normal
socket/timeout guards stayed enabled. Existing provider tests emitted blocked
nonlocal socket warnings; no live provider success is claimed. Ruff and
`git diff --check` pass. Scoped Bandit against the existing baseline has zero
new findings/errors. Its copied shell-delimiter password false positives were
reviewed and annotated locally; the baseline was not weakened.
Graft was explicitly rebuilt and checked: wiring graph fresh, 48,670 nodes;
optional deep context remains absent. The exact changed-file secret scan is clean.

A separate read-only `gpt-6-sol` High review found private source bytes surviving
session purge/retention. Two meaningful RED tests reproduced that defect. The
transactional fix passes: **104 relevant queue/retention cases**; the corrected
actual-terminal provenance module passes **20 cases**. The reviewer verified
instance isolation/pending preservation and found no further issue in its scope.
A misplaced test insertion was corrected before the final union; all ten
parametrized intent/source mutations execute their assertions in the final run.

The root's initial real-terminal tests failed for missing stable provenance and
then missing durable source APIs; final regressions cover both, database reopen,
cross-task/cross-turn replay, intent/deadline/origin/namespace/signature/purpose
changes, signer/storage failures, ordinary human approval, Smart DENY and outer
transaction preservation. The classifier implementer reports 33/33 direct
representative detector outputs matching the isolated pinned Hermes snapshot.
The MIT notice is byte-identical to that snapshot's LICENSE.

Guarded backend **collection only** exited 0: **22,067 cases in 1,071 modules**.
Tracked counts/generated documents were synchronized without altering the old
CI commit stamp. There is no new full-backend execution receipt for these bytes;
the earlier complete backend result remains bound to its historical checkpoint.
Generated Hermes reports retain changed evidence as needs-review instead of
blindly restamping it: **173/697 equivalent (24.8%)**, 259 partial, 62 missing,
203 requiring review and zero excluded. No equivalence credit is added here.

The record gate first exposed stale shared coordinator pins for H515/H660 and
coordinator/ToolRPC pins for H595. Each complete source diff was inspected against
its exact claim; all other pins already matched. **349 image cases** and **232
code/kernel/transport cases** pass; seven Docker-dependent cases skip. Those
three records retain partial status and every remaining requirement. The final
counts are 259 partial, 62 missing and 203 needing review, with equivalent still
173; no fresh container or frontend acceptance is claimed.

## Remaining work and limits

H487 is unfinished. The captured source proves enqueue provenance, not consent,
owner authentication for a later request, a B7 receipt or execution authority.
The signed policy is the original snapshot; a future consumer must independently
revalidate live policy, registration, target/configuration, hardline and kernel
floors. Fingerprints do not authenticate mutable closure/instance state or
transitive dependencies; the explicit registrar contract remains necessary.
Unavailable/oversized provenance keeps ordinary approvals.

Next action: connect the category ledger to real owner session/always choices,
atomically settle matching followers with separate mediated receipts, enforce
monotonic revocation at physical dispatch, then integrate HTTP/HUD/Telegram and
other accepted producers/channels. Exact-request-only grants cannot replace the
required category semantics. Full DB rollback and restoring old valid signed
consent/decision pairs still need an external monotonic revocation anchor.
No push, merge, deployment, provider spend or runtime activation occurred.

## Changed paths and rollback

- `agents/core/autonomy/hermes_command_detection.py` and
  `terminal_consent_categories.py`: pinned detector and closed warning catalog.
- `agents/core/autonomy/consent_registration.py`, `approval_grouping.py`,
  `agents/core/tool_rpc.py`: stable, live-verified registrar provenance.
- `agents/core/autonomy_coordinator.py`: actual terminal producer wiring.
- `agents/core/autonomy/consent_sources.py`, `queue.py`, `worker.py`: signed
  private enqueue capture/read and transactional retention cleanup.
- `tests/test_h487_consent_registration.py`,
  `test_h487_terminal_consent_categories.py`,
  `test_h487_terminal_consent_provenance.py`: registration/category/runtime checks.
- `docs/hermes/h487-consent-producer-plan-2026-10-03.md`, this report/receipt and
  `docs/hermes/licenses/hermes-command-detection-MIT.txt`: design/evidence/license.
- `BACKLOG.md`, `HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md`: unfinished
  continuation and truthful evidence freshness.
- `docs/hermes/assessment.json`: claim-specific H515/H660/H595 collateral review;
  no status upgrade or unrelated evidence restamp.
- `project-status.json`, `README.md`, `NERVA.md`, `STATUS.md`, `GO_LIVE_PLAN.md`:
  collected test counts only.

Rollback: revert this localized increment; keep task/chat/approval history.
The new source table grants no rights and becomes inert if the producer is
removed. If removing its retained private metadata too, remove only the new
`task_consent_sources` table, never the existing task/history tables.
