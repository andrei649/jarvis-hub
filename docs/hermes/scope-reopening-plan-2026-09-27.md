# Reopen the former Hermes exclusions

Goal: make the owner's full-parity directive visible in the generated status
without rewriting historical inventory or granting implementation credit.
Base/head: `bd2bb70ead1b493043a335e77713fc42c47d4013` plus local sprint work.
Generated: 2026-09-27. Owner: coordinator; no subagent edits these paths.

1. Extend the assessment reader with a version-2 additive `scope_reopenings`
   collection. Each entry names an existing excluded ID, its frozen row hash,
   the decision date and the owner's reason. Version 1 retains its old behavior.
2. Validate exact fields, distinct excluded IDs, dates and identity hashes.
   Reopened rows without a code review become `needs_review`, including rows
   whose historical technical state was superior. A later equivalence review
   still needs current source and test evidence and no remaining work.
3. Record all 107 former exclusions under the already authorized directive.
   Keep the frozen 697-row ledger byte-identical and preserve all existing IDs.
   September upstream additions require a separate inventory migration.
4. Generate truthful counts, scope labels and per-row basis. Test malformed and
   stale identities, duplicate decisions, no completion credit, later reviewed
   equivalence and the real 697-row mapping before regenerating reports.

Owned paths: `scripts/hermes_status.py`, `tests/test_hermes_sprint_status.py`,
`docs/hermes/assessment.json`, this plan and the two generated Hermes reports.
Rollback: restore this increment's schema/reader/tests/reports together, leaving
all feature implementations and unrelated local changes untouched. No remote
operations, runtime settings or provider calls are involved.

Implemented: version 2 carries all 107 explicit reopenings. The frozen inventory
hash and bytes are unchanged; all 697 IDs remain stable. Reopened rows start at
`needs_review` without completion credit. Version-1 data keeps its prior rules.

Verification: the new behavior first produced three expected failures. Reader,
identity, malformed-entry, evidence and generated-report checks then passed
(47 tests). The remaining existing images/SDK test depends on shared UI evidence
hashes and will run with the final sprint evidence refresh. This is not a claim
that all old or new feature tests have already passed after this migration.

Next action: review the readmitted families and record tested capability results
individually. No feature equivalence was granted by the scope migration.
