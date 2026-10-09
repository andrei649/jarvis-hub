# H487 full-backend result, binding repair and collateral review

Goal: complete all 697 accepted Hermes capabilities locally. Generated 2026-10-03.
Tested base/head: `c70e040707d007e0a50d31243e69894dbf332bb6`.
Exact artifacts, module outcomes and source pins: [receipt](h487-consent-anchor-full-review-2026-10-03.json).
Prior storage milestone: [anchor report](h487-consent-anchor-progress-2026-10-03.md).
Next integration design: [owner/queue plan](../h487-owner-queue-integration-plan-2026-10-03.md).
All work remains local; no push, merge, deployment, provider spend or activation.

## Complete backend result and correction

The normal socket/30-second timeout guards remained enabled:

```text
python -m pytest -q --junitxml=/tmp/nerva-h487-consent-anchor-full-backend-guarded-20261003.xml
```

Terminal exit **1**, 1,150.123 seconds: **22,093 cases**, **22,057 passed**,
**34 ordinary skips**, **one existing xfail**, **one failure**, zero errors.
The xfail is the existing pending `tool:browser_run` registration in
`test_tool_backed_ids_match_the_real_toolrpc_registrations`. No complete-suite
success or new GitHub CI result is claimed. The 2,522 tracked source/test/config/
document hashes frozen before launch still matched after terminal completion;
the implementation and working checkout were not changed while it ran.

The sole failure is
`test_external_binding_writer_inventory_exactly_matches_production_calls`.
Its AST scan found no parse errors, new/removed bindings, ownership or column
changes. Exactly 14 existing coordinator writer locations moved by seven lines
when terminal producer provenance was added in bd38d00c. The focused test
reproduced the failure before correction. Only those 14 literal coordinates in
`agents/core/orchestrator_bindings.py` were updated. Every name/path/column and
the exact AST equality, alias and undeclared-writer guards remain unchanged.
All **50 tests in test_orchestrator_bindings.py pass**, zero skips/errors/failures,
8.328 seconds. The serial complete guarded rerun on the new checkpoint is
pending; its actual terminal outcome must be recorded separately.

## Claim-specific collateral review

A read-only `gpt-6-luna` Medium investigator matched historical pinned files in
local Git history and reviewed H262/H298/H309/H314/H315/H507/H594/H681. The
coordinator independently read their complete claims, verified all other pins
already match current bytes, and inspected the complete corresponding source
diffs: coordinator from 7b6c08c (H314's older pin from 1b7afa8c) and ToolRPC from
ce345581. The current additions declare registrar consent metadata and export a
private live-verified key; they preserve these accepted code contracts.

| Capability | Accepted behavior preserved | Referenced backend modules in the completed run |
| --- | --- | --- |
| H262 | Interval-gated retention prune/archive/optional VACUUM | 133 pass |
| H298 | Bounded result preview, durable spill and exact paging | 378 pass |
| H309 | Named canvas anchors and bounded pointer tips/tours | 60 pass |
| H314 | Owner-clean guarded/atomic memory operations and undo | 72 pass |
| H315 | Bounded per-session todo checklist, provenance and visibility | 274 pass, 1 skip |
| H507 | Nonblocking dangerous-code warnings on accepted write/install paths | 136 pass |
| H594 | Project conventions and actual terminal cwd/result context | 85 pass, 1 skip |
| H681 | Child override precedence and truthful batch failure causes | 195 pass |

Module results overlap across capabilities and must not be summed as separate
runs. Their tests have no failures in the first full execution despite its
unrelated binding inventory failure. Frontend source/evidence stayed unchanged;
no fresh frontend rendering, live project, device or provider acceptance is
claimed. Prior mutation reports remain historical rather than fresh mutant runs.
Only the changed coordinator/ToolRPC evidence pins and these eight summaries are
updated for restored equivalence. The binding correction also drifted H515's
inventory pin: its complete 14-coordinate diff preserves cloud_images ownership
and runtime binding. That exact pin alone is updated after source review and
the 50-case binding pass, retaining partial status and all image requirements.
Its referenced backend modules also have no failures in the completed first run;
the receipt records their overlapping counts. No other assessment record is
restamped or reclassified.

This restores existing documented equivalence after source drift: **181/697
(26.0%)**, 259 partial, 62 missing, 195 needing review, zero excluded. It adds no
new feature-equivalence credit. The H487 anchor/producer primitives still have
no owner-choice, follower settlement or physical execution consumer; H487 and
the full 697-capability goal remain unfinished.

## Remaining work and rollback

Finish the serial complete rerun, then implement the connected real-owner
terminal path in the next design: transactional source/current-grant checks,
authenticated session/always/deny choices, separate follower receipts, future
category reuse without fabricated human metadata, and current grant validation
at physical dispatch. Other accepted producers/channels remain required.
No live runtime state or permission has been activated by these records.

Changed paths: binding inventory, its focused design follow-up, eight existing
assessment records, generated Hermes reports, BACKLOG and the local evidence /
next-owner plan. Collected test counts and the historical CI stamp are unchanged.
Rollback: revert the literal inventory adjustment and record updates together
with the provenance source lines whose movement required it; preserving old
line coordinates with new source would deliberately make the exact guard red.
Do not erase task/chat history, consent evidence or the independent B7 anchor.
