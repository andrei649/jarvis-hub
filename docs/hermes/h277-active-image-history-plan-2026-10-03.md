# H277 Active Image History Implementation Plan

> **For agentic workers:** use `superpowers:executing-plans` task by task. Each
> task starts with a failing behavior test, ends with a focused green run and a
> reviewable local commit.

**Goal:** Let a selected browser conversation explicitly reuse active image
parts in a reviewed visual follow-up, without persisting or silently replaying
private bytes.

**Architecture:** Conversation memory owns a bounded process-local image store.
The composer binds selected handles and fresh images into a new one-use review,
then sends ordered native parts through the existing guarded selected route.
Durable conversation rows remain text/provenance projections.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, HTTPX, React/TypeScript,
pytest/Vitest.

**Spec:** `docs/hermes/h277-active-image-history-design-2026-10-03.md`.

## Global constraints

- No silent image replay from `/chat` or `/chat/stream`.
- Every physical resend requires a fresh selected-route owner review and H513 check.
- No image bytes/data URIs/digests in snapshots, logs, embeddings, audit or
  public history; process-local cache only, 16 MiB/32 handles, bounded TTL.
- No push, merge, deployment, live model or paid provider request.

## Review focus

1. A session reset or restart after preparation must refuse old handles before
   egress, even when the text session ID is reused.
2. Reordering prior handles or mutating newly attached bytes must burn the
   one-use review and send nothing.
3. A selected route/key/policy change after preparation must refuse at the
   physical request; no new destination inherits the old acknowledgment.
4. Client Stop while inference waits must cancel the owned task and commit
   neither answer nor active bytes.
5. A combined historical/new payload over the native size cap must refuse
   before any provider request, without truncating the owner's intended media.

---

### Task 1: Process-local active image ownership

**Files:** Create `agents/core/llm/vision_history.py`,
`tests/test_h277_active_image_history.py`; modify
`agents/core/memory/conversation.py` and `agents/core/session_continuation.py`
to own the store and invalidate it whenever a turn list is cleared/replaced.

**Interfaces:** `ActiveImageHistory` has `remember(session_id, instance,
agent_id, question, images) -> str | None`, `list(session_id, instance,
agent_id) -> list[dict]`, `resolve(session_id, instance, agent_id, handles)
-> tuple[bytes, ...]`, and `clear(session_id=None)`. `instance` is a process-
local session-instance token, never a public session ID alone. A successful
remember returns a random opaque handle; over-capacity returns `None`.
Resolve raises a fixed `ActiveImageUnavailable` on missing/stale state.
`ConversationMemory.active_image_instance(session_id)` returns a process-local
random token for an in-memory session and `None` if the session is absent.

- [x] Write red-first tests for scoped lookup, restart/new store, expiry,
  eviction, 4 MiB/image and 16 MiB/32-handle bounds, copy-on-input and
  copy-on-output, and secret-free repr/list output.
- [x] Run `pytest -q tests/test_h277_active_image_history.py`; confirm the
  missing interface is the reason for failure.
- [x] Implement the store with an injectable monotonic clock and immutable
  bytes. Keep invalid inputs out of exception text.
- [x] Rerun the focused tests and relevant session/memory tests; commit Task 1.

### Task 2: Ordered native history wire

**Files:** Modify `agents/core/llm/vlm.py` and each supported
`vision_*_wire.py` codec; create `tests/test_h277_native_image_history_wire.py`.

**Interfaces:** A new checked VLM operation consumes a bounded sequence of
logical user/assistant turns with image parts and an exact current model. It
uses the existing physical request/empty-retry scope, not a second sender.
Unsupported or malformed provider history fails before transport.

- [ ] Write one failing real HTTPX test per selected-main native codec for
  ordered prior image/question/answer plus current question and images.
- [ ] Write refusal tests for malformed roles, missing image part, oversized
  combined body and provider codec limitations.
- [ ] Implement wire conversion without changing ordinary single-image
  requests, and run the codec/selected-image/H513 suites green; commit Task 2.

### Task 3: Reviewed server conversation follow-up

**Files:** Modify `agents/core/routers/composer_vision.py`,
`agents/core/orchestrator.py`; add `tests/test_h277_active_image_followup.py`.

**Interfaces:** An authenticated active-history endpoint lists bounded labels
and handles. Prepare/submit accept explicitly selected handles and zero or
more fresh images. The one-use review binds ordered active bytes, fresh image
digests, route, session instance and transcript. Success commits one user/
assistant pair and retains only newly attached bytes.

- [ ] Write a failing end-to-end reviewed follow-up through the real route
  and offline HTTPX transport; prove one physical send and correct durable
  projection.
- [ ] Add red-first failure tests for all five Review Focus cases, current
  consent and authority revocation, and ordinary text chat not replaying.
- [ ] Implement the route with the existing session lease, review store and
  selected physical guard; run focused route/memory/H513 suites; commit Task 3.

### Task 4: Explicit HUD selection and state

**Files:** Modify `frontend/src/composer-images.tsx`,
`frontend/src/vision-turn.ts`, relevant tests and generated API types.

- [ ] Write failing component tests: available active image cards, explicit
  selection, total-image/destination/retry disclosure, restart/eviction
  unavailable state and no silent text-turn replay.
- [ ] Implement the opt-in UI and request shape; regenerate schema and HUD.
- [ ] Run selected Vitest, typechecks and build; commit Task 4.

### Task 5: Exact milestone and truthful ledger

**Files:** Only affected Hermes rows, generated status files, and this plan.

- [ ] Run full backend/frontend suites on the committed source; record exact
  pass/skip/xfail counts and a targeted mutation campaign for review binding,
  cache isolation and physical resend.
- [ ] Rebuild/check Graft; inspect cited source changes and restamp only
  justified rows. Keep H277 partial unless all remaining obligations pass.
- [ ] Run status/Hermes checks, scoped lint, staged secret scan and diff check;
  commit records separately, leave a clean local checkout.

## Task 1 evidence

The missing store caused the first focused test to fail before implementation.
After implementation, the 97-case active-image/memory/continuation selection
passed. A deliberate one-line removal of continuation invalidation failed its
specific regression, then the restored source passed the 97-case selection.
Scoped Ruff and `git diff --check` passed. This is a private cache primitive;
there is no active-image replay route or UI yet, and H277 remains partial.
