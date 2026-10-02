# Nerva PR integration continuation

**Goal:** Finish remaining PR integration, publish verified local Hermes progress,
and continue the accepted Nerva backlog. Owner explicitly authorized publication,
closing redundant PRs and merging useful drafts in the current request.
**Base:** remote main `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`;
local source `aa4865b5d061b52f3cee7e044dab2d922e4a4617`.
**Generated:** 2026-10-02. **Architecture:** Preserve existing local-first routing,
request authority and source-bound evidence. No dependency or global policy change.
**Rollback:** Revert the eventual integration commit; retain existing local commits.
**Non-goals:** Deployment, paid/live providers, credential import and unsupported
claims of full Hermes parity.

## Plan

- [x] Recheck GitHub: zero open PRs; useful dependency/UI/security fixes are merged.
  Redundant #1212/#1214/#1216/#1217 are already closed. Preserve their history.
- [x] Repair the remaining missing-blob test fixture with a red-first packed-object
  regression and a disposable object database; preserve commit history and actual
  missing-blob assertions. Own `tests/test_hermes_restamp.py` only for runtime fix.
- [x] Regenerate test counts and run the backend on a clean frozen commit. Preserve
  the failed aa4865b5 result (20503 passed, one failed,34 skipped,one xfailed).
- [x] Finish the 21 affected auxiliary evidence reviews without promoting the
  original207 stale rows. Update implementation/continuation records and checks.
- [x] Scan the exact publication set, push the existing continuation branch, open
  a reviewable PR, inspect every reported CI check, fix concrete failures and merge
  only the verified candidate. Do not infer CI success from local tests.
- [ ] Continue the next bounded Hermes backlog slice: acquisition auxiliary model
  selection with operation-bound backend/model and fresh request authorization.

## Verification focus

Packed and loose Git stores must produce the same missing-blob behavior. Existing
runtime model/guard source must stay unchanged during fixture repair. Do not mark
partial capabilities equivalent. Preserve frontend proof only where source matches.
Remote main and candidate SHA must be rechecked before merge.

PR1226 merged as a5b74939 after both CI rounds passed. GitHub required linear
history, so squash replaced the planned merge commit; the archive branch preserves
original source commits. Canonical local main is synchronized. The next step is
[acquisition routing](2026-10-02-h277-acquisition-auxiliary.md).
