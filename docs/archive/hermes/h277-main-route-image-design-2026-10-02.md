# H277 main-route image integration design

Generated 2026-10-02. Goal: make Nerva's automatic image route inherit the
**actual selected conversation provider and model** before its OpenRouter →
Nous → DeepInfra fallback, while retaining owner review before image egress.
Base/head at investigation: `186fee7a91164ac8826c27baa21cf2986c1bd64b` on
`codex/h277-provider-discovery-20261002`. Pinned Hermes source:
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e` in the local source archive.
Next action: implement the first prepared-turn seam with red HTTP/turn tests;
then add provider wires and the browser flow. No push, merge, deployment,
credential copy or live/paid provider call is in this local plan.

## Observed contract and gap

Hermes `agent/auxiliary_client.py:_vision_auto_route` tries the main runtime
provider/model before its three-provider fallback. Its
`_vision_main_provider_client` skips a known text-only model, may use a provider
vision default, and delegates credential/endpoint construction to its provider
resolver; `agent/image_routing.py:_lookup_supports_vision` consults explicit
overrides and provider probes. Unknown capability may be attempted. This is a
*selected runtime route*, not a global API key.

In Nerva, `agents/core/orchestrator.py` classifies a turn and selects its
backend after constructing the actual agent prompt; history and context can
change the selected model. The current browser image path instead calls
`/api/vlm/composer/status` when an image is attached and sends it through
`/api/vlm/composer/describe`. These endpoints have no selected agent, full
prompt or conversation route. `vision_auto._main` already accepts an explicit
`VLMConfig`, but no product caller supplies it. `frontend/src/app.tsx::runVision`
adds a separate vision bubble rather than a normal agent turn. Merely passing
the current text field or a global model setting to `_main` would advertise a
route that the actual turn might not use.

## Chosen boundary

Make image submission a prepared conversation turn. An explicit preflight
request selects the agent, builds the same prompt inputs used for dispatch,
selects the backend/model, and returns a short-lived, opaque review handle
with public destination, model, provider and policy requirements. Preflight
does not send or persist image bytes, does not write a completed chat turn,
and does not run tools. If its classifier uses a model, that text-only call is
governed by the normal text route and is disclosed as preflight work.

The confirmed request supplies the handle and images. It rechecks session,
prompt, selected route, model, endpoint, credential identity and policy, plus
the existing remote, training and cost acknowledgements. Any drift returns
409 with no image egress; the browser clears confirmations and obtains a fresh
preview. Keep the prepared selection scoped to this turn rather than reading a
mutable global last-route value. Persist a normal conversation turn only after
the image request has passed its guards. The browser must not silently switch
back to text submission when preflight fails.

The selected main route is used only when its model is not known text-only and
there is a matching image wire. The conversion must use the selected backend's
own endpoint and credential authority; no ambient key follows an unrelated
origin. If the selected route is unsupported or unavailable, evaluate the
existing OpenRouter → Nous → DeepInfra chain under the same preflight. A
strict-local agent must never fall through to a remote candidate. An unknown
capability may be tried with explicit consent, as in Hermes, but a known
text-only model is skipped. No fallback after a physical request may silently
charge a different provider: it needs a new preview.

Provider work is explicit: the existing OpenAI-compatible vision wire can
serve selected LM Studio and compatible/OpenRouter endpoints after endpoint,
key and capability checks. Ollama native, Claude Messages, Gemini and
Responses/xAI need matching image adapters and request-policy tests; they
cannot be relabeled as `custom` to pass through a chat-completions-only wire.
Nous's Messages mode remains account-bound to Nous and cannot borrow Claude
credentials. The existing role override remains authoritative above auto
selection. Explicit roles and signed video retain their current semantics.

## Rejected shortcuts

- Reading `llm.*` settings or `OPENROUTER_API_KEY` directly in the composer:
  these are not the route selected after agent/prompt policy and job pins.
- Running a selector on the raw text at preview and assuming it equals the
  subsequent full-prompt route: history, classification and routing can change.
- Choosing a new provider after remote consent or after a transport error:
  the reviewed destination would no longer describe the actual image send.

## First implementation and acceptance checks

1. Extract a reusable prepared-turn route result from the existing
   orchestrator path without changing ordinary text behavior. Its immutable
   identity must include session and selected agent/backend/model/route; it
   carries no image bytes, raw secret, or mutable cross-turn state.
2. Add one preflight/confirm backend path. Tests must show a history-size or
   job-selection change yields 409 before any image send; concurrent sessions
   cannot consume each other's handle; expiry and cancel leave no chat artifact.
3. Wire selected local and compatible/OpenRouter image adapters with mocked
   transports, then native adapters. For every provider, prove the exact URL,
   auth scope, model, policy payload and final physical-request guard. Known
   text-only and local-only routes must refuse or take only an allowed fallback.
4. Update the browser to request preflight from the current prompt/session,
   show the exact destination and independent confirmations, and submit only
   the reviewed handle. Desktop and mobile browser tests cover edit, route
   drift, cancel, retry and no unconfirmed egress.
5. Run focused tests per step, the backend/frontend integration suites, then
   one frozen full milestone. Update H277, H139 and H522 records only for
   behavior proved; live provider acceptance stays separately labeled.

Likely touched paths: `agents/core/orchestrator.py`, a focused
`agents/core/llm/` route/capability module, `agents/core/routers/composer_vision.py`
or a chat-media router, `agents/web.py` request wiring, and
`frontend/src/{app,composer-images,cockpit}.tsx` with matching tests. The
rollback unit is the prepared-turn API, adapters and browser submission;
preserve the already verified explicit VLM and auto fallback paths.
