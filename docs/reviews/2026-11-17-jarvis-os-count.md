# PR #1372 backend count follow-up

Goal: fix the generated count mismatch without weakening the existing CI guard.
Investigation base: `3f47f602ffb21bf00e062d3e2599642a4792b02d` (2026-11-17 UTC).

## Hosted evidence and access limit

[Attempt 2 Linux job](https://github.com/andrei649/jarvis-hub/actions/runs/44029100603/job/133895869640)
passed the backend Test step and all **23/23 Hermes areas**. Only the count step
failed. At 08:12:51 UTC its exact-JUnit guard printed:

```text
backend test count: 37071 (tracked 37070)
```

The workflow did not upload the XML; its artifact list is empty. The terminated
hosted runner's raw `pytest-junit.xml` cannot be downloaded. The aggregate above
is directly evidenced by the guard that read it. The specific hosted module skip
is inferred from the matching pinned dependency set and local evidence below;
this report does not claim to have inspected a hosted testcase record.

## Reproduced cause

At the investigation base, the real local collect-only run reports **37,070
items**, while its collection-only JUnit has exactly **one** testcase:

```xml
<testcase classname="" name="tests.test_h070_discord_media" time="0.000">
  <skipped message="collection skipped" />
</testcase>
```

`tests/test_h070_discord_media.py` calls `pytest.importorskip("discord")` at module
scope. Discord is absent from the locked core test environment. Pytest emits a
JUnit collection-skip outcome, but the module contributes no collected items.
Thus **37,070 items + 1 collection outcome = 37,071 reported outcomes**. The prior
generator used only the textual item count; CI correctly used the full JUnit
aggregate. Regenerating counts for this PR exposed that pre-existing mismatch.

The earlier local broad JUnit also contains that exact empty-classname skipped
record. Tiny isolated pytest trees reproduce the discrepancy independently of
Jarvis: an ordinary item plus a skipped module produces two JUnit outcomes but
only one collected item.

## Repair

The generator now uses one collect-only subprocess with a unique private temporary
JUnit report, adding its collection-phase reports to the ordinary item count.
Test bodies are never executed during generation. Runtime skips are already
collected items and are not added twice. Failed collection and missing/malformed/
invalid report data refuse to update the count. The nested-project-collection
guard remains intact. XML parsing uses the already pinned `defusedxml`, imported
only inside the live collector; bare-Python backlog/help and fast consumers retain
their previous import behavior.

The exact-JUnit parser, comparison and CLI verification functions are unchanged
(AST equality checked). No workflow, security setting, skip list or acceptance
policy changed. The status caption now says **reported**, accepting legacy
`passed`/`collected` wording on input, so it does not imply every outcome executed.

Eight regression cases were added. Fresh generation computes **37,079**, accounting
for those cases and the collection report; this value was not set by hand.
Frontend/mobile tracked counts are reused, not newly asserted as executed.

## Verification and publication

- RED observed: real tiny module-skip and module+runtime-skip comparisons returned
  one too few; missing/malformed/invalid reports were incorrectly accepted.
- GREEN: real tiny collection-vs-full-JUnit cases, collection-error refusal,
  report validation and nested-collection refusal pass.
- Independent review found an eager-import compatibility regression; a failing
  `python -S scripts/backlog.py --help` regression was added, then fixed by lazy
  importing XML support. No dependency or lockfile change was needed.
- PASS: final status/release/build/documentation integration, **70 tests**; full
  repository Ruff; targeted Bandit with zero findings; fresh live generator and
  generated-status consistency; bare-Python backlog help. Existing local network
  guard warning blocked an ambient non-loopback connection attempt.
- Pending: new-head hosted count verification. It must complete before it can be
  described as passing; the earlier head's successful backend/Hermes result is
  retained as separate evidence. No new full local backend or frontend/device
  acceptance is claimed for this tooling-only follow-up.

Scope: `scripts/status_sync.py`, `tests/test_status_sync.py`, five generated status
mirrors and repair/continuation evidence. Rollback is a revert of this follow-up
commit. Keep the PR draft. No merge, deploy, real-data activation or credential
access was performed.
