# H277: selected image as a real conversation turn

Goal: an image submitted in the shared web composer must be one server-owned turn
of the selected agent and session. The answer must survive reload and inform later
text turns. The browser may display progress, but must not be the authority for
conversation history. This is an increment toward the pinned Hermes reference
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`, not closure of H277 or H139.

Base: `1d076b39` on `codex/h277-provider-discovery-20261002`, 2026-10-02.
Relevant source: `agents/core/routers/composer_vision.py`,
`agents/core/llm/vision_turn.py`, `agents/core/orchestrator.py`,
`agents/core/memory/{manager,conversation}.py`, `frontend/src/app.tsx` and
`frontend/src/vision-turn.ts`.

## Observed contract and gap

`prepare_selected_image_turn` already builds the agent prompt from the selected
session, freezes a transcript fingerprint and resolves the selected backend.
`describe-prepared` consumes a one-use review and sends the image under the
physical destination guard. It then returns text without entering
`Orchestrator._complete_llm_turn`; `frontend/src/app.tsx` adds only an in-memory
vision bubble. The successful response is absent from `GET /memory`, session
continuation and the next prompt. `/chat/stream` owns a session lease and normal
memory/telemetry, while the image route does not. Tests for the old contract
explicitly assert zero history after a successful image response.

Pinned Hermes `agent/image_routing.py` distinguishes native image parts from a
vision-to-text fallback. Its `agent/session_persistence.py::_durable_content`
projects image parts to text markers rather than persisting base64. Reuse that
privacy property, not its provider SDK or transcript schema.

## Design decision

Make the selected **native-capable** image route a server-owned conversation
turn. Keep the existing prepared review and physical request guard. After the
session lease is acquired, recompute selection and transcript, consume the
review, send to the same selected provider, then commit the user's question and
bounded image marker plus the actual answer to the selected session. Record the
actual route/model as conversation provenance and use the normal post-turn seam
for telemetry and cognition; do not invent a second agent/model call. The
response tells the HUD that the turn was committed, so it renders the returned
server event and rehydrates the same kind of message after reload.

The current `describe-prepared` path stays for explicit standalone VLM use.
The shared composer uses a dedicated selected-conversation operation so a
standalone VLM response can never accidentally be recorded as an agent turn.
Both operations may share raster validation, review binding and the physical
sender. Text-only `/chat` and `/chat/stream` remain unchanged.

The session lease covers revalidation, dispatch and commit. A changed session,
history, provider, key, model, endpoint, policy or ordered image digest refuses
before image egress. If the client stops before a result is accepted, cancel
the owned task and commit no answer. A normal successful commit can precede
delivery of the HTTP response, as it does for existing streamed text turns.
Errors return bounded reason codes and write no successful conversation pair.
No raw data URI, image byte array, digest, credential or full endpoint is
written to durable conversation storage or long-term embedding. The durable
user text says that images were attached; model/backend/locality metadata may
be retained only through a small validated, secret-free provenance shape.

The selected model's existing image policy controls remote disclosure,
training/cost confirmation and local-only agents. A non-native main model must
not be silently upgraded to this path; it keeps the governed auxiliary route
until a separate, explicit two-model turn contract is implemented. The UI must
tell the owner when it will use that auxiliary path.

## Acceptance and evidence

- Red-first route test: a reviewed selected image reaches the selected model
  once, then `GET /memory` contains the question marker and actual answer in
  the same session; a follow-up text turn sees that answer in its context.
- Refusal tests: reordered/changed image, expired review, session reset,
  history drift, model/key/endpoint drift, local-only violation, busy lease,
  client cancellation and provider failure cause no successful image pair and
  no unauthorized second send.
- Persistence test: reload restores the server-owned vision provenance; stored
  snapshot/log/embedding inputs contain no image data URI or credential.
- Run focused H277/H139/H513 and memory/session tests, frontend component tests,
  typecheck/build, then full suites at the milestone. Rebuild Graft, restamp
  only impacted Hermes rows after source review, and run consistency/secret gates.

Remaining after this increment: auxiliary-to-main text routing, richer
multi-part image history while the session is active, native mobile image
composer, broader provider/model discovery and live-provider acceptance. H277
and H139 remain partial until their whole accepted contracts are met.

Rollback: revert the operation, frontend call and provenance projection as one
coherent local change; the pre-existing standalone VLM operation stays usable.
No push, merge, deployment or paid provider call is part of this work.
