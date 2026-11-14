# Open PR integration checkpoint — 2026-11-14

Observed at **21:04 UTC**. The owner authorized review and merge of eligible open PRs. Source repairs are published; this is not a declaration that the backlog or Hermes integration is complete.

| PR | Reviewed published head | Observed state / next requirement |
|---|---|---|
| #1360 | merged as `a5dc55fbebe70c8359e50a63c5fe1ae7fc4af06d` | Merged into main after review and green checks. |
| #1363 | `cac4704cf9012d4fa86ac55f4cb479862405236a` | Ready; 13/14 checks passed, Windows full suite running. Refresh before merging. |
| #1365 | `17eaceaa2c89872c58528dfc3e36a33b151aeb38` | Main conflicts resolved; CI green. Draft pending cumulative lifecycle review. |
| #1366 | `fd5c9c1f5e7c999a59aef3323b8273842e84b603` | MoA and integration defects repaired; CI green. Draft pending macOS rollback and inherited review holds. |
| #1367 | `8a27fee5b28cddaacbc2e73f105385f1dc99ebad` | Sync metadata, pets and environment repairs published; Linux suite running. Sync conflict/admission holds remain. |
| #1368 | `e355da06d7c4a5275401ee2925582c195d270235` | Combined streaming, CLI and benchmark repairs published. Gitleaks passed; Linux/HUD/Semgrep still running at observation. Inherits the stack's holds. |
| #1369 | Planning refresh over `e355da0` | Refreshed catalog and handoff; application bytes match #1368. Resolve its current head from GitHub. |

The six open PRs are a dependency stack, not six interchangeable merges. After any main change, refresh/reconcile the next branch and rerun affected checks. Separate green PR checks do not prove an untested combination. #1363 must finish first; #1365 and its descendants stay draft until their concrete holds are resolved.

PRs #1359, #1361 and #1362 were closed as superseded by #1363; #1364 was closed as an ancestor of #1365. Branches and source history were retained. Their closure does not mean all their features are already on main.

## Implemented repairs and evidence

- [MoA repair](2026-11-14-moa-repair.md): real cloud streaming signatures, active-preset selection pins, environment/component guards; **194 focused tests passed**.
- [Sync and pets repair](2026-11-14-sync-pets-repair.md): default-path metadata restoration, bounded ZIP validation, alias and credential/path classification, exact component inventories; **375 focused tests passed**, followed by **15 pet** and **36 final classification/alias** checks.
- [Combined streaming/CLI repair](2026-11-14-streaming-cli-repair.md): falsey callback privacy, actual stream redaction, optional-dependency handling, static migration import, alias consistency, delegation compatibility and exact binding pins. **521 focused integration tests passed** before two bounded follow-ups; **8 CLI/skin** and **8 benchmark** tests passed afterward.
- Benchmark accounting now declares synthetic UTF-8 byte-based units; optional tokenizer cache state cannot alter its deterministic result. Artifacts were regenerated from actual offline execution. Production tokenization and strict artifact comparison remain unchanged. These simulated baselines do not establish live superiority over Hermes or OpenClaw.
- Unchanged full Bandit baseline gate, relevant Ruff and whitespace checks passed. GitHub Gitleaks passed on `e355da0`; the local pinned detector/negative-control exercise was not run.

These groups overlap; do not sum them as a unique test total. The expected locked Linux JUnit count for #1368 is **36798**, derived from authentic baseline CI plus a verified collection delta. It is not a claim that 36798 tests passed. Full exact-head CI remains authoritative.

## Remaining blockers

1. The cumulative update/restart security review was previously blocked by the platform. It was not retried or circumvented, and functional CI does not clear it.
2. macOS library staging can lose its rollback journal when staging fails partway. Real TCC permission continuity also needs platform evidence.
3. Sync snapshot application can overwrite newer local changes. Constructor persistence is repaired; conflict/replay semantics and skill discovery/admission remain separate unfinished work.
4. #1363 still needs its final Windows result. Do not treat pending or cancelled checks as passed, or relax the trusted merge policy.

## Next-agent handoff

Use the [refreshed small-model package](../superpowers/plans/2026-11-14-small-model-backlog/README.md). It preserves **697 contracts and 93 open backlog records**. Recorded ledger totals remain **187 equivalent / 474 partial / 0 missing / 36 excluded**; those are source accounting, not live certification.

SM-002, SM-003, SM-004, SM-005, SM-006 and SM-008 are marked locally implemented with reviewer evidence. The planning helper skips them and satisfies their implementation dependencies. SM-001 and SM-007 retain their outstanding exact-head/count and scanner evidence requirements. Broader packets, including sync protocol design and honest competitor comparisons, remain open. The helper's **10 offline safeguard tests passed**.

Refresh GitHub before acting. The current task authorizes eligible PR merges into main; it does not authorize deploys, release tags, paid activation, network reconfiguration or resuming paused services/schedules. Original dirty workspace/source archives were preserved. No Drive upload or scheduled report was performed. A transferable [structured report](2026-11-14-integration-status.json) accompanies this checkpoint.
