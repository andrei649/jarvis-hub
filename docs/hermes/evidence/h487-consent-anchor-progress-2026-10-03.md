# H487 externally anchored consent revocation progress

Goal: complete all 697 accepted Hermes capabilities locally. Generated 2026-10-03.
Base/head before this increment: `bd38d00c816a9c2072892bba4040ce0d4ac9464c`.
Design: [revocation plan](../h487-consent-revocation-plan-2026-10-03.md).
Exact implementation/test hashes and local artifacts: [receipt](h487-consent-anchor-progress-2026-10-03.json).

Later follow-up at `c70e0407`: the complete guarded backend executed and exposed
one stale external-binding line inventory. Its reproduced correction and eight
claim-specific freshness reviews are recorded in the
[full-backend follow-up](h487-consent-anchor-full-review-2026-10-03.md).
The checkpoint results below remain historical; the follow-up is not a claim
that the failed complete run passed.

## Delivered behavior

ConsentLedger accepts an optional MonotonicHeadAnchor. Its signed local head
binds a deterministic manifest of all grant and decision rows, including row
identities, signed payload bytes and signatures. Each successful grant or
revocation advances the external head before releasing the local savepoint.
Lookup verifies both the SQL snapshot and current external head, including a
second verification before returning success. A concurrent revocation therefore
invalidates even a consistent older database snapshot.

The new consent file backend uses a separate lazily resolved
`security/h487_consent_head.json` path. Locked compare-and-swap rejects stale
heads and distinguishes an absent path from an existing malformed or unreadable
file. Writes use a temporary file, file fsync, atomic replacement and directory
fsync. The existing B7 head file and mediation policy are unchanged.

Only an empty consent store with no prior external head can bootstrap. Existing
unanchored grants are never silently adopted. Restoring former signed grant and
decision rows, or a complete older valid SQLite database, cannot reactivate a
revoked grant while the external anchor is preserved. Missing/corrupt/substituted
anchors and signing/CAS failures refuse authority. Caller transactions are not
committed by the ledger. If an enclosing transaction rolls back after external
advance, reusable consent becomes unavailable until separately reviewed recovery;
older permission is not restored.

## Verification and review

Two disjoint implementation agents used `gpt-6-sol` High, with one writer per
file and no child delegation, remote mutation or runtime activation. The ledger
implementer reported seven RED cases before the constructor/behavior existed,
then 30 passing ledger cases. The factory implementer's initial RED was an
absent-module collection error, followed by actual-file tests. The coordinator's
first five integration cases also failed before the factory existed. Later
behavior checks use real temporary SQLite backups/files and two database handles.

The coordinator reviewed the complete changed implementation and ran:

```text
python -m pytest tests/test_h487_consent_anchor_integration.py tests/test_h487_consent_ledger.py tests/test_h487_consent_head_store.py tests/test_task_mediation_head_store.py -q
python -m pytest tests/test_h487*.py tests/test_task_mediation_head_store.py tests/test_task_mediation_evidence.py -q
```

The first final union has **83 cases**, exit 0, no failures/errors/skips, 1.677s.
The broader guarded union has **686 cases**, exit 0, no failures/errors/skips,
12.119s. These overlap and must not be summed. They cover database-prefix and
whole-database restoration, two file handles, concurrent revocation during
lookup, malformed/unreadable anchors, isolation from B7, caller transaction
rollback, and existing category/session/content constraints. An additional
read-only implementer review reran 19 actual-file/factory cases and reported no
concrete issue within the documented threat scope.

Normal pytest socket/timeout guards remain enabled. Full backend collection
exited 0: **22,093 cases in 1,073 modules**. This is collection, not execution.
There is no fresh full-backend run bound to this checkpoint. Ruff and diff checks
pass. Scoped Bandit reports zero new findings/errors against the unchanged
baseline. Graft was rebuilt and checked: wiring graph fresh, 48,717 nodes;
optional deep context remains absent. The receipt records the separate exact
changed-file secret scan and record gates when available.

The Hermes report remains **173/697 equivalent (24.8%)**, 259 partial, 62 missing,
203 needing review, zero excluded. No assessment is restamped or upgraded by this
storage-only increment. Collected counts/generated documents are synchronized
without claiming a new GitHub CI result.

## Remaining work and limits

H487 is unfinished. This primitive is not connected to real owner session/always
choices, atomic follower settlement with each task's own B7 receipt, or physical
execution. An unanchored ledger remains evidence-only; production reuse must
require the anchored contract. Live registration/policy/target/category checks,
Smart DENY once/reject behavior, kernel/e-stop/hardline/budget floors, and
HTTP/HUD/Telegram/other producer integration still need complete behavior proof.

The external file protects against consent-database rollback, not restoration
of the entire runtime directory or compromised signer/CAS callbacks. A crash or
outer rollback between external advance and SQL commit deliberately sacrifices
availability. No automatic repair/re-adoption or operator recovery flow is
implemented. Ordinary explicit approval remains the existing separate path.

Next action: implement authenticated owner choices and queue/dispatch proof
integration, retaining this revocation boundary. Run the serial full guarded
backend at this integrated storage milestone and report its actual outcome.
No push, merge, deployment, provider spend or runtime activation occurred.

## Changed paths and rollback

- `agents/core/autonomy/consent_ledger.py`: optional signed manifest/head and
  verification around existing caller-owned consent operations.
- `agents/core/autonomy/consent_head_store.py`: independent durable file CAS.
- `tests/test_h487_consent_ledger.py`, `test_h487_consent_head_store.py`,
  `test_h487_consent_anchor_integration.py`: signed rollback, actual files,
  concurrent reads and transaction preservation.
- Revocation plan, this report/receipt and `BACKLOG.md`: scope, limits and next work.
- `project-status.json`, `README.md`, `NERVA.md`, `STATUS.md`, `GO_LIVE_PLAN.md`:
  collected backend counts only; existing CI stamp retained.

Rollback: revert this localized increment while preserving task/chat/history
and the independent B7 anchor. The new consent head/state remain inert without
production consumers. Removing an anchor must never make a populated store
bootstrap-eligible or authorize adoption of older signed grants.
