# Mobile Tasks Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for the API client contract and superpowers:verification-before-completion before marking this done.

**Goal:** Deliver H18.13 mobile Tasks board parity in one focused PR.

**Architecture:** Reuse the existing `/tasks` backend route. Mobile is a read-only client; task decisions remain in the existing Approvals tab.

**Tech Stack:** Expo / React Native, TypeScript, Jest, existing mobile API client.

## Global Constraints

- No backend route changes.
- No task mutation from this screen.
- Use the existing user-token path only.
- Preserve the backend's honest empty queue behavior.

---

### Task 1: Red API Tests

**Files:**
- Add: `mobile/src/api/__tests__/tasks.test.ts`

**Interfaces:**
- Expected: `fetchTasks(config)`.

- [x] Add test for user-auth `GET /tasks`.
- [x] Add sparse-payload normalization test.
- [x] Run the new test and confirm it fails on missing `fetchTasks`.

### Task 2: Client and UI

**Files:**
- Modify: `mobile/src/api/client.ts`
- Add: `mobile/src/screens/TasksScreen.tsx`
- Modify: `mobile/App.tsx`

- [x] Add typed task response/client helper.
- [x] Make the focused API test green.
- [x] Add the Tasks screen with counts, cards, refresh, error, and empty states.
- [x] Wire the bottom tab.
- [x] Run full mobile Jest and TypeScript check.

### Task 3: Docs and PR

**Files:**
- Modify: `mobile/PARITY.md`
- Modify: `mobile/README.md`
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

- [x] Flip Tasks board mobile parity to shipped.
- [x] Add H18.13 backlog row and sync the ORIZONT 18 count.
- [x] Record verified mobile test/typecheck results.
- [x] Run final hygiene checks.
- [x] Commit, push, and open draft PR #566.
- [x] Monitor CI, mark ready after checks pass, and merge #566.
