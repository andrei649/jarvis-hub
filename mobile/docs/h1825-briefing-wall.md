# H18.25 native briefing wall

Generated: 2026-10-09 UTC. Goal: bring the existing browser briefing board to
native Chat with source-backed activity, a bounded neural field and explicit
dictation. Base/head at design: `d720681ff60c1f04f30f4b852ebbb0a462424e6d`.
Branch: `codex/mobile-briefing-wall-20261009`.

The Chat toolbar opens a briefing view while the conversation remains owned by
the same Chat controller. A separate mode key cancels the old microphone control
when entering or leaving. Dictation still appends to the draft; Review draft
returns to the composer and Send stays explicit. The last dictated line is hidden
from rendering and accessibility until Show transcript is selected. Visibility
resets on every visit or connection/session/agent change; it is not persisted.

Five independent read-only sources provide liveness, the agent roster, running
task feed, microphone/cloud/local policy and measured routing locality. Failures
and malformed responses remain unavailable; successful empty lists can report
zero. The task metric describes the running entries in the latest-30 feed, not
an unrestricted queue total. The backend currently masks some queue exceptions
as an empty response, which the client cannot distinguish from a real empty feed.
Locality uses routed local/cloud runs; unknown routes never become a fabricated
percentage or a strict-local policy-derived 100%.

Refresh while foregrounded every 15 seconds after the previous read completes,
or explicitly by button. Reads have five-second deadlines, cancellation and a
bounded JSON validation envelope. Clear previous evidence during refresh,
backgrounding and scope changes. No old values drive activity after evidence is
removed. Liveness failure means status unavailable, not a claim that every hub
service is down. Incomplete activity feeds mean activity unknown unless positive
voice/work evidence is available.

The SVG field uses existing native SVG support and real tier groupings, with
bounded deterministic geometry, count labels, source labels, reduced-motion
handling and foreground-only animation. No roster produces no invented agent
regions. Listening is measured only when a finite native level exists. The
existing 500-vector `wallState` contract remains unchanged.

Non-goals: backend changes, auto-send, automatic speech, new graphics/SDK
dependencies, demo numbers, authority changes, a new tab or external publication.
The existing microphone controller rechecks permission/trust independently; the
displayed trust snapshot never grants microphone authority.

Owned paths: new native API and tests, field model/renderer and tests, briefing
view and mounted tests, Chat integration, parity/evidence and generated status.
Two `gpt-6-sol`/high implementation agents own API and field separately; the
coordinator owns integration. A `gpt-6-luna`/medium read-only investigator mapped
the routes. No nested delegation.

Validation plan: API schema/partial failure/deadline/abort tests, geometry and
source invariants, mounted refresh/background/scope/privacy tests, Chat mode
transition/draft-only tests, full mobile/native suites, TypeScript and Android/iOS
exports. Rollback: revert this unit, retaining the independently completed orb
and dictation commits. No stored conversation schema changes.

Verification on 2026-10-09 UTC:

- Full mobile Jest: **226/226**, 45 suites, including the unchanged shared
  `wallState` vectors; report `/workspace/scratch/h1825-mobile-final.json`.
- Full native React host suite: **84/84**, 11 files; report
  `/workspace/scratch/h1825-native-final.json`. Includes hidden transcript,
  per-visit microphone contexts, explicit draft review, source failure/refresh,
  background cancellation, stale hub responses, polling cleanup and motion rules.
- Mobile TypeScript passed. No package or lockfile changes in this unit.
- Final offline Android and iOS Metro/Hermes exports passed:
  `/workspace/scratch/h1825-export-android-final` and
  `/workspace/scratch/h1825-export-ios-final`. An earlier Android export was
  superseded after the missing-tier validation fix. These exports compile the
  bundles; they are not physical-device rendering or microphone acceptance.
- Backend dashboard/trust/roster/health/run-history suites: **87 passed, 2 skipped,
  0 failures**. The two operability skips require an unavailable IPv6-family
  failure and a root-to-unprivileged port bind respectively; neither condition
  can be staged in this environment. Report
  `/workspace/scratch/h1825-backend-contract.xml`. These cover existing contracts;
  no backend routes were changed.
- Status/Hermes Python suites: **86/86**; report
  `/workspace/scratch/h1825-status-final.xml`. Generated status, mobile count and
  Hermes freshness checks passed. Backend/browser counts were reused without a
  new full-suite pass claim. No unrelated evidence hashes were restamped.
- Independent `gpt-6-sol`/high review found and closed a missing-tier fallback
  that could invent a reported category. Red-first regression now rejects that
  source. Coordinator regressions also prevent unknown feeds from announcing
  zero or idle; overflow grouping preserves a literal `other` tier separately.
  No remaining Important/Critical issue was identified in the bounded review.

The wall is a local candidate. Physical Android/iOS graphics, accessibility,
microphone and live-Hub acceptance remain open. This base unit excludes browser
attention/calendar, resident-model and voice-capability cards; the separate
[additional-sources candidate](h1825-briefing-sources.md) adds those reports and
heartbeat schedule counts. API validation is
bounded after native buffering; it does not prove streaming memory limits or
native redirect isolation. Queue read failures that the backend masks as an empty
list remain indistinguishable here. Next action: device/live acceptance and the
remaining read-only wall cards, then integration with the separate local units.
PR1247 remains separate; this increment is not pushed or published.
