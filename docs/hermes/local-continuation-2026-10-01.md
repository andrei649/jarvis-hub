# Local Hermes continuation — 2026-10-01

- Goal: complete functional parity with pinned Hermes, including H277 and all
  697 accepted inventory rows plus separately identified upstream additions.
- Base: `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`.
- Branch: `codex/local-hermes-continuation-20261001`.
- Reference: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
- Publication: none; no push, merge, deployment, paid provider calls or personal
  profile imports are authorized for this continuation.
- Head/evidence freshness: the base above starts this batch; subsequent local
  commits and their test snapshots must be recorded separately.

## Plan and ownership

1. Revalidate the H277 handover on current code. Keep historic mutation receipts
   unchanged. Re-run the 14 shared-runner mutations in a disposable archive of
   the exact base, counting invalid anchors/setup errors separately from kills.
2. Repair task-bound permission-grant replay. The implementation agent owns
   `agents/core/permission_ledger.py` and focused tests. Transactions must roll
   back failed effects; replay must not duplicate or restore revoked authority.
   Existing ambiguous legacy rows must not make the whole ledger unusable.
3. Design and implement a real video-analysis consumer for H277. This is separate
   from H516 video generation. The contract must cover actual tool offering and
   execution, bounded sources, role/model selection, destination/credential
   binding, consent and output provenance. Provider/fallback expansion stays in
   the full goal; an initial transport cannot silently replace that contract.
4. Review each coherent change, run focused regressions after implementation,
   then run the relevant integration/full suites serially at the milestone.
   Update only re-read Hermes evidence, BACKLOG and generated test counts.
5. Continue the remaining capability queue and reassess prior exclusions;
   neither this plan nor one completed batch closes the full-parity objective.

The coordinator owns integration and records. At most two Sol High implementers
work concurrently, with one writer per source file and no subdelegation.

## Verification and rollback

Permission tests cover actual SQLite audit/commit failures, uncertain commit,
restart, concurrent instances, payload mismatch, inactive authority and legacy
adoption. Video tests must cover real ToolRPC-to-mocked-native-transport dispatch,
not merely schema presence. H277 mutation baselines and restoration hashes pin
their own source snapshot. Existing socket/time limits remain enabled.

Rollback a local feature commit independently; retain prior user work and
historical evidence. Do not promote H277 or any compound row to equivalent while
accepted requirements remain unimplemented or unverified.

Next action: inspect current mutation results and the permission regression;
settle the video source/authority interfaces before assigning code ownership.
