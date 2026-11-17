# Standalone ANDREI OS consent repair

Goal: fix the four confirmed post-merge findings from #1370. Base:
`3a482575ec9d3f59d6baa47d70cf4455d5f84572` (2026-11-17); initial head equals base.

The standalone `/api/chat` router will default to Ollama followed by its offline
grounded fallback. A separate `cloudConsent` JSON boolean, default false, permits
cloud dispatch, including CLI subscription and remote/custom endpoints. Legacy
`auto` is retained but becomes local-first; existing keys, login, or provider
selection do not grant consent. Invalid settings fail closed. Hub `/os` continues
to use its separate `/chat` policy; this repair does not establish a hub bypass.

Non-goals: live provider/vault testing, native HUD/mobile clients, merge, deploy,
service activation, or workflow/security-control changes. No dependencies added.
Rollback: revert this branch's repair commit; it contains no data migration.

Files: standalone server, example config, settings page/main.js, README; focused
Python and shipped-JS regressions; HUD parity gate and HUD/mobile gap ledgers;
BACKLOG and continuation ledger where delivery evidence changes.

- [x] Reproduce cloud dispatch without consent, invalid config handling, hardlink
  config omission, and the settings mask/save error with synthetic inputs.
- [x] Add strict consent normalization and per-step dispatch checks; make auto
  local-first and block remote Ollama and local HTTP redirects without consent.
- [x] Expose consent and truthful effective engine in status/settings; retain
  saved secrets on unrelated saves and fix the OpenRouter input ID.
- [x] Load/save `allowHardLinks` while preserving its false default and existing
  provenance-based read policy. Test only temporary synthetic hardlinks.
- [x] Record genuine HUD V2/mobile gaps; do not count the separate `/os` client as
  a native HUD/mobile surface.
- [x] Run focused regressions, lint, parity/auth/OpenAPI/lifespan and applicable
  aggregate checks. Obtain a separate read-only adversarial review, resolve
  findings, and report every failed/blocked/unexecuted stage.
- [ ] Recheck remote overlap, commit/push and open a draft PR; verify draft state.

Review focus: migrated auto plus inherited keys/login; malformed booleans and
provider names; cloud failures crossing fallback boundaries; remote/redirected
Ollama; settings hydration failure/blank/masked secret saves. All provider tests
must intercept dispatch/transport and may only use synthetic notes.

Next action at generation: add failing focused regressions, then implement.
