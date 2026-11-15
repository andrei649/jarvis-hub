# Sync containment and benchmark reconciliation

Prepared 2026-11-14 over `e355da06d7c4a5275401ee2925582c195d270235`, incorporating the reviewed containment parent `4f61b8d196eeaab8dcdffd9bcf65a427ea089493`. The parent's source includes the bounded macOS journal repair.

The previous B5 benchmark expected incoming snapshots to overwrite settings and skill files, then imposed a timestamp order in the test harness. Those expectations conflict with safe inbound containment. The updated, explicitly versioned `nerva.differentiator_bench.v2` workload measures encrypted candidate staging and preservation of local edits instead. It does not claim automatic synchronization, last-write-wins reconciliation, import or installation.

Across all six arrival orders of three peers, the workload retains the same six candidates, preserves existing settings/skill bytes, and preserves further local edits through restart/replay. Mutating outer digest/device/timestamp metadata cannot suppress authenticated candidates. Existing secret-stripping, plaintext-field refusal, hostile-skill quarantine and eight ciphertext-tampering checks remain. B1–B4 deterministic metrics are unchanged.

Both report artifacts were regenerated from actual offline execution: five bounded workloads passed with zero socket attempts. The eight existing benchmark tests pass, including strict fresh-artifact comparison and negative/link checks. Illustrative baseline fixtures are now identified as such; Hermes and OpenClaw were not executed and no superiority is inferred. Historical artifact filenames remain for link compatibility.

The coordinator's combined 66-test backend run covers sync, its legacy crypto/alias contracts, generic macOS journal/import tests and all benchmark tests. Full Ruff and the unchanged full Bandit gate are recorded in the publication receipt. Seven rendered HUD tests and TypeScript checking passed on the identical inherited frontend source.

Expected locked totals are backend **36820**, frontend **3213**, mobile **420**: previous actual CI totals plus the verified 22 backend and six frontend additions from the parent. Benchmark edits add no test nodes. These counts are not a claim of a complete local test run; new-head CI must verify them.

Remain draft. Candidate retrieval/import/install UX, automatic reconciliation and application receipts remain unfinished. Composed/native macOS acceptance and the previously blocked cumulative lifecycle/security review remain unresolved. Generic text-file tests are not device/update/restart proof. No deploy, service activation or network reconfiguration occurred.

## CI follow-up, 2026-11-15

On `c75d33487d9dc807fd3a0cb52d7b2791e66d3cf7`, HUD tests, both TypeScript checks and the build passed, but the committed bundle check failed. Both outputs were regenerated with the canonical build; a repeat produced identical hashes for all 27 output files. Only generated-output conflicts with parent `d000cf8b0b4c7a69b0a0332e8b575e6a1cdfb68a` were resolved this way; application source was preserved.

Linux job 132599651628 also found four benchmark fixture text operations without explicit encoding. The existing Windows encoding guard reproduced the failure; adding UTF-8 to those four calls makes the four guard tests and eight benchmark tests pass (12 total). Existing artifacts still match strict fresh generation. No gate, timeout or baseline was weakened.

The other Linux failure was the unchanged Chromium fixture failing its native readiness deadline before the orphan-reaper assertion ran. Exact fixture/test/reaper bytes match published head `cac4704`; this does not prove a main merge or passing behavior. No browser/reaper source change is justified by the available evidence. Runner contention is only a possible explanation; new-head CI must confirm the result. This follow-up does not clear the existing cumulative/native review holds.
