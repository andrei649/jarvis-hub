# H523 scheduled media delivery implementation plan

**Goal:** Owner-authored scheduled delivery of retained opaque media IDs with a total deadline and durable refusal to replay ambiguous sends.
**Base:** 11e043a47b7be7fa4e6391098dc86dd156a0fbf0. **Generated:** 2026-09-15. **State:** implemented and focused verification passed; independent review in progress.

Execute inline with planning/TDD; no subagents. Parent owns assessment, publication and browser bundle integration. The corrected H523 audit remains in its separate worktree. No protected policy/kernel changes or new dependencies.

## Accepted bounded contract

Add optional `media_ids` only to the owner-authored `remind` action: one to eight unique catalog `md-`, attachment `ba-`, or generated 32-hex IDs, never paths, URLs or model-produced directives. Existing admin jobs routes persist the field; CLI create/edit offer explicit repeatable `--media-id`, and the custom reminder UI authors it. Media reminders require the configured Telegram owner and reject other delivery targets explicitly. Existing text-only jobs retain their contract.

At create or explicit action edit, resolve all media through the shared bounded reader, require supported MIME, cap each file at16MiB and aggregate at32MiB, and privately bind ID/MIME/size/SHA256 plus current configured owner and Telegram bot endpoint/credential fingerprint. No private binding or credential hash enters API/CLI output. Rename/schedule edits do not silently reauthorize another recipient. At delivery recheck configuration, current job action/binding and all bytes before any send, then recheck live recipient/e-stop/binding before every external call. Send only already-validated captured bytes, never reread a caller path in an adapter.

Use a validated integer owner setting `jobs.media_send_timeout_seconds` (default300, range1..300) for one wall-clock deadline spanning lookup, resolution, all files and associated text. Invalid explicit settings refuse media delivery; no per-file timeout reset. Network calls are cancellation-aware and never automatically retried. Telegram sends a fixed multipart document endpoint with an ID-derived filename; no user-provided URL or API method. A separate plain scheduled-text method sends the associated text under the same deadline. Rate-limit every external media/text dispatch and audit before sending; unavailable audit refuses.

A private bounded SQLite journal beside the existing jobs data stores bindings and delivery receipts, not bytes. Commit `sending` before each network call and `sent` only after positive acknowledgement. Durable partial/unknown states never automatically replay that receipt. A crash with unresolved progress is unknown and pauses the job; explicit action re-save binds a new authorization generation, then the owner separately resumes. New scheduled occurrences are distinct receipts only while no unresolved receipt remains for the authorization generation. Cross-process nonblocking ownership prevents overlapping sends. Public summaries expose state/counts/reason, no token/recipient secret/hash.

Quiet-hour media deliveries persist the bound receipt and text; foreground flush uses its original binding, never whatever a subsequently edited job happens to contain. Deleted/edited jobs discard obsolete held receipts. E-stop and changed credentials/content refuse before dispatch; e-stop/cancellation after a send begins remains unknown. Persist partial outcomes before pausing. Bounded receipt retention never drops unresolved authority records. Future adapters and model-generated attachments remain out of scope.

## Modules and test increments

- [x] New `agents/core/autonomy/jobs_media.py`: validation/binding, private journal, held receipts, deadline, durable send state and public status. Failing tests in `tests/test_jobs_media.py`: malformed fields, target/content drift, incomplete audit, empty/oversized media, overall deadline, multiple files, late cancellation, restart ambiguity, quiet hours and e-stop.
- [x] Narrow `agents/core/autonomy/jobs.py` integration: additive remind key validation; bind at runner create/explicit action edit; media branch in delivery, flush and status. Preserve model-pins agent ownership of `_ask`/options; coordinate additive validation changes. Actual admin route→runner→mock adapter tests prove fields execute and status is honest.
- [x] `agents/core/channels/telegram.py`: bounded bytes-only media method; mocked HTTP verifies fixed method, recipient and multipart bytes, no retries. No actual Telegram call.
- [x] CLI `agents/cli/nerva.py` and custom-job UI `frontend/src/panels/job-builder.tsx` plus jobs outcome view: explicit media authoring/editing and partial/unknown reporting. Focused CLI/React tests prove serialized field and actionable result text. No inert fields.
- [x] Verification: focused jobs/media/channel/API/CLI tests, relevant Ruff/Bandit, frontend tests one worker, both frontend typechecks. Parent coordinates full backend, global schema/evidence and final bundle production. Record actual results and limitations before source handoff.

## Safety and rollback

No optional live provider calls, media generation, upload intake changes, arbitrary recipient/host paths, kernel authority additions, or global evidence updates. Existing owner-authored recurring job authorization is constrained to fixed retained content and configured owner, with a private server binding. A single source unit contains the listed modules/tests/guide; rollback preserves existing text-only job data and does not reinterpret unresolved media receipts as success.

## Owner operation and verification boundaries

Create a custom Reminder in Jobs and enter retained opaque IDs in its scheduled media field, or use `nerva jobs create --name report --when '0 9 * * *' --action '{"type":"remind","message":"Report"}' --media-id ba-<32-hex-id>` (repeat the flag for more files). The existing JSON action editor and CLI edit with `--action` plus `--media-id` explicitly reauthorize content. Jobs status/API and the Jobs card report acknowledged items versus total items, including the final text. A partial/unknown result requires checking Telegram, explicitly saving the action again and separately resuming; resuming alone cannot replay unresolved progress.

The owner settings category `jobs` exposes `media_send_timeout_seconds`, an integer from 1 through 300, default 300. This bounds delivery, not synchronous authoring validation. The absolute budget starts before dispatch binding/configuration/receipt lookup and is never reset. Synchronous local SQLite/filesystem operations cannot be preempted; after an over-budget operation returns, no subsequent external dispatch is permitted. File resolution runs in a bounded background reader; a timed-out read may finish locally but cannot start a send. Network cancellation cannot retract a request already accepted remotely, hence the durable unknown outcome. A cancellation-resistant late response cannot acknowledge or continue an abandoned receipt.

Scheduled Telegram text uses one plain `sendMessage` request with strict positive integer acknowledgement, without the legacy formatted-text fallback. Both file and text requests are independently rate checked and audited, under one deadline. Quiet-hour receipts are rechecked inside the delivery gate; already completed/deleted receipts cannot replay from a stale snapshot, and paused/disabled held rows do not starve runnable work.

No native UI, live Telegram account, paid provider, production deployment or full backend suite was used. The API acceptance test uses actual admin route authorization, JobRunner and TelegramChannel with HTTPX MockTransport for the external requests. Parent owns final generated HUD assets and global assessments.


## Recorded verification

- Backend: **228 passed**, one pre-existing Starlette/httpx deprecation warning, command: `/tmp/nerva-python-runtime/bin/python -m pytest tests/test_jobs_media.py tests/test_owner_jobs.py tests/test_jobs_edit.py tests/test_jobs_advanced.py tests/test_jobs_routes.py tests/test_job_quiet_hours.py tests/test_job_dispatch.py tests/test_nerva_cli.py tests/test_settings_db.py tests/test_telegram_streaming.py -o addopts='' -q`. New coverage: 47 scheduled-media cases and one CLI case.
- Frontend: **16 passed** in `src/panels/jobs.test.tsx` via `npm test -- --maxWorkers=1 src/panels/jobs.test.tsx`, including one new authoring/outcome regression. Both `npm run typecheck` and `npm run typecheck:e2e` passed.
- Whole-repository `ruff check .` passed. Bandit 1.9.4 with `-r agents scripts -b .bandit-baseline.json` passed with no new findings. `git diff --check` passed.
- RED evidence preceded fixes for media authoring/delivery, held destination reporting, adapter transport, route projection, e-stop, setting registration, UI/CLI fields, empty options, paused holds, cancellation-resistant late acknowledgement, stale held snapshot, paused backlog starvation, text fallback and transport-secret sanitization. Late-read, final-text and deterministic over-budget binding lookup regressions also pass. Passed snapshot/action identity and exact reminder text are checked against current authorization, with stale-snapshot and replacement-text RED regressions. Explicit reauthorization normalizes superseded interrupted receipts to unknown without clearing pause state; late cleanup preserves uncertainty.
- Additional narrow settings module: `agents/core/settings_db.py` registers the real owner-editable deadline field and strict validation; no inert environment variable or new configuration authority.

## Root integration results

The explicit empty-options and stale-held-snapshot findings were repaired before
acceptance, along with paused-queue starvation, text fallback, late acknowledgements
and snapshot binding. Independent review passed 98 backend and 16 frontend tests.
Rebased with model pins and cloud images, preserving both CLI/UI features: 127
combined jobs/pins/CLI checks and 148 H523 reader/delivery contract checks pass.
Full backend: 11,428 collected, 11,404 passed, 23 skipped, one expected failure,
zero unexpected failures. Full frontend: 1,315 passed. All three frontend
TypeScript configurations, Vite build and whole Ruff pass. No live sends.
