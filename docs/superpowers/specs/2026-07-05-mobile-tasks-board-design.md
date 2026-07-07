# Mobile Tasks Board Design

**Goal:** Close the next useful mobile parity gap by exposing the browser HUD's read-only `/tasks` surface in the native app.

**Non-goals:** No admin task decisions, no task creation, no autonomy queue mutation, and no backend route changes. The approval workflow remains in the existing Approvals tab.

## Context

The browser already consumes `GET /tasks` for the HUD task fan. The backend deliberately returns an empty list when there is no work, rather than seeded/demo tasks. Mobile had no equivalent read-only view, so a phone user could approve blocked actions but could not quickly see live/recent autonomy work.

## Approach

- Add `fetchTasks(config)` to the stateless mobile API client.
- Keep authentication on the existing user-token path. No admin token is needed because `/tasks` is read-only and already user-guarded.
- Add a Tasks tab that shows:
  - active / waiting / done counts,
  - owner/project/state task cards,
  - pull-to-refresh,
  - the honest empty state when the hub returns no tasks.
- Update `mobile/PARITY.md`, `mobile/README.md`, `BACKLOG.md`, `STATUS.md`, and `docs/SPRINT.md`.

## Risks

The bottom tab bar now has six entries. The labels stay short and use the existing compact icon/text pattern. If this starts feeling crowded later, the next native IA pass can combine read-only surfaces behind a More tab, but that is deliberately out of scope for this small parity slice.

## Tests

- Red/green mobile API contract test for `GET /tasks` user-auth and sparse normalization.
- Full mobile Jest suite.
- Mobile TypeScript check.

## Rollback

Remove the Tasks tab/screen, remove `fetchTasks()` and its test, and flip the `mobile/PARITY.md` Tasks board row back to not started.
