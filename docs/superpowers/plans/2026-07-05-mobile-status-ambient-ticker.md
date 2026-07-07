# Mobile Status Ambient Dashboard + Ticker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship H18.14 by adding read-only mobile parity for `GET /dashboard` and `GET /ticker` inside the existing Status screen.

**Architecture:** Keep the backend unchanged. Add typed mobile client functions that normalize sparse dashboard/ticker payloads, then render compact Status-screen cards from those stable shapes.

**Tech Stack:** Expo / React Native / TypeScript / Jest.

## Global Constraints

- One PR for H18.14.
- No new backend routes.
- No new bottom navigation tab.
- No mobile writes.
- No demo rows when the hub returns empty arrays.

---

### Task 1: Mobile API Contract Tests

**Files:**
- Create: `mobile/src/api/__tests__/dashboardTicker.test.ts`
- Modify: `mobile/src/api/client.ts`

**Interfaces:**
- Produces: `fetchDashboard(config)` and `fetchTicker(config)`.

- [ ] Add tests that expect `fetchDashboard()` to call `/dashboard` with `X-User-Token` and normalize sparse payloads.
- [ ] Add tests that expect `fetchTicker()` to call `/ticker`, normalize `text` from `obj`, `bar` from `pct`, and sparse payloads to `ticker: []`.
- [ ] Run the focused Jest file and confirm it fails because the functions do not exist yet.
- [ ] Implement the client types and functions.
- [ ] Re-run the focused Jest file and confirm it passes.

### Task 2: Status Screen Cards

**Files:**
- Modify: `mobile/src/screens/StatusScreen.tsx`

**Interfaces:**
- Consumes: `DashboardResponse`, `TickerResponse`, `fetchDashboard`, and `fetchTicker`.

- [ ] Load status, dashboard, and ticker together.
- [ ] Keep `/status` as the only fatal load for the page.
- [ ] Render a `Today` card for weather/calendar/notifications.
- [ ] Render a `Ticker` card for live rows, with an honest empty state.
- [ ] Run mobile TypeScript.

### Task 3: Docs and Ledger

**Files:**
- Modify: `mobile/PARITY.md`
- Modify: `mobile/README.md`
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Produces: H18.14 as the tracked parity task for `/dashboard` and `/ticker`.

- [ ] Mark Dashboard and Ticker mobile parity as H18.14.
- [ ] Add H18.14 to ORIZONT 18.
- [ ] Update mobile test count after Jest passes.
- [ ] Record the branch and verification status in sprint/status docs.

### Task 4: Verification and PR

- [ ] Run `npm test -- --runInBand` in `mobile`.
- [ ] Run `npx tsc --noEmit` in `mobile`.
- [ ] Run `python scripts/status_sync.py --check`.
- [ ] Run `git diff --check` and `git diff --cached --check`.
- [ ] Commit, push, open a draft PR, and monitor CI.
