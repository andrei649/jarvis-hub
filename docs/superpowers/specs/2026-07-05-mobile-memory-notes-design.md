# H18.16 Mobile Memory + Notes Design

## Goal

Bring the browser HUD memory/notes read surfaces to the native mobile app with
a read-only Memory tab backed by `GET /memory` and `GET /api/notes`.

## Non-goals

- No backend route changes.
- No memory clearing, note editing, note rewriting, or note deletion from the phone.
- No knowledge-graph entity controls.
- No demo turns or invented notes when the hub returns empty payloads.

## Approach

The backend exposes two existing user-token guarded routes:

- `GET /memory` returns `{ session, turns }`, where `turns` is the recent
  conversation history for the current session.
- `GET /api/notes` returns `{ session, content }`, where `content` is the
  current session note text injected into future turns by the browser/HUD flow.

Mobile adds typed client functions that normalize sparse payloads, then renders
a compact read-only Memory tab:

- `Recent Turns`: the latest session turns with role, optional timestamp, and
  a bounded preview.
- `Session Notes`: the current notes block, or an honest empty state.
- Summary row: turn count, session label, and note character count.

## Data Contracts

Mobile client additions live in `mobile/src/api/client.ts`:

- `MemoryTurn`
- `MemoryResponse`
- `NotesResponse`
- `fetchMemory(config): Promise<MemoryResponse>`
- `fetchNotes(config): Promise<NotesResponse>`

Normalization guarantees:

- `turns: []` when missing or malformed.
- `content: ""` when missing or malformed.
- `session` is preserved when present.
- turn `role` and `content` are coerced to strings for stable rendering.

## Risks

`GET /memory` returns 503 when the orchestrator is not initialized. The mobile
screen treats that as a real load error instead of inventing history. Notes are
still shown only when the notes route succeeds.

## Verification

- Mobile API Jest tests prove request paths, user-token auth, turn
  normalization, note normalization, and sparse-payload handling.
- Mobile TypeScript verifies the new screen and tab wiring.
- `scripts/status_sync.py --check` verifies docs/status counters stay aligned.
