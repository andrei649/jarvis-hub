# Paused checkpoint — 2026-10-29

The owner paused implementation and requested publication of all current work.
The integrated draft remains [PR1321](https://github.com/andrei649/jarvis-hub/pull/1321).
Unreviewed source is preserved on the two WIP branches below; it has not been
merged into the integrated branch. No merge, deployment or provider activation
is performed by this checkpoint.

| Work | Branch and saved commit | State |
| --- | --- | --- |
| Integrated implementation and evidence | `codex/local-development-20261028`, through `22007e7b` plus this handoff | Reviewed implementation; latest full backend proof remains source-bounded to `e68eb272`. |
| Native browser dialogs | [codex/native-dialog-supervision-20261029](https://github.com/andrei649/jarvis-hub/tree/codex/native-dialog-supervision-20261029), `e5b0a4114a53ae4d539cceedb5d8eeee6c985cc1` | WIP Round1 repairs; independent final review and root integration pending. |
| Windows private store, locking and SQLite | [codex/windows-h011-unit2-plan-20261029](https://github.com/andrei649/jarvis-hub/tree/codex/windows-h011-unit2-plan-20261029), `af52873a8cc180010271857b475cc39233127704` | Unit2 source checkpoint; independent source review and actual Windows execution pending. |

## Verified integrated baseline

- Full backend on unchanged `e68eb272`: 30,392 passed, zero failures/errors,
  111 skipped, 30,503 total. This is not a full passing result for later source.
- Integrated source collects 30,544 backend cases; prior complete frontend
  2,703 passed with unchanged frontend source, mobile359 reused, 734 HTTP routes.
- Windows read primitives on `b5134e9a`: [job123389933746](https://github.com/andrei649/jarvis-hub/actions/runs/40856875302/job/123389933746)
  passed40 tests, including6 actual native cases, with zero skips/errors/failures.
  Windows Server2025 build26100, Python3.12.10 x64, NTFS. See the
  [source-bounded receipt](../hermes/evidence/windows-read-primitives-b5134e9a-2026-10-29.json).
- Windows H011 production history remains disabled. The isolated Unit1 proof
  does not establish private-store, capture, restore, maintenance or GC support.

## Browser WIP handoff

The first frozen candidate `21a3e58f` failed three P1 reviews: initial-start modal
discovery, popup implicit dismissal, and durable authority revocation after an
await. The saved repair includes focused regressions for all three, a deterministic
reaper race repair, and separate confirmed native response versus incomplete
opener settlement for beforeunload dismissal. Author-reported focused results:
326 backend,46 action-matrix,17 HUD parity passes; actual Chrome focused start,
popup, beforeunload accept and dismiss runs passed. A final complete frozen Chrome
result and independent scoped reviews are still required; these focused results
must not be treated as full integration acceptance.

An additional outstanding readiness issue was identified immediately before
pause: `action:browser.dialog` is currently WIRED, but its generic
`action-browser-dialog-kernel-halt` reality case defaults to promotable. That
kill-switch probe does not establish the owner/worker/native response contract.
Remove it from generic promotable coverage, add a dedicated non-promotable
refusal case, and classify the honest coverage gap before integration. No fix
for this finding is claimed in the saved checkpoint.

Root integration still needs exact reviewed source, four new admin-only dialog
API routes, generated types/assets/snapshots, fresh auth/parity checks, full
frontend and native checks, and semantic/citation reconciliation of the actual
affected Hermes claims. Preliminary impact:132 rows; H306/H538/H616 have conditional
semantic text changes, others preserve verdicts. Broader frame/background/native,
vision, governed JS, CDP, engines, profile consent, recording and spill/reaping
requirements remain open.

## Windows Unit2 WIP handoff

The spec and plan were independently approved before implementation. Source
adds protected private creation, held store/lock identities, LockFileEx, shared
identity probes and synthetic ordinary-SQLite crash/substitution tests. Latest
author-reported local selection:49 passed,14 native Windows skips on Mac; the
focused Windows workflow requires at least63 collected cases and zero skips.
There is no native Unit2 passing claim yet. Strict Unit1 read/store/lock policy
remains separate from restricted inherited SQLite sidecar ACL handling.

Review the six-file Unit2 diff against `b5134e9a`, run its Windows lane, and
preserve truthful claim/row/guard/uncertainty ordering. Destination-leaf-ID CAS
and a custom SQLite VFS/connection-ID hook are not invented POSIX parity gates;
stronger mechanisms require a concrete native failure and separate review.

All39 open backlog items and all697 accepted Hermes contracts remain in scope:
134 equivalent,446 partial,117 missing, zero excluded. Work remains paused until
the owner resumes it. Local recovery refs and private runtime material are
preserved; ignored credentials, runtime data and raw private logs are not
published as repository source.
