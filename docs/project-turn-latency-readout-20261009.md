# Current-turn duration in chat — local candidate

Base: `33e542bd474fb25afa8908dd0e99fe0e1d247966`.
Branch: `codex/turn-latency-readout-20261009`.
Generated: 2026-10-09 UTC. Delivery is local; PR #1247 still contains only its
original mobile-session publication. No provider, device, merge or deployment was used.

Both public orchestrator entrypoints measure their invocation through cleanup.
A request-owned collector publishes once after normal return and is then closed;
nested or late copied-context work cannot replace it. Commands and handled refusals
can have a duration, which does not mean an action succeeded. Exceptions,
cancellation, busy and uninstrumented paths have no measured outcome. Both HTTP
chat and every SSE end carry `outcome: null` or `{latency_ms: integer >= 0}`.
The interval excludes HTTP setup and network delivery and is not model-only latency.

The declared `display.status_bar_fields` setting defaults to `['latency']`.
The existing Admin Settings editor persists a bounded unique vocabulary list;
empty, invalid or unavailable selection hides the readout without failing chat.
The API filters the metric, so ordinary chat readers need no admin settings access.
The tags input now has an accessible name. Other reserved fields do not fabricate
zero values. This common outcome is the extension point for H220/H396, per build
queue critic note 10; H686 stays partial. TPS, context occupancy, cache ratios,
compression counts and typed completion/accounting remain open. Native ignores
this additive field; its readout gap is tracked as H18.33.

Cockpit and focus chat use the same transient Turn duration strip. Sending,
stopping, errors, session/agent changes and DEMO transitions clear it. A new
regression proved that switching to DEMO during a live turn formerly permitted
a late end; entering DEMO now cancels that turn before paint. A compiled browser
check found the focus composer forcing the new strip to x=-127 at 390px. Applying
the existing cockpit wrap/shrink rules to the focus column, plus min-width:0,
keeps the metric visible at both tested widths. The value is not persisted.

## Verification

- Feature availability RED on unchanged base: backend 12/12 fail (missing wire,
  setting, schema/module); frontend 15 cases = 8 missing-readout failures and
  7 negative controls passing. Module-not-found failures are feature availability
  evidence, not a pre-existing backend bug reproduction.
- DEMO race: one explicit pending-live/DEMO/late-end regression failed before the
  fence and passed after it. Final mounted suite: 18/18, 1.739 s.
- Backend focused union: 87/87, 3.095 s. Root integration: 277/277, 14.470 s.
  These overlap in 15 chat cases: **349 distinct passing cases**, 364 executions.
  New backend module adds 24 collected cases. Real public wrappers are tested
  with stubbed inner workers; transport tests separately use measured test doubles.
  This is not live-provider end-to-end timing evidence.
- Full frontend/native: **2027/2027**, zero failures/skips; 226 modules. Native
  source did not change. Mobile Jest's prior 306 count is reused, not rerun.
- App and E2E TypeScript gates pass. Production build passes. Compiled browser:
  **2/2**, 1280px and 390px, 4.2 s, including no-data response and hard reload.
  The initial browser run was 1 pass/1 measured layout failure before the CSS fix.
  Browser responses are fixtures; backend tests prove the clock/collector contract.
- Ruff and diff checks pass. One serial full backend milestone is pending on the
  frozen source; its exact result will be recorded below before completion.

Artifacts: `/workspace/scratch/h686-turn-latency-*` contains RED/green/focused,
full-client JSON, browser logs, OpenAPI input, exact-base pin inventories,
independent backend/frontend/collateral reviews and the source manifest.
Independent implementation/review used gpt-6-sol/high; the read-only inventory
used gpt-6-luna/medium. Root owned contract, integration, CSS/browser repair,
schema/build generation, metadata and git; maximum four active, no nested agents.

The initial integration command named one nonexistent parity test and exited
before collection; the corrected 11-module command produced the 277-pass result.
The first bounded backend integration exposed one exact SSE fixture that needed
its new null outcome key; after that explicit contract update the 87-case union
passed. No failures or skips were hidden by these corrections.

Metadata: 22 exact-base-fresh pins refreshed after bounded collateral review;
unrelated stale pins retained. H686 was explicitly reassessed against the bounded
new implementation and tests; H220/H396 record the shared-outcome dependency
without upgrading their broader claims. All 226 review status/identity values and
the immutable inventory hash remain unchanged. No capability is marked complete
from latency alone. Rollback is this coherent unit; the additive ordinary setting
may remain unused after code rollback, with no chat-state migration required.
