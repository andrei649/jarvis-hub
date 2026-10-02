# Selected Image Conversation Turn Implementation Plan

> **For agentic workers:** use `superpowers:executing-plans` task by task. Each
> task keeps a red-first test, a focused green run and a reviewable local commit.

**Goal:** Make a reviewed image in the shared browser composer a real selected
agent/session turn, with a durable text projection and honest provenance.

**Architecture:** Keep the existing one-use review and guarded native image
sender. A new selected-conversation operation holds the normal session lease
through revalidation, egress and commit. The orchestrator records the answer
through its post-turn seam; memory stores text and bounded provenance only.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, existing Orchestrator and
ConversationMemory, React/TypeScript, pytest/Vitest.

**Spec:** `docs/hermes/h277-main-image-turn-design-2026-10-02.md`.

## Global constraints

- No paid/live provider call, push, merge or deployment.
- Keep text `/chat` and `/chat/stream` behavior unchanged.
- Never persist raw image data, data URI, image digest, credential or full endpoint.
- Keep local-only and separate remote/training/cost consent rules enforced.
- Preserve user/agent/session selection and require one consumed review per send.

## Review focus

1. Session reset while an image request waits: refuse before egress or commit.
2. Client Stop during slow image inference: no answer or provider retry after cancellation.
3. Two concurrent text/image submissions: one session lease serializes them.
4. Cloud credential rotates after review: the physical request must refuse.
5. Reload after a successful image turn: show the server's stored provenance,
   while the snapshot and embedding input contain no raw bytes.

---

### Task 1: Bounded durable vision provenance

**Files:** `agents/core/memory/conversation.py`,
`agents/core/memory/manager.py`, `agents/core/session_continuation.py`, new
`tests/test_h277_image_turn_memory.py`.

**Interfaces:** Add optional `media` to `Turn` and `MemoryManager.add_turn`,
with a validator accepting only `{kind: "image", count: 1..8, model: <=512
printable characters, backend: <=64 identifier characters, local: bool}`.
Old snapshots without `media` load unchanged. `get_history` returns validated
metadata; `get_context` remains text-only. It never stores destination or digest.

- [x] Write tests for allowed metadata, malformed old/edited metadata, snapshot
  reload and absence of base64/data URI in persisted JSON and embed input.
- [x] Run `pytest -q tests/test_h277_image_turn_memory.py`; confirm the new
  acceptance tests fail on the missing interface.
- [x] Implement the optional projection and run that test file green.
- [x] Run existing conversation/session continuation tests and commit Task 1.

### Task 2: A reviewed image completes a selected conversation turn

**Files:** `agents/core/routers/composer_vision.py`,
`agents/core/orchestrator.py`, new
`tests/test_h277_main_image_turn.py`; update old selected-image tests that
assert the explicitly transient contract only for the old operation.

**Interfaces:** `POST /api/vlm/composer/chat-prepared` accepts
`PreparedComposerVisionBody` with `selected_turn=true` and returns
`{ok, response, model, backend, local, committed: true}` only after a
successful server commit. Existing `/describe-prepared` remains standalone.
Use `Orchestrator.turn_lease(session_id)` and a dedicated
`Orchestrator.complete_selected_image_turn(...)` to bind the session, add a
user text/marker row and call `_complete_llm_turn` once with the actual answer.
The function receives the selected route/model and measured latency, and must
not invoke a second model. The selected review is consumed only after acquiring
the lease and revalidating the prepared transcript.

- [x] Write a real HTTPX transport test: prepare, send one PNG, verify one
  physical send and the two rows in `GET /memory`; ask a text follow-up and
  assert the prior image answer is in its prompt.
- [x] Run the new test red; implement the route/orchestrator seam; rerun green.
- [x] Add focused refusal/cancellation tests from Review Focus 1–4 and make
  each red then green. Verify no history mutation on review/provider failure.
- [x] Run H277/H139/H513/composer and memory/session regressions; commit Task 2.

### Task 3: Browser uses the committed operation and rehydrates it

**Files:** `frontend/src/vision-turn.ts`, `frontend/src/app.tsx`,
`frontend/src/composer-images.tsx`,
`frontend/src/test/composer-vision-turn.test.tsx`,
`frontend/src/test/composer-images.test.tsx`, generated
`frontend/src/api/schema.gen.ts` and `agents/web/v2/*`.

**Interfaces:** `describeImages` chooses `/chat-prepared` for selected turns;
standalone drafts continue `/describe-prepared`. Validate `committed:true`
before the HUD accepts a selected reply. The reload mapper reconstructs a
vision bubble from stored `media` metadata and makes no locality claim when
it is absent. The composer copy says image bytes are transient and the
question/answer are saved in the conversation.

- [x] Write a failing component test for selected dispatch, `committed:true`
  validation and rehydration from `GET /memory` with `media` metadata.
- [x] Run the focused Vitest tests red; implement and rerun green.
- [x] Generate OpenAPI types/HUD, run TypeScript checks, frontend tests and
  build; commit Task 3.

### Task 4: Frozen milestone and truthful records

**Files:** only impacted rows in `docs/hermes/assessment.json`, generated
Hermes/status reports, relevant `mobile/PARITY.md` or
`docs/design/HUD_V2_REMAINING.md`, and this plan's verification section.

- [ ] Rebuild/check Graft after source changes. Run the full backend and
  frontend suites on the exact source commit, with JUnit/test-count checks.
- [ ] Inspect touched Hermes evidence and restamp only justified rows;
  H277/H139 stay partial. Run Hermes/status consistency tests.
- [ ] Run scoped Ruff, diff and strict staged secret checks. Commit records
  separately. Leave a clean local branch and no remote mutation.

## Current verification

Task 1 verified: its red run showed seven interface failures, then the
focused 10-case test and the 80-case memory/session selection passed. Scoped
Ruff and Graft wiring check passed. The previous base milestone passed
21,216 backend tests (35 skipped, zero failures/errors) and 1,868 frontend
tests; those base results do not verify Task 2 or Task 3.

Tasks 2-3: the new HTTPX route test failed before the route existed, then the
selected-main route and seven image-turn cases passed. A slow-provider Stop
test failed while the request kept running, then passed after the owned task
was cancelled on disconnect. All selected H277/H513/composer/session regressions
passed; route/OpenAPI/auth snapshots and the generated API sweep are current.
The full frontend suite passed 1,872/1,872; TypeScript, E2E typecheck and HUD
build passed. The complete backend suite and Hermes evidence recertification
are pending in Task 4.
