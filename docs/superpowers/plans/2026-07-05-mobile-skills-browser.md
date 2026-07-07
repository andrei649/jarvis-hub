# Mobile Skills Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship H18.15 by adding read-only native mobile parity for `GET /skills`.

**Architecture:** Keep the backend unchanged. Add a typed mobile client function that normalizes the map-shaped skills catalog into a stable array, then render that catalog in a new read-only Skills tab.

**Tech Stack:** Expo / React Native / TypeScript / Jest.

## Global Constraints

- One PR for H18.15.
- No backend route changes.
- No mobile skill writes or admin actions.
- No demo rows when the hub returns an empty catalog.

---

### Task 1: Mobile API Contract Tests

**Files:**
- Create: `mobile/src/api/__tests__/skills.test.ts`
- Modify: `mobile/src/api/client.ts`

**Interfaces:**
- Produces: `fetchSkills(config): Promise<SkillsResponse>`.

- [ ] Add a test that expects `fetchSkills()` to call `/skills` with `X-User-Token`.
- [ ] Add a test that expects map-shaped backend payloads to normalize into a sorted skill array.
- [ ] Add a test that expects sparse payloads to normalize to `skills: []`.
- [ ] Run the focused Jest file and confirm it fails because `fetchSkills` does not exist yet.
- [ ] Implement `HubSkill`, `SkillsResponse`, normalization helpers, and `fetchSkills`.
- [ ] Re-run the focused Jest file and confirm it passes.

### Task 2: Skills Screen and Tab

**Files:**
- Create: `mobile/src/screens/SkillsScreen.tsx`
- Modify: `mobile/App.tsx`

**Interfaces:**
- Consumes: `fetchSkills(config)` and `HubSkill`.

- [ ] Add a read-only Skills screen that loads on mount and pull-to-refresh.
- [ ] Render total skill count, skills with versions, descriptions, agents, and command counts.
- [ ] Render "No hub connected" when settings are missing and an honest empty state when the hub returns no skills.
- [ ] Add the Skills tab to the root shell.
- [ ] Run mobile TypeScript.

### Task 3: Docs and Ledger

**Files:**
- Modify: `mobile/PARITY.md`
- Modify: `mobile/README.md`
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Produces: H18.15 as the tracked parity task for `/skills`.

- [ ] Mark Skills browser mobile parity as H18.15.
- [ ] Add H18.15 to ORIZONT 18 and update the section progress.
- [ ] Update mobile test count after Jest passes.
- [ ] Record the active branch and verification status in sprint/status docs.

### Task 4: Verification and PR

- [ ] Run `npm test -- --runInBand` in `mobile`.
- [ ] Run `npx tsc --noEmit` in `mobile`.
- [ ] Run `python scripts/status_sync.py --check`.
- [ ] Run `git diff --check` and `git diff --cached --check`.
- [ ] Commit, push, open a draft PR, and monitor CI.
