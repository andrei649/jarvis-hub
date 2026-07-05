# Mobile Channel Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for the API client contract and superpowers:verification-before-completion before marking this done.

**Goal:** Deliver H18.12 mobile Safe Comms inbox parity in one focused PR.

**Architecture:** Reuse the existing Safe Comms backend. The mobile app becomes another client of `/api/channels/inbox*`; reply drafts are still governed server-side and only execute after approval.

**Tech Stack:** Expo / React Native, TypeScript, Jest, existing mobile API client.

## Global Constraints

- No backend route changes.
- No direct mobile send path; only queue governed replies.
- Use `X-User-Token` through the existing client auth path. Do not require `X-Admin-Token` for reply drafting.
- Update the mobile parity ledger and backlog in the same PR.

---

### Task 1: Red API Tests

**Files:**
- Add: `mobile/src/api/__tests__/channelInbox.test.ts`

**Interfaces:**
- Expected: `fetchChannelInbox(config)`.
- Expected: `fetchChannelThread(config, threadId)`.
- Expected: `sendChannelReply(config, threadId, text, agent?)`.

- [x] Add tests for thread list fetch with user auth.
- [x] Add sparse-payload normalization test.
- [x] Add encoded thread-id read test.
- [x] Add reply enqueue payload test with `source:"mobile"` and no admin auth.
- [x] Run the new test and confirm it fails on missing functions.

### Task 2: Client and UI

**Files:**
- Modify: `mobile/src/api/client.ts`
- Add: `mobile/src/screens/CommsScreen.tsx`
- Modify: `mobile/App.tsx`

**Interfaces:**
- Produces typed channel inbox thread/message/reply response types.
- Produces a Comms tab that can list, inspect, refresh, and queue replies.

- [x] Add the typed client functions.
- [x] Make the API test green.
- [x] Add the Comms screen with thread list, selected thread messages, reply composer, and queue confirmation.
- [x] Wire the bottom tab.
- [x] Run full mobile Jest and TypeScript check.

### Task 3: Docs and PR

**Files:**
- Modify: `mobile/PARITY.md`
- Modify: `mobile/README.md`
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

- [x] Flip channel inbox mobile parity to shipped.
- [x] Mark H18.12 done with verified mobile test/typecheck results.
- [x] Run final hygiene checks.
- [ ] Commit, push, and open draft PR.
- [ ] Monitor CI and mark ready after checks pass.
