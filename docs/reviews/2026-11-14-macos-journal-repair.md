# macOS replacement journal repair

Base: `fd5c9c1f5e7c999a59aef3323b8273842e84b603`. Prepared 2026-11-14 in an isolated checkout for the owner's review-and-merge task. This remains a draft repair with limited verification.

The library staging helper formerly returned its rollback journal only after every replacement succeeded. An earlier failure lost the recovery records; rollback could also delete a backup after restoration failed. Static review found the same stale-backup deletion and suppressed restoration outcome in the binary replacement loop.

Both loops now use one caller-owned journal. Intent is recorded before renaming the original; completed rename steps are tracked separately. Existing recovery backups cause refusal. Restoration atomically replaces the destination from the backup, preserves both copies if restoration fails, and continues recovering other entries. Retrying recovery cannot delete already-restored originals. Binary and library recovery failures are reported separately. Temporary staging files are cleaned without deleting recovery copies.

## Evidence

- Two original byte-preservation regressions failed before the change.
- Twelve focused tests of the generic journal, recovery and failure reporting passed using ordinary text files in private temporary directories. Cases include partial failure, multiple entries, failed/missing backups, retry, stale backup refusal and independent binary/library recovery outcomes.
- A standalone module-load regression reproduced a new dataclass/loader incompatibility; the internal record is now a plain class compatible with the existing bootstrap loader. No bootstrap operation was invoked.
- Independent coordinator review traced both production callers and their exception paths. Relevant Ruff and whitespace checks passed; the unchanged full Bandit baseline gate passed.

These tests did **not** invoke the anchor, interpreter/library staging, signing, boot gate, bootstrap, updater or restart. The existing composed H690 tests were not run locally in this repair. The in-memory journal does not establish process-crash recovery or correctness under arbitrary external filesystem mutation. No macOS device or TCC permission-continuity acceptance is claimed.

The earlier platform-blocked cumulative update/restart adversarial review remains unresolved and was not retried or bypassed. Functional CI and these generic tests cannot clear that hold. Keep the dependent PR stack draft until applicable integration/security review is completed. No deployment or service activation occurred.

Expected locked backend count: **36735**, from the prior successful CI count 36723 plus the 12 new executed test cases. Full local collection with the first 11 cases recorded 36743 (the local environment carries nine extra optional cases); the final additional loader case is included in the 12-case passing module. This accounting is not a full-suite pass; new-head CI remains authoritative.
