# Mobile Memory + Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship H18.16 by adding read-only native mobile parity for `GET /memory` and `GET /api/notes`.

**Architecture:** Keep the backend unchanged. Add typed mobile client functions that normalize memory and notes payloads, then render them in a new read-only Memory tab.

**Tech Stack:** Expo / React Native / TypeScript / Jest.

## Global Constraints

- One PR for H18.16.
- No backend route changes.
- No mobile memory clearing or notes writes.
- No knowledge-graph controls.
- No demo rows when the hub returns empty arrays or blank notes.

---

### Task 1: Mobile API Contract Tests

**Files:**
- Create: `mobile/src/api/__tests__/memoryNotes.test.ts`
- Modify: `mobile/src/api/client.ts`

**Interfaces:**
- Produces: `fetchMemory(config): Promise<MemoryResponse>`.
- Produces: `fetchNotes(config): Promise<NotesResponse>`.

- [ ] Add a test that expects `fetchMemory()` to call `/memory` with `X-User-Token` and normalize role/content strings.
- [ ] Add a test that expects `fetchNotes()` to call `/api/notes` with `X-User-Token`.
- [ ] Add a test that expects sparse payloads to normalize to `turns: []` and `content: ""`.
- [ ] Run the focused Jest file and confirm it fails because the functions do not exist yet.
- [ ] Implement the client types, normalization helpers, and fetch functions.
- [ ] Re-run the focused Jest file and confirm it passes.

### Task 2: Memory Screen and Tab

**Files:**
- Create: `mobile/src/screens/MemoryScreen.tsx`
- Modify: `mobile/App.tsx`

**Interfaces:**
- Consumes: `fetchMemory(config)`, `fetchNotes(config)`, and `MemoryTurn`.

- [ ] Add a read-only Memory screen that loads on mount and pull-to-refresh.
- [ ] Render turn/session/note summary.
- [ ] Render recent turns with role labels and bounded content previews.
- [ ] Render session notes with an honest empty state.
- [ ] Add the Memory tab to the root shell.
- [ ] Run mobile TypeScript.

### Task 3: Docs and Ledger

**Files:**
- Modify: `mobile/PARITY.md`
- Modify: `mobile/README.md`
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Produces: H18.16 as the tracked parity task for `/memory` and `/api/notes`.

- [ ] Mark Memory / notes mobile parity as H18.16.
- [ ] Add H18.16 to ORIZONT 18 and update the section progress.
- [ ] Update mobile test count after Jest passes.
- [ ] Record the active branch and verification status in sprint/status docs.

### Task 4: Verification and PR

- [ ] Run `npm test -- --runInBand` in `mobile`.
- [ ] Run `npx tsc --noEmit` in `mobile`.
- [ ] Run `python scripts/status_sync.py --check`.
- [ ] Run `git diff --check` and `git diff --cached --check`.
- [ ] Commit, push, open a draft PR, and monitor CI.
