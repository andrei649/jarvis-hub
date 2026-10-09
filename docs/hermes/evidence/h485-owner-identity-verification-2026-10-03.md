# H485 Telegram owner identity verification

**Execution Plan:**

Base: `ce34558179a7fc267555952f8a3856b40c3317f6`, branch
`codex/h277-provider-discovery-20261002`. Continue the full 697-capability local
objective; this security prerequisite grants no new equivalence credit. The
[bounded design](../h485-owner-identity-plan-2026-10-03.md) records the
evidence-driven addition of separate persisted owner IDs.

**Files Modified:**

- `agents/core/telegram_owner.py`: pure canonical sender validation and explicit
  owner-list resolution. Malformed explicit configuration cannot inherit legacy
  authority. A group destination never identifies its owner.
- `agents/core/autonomy_coordinator.py` and `agents/core/orchestrator.py`: use
  that identity for decisions/reason replies and administrative commands. Use the
  existing environment-first destination resolver consistently. Callback authority
  requires a currently configured destination.
- `agents/core/settings_db.py`: nullable JSON `autonomy.owner_user_ids`, declared
  for normal settings persistence and reload. `null` preserves the legacy sender
  list; an explicit owner list is independent of ingress admission. Authority uses
  a single read-only, timeout-zero persisted snapshot, independent of the cache.
- `agents/core/orchestrator_bindings.py`: move only the 14 existing coordinator
  callsite positions by twelve lines; names, columns and authority are unchanged.
- `agents/core/channels/outbound.py`: allow the shared environment-first resolver
  to receive the fresh persisted destination. Ordinary outbound resolution is
  unchanged. `agents/core/channels/telegram.py`: acknowledge only applied callbacks.
- `frontend/src/gap.tsx` and its JSON settings tests: preserve explicit `null`
  through the settings editor. Regenerated committed HUD assets in `agents/web/v2/`.
- Owner/helper/settings, SEC-B3, slash-command and H117/H487 tests: real queue,
  settings persistence/reload, channel polling and administrative authorization.
  H117's fixture explicitly declares its owner while guest ingress remains open.

**Verification Results:**

- Initial guarded integration: 207 passed / 21 failed. All failures exposed the
  H117 fixture's destination-only authority assumption; private sender 99 was
  distinct from destination 42 and open group fixtures declared no owners.
- Red-first environment regressions: four callback/reason cases and one
  administrative-command case failed before destination resolution was unified.
- Separate-owner red regressions: three open-group callback/admin/reason cases
  failed before integration. Clearing a destination reproduced one stale callback
  authorization. The real settings-store regression reproduced the undeclared
  key being skipped before its declaration was added.
- The helper preserves its original 42 cases and adds 20 resolver cases; all
  **62 pass** with configured pytest guards.
- Intermediate integration: 292 passed / one failed; the remaining legacy test
  expected an unauthorized group member's rejection to create its own reason
  window. It now asserts that task remains undecided, while the actual owner's
  reason sent on time is saved behind the slow group turn.
- Expanded settings/channel integration: 382 passed / one inventory failure.
  Exact AST inventory identified the 14 unchanged calls at positions shifted by
  four lines. After that precise refresh, **383 tests pass** in 33.71 seconds.
- H277/H485 and safe-mode regression: **2,109 tests pass**, seven warnings,
  54.43 seconds, before the final review fixes. No socket/timeout addopts were cleared.
- Final review reproduced a persisted revocation accepted through stale runtime
  settings. Four red regressions cover immediate revocation, destination removal,
  empty explicit group-owner IDs and unavailable storage. An exclusive-lock red
  regression reproduced a **5.346-second** settings wait. The read-only snapshot
  fixes those cases and the lock test requires refusal in **under one second**.
- A concurrent intermediate run loaded the old binding inventory and returned
  398 passed / one position failure. The refreshed fresh-process binding union
  passes 50 tests; the final guarded integrated union passes **400 tests**, one
  existing deprecation warning, in **34.52 seconds**. It includes real queued
  callback acknowledgment, persisted revocation and the exclusive-lock regression.
- Frontend integration passes **1,886 tests**; TypeScript and the HUD build pass.
  JSON-field regressions exercise the actual settings panel, including nullable
  values, list saving and the undefined-value fallback.
- The separately configured legacy HUD coverage command passes its **60% line
  threshold**, recording **69.75% lines**. Its generated badge was restored to
  the previously clean baseline; this result does not measure V2 coverage.
- Real count synchronization records **21,825 backend cases**, 87 more than the
  parent; it runs frontend/mobile checks and records **1,886 / 142** respectively.
- The initial complete backend run was explicitly interrupted after the final
  review demonstrated the cache-revocation flaw. Its KeyboardInterrupt result is
  not complete-suite verification. A fresh complete guarded run is required.
- Final local Graft rebuild records **48,177 nodes**; `graft check` confirms the
  wiring graph is in sync. The optional concept layer remains absent/unbuilt; no
  paid deep pass was requested. Its generated ignore cache was preserved under
  `/tmp` and removed from the source checkout.
- Ruff passes on all 14 touched Python source/test files. Baseline-aware Bandit
  reports **zero findings and zero errors** across `agents`.
- All **228 record/reference/count gate tests pass** after rereading 53
  parent-current reviews. Their original statuses and remaining requirements
  are unchanged; the 60 already-stale impacted reviews were not promoted.
  The generated Hermes report returns to **180/697 (25.8%)**. This is restored
  evidence freshness, not additional completed capability credit.
- The fresh complete guarded backend run terminates with **21,790 passed,
  34 skipped, one existing xfailed and 67 warnings**, in **1,137.75 seconds**
  (18:57), exit zero. Its JUnit records 21,825 cases, zero failures and zero errors;
  the backend count guard matches the generated inventory. All **2,806 frozen
  source/configuration hashes match** after terminal completion.
- Exact staged Gitleaks scanning reports zero findings before the full run.
  Final report updates require a renewed staged scan and local commit verification.
  No remote CI, publication, deployment or runtime activation is claimed.

Final focused logs/XML use `/tmp/nerva-h485-owner-authority-final-20261003.{log,xml}`;
real count sync uses `/tmp/nerva-h485-owner-authority-count-sync-20261003.log`.
The complete guarded result uses
`/tmp/nerva-h485-owner-authority-full-backend-guarded-20261003.{log,xml}`;
its frozen manifest is `/tmp/nerva-h485-owner-authority-frozen-source-20261003.json`.
Earlier logs/XML use `/tmp/nerva-h485-owner-identity-focused-final-20261003.{log,xml}`
and `/tmp/nerva-h485-owner-smart-regressions-20261003.{log,xml}`. The raw prior
failures remain under the corresponding `owner-identity`, `owner-env`,
`owner-separated`, `owner-destination-revocation` and `owner-persisted` filenames.

**Remaining Risks:**

H277/H485 remain partial. Context-bound interactive DENY override and same-turn
continuation, shell/nested/scheduled origin behavior, native controls and live
model/channel/device acceptance remain required. Owner authority bypasses the
runtime settings cache; normal unrelated settings retain the watcher cadence.
Missing, unreadable or locked settings storage refuses administrative authority.
No live bot or paid provider was activated.
An explicit empty owner list still allows only the exact configured private-owner
fallback; it grants no group authority. Malformed persisted owner configuration
fails closed and may require an operator correction. Legacy admission-list
identity is retained only when the new owner setting is absent/null.
No coverage percentage is inferred from case counts. No push, merge or deployment.
