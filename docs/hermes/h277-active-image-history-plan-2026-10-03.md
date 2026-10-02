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
agent_id, question, answer, images) -> str | None`, `list(session_id, instance,
agent_id) -> list[dict]`, `resolve(session_id, instance, agent_id, handles)
-> tuple[bytes, ...]`, and `clear(session_id=None)`. `instance` is a process-
local session-instance token, never a public session ID alone. A successful
remember returns a random opaque handle; over-capacity returns `None`.
`resolve_turns` returns the ordered prior question, answer and image tuple;
`resolve` returns the flattened image bytes for review digests. Both raise a
fixed `ActiveImageUnavailable` on missing/stale state.
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

- [x] Start with a failing ordered-history codec test, then add real offline
  HTTPX tests per selected-main native codec for prior image/question/answer
  plus the current question.
- [x] Write refusal tests for malformed roles, missing image part, oversized
  combined body and provider codec limitations.
- [x] Implement wire conversion without changing ordinary single-image
  requests, and run the codec/selected-image/H513 suites green; commit Task 2.

### Task 3: Reviewed server conversation follow-up

**Files:** Modify `agents/core/routers/composer_vision.py`,
`agents/core/orchestrator.py`; add `tests/test_h277_active_image_followup.py`.

**Interfaces:** An authenticated active-history endpoint lists bounded labels
and handles. Prepare/submit accept explicitly selected handles and zero or
more fresh images. The one-use review binds ordered active bytes, fresh image
digests, route, session instance and transcript. Success commits one user/
assistant pair and retains only newly attached bytes.

- [x] Write a failing end-to-end reviewed follow-up through the real route
  and offline HTTPX transport; prove one physical send and correct durable
  projection.
- [x] Add failure tests for all five Review Focus cases, current
  consent and authority revocation, and ordinary text chat not replaying.
- [x] Implement the route with the existing session lease, review store and
  selected physical guard; run focused route/memory/H513 suites; commit Task 3.

### Task 4: Explicit HUD selection and state

**Files:** Modify `frontend/src/composer-images.tsx`,
`frontend/src/vision-turn.ts`, relevant tests and generated API types.

- [x] Write failing component tests: available active image cards, explicit
  selection, total-image/destination/retry disclosure, restart/eviction
  unavailable state and no silent text-turn replay.
- [x] Implement the opt-in UI and request shape; regenerate schema and HUD.
- [x] Run selected Vitest, typechecks and build; commit Task 4.

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

## Task 2 evidence

The first ordered-history codec test failed on Ollama's prior assistant turn
before conversion. Offline HTTPX regressions now exercise the compatible,
Ollama, Gemini, OpenAI Responses, xAI and Anthropic Messages transports in
order. Five codec refusal variants reject malformed role order and missing
image parts; a 20 MB combined-body refusal proves no request is sent. The
native/selected-image/H513/memory test selection passed, along with scoped
Ruff, Graft wiring freshness and `git diff --check`. These are local simulated
transports, not live provider compatibility proof. The server route and HUD
remain for Tasks 3 and 4.

## Task 3 evidence

The end-to-end follow-up test first failed because the active-image endpoint
was absent, then because preparation rejected selected handles. The route now
lists scoped handles and short labels, resolves prior question/answer/image
parts only for an explicitly selected review, and binds their order, image
digests and process-local session instance with the fresh-image digests,
selected route and transcript. A second check runs at the physical request.
Only fresh bytes are retained after the durable pair commits; a cache fault
cannot turn an already committed response into a failure. A follow-up with no
fresh image records a referenced-image marker, while mixed old/new turns
record both kinds without storing bytes.

Offline integration tests cover reviewed reuse, mixed media, no implicit replay
on a new selected turn or ordinary text chat, reordered handles, changed fresh
bytes, reset with the same session ID, rotated credentials, newly required
consent, total image count, physical-time eviction, and Client Stop. The broad
H277/H513/composer/session test selection, scoped Ruff, Graft freshness and
`git diff --check` passed. The source remains local and provider calls were
simulated; explicit HUD selection is Task 4.

## Task 4 evidence

The first component tests failed because the HUD had no earlier-image control.
The composer now fetches process-local labels only after the owner clicks
"Reuse earlier images". Each checkbox adds an ordered handle to a fresh
review; a history-only follow-up requires a typed question. The HUD checks
the server's current session and selected-image count, combines previous and
new images under the eight-image limit, displays destination/retry/policy
information and clears acknowledgements whenever the selection changes.
Restart/eviction displays an unavailable state and leaves ordinary text chat
usable. A history draft cannot use the non-committing describe route.

The selected composer/turn Vitest set, both TypeScript checks and the
production build passed. OpenAPI types were generated from a temporary local
test server with runtime state outside the checkout; that server was stopped.
The committed HUD bundle was regenerated from source. No live provider or
browser-hardware proof is claimed.
