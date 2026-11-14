# Sync, pet archive and integration contract repairs

Generated 2026-11-14 UTC. Candidate combines PR #1367 at `d454227dbb23702e8c8d2e0a00702e4f33d99846` with repaired parent #1366 at `fd5c9c1f5e7c999a59aef3323b8273842e84b603`. Owner requested review and merge of eligible PRs; this PR retains its documented merge holds.

## Changes and evidence

- Default-path E2E sync construction reloads persisted labels, peers and per-skill opt-outs, including when optional crypto is unavailable. Missing/corrupt metadata remains untouched during construction.
- Pet ZIP import uses the shared bounded archive validator and private temporary staging; traversal, links, normalized duplicates, size limits, corrupt CRC/data and cleanup are covered. The inventory permits the existing export writer while continuing to reject direct readers.
- Device, room and browser options use central aliases and typed readers. Command toggles use shared boolean parsing. Raw-read limits and alias inventory guards are retained.
- Capability snapshots add only the two actual constructed components, browser broker and pets, as wired. Exact inventory and executable probe checks remain. Sprite scale is classified as a bounded visual setting without changing safe-mode production policy.
- H040 checks the encrypted envelope and decrypted value; it no longer assumes a three-digit sequence cannot occur in random ciphertext.
- Pet activity/settings-mirror failures log only exception types, retaining existing fallback behavior.

Red regressions were captured before the fixes. Combined focused suites: **375 passed**. This includes sync, pets, archive validation, aliases, MoA, component guards, capability verification/readiness and safe-mode classification. It is not the full suite or real-device acceptance. No secret values are included in this report.

## Remaining holds

The automatic sync conflict winner policy is undefined. Current snapshot application can overwrite newer local edits; restoring constructor metadata does not fix that protocol defect. Synced skill staging also is not proof of complete loader admission. The inherited macOS rollback-journal defect and platform-blocked cumulative update/restart review remain open. No blocked action was retried, no services were activated, and no deployment occurred. Keep this PR draft until these findings have a valid resolution.

Final pet tests after the diagnostic-only changes: **15 passed**. The unchanged Bandit baseline gate exits 0, Ruff and whitespace checks pass. Expected locked Linux JUnit entries: **36768**, derived from the authentic 36700 parent CI total plus 68 exact new node IDs in successful same-environment full collection (36709→36777, no removed nodes). This is collection accounting, not a full-suite pass. Existing generated-status APIs preserve frontend/mobile counts and source provenance.

Independent review additionally found missing credential/path classifications. `ROOM_FENCING_SECRET` now receives credential interpolation refusal and `E2E_SYNC_DIR` receives path interpolation refusal, with both aliases exercised inside existing regression cases. No case count changed.
Final credential/path classification checks and alias regressions: **36 passed**.
