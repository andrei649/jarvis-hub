# Incoming sync containment

Prepared 2026-11-14 over `8a27fee5b28cddaacbc2e73f105385f1dc99ebad`, incorporating the macOS journal repair `6342dbbd75f612ce1aec7f0cbc34e5f242ecd910`. The owner requested correction and verification of sync overwrites while keeping unsafe work draft.

## Behavior and deliberate limitation

Incoming configuration and skill candidates are now retained encrypted for review. They do not write settings or overwrite skill files. This deliberately suspends automatic incoming application: the previous snapshot importer could overwrite newer local edits, and neither an unchanged default nor an unauthenticated transport timestamp establishes permission to replace local state.

The API reports `inbound_mode: stage_only`, `config_applied: 0` and `skills_applied: []`, with explicit `config_pending_import`, `skills_pending_install` and `staging_errors`. The HUD distinguishes staged candidates, partial failures, disabled sync and older server receipts. CLI help describes staging. A staging success is not an import, installation, consent grant or complete synchronization.

The private SQLite inbox stores encrypted candidates with content-derived fingerprints. A transaction serializes duplicate detection, capacity checks and insertion. Identical authenticated content remains idempotent across restarts and re-encryption; peer-supplied digest/timestamp fields do not determine which content is retained. Duplicate lookup precedes capacity refusal. There is no automatic eviction. Limits are 256 candidates, 16 MiB of encrypted payload and 512 KiB per canonical candidate. Failed insertion/commit is retryable and does not acknowledge application.

Secrets, credential-like values, environment references and route-only settings are excluded before staging. Invalid payloads and hostile skills are reported without exposing payload values, local paths or keys. Existing local configuration and skill contents remain untouched even when a peer replays an older snapshot.

## Evidence and remaining work

Six initial overwrite/staging regressions failed before the change. The backend's 46 focused H040, legacy encryption and alias tests pass, covering explicit local defaults, newer edits, restart/replay, forged outer metadata, two-instance capacity races, partial failures and insert/commit rollback. Seven rendered HUD tests and TypeScript checking pass. On the combined candidate, 58 focused backend tests (including the 12 generic macOS journal/import cases), seven HUD tests, full Ruff and the unchanged full Bandit baseline gate pass. These groups overlap; they are not a full backend run.

Independent review found no remaining concrete blocker in this containment mechanism or its receipt presentation. This is a bounded review, not complete sync acceptance. Metadata timestamps/peer preferences retain their existing persistence mechanism; this change does not claim cross-process reconciliation of that metadata.

The inbox has no finished candidate retrieval/import/install UI yet. General conflict resolution, atomic application plus replay receipts, real user-skill discovery/admission and key migration remain unfinished. The original shared key is needed to decrypt retained candidates. No Hermes capability verdict is upgraded by this containment. The downstream B5 benchmark must measure staging and local-data preservation, replacing its obsolete automatic-write/LWW assumptions.

No real-device/provider acceptance, deployment, service activation or resumption of the blocked lifecycle review occurred. The inherited cumulative review and composed/native macOS acceptance remain open; keep the stack draft.

The expected locked counts are backend **36790** and frontend **3205**, with mobile unchanged at 420. Backend accounting uses authentic prior CI 36768 plus a paired full-collection delta of 22 cases (local 36777 to 36799, no removed cases); frontend adds six executed cases to the prior 3199 count. New-head CI must verify these totals.

## Generated HUD follow-up

CI on `4f61b8d196eeaab8dcdffd9bcf65a427ea089493` passed all 325 HUD test files, both TypeScript checks and the build, then rejected stale committed bundles (job 132598356191). The canonical `npm run build` was run with existing locked dependencies to regenerate both HUD outputs. A second build reproduced every output hash exactly. No source, test, dependency or workflow was changed in this follow-up; new-head CI still must confirm freshness.
