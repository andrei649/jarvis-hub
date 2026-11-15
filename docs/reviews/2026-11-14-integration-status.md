# Open PR integration checkpoint — 2026-11-15

Observed **00:11 UTC**. Owner authorization covers review and merge of eligible PRs. Main remains `a5dc55fbebe70c8359e50a63c5fe1ae7fc4af06d` (merged #1360). The backlog and Hermes integration are **not complete**.

| PR | Published head | State at observation |
|---|---|---|
| #1363 | `cac4704cf9012d4fa86ac55f4cb479862405236a` | Ready; 13 checks passed, Windows cancelled at the 180-minute limit. Cannot merge under the trusted check policy. |
| #1365 | `17eaceaa2c89872c58528dfc3e36a33b151aeb38` | 13 checks successful/skipped. Draft; cumulative review hold and prospective source conflicts remain. |
| #1366 | `6342dbbd75f612ce1aec7f0cbc34e5f242ecd910` | 13 checks successful/skipped. Mac journal repair published; draft pending inherited review/native acceptance. |
| #1367 | `d000cf8b0b4c7a69b0a0332e8b575e6a1cdfb68a` | HUD freshness repaired and green; Linux running. Incoming sync deliberately stages candidates only. |
| #1368 | `c235250071b49b24e0b92e7f78c5d952fa0e2095` | Encoding and generated bundle corrections published; new CI running. |
| #1369 | Previous `c2f6ecbf3d3e63c60c6b740a6cc96d0da7a7a5ea`; this refresh over `c235250` | Previous head green; resolve the containing commit and its own CI before using this refresh. |

These PRs form a dependency stack. Separate green checks do not validate an untested combination. PRs #1359/#1361/#1362 were closed as superseded by #1363, and #1364 as an ancestor of #1365; source history was retained. Those closures do not mean their features are on main.

## Delivered repairs and proof

The earlier [MoA](2026-11-14-moa-repair.md), [sync/pets/environment](2026-11-14-sync-pets-repair.md) and [streaming/CLI](2026-11-14-streaming-cli-repair.md) repairs remain. Their recorded focused groups are 194, 375 and 521 tests respectively, with bounded follow-ups documented in those reports.

- [macOS journal repair](2026-11-14-macos-journal-repair.md): the caller retains replacement intent through partial failure, restoration preserves recovery copies, and incomplete recovery is explicit. **12 generic file-journal/module-load tests passed.** This is not a rollback of the owner's Mac or native TCC proof.
- [Incoming sync containment](2026-11-14-sync-containment.md): authenticated candidates are retained in a bounded encrypted SQLite inbox; settings and skill files are not overwritten. API/HUD/CLI report staging honestly. **46 backend and seven rendered HUD tests passed.** Candidate retrieval/import/install remains unfinished.
- [Benchmark reconciliation and CI follow-up](2026-11-14-sync-benchmark-reconciliation.md): the v2 benchmark measures staging and local-data preservation. Five offline workloads completed with zero socket attempts; illustrative baselines do not establish superiority over products that were not run. The **combined 66-test** backend run passed; the final UTF-8 fix passed **12 guard/benchmark tests**, including strict artifact comparison.
- Both canonical HUD outputs were regenerated using existing dependencies; a repeat reproduced all **27 output hashes**. No workflow, timeout, test gate or dependency was weakened. The corrected #1367 HUD job is green.
- The refreshed taskpack's **10 helper tests pass**. Full Ruff and the unchanged Bandit baseline gate passed for the containment source.

These groups overlap; do not sum them. Expected #1368 locked totals are **36820 backend / 3213 frontend / 420 mobile**, based on prior actual CI plus reviewed collection deltas. Exact-head CI must confirm them; they are not a full local pass claim.

## Remaining integration and acceptance holds

1. **Windows #1363:** job [132569127431](https://github.com/andrei649/jarvis-hub/actions/runs/43634774758/job/132569127431) was cancelled at three hours. Setup, dependencies and Ruff passed; the test step did not finish. Repeated connector requests for the raw log returned `Transport closed`, and the run has no artifacts. Existing diagnostics already print test names and thread stacks. Recover that log to identify the cause; no blind repeat, timeout increase or success claim was made.
2. **Cumulative review:** the previously platform-blocked update/restart security review remains unresolved. It was not retried or bypassed; green functional tests do not replace it.
3. **Combination conflicts:** the [read-only preview](2026-11-14-prospective-conflicts.md), with [exact paths](2026-11-14-prospective-conflicts.json), found **62 conflict paths** between `cac4704` and `17eace`: 17 production, 10 tests, 21 generated HUD and 14 docs/status. No combined source was produced or tested. This is additional future #1365 integration work, not a new defect in #1363's independent scope.
4. **macOS acceptance:** generic rollback-state defects are repaired; real-device TCC/native acceptance is still unverified.
5. **Sync completeness:** containment deliberately disables automatic incoming application. Outbound owner-skill discovery, candidate retrieval, explicit consent/import/install, key migration and atomic application/replay recovery remain open. Inbox receipts prove staging only.
6. **Previous #1368 Linux run:** explicit UTF-8 omissions were repaired. Its other failure was unchanged Chromium fixture readiness before the orphan-reaper assertion ran. Available evidence does not justify a production change; new-head CI must establish the result.

## Next-agent handoff

Use the [small-model package](../superpowers/plans/2026-11-14-small-model-backlog/README.md) from the **#1369 commit containing this handoff**. Its application-source baseline is `c235250071b49b24e0b92e7f78c5d952fa0e2095`; that earlier commit does not contain the planning package. The package preserves **697 contracts, 93 backlog records and 26 packets** (16 ready, six implemented, three needs-design, one external). Recorded ledger totals remain **187 equivalent / 474 partial / 0 missing / 36 excluded**; these are ledger verdicts, not 100% live acceptance.

SM-009 now covers only real outbound owner-skill discovery; SM-010 requires reviewed retrieval/consent/application design. Do not reassign the six implemented packets. First confirm new CI and recover Windows diagnostics; after an eligible #1363 merge, reconcile #1365 source contracts in an isolated checkout and rerun affected integration tests before advancing the stack.

No deploy, service/scheduler reactivation, network reconfiguration or Drive upload occurred. The original dirty workspace was preserved. Delegated workers used gpt-6.1-sol/medium; no token/cost measurement is claimed. The [structured receipt](2026-11-14-integration-status.json) records exact observations and limits.
