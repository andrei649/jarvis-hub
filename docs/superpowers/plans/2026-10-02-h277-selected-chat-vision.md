# H277 Selected Chat Vision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preview and send an image through the active conversation's selected provider/model when it has a compatible image wire, with a reviewed fallback only when agent policy permits it.

**Architecture:** Build a read-only image-turn prompt from the selected agent, session history and local prompt context, then ask the existing `HybridRouter.select_backend` for that full prompt. Rebuild and compare it at confirmation; carry only digests and a one-use handle across requests. The confirmed path uses the selected backend's own credential and endpoint through an appropriate image adapter and the existing physical egress guards.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, React/TypeScript, pytest, Vitest.

**Spec:** `docs/hermes/h277-main-route-image-design-2026-10-02.md`.

**Checkpoint (2026-10-02T11:27Z):** base/head `12ed8203`; this plan's local
changes are in `agents/core/llm/vision_{turn,capability}.py`,
`agents/core/routers/composer_vision.py`, `frontend/src/composer-images.tsx`,
the generated API/HUD assets and their tests. The next step is to pin the code
checkpoint, re-read and restamp affected Hermes rows, then rerun the complete
backend suite. No remote PR state is implied by this local checkpoint.

## Global Constraints

- Keep this sprint local: no push, merge, deployment, credential copy or live/paid provider call.
- Do not send the question to a model while merely previewing a destination. Image turns do not run tools, plugins or recall; their selected route is computed from the exact prompt this image turn will use.
- Strict-local agents (`frigga`, `ultron`, `howard`, `hestia`) cannot fall through to a remote vision candidate.
- Preserve the explicit vision-role override and the existing CLI status/describe contract.
- A different provider after physical request failure requires a fresh review; no silent fallback.

## Review Focus

- A session's history changes between preview and send: return 409 before image egress (Task 2 test).
- A provider credential rotates or consent policy changes: return 409 before image egress (Task 2 test).
- A local-only agent has no compatible local image wire: refuse without remote discovery (Task 2 test).
- A selected model is known text-only: skip it and preview only an allowed fallback (Task 2 test).
- A browser stops or changes question/agent: never reuse the old handle or persist a completed turn (Task 3 test).

---

### Task 1: Read-only selected image-turn route

**Files:** Create `agents/core/llm/vision_turn.py`; modify `agents/core/orchestrator.py` only for a method delegating to it; test `tests/test_h277_selected_image_turn.py`.

**Interfaces:** `await prepare_selected_image_turn(orch, *, question: str, agent_id: str, session_id: str) -> SelectedImageTurn`. The immutable result contains `session_id`, `agent_id`, a digest of the full prompt and history identity, `backend`, `model`, `route`, and no image bytes. It does not persist a user turn, run a model, or modify `orch.session_id` globally.

- [x] Write a failing test using real prompt construction and `HybridRouter.select_backend`: adding prior history changes the selected route or prompt digest, while no turn is persisted.
- [x] Run that test and confirm it fails for the missing prepared-turn interface.
- [ ] Implement the read-only builder, including the active agent's persona/context, notes, session history, and local runtime block. Use the same helper at confirmation; never substitute the raw input text for the full prompt.
- [ ] Run the focused test plus existing route-compaction, concurrent-session and selected-main adapter tests.

### Task 2: Main-first HTTP review and physical send

**Files:** Modify `agents/core/routers/composer_vision.py`, `agents/core/llm/vision_review.py`, `agents/core/llm/vision_auto.py` and focused image transport modules as needed; tests `tests/test_h277_selected_image_turn.py`, `tests/test_h277_vision_auto_consumer.py`, `tests/test_h277_vision_review.py`.

**Interfaces:** `POST /api/vlm/composer/prepare` issues a handle bound to the prepared prompt/history route; `POST /api/vlm/composer/describe-prepared` re-prepares and consumes it before the existing physical request guard. The selected main candidate comes from `vision_main.selected_main_config`, never ambient provider keys.

- [x] Write failing HTTP tests for main-first selection, history/agent drift, strict-local refusal and a known text-only main model. Credential-rotation and concurrent-session cases remain to be added to the selected-turn HTTP suite.
- [ ] Run each new test red, then route the exact selected main candidate through `vision_auto.prepare_config` and the confirmed image adapter.
- [ ] Recheck the prompt/history fingerprint and route at confirmation and immediately before egress; deny unsupported native wires rather than relabeling them as compatible.
- [ ] Run focused tests, route/auth/OpenAPI snapshots, and the existing explicit-role and CLI image suites.

### Task 3: Browser turn and safe persistence

**Files:** Modify `frontend/src/composer-images.tsx`, `frontend/src/cockpit.tsx`, `frontend/src/app.tsx`, `frontend/src/vision-turn.ts`; add focused Vitest/Playwright tests; adjust the conversation persistence path only after a taint-safe representation is proved.

**Interfaces:** The browser reviews one question/agent/session and transmits only its matching one-use handle. A successful image turn is either persisted with image-derived content marked untrusted or remains explicitly client-only and H277 stays partial.

- [ ] Write failing tests for edit, cancel, stale history, local-only route, and no unreviewed send; prove no conversation artifact exists on refusal.
- [ ] Implement the client transitions, then test the server's post-success persistence under the existing taint and session boundaries before enabling it.
- [ ] Run frontend unit and browser checks, then rebuild committed HUD assets and generated OpenAPI types.

### Task 4: Provider breadth, evidence and milestone

**Files:** Extend provider-specific image adapters and tests; update `docs/hermes/assessment.json`, `HERMES_STATUS.md`, generated reports, `mobile/PARITY.md` and HUD documentation.

- [ ] Add exact-wire tests for selected LM Studio, compatible/OpenRouter, Ollama native, Claude Messages, Gemini and Responses/xAI before enabling each route; test URL, auth, model, policy payload and physical guard.
- [ ] Run bounded mutations on an exact-commit archive, fix meaningful survivors, and verify source restoration.
- [ ] Run targeted suites, a frozen full backend/frontend milestone, typecheck/build, status and secret gates; restamp only rereviewed Hermes rows.
- [ ] Keep H277 partial until every accepted provider and browser/native requirement is evidenced; record live-provider acceptance separately.
