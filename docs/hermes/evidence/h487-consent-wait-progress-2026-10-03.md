# H487 consent storage and explicit-deadline waiting

Goal: complete all 697 accepted Hermes capabilities locally. Generated 2026-10-03.
Base/head before this uncommitted increment: `7b6c08c5558f44a69af6743435face28650b9375`.
Design and required next integration: [plan](../h487-reusable-consent-design-2026-10-03.md).
The [receipt](h487-consent-wait-progress-2026-10-03.json) pins five implementation/test
files and local result artifacts. No publication, merge, deployment or activation.

## Delivered behavior

CompanyMode now derives a new approval-wait window's frozen ceiling from its
initial verified explicit deadlines, adding the Hermes 60-second margin.
Sources without deadlines and legacy epochs retain 360 seconds. Actual credit
ends at each task's deadline or first human decision. Overlap is counted once;
later followers cannot renew the ceiling. The same formula and frozen initial
source sequence IDs are checked on read-only reporting and settlement. Corrupt
or nonfinite observations and a fabricated checksummed ceiling grant no credit.
Absolute goal deadlines and ordinary wall-time accounting remain unchanged.

The adjacent `ConsentLedger` persists signed category grants and human decisions
on a caller-owned SQLite connection. Session identity is exact; always survives
reopening across sessions while retaining principal, surface, registration,
policy and target binding. All requested categories need coverage; content-only
categories cap at session. A trusted server catalog is required. Supported
internal origin labels are owner/admin, not external authentication proof.
Savepoints preserve outer rollback and give lookup one coherent read snapshot.
Revocation signs decision tombstones, including superseded decisions; copying a
grant alone cannot recreate revoked consent. Decision IDs cannot be replayed.

## Verification

Two disjoint gpt-6-sol High implementers were used; neither delegated or committed.
Coordinator inspected both complete diffs and ran the guarded integration union:

```text
/tmp/nerva-pr-python-20261001/bin/python -m pytest tests/test_h487*.py tests/test_company*.py tests/test_pending_requests.py tests/test_h464*.py -q --junitxml=/tmp/nerva-h487-consent-wait-integrated-20261003.xml
```

Exit 0: **841 cases, zero failures, errors or skips**, 11.822 seconds. One existing
Starlette deprecation warning. Ruff on the five changed Python files and
`git diff --check` pass. Graft wiring was explicitly rebuilt without editing
ignore/instruction files; 48,543 nodes, no added/removed/changed/stale files at
the subsequent check. Optional paid/deep context was not built.

RED evidence reported by implementers: real runtime long wait returned 360
instead of 500; an inflated recomputed-checksum ceiling returned 700 instead of
zero; a nonfinite observation returned 100 instead of zero; consent stub grants
failed; copied revoked grants initially looked active. Each corresponding final
regression passes in the coordinator's union. The individual reports and their
hashes are retained in the receipt; no historical full-suite result is attributed
to these changed bytes.

Guarded full-repository **collection only** finished with exit 0: 22,010 cases
across 1,068 test modules. The tracked count and generated project documents
were synchronized to that collection, not to an unrun full-suite success.
The previous full backend receipt remains bound to the 7b6 source checkpoint.

## Remaining work and evidence limits

H487 is not complete. The ledger is an internal storage primitive: it is not
called by production queue/owner/dispatch paths and grants no execution authority.
Required next steps are verified producer capture at enqueue, reviewed category
classification/stable registration identity, atomic follower decisions with each
task's independent mediated receipt, real owner HTTP/HUD/Telegram choices and
revocation checks at physical dispatch. Smart DENY retains once/reject only.
Other accepted producers/channels and live acceptance remain requirements.

HMAC does not prevent restoring an older valid grant together with its old signed
active decision or restoring an entire DB snapshot. A monotonic revocation anchor
is required before claiming resistance to that attack. The work-run metadata
checksum is likewise not authentication against a privileged whole-store writer.
Shared-connection serialization belongs to the caller.

Final record/reference/status union passed **228 cases**, zero failures/errors/
skips. Hermes generated reports and project-status checks are in sync. Scoped
Bandit against the existing baseline found zero new findings and zero errors;
Gitleaks found zero secrets in the exact 16-file changed set.

## Changed paths

- `agents/core/autonomy/consent_ledger.py`: signed category/decision storage.
- `agents/core/autonomy/work_runs.py`: frozen explicit-deadline wait ceilings.
- `tests/test_h487_consent_ledger.py`: grant, identity, revocation and transaction regressions.
- `tests/test_h487_human_wait_budget.py`: union, restart and metadata bounds.
- `tests/test_h487_human_wait_integration.py`: real CompanyMode long-deadline checks.
- `docs/hermes/h487-reusable-consent-design-2026-10-03.md`: design, contracts, remaining integration.
- `docs/hermes/evidence/h487-consent-wait-progress-2026-10-03.md`: delivery and limits.
- `docs/hermes/evidence/h487-consent-wait-progress-2026-10-03.json`: source and artifact hashes.
- `BACKLOG.md`: truthful unfinished H487 continuation.
- `HERMES_STATUS.md` and `docs/HERMES_CAPABILITIES.md`: generated evidence freshness.
- `project-status.json`, `README.md`, `NERVA.md`, `STATUS.md`, `GO_LIVE_PLAN.md`:
  collected test-count synchronization; no full-suite or deployment claim.

Generated assessment remains **180/697 equivalent (25.8%)**: 261 partial, 62
missing, 194 requiring review, zero excluded. Changed shared evidence moved two
previously current reviews to needs-review; their hashes were not blindly
restamped. Existing equivalence counts received no credit for this increment.
Next action: connect the consent store to verified producer/owner/dispatch
contracts, then run broader milestone verification and claim-specific reviews.
Rollback: revert this increment; preserve existing queue/chat history. New consent
tables remain inert without production integration.
