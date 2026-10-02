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

Progress: the 14 shared-judge mutations were killed on the exact base snapshot;
permission replay and restore-token durability are committed locally as `b7a15e89`
and `d2e065c4`. Video understanding now has approved native dispatch, independent
role consent and bounded vision-route inheritance. See the
[video implementation and verification report](h277-video-analysis-2026-10-02.md).

The immutable full-backend milestone passed on `78780b64`: 20,108 passed, 34 skipped
and one expected failure, with 1,836 frontend tests passing separately. Source hashes
were unchanged through the full backend run. PR reconciliation left zero open PRs;
the new continuation commits remain local on the branch above.

Current video mutation coverage is frozen on `92905443`: 29 detected, two documented
survivors and zero invalid mutations; 168 baseline tests pass and all 4,130 archived
source hashes were restored. See the [exact campaign](evidence/h277-video-mutations-verified-2026-10-02/report.md).

Configured provider-chain milestone: runtime `591c9e15`, full backend snapshot
`a38d7546`: 20,306 passed, 34 skipped and 1 expected failure. All 4,218
tracked regular source hashes remained fixed; full frontend has 1,838 passing tests.
The [current report](h277-video-provider-chain-2026-10-02.md) and its receipt separate
this proof from the earlier mutation campaign. New continuation commits remain local.

Native Gemini video milestone: code `0382ef0b`, frozen full-backend commit
`c4231b64982bbab150e564794b42ee3f7797247f`: **20,402 passed, 34 skipped,
1 expected failure, zero unexpected failures**, with 61 warnings. All 4,227 tracked
regular files remained unchanged through the run; the checkout stayed clean. The
707-case focused set includes 66 pure codec and 30 signed Gemini cases. Frontend
source/schema are unchanged from the separately tested `2d9a3c39` snapshot with
1,838 passing tests, typecheck and build. See the
[immutable Gemini receipt](evidence/h277-gemini-video-integration-2026-10-02.json)
and [implementation report](h277-gemini-video-2026-10-02.md).

Next action: turn the [retry investigation](h277-retry-investigation-2026-10-02.md)
into a bounded approval-bound transient-retry design, then continue shared auxiliary
routing, broader adapters and the accepted Hermes queue. Larger native video upload
lifecycle and live acceptance remain open. Keep H277 partial. The current
ledger has 172 equivalent, 254 partial, 64 missing and 207 requiring review out of
697 accepted rows. Preserve these local checkpoints and existing source evidence.
