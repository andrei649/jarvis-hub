# Sync containment and benchmark reconciliation

Prepared 2026-11-14 over `e355da06d7c4a5275401ee2925582c195d270235`, incorporating the reviewed containment parent `4f61b8d196eeaab8dcdffd9bcf65a427ea089493`. The parent's source includes the bounded macOS journal repair.

The previous B5 benchmark expected incoming snapshots to overwrite settings and skill files, then imposed a timestamp order in the test harness. Those expectations conflict with safe inbound containment. The updated, explicitly versioned `nerva.differentiator_bench.v2` workload measures encrypted candidate staging and preservation of local edits instead. It does not claim automatic synchronization, last-write-wins reconciliation, import or installation.

Across all six arrival orders of three peers, the workload retains the same six candidates, preserves existing settings/skill bytes, and preserves further local edits through restart/replay. Mutating outer digest/device/timestamp metadata cannot suppress authenticated candidates. Existing secret-stripping, plaintext-field refusal, hostile-skill quarantine and eight ciphertext-tampering checks remain. B1–B4 deterministic metrics are unchanged.

Both report artifacts were regenerated from actual offline execution: five bounded workloads passed with zero socket attempts. The eight existing benchmark tests pass, including strict fresh-artifact comparison and negative/link checks. Illustrative baseline fixtures are now identified as such; Hermes and OpenClaw were not executed and no superiority is inferred. Historical artifact filenames remain for link compatibility.

The coordinator's combined 66-test backend run covers sync, its legacy crypto/alias contracts, generic macOS journal/import tests and all benchmark tests. Full Ruff and the unchanged full Bandit gate are recorded in the publication receipt. Seven rendered HUD tests and TypeScript checking passed on the identical inherited frontend source.

Expected locked totals are backend **36820**, frontend **3213**, mobile **420**: previous actual CI totals plus the verified 22 backend and six frontend additions from the parent. Benchmark edits add no test nodes. These counts are not a claim of a complete local test run; new-head CI must verify them.

Remain draft. Candidate retrieval/import/install UX, automatic reconciliation and application receipts remain unfinished. Composed/native macOS acceptance and the previously blocked cumulative lifecycle/security review remain unresolved. Generic text-file tests are not device/update/restart proof. No deploy, service activation or network reconfiguration occurred.
