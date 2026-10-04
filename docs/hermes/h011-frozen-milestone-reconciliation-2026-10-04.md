# H011 frozen milestone and prepared H277 mutation follow-up

Generated 2026-10-04; base/source `45a2a9c2`. Goal remains all 697 pinned
Hermes capabilities. Local only; no push, merge, deployment or live effects.

The frozen backend ran all 23,120 cases with 23,080 passes, five failures,
34 ordinary skips and one existing xfail. All 3,098 input hashes remained
unchanged. Serial full clients passed: HUD V2 1,889, mobile 185, legacy HUD 233.

1. Reconcile the two AUD-7 tests with `save_memory`'s revision/checkpoint keyword
   arguments. Their old two-argument fakes raise TypeError before observation;
   production still awaits off-loop persistence. Use spies forwarding to real
   temporary-store writes and assert both append/snapshot thread identity,
   complete persisted turns and each durable revision. Keep rewind fences intact.
2. Add only the two intentionally introduced checkpoint actions to the readiness
   snapshot as WIRED, not VERIFIED. Update fixed harness counts from 31 to 33
   and 108 to 110, explicitly checking the new action case identities. Retain
   executable-case, promotion, coverage-gap and no-fabricated-proof assertions.
3. Review and integrate the prepared #23 public-route regression. The unchanged
   production guard is correct; the exact mutation leaked a sanitized loopback
   origin on a nonlocal unknown-policy custom judge. The new test is GREEN on
   current source and RED under that exact fault in an isolated snapshot.
4. Run affected persistence/rewind, real checkpoint effects, capability/harness
   and H277 API tests. Refresh only reviewed evidence impacted by these edits,
   including actual collection count, then freeze the next complete backend run.

Owned paths: tests/test_aud7_sse_hotpath.py,
tests/_snapshots/capability_readiness.json, tests/test_h27_capability_verification.py,
tests/test_h277_approval_judge.py, and relevant Hermes verification records.
No production change is indicated by these five failures. If new evidence
contradicts that finding, investigate and record it before modifying production.

Rollback removes these test/evidence updates; source behavior, history, payloads,
durable journals and audits are preserved. H011/H277 remain partial. A complete
test suite does not establish full functional parity or native/live acceptance.
