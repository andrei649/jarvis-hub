# Local Nerva sprint handover — 2026-09-27

Goal: full Nerva/Jarvis parity with all 697 pinned Hermes capabilities. The owner
requested finishing the current slice and stopping within 90 minutes, by
2026-09-27 18:05 UTC / 21:05 Europe/Bucharest. This is a pause/handover, not a claim
that the complete project or Hermes backlog is finished.

## Publication update

After this handover, the owner explicitly requested publishing the progress to
GitHub. The commit containing this update publishes the preserved sprint source,
tests, generated HUD and evidence on the existing PR #1207 branch. The PR remains
a draft; this authorization does not merge, deploy or resume development.
Current remote entry point: https://github.com/andrei649/jarvis-hub/pull/1207.
The verification figures below remain the freshly verified local milestone;
GitHub CI evaluates the published head independently.

## Start here

Canonical checkout: `/Users/andrei649/Projects/nerva-hub`.
Branch: `claude/cto-session-recovery-qinvkg`.
Pre-publication base HEAD: `bd2bb70ead1b493043a335e77713fc42c47d4013`.
The Documents/Nerva directory is not the current source checkout.

At handover capture, the implementation was in the local working tree, including
untracked source and tests, and the base HEAD did not contain the sprint. The
subsequent owner-authorized publication includes that work in the existing PR.
Preserve any newer local edits; do not reset, clean or rebase blindly. No merge or
deployment was performed. There are no task-owned services to keep alive;
resumption starts from files and retained evidence, not process state.

Read `AGENTS.md`, this handover, `HERMES_STATUS.md`, then only the relevant plan and
source paths. Existing owner authorization permits local kernel/control-plane
work; publication still requires a new owner request. Python is `.venv/bin/python`
(3.12.14); do not substitute the older macOS system Python.

## Current truthful completion

125/697 (17.9%) documented code-equivalent; 253 partial, 64 missing,
255 need review, zero excluded. The whole 697-row scope remains active for the next
sprint. Of the equivalent count, 108 are inherited records; 77 reviews are current.
Prepared plans, passing offline tests and live provider/hardware acceptance are
separate facts. Do not promote a row merely because its partial slice passes tests.

This handover closes the current H517/H613 named-provider slice:

- Shared ProviderBase/ProviderRegistry is used by real local image and named speech
  dispatch. Image approval binds shared implementation bytes. Protocols remain
  finite trusted adapters, not arbitrary importable Python.
- Independent named TTS/STT configuration uses read-only catalog lookups and
  revisioned transactional approval storage. Exact named approvals cannot survive
  clear/recreate, same-argv replacement or a changed original waiting invocation.
- Existing signed kernel intake and explicit human floor remain. Arbitrary
  programs remain outside verified-local speech; local_only, persona consent,
  arming, safe-mode, process and output limits are preserved.
- HUD supports named registration/update/clear, pending-only cancellation, STT
  selection and exact provider name/revision in the Decision Inbox. A missing
  selected name stays unavailable; corrupt catalog state is visible.
- Joined tests use actual admin HTTP, signed worker decisions and bounded synthetic
  speech processes. Native image factories remain compatible with existing tests.

The prerequisite voice-authority milestone and previous local-image milestone are
recorded separately under `docs/hermes/evidence/`. Previous sprint work also includes
H277 mutation/security/kernel follow-up, H487 bounded human-wait/grouping/outcome
work, and the H513 frozen code contract. Their plans/reviews/evidence remain in
`docs/hermes/` and `docs/handoff/h277/`; they were not all reimplemented in this slice.

## Final verification

- Full backend: 19,537 collected, **19,502 passed, 35 skipped**, no failures/errors,
  250.397 seconds; tests ran with three xdist workers and existing socket/timeout guards.
- Full HUD: **1,835 passed**, no failures. TypeScript check and production build passed.
- Stable-source impacted gate: 1,230 passed. Shared-feature compatibility: 762 passed,
  one skipped. The final full suite includes those paths and the corrected regressions.
- Ruff, Bandit against the existing baseline, scoped Gitleaks and diff checks passed.
  Selected-directory Graft graph rebuilt and fresh; no deep/whole-repository graph claim.
- No new numeric coverage measurement. Native mobile's existing 142-test count is
  inherited, not a new run. Live providers and devices were not exercised.

## Evidence and files

Current design: `docs/hermes/h517-named-provider-plan.md`.
Current behavior/limits: `docs/hermes/h517-named-provider-review.md`.
Exact final counts/check outcomes and source hashes:
`docs/hermes/evidence/h517-named-providers-2026-09-27.json`.

Companion handover files preserve the specialist reports without depending on
/tmp: `storage-report.md`, `dispatch-report.md`, `independent-review.md`.
Reports retain original temporary log paths for optional deeper inspection;
structured totals and report hashes persist in the evidence JSON.
The pre-publication working-tree path inventory and source manifest are in `working-tree.txt`
and `source-manifest.json` next to this note. These are handover metadata, not a backup of the complete checkout. The base SHA
and dirty-state inventory describe the capture before publication.

The coordinator owned interfaces, image/HUD integration, joined tests and records.
Two Sol High implementers owned disjoint storage/approval and speech-dispatch
files. One bounded Luna Medium read-only review found the selected-store capability
failure, which was reproduced, fixed and re-reviewed. No subagent delegated.

## Resume without repeating exploration

1. Check current PR/HEAD and `git status --short`; the inventory records pre-publication state.
   Preserve any newer edits. Read final evidence before rerunning expensive suites.
2. Reuse the pinned Hermes reference at
   `/Users/andrei649/Projects/hermes-source-59b2aeef6c7a/hermes-agent-59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`
   and `docs/hermes/upstream-reference-2026-09-27.json`; do not silently move upstream.
3. Choose the next bounded H517/H613 contract from the pinned source. Still open:
   vendor/local provider matrix, Python plugins, full setup hooks, video/browser/web/
   terminal registry integration, remaining voice persona/tags/limits/cloning/bubble
   behavior and native mobile controls. The old next-plan draft is superseded by
   the named-provider plan and this handover; named providers are no longer missing.
4. H516 remains a design checkpoint: live local video workflow/decoder contract is
   unverified. Do not fabricate video acceptance or start paid generation. H487
   broader standing grants/credit producers and other partial/missing rows also remain.
5. Apply localized TDD, one writer per file, maximum two Sol High implementers and
   optional bounded Luna investigator. Run focused and impacted gates first; one
   serial full-suite milestone after stable code. No duplicate full runs without a
   source change, failure or unresolved concern.
6. Refresh only substantively reviewed evidence. Prior stale reviews elsewhere in
   the ledger were deliberately not mass-refreshed. Use `scripts/hermes_status.py`
   and `scripts/status_sync.py`; the original research ledger remains immutable.

## Guardrails and remaining risks

- Named commands run as the hub user, not in a sandbox. Executable/script bytes are
  pinned; their imports/libraries are not. Clear stops future dispatch, not a process
  that already began. Named tombstone/history limits intentionally require explicit
  future design rather than automatic recycling.
- No live model/provider/hardware acceptance, paid provider calls, native mobile
  implementation was performed. Publication was separately authorized after the local milestone.
  Full offline suites do not prove
  those external integrations.
- Local image durability requires verified directory fsync; native Windows support
  remains open. Existing 64 approval-request records may evict an old pending card,
  which then refuses safely. Legacy records without revision metadata retain their
  identical-restoration limitation.
- Scope rollback to this slice's hunks. Set JARVIS_VOICE_COMMANDS off to stop future
  commands while preserving named rows/history. Do not reset the settings DB.
- PR #1207 was rechecked for publication and remained open/draft at the recorded
  base. New-head CI and GitHub security state must be checked separately; local
  success does not prove remote CI or merge readiness.
- User stop deadline is a hard bound. The current goal is paused after handover;
  resume only when the owner asks to continue. No new scheduled work was installed.

Suggested next prompt: "Continue Nerva from docs/handoff/2026-09-27-local-sprint/README.md
in /Users/andrei649/Projects/nerva-hub. Preserve all local changes, keep the full
697-capability scope, select the next bounded verified Hermes parity slice, and
remain local without push/merge/deployment."
