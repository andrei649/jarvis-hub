# H18.25 briefing attention and subsystem reports

Generated: 2026-10-09 UTC. Goal: add the remaining read-only room reports to
native Briefing. Base/head at design:
`8c47e4df3bef812fb38067c2eb9619628883285f`.
Branch: `codex/mobile-briefing-sources-20261009`.

This separate local increment extends the existing wall snapshot with returned
approval counts, a calendar sample, local-model residency reports, server voice
capabilities and heartbeat schedule counts. It retains the existing field,
dictation-to-draft flow, per-visit transcript privacy, foreground-only refresh
and scope/cancellation fences. These extra reports do not drive the activity
animation and do not authorize recording, speech or any task action.

The bounded reader uses the actual read contracts:

- `/autonomy/approvals` includes both blocked and proposed tasks, with at most
  100 returned decisions. A valid empty response can show zero; denied or
  malformed responses remain unavailable. No task titles or contents survive
  the projection.
- `/dashboard` supplies at most ten calendar entries over a rolling 24-hour
  window. The backend can retain cached entries and cannot distinguish an empty
  calendar from some failures. Empty/error data therefore remains unavailable;
  a positive count is only a returned sample, without a freshness claim. Event
  titles, descriptions, participants and locations are discarded.
- `/status` reports ready, unknown, no_model or offline, and resident entries.
  A starting or incomplete response remains unavailable. The count is hidden
  for unknown/offline; it is zero only for a valid no_model report. Model names
  and provider/configuration details are discarded. A residency report does
  not prove that inference will succeed.
- `/api/voice/capabilities` contributes only the four headline booleans for
  STT, TTS, local TTS and local-only policy. Provider/voice diagnostics and
  consent messages are discarded. This is a server capability report, not
  microphone permission, recording state or a grant of consent.
- `/heartbeat/status` contributes scheduler state, scheduled-job count and
  quarantined-schedule count. It does not represent completed work or recent
  notifications. File paths, digests, triggers and next-run times are discarded.

All sources retain independent five-second deadlines, body validation bounds,
trimmed configured credentials, cancellation and generic unavailable states.
Native fetch buffers before validation; neither a streaming memory limit nor
native redirect isolation is claimed. Existing source clearing on refresh,
background, hub/session/agent/visit changes applies to all new fields. No data
from these reports is persisted.

Non-goals: backend/authority changes, additional SDK dependencies, approvals or
model controls, provider calls during validation, automatic speech/send,
calendar connectivity repair, global task totals or external publication.

Owned paths: existing wall API and its Jest tests; existing wall screen and
mounted native tests; evidence, parity and generated status. Two
`gpt-6-sol`/high implementation agents own API and UI separately; root owns
integration and review. A `gpt-6-luna`/medium read-only investigator mapped the
contracts. No nested delegation.

Verification on 2026-10-09 UTC:

- Full mobile Jest: **232/232**, 45 suites; report
  `/workspace/scratch/h1825-sources-mobile-final.json`. Includes strict schemas,
  caps, empty versus unavailable, private-field projection, independent source
  refusal, deadline/abort and RFC3339 fractional timestamp regressions.
- Full native React host suite: **86/86**, 11 files; report
  `/workspace/scratch/h1825-sources-native-final.json`. The new cards preserve
  real zero/unknown distinctions, refresh/background/scope clearing and private
  text omission. Dictation controls precede the expanded cards on phones.
- Mobile TypeScript and final offline Android/iOS Metro/Hermes exports passed;
  outputs `/workspace/scratch/h1825-sources-export-android-final` and
  `/workspace/scratch/h1825-sources-export-ios-final`. Final runs supersede the
  earlier 231-test/export runs before the fractional timestamp fix. Exports
  compile bundles; they do not prove device graphics or microphone behavior.
- Existing backend approval, model-status, dashboard, voice, bounded-request,
  heartbeat read-scan and route-guard tests: **133/133**, no skips/failures;
  `/workspace/scratch/h1825-sources-backend-contract.xml`. No backend was changed.
- Status/Hermes Python tests: **86/86**, no skips/failures;
  `/workspace/scratch/h1825-sources-status-final.xml`. Generated status, mobile
  count, Hermes freshness and diff checks passed. Backend/browser full counts
  are reused without claiming new whole-suite runs. No evidence pin refresh.
- Independent API and UI cross-reviews by `gpt-6-sol`/high found no remaining
  Critical/Important issue. A stale test name and valid timestamps with more
  than six fractional digits were fixed. A new nine-digit timestamp test first
  failed, then passed; full syntax/date bounds remain checked, and only the
  temporary native Date.parse input is shortened to milliseconds.

Rollback: revert this unit while retaining the independent wall, dictation and
orb commits. Device graphics/accessibility, microphone and live-Hub acceptance
remain open. The unit is a verified local candidate, not published or merged;
PR1247 remains separate. Next action: integrate the independent local candidates
and obtain device/live-Hub acceptance while other offline backlog work continues.
