# H18.26 native command discovery

Date: 2026-10-09. Base SHA: `da7c8a2` (stacked on candidate PR #1247). Head SHA at task start: `da7c8a2`.

Goal: Let native Chat discover the hub's live, principal-filtered `GET /api/commands` catalog. Show command, usage, description, and owner tier with distinct loading, empty, error, and unavailable states. Selecting a command fills the existing composer; only a later Send invokes the guarded conversation path and retains its session ID.

Non-goals: command execution from the catalog, server/router/policy changes, catalog caching, new dependencies, and a claim of device or live-Hub acceptance.

Likely paths: `mobile/src/api/commands.ts`, `mobile/src/components/CommandsModal.tsx`, `mobile/src/screens/ChatScreen.tsx`, focused native host tests under `frontend/native-tests/`, `BACKLOG.md`, `mobile/PARITY.md`, and `docs/design/HUD_V2_REMAINING.md`.

Tests: add failing API transport/response tests and mounted React Native host tests for catalog display, composer insertion, guarded Send, refresh/error/unavailable states, and stale results; run focused native Vitest and mobile TypeScript checks. The coordinator will serialize broader suites.

Rollback: revert this one native discovery slice and its parity/roadmap entries. Existing typed slash commands remain on the guarded chat path.

Dependency: existing HA-4i-catalog router and H18.30 native conversation/session continuity from PR #1247. No remote mutation in this task.

## Delivered behavior and verification

The native catalog forwards both configured credentials, including admin-only configurations. It validates at most 256 command rows with bounded strings, preserves the endpoint's unavailable response, and keeps HTTP authorization errors distinct. Reads time out after 15 seconds; close, unmount and connection changes abort requests and revoke late responses. Native fetch parses buffered JSON; the row/string checks do not constitute a streaming network byte cap.

The modal lists the hub's live command, usage, description and tier. Choosing a row inserts only its command into the composer. A draft edited after opening the modal is preserved. The subsequent explicit Send retains the selected conversation ID and goes through existing server authorization.

- Builder: `gpt-6-sol`, high reasoning; coordinator owns integration. No subagent delegation.
- Focused native/API tests plus conversation regressions: **19/19 passed**, including a stalled read, unmount, late responses, admin-only credentials and session-bound Send.
- Full native React host lane: **58/58 passed** (`cd frontend && npx --no-install vitest run --config vitest.native.config.ts --reporter=json --outputFile=/workspace/scratch/h1826-native.json`).
- Full mobile Jest: **173/173 passed** (`cd mobile && npm test -- --runInBand --json --outputFile=/workspace/scratch/h1826-mobile.json`).
- Mobile TypeScript, Hermes report freshness, generated status checks with explicitly reused counts, and `git diff --check`: passed.

The native lane uses the existing React DOM/service mocks. The existing SessionsModal nested-button warning remains; no new warning is produced by the command modal. The default browser suite and backend suite were not rerun for this local slice. Android/iOS packaging and device/live-Hub acceptance remain open. Next action: review and integrate this branch after its H18.30 dependency, then verify the catalog with user and owner credentials on an actual device.

Independent review (`gpt-6-sol`, high) found no remaining slice-specific Important or Critical issues. It verified that the global React Native fetch transport inherits the application's existing redirect behavior: `redirect: 'error'` is ignored by its polyfill. This slice makes no new redirect-isolation claim; the mocked host tests do not prove native networking behavior. Catalog identity, insertion-only behavior, explicit session-bound Send and stale-response handling were reviewed separately.
