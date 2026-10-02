# H277 vision auto selection plan

Generated 2026-10-02. Goal: advance full local Nerva/Hermes parity using the
pinned Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. Base/head
`33d9e6d1` on `codex/h277-provider-discovery-20261002`. No push, merge,
deployment, credential copying or live/paid provider requests.

## Contract

The owner explicitly selects `JARVIS_ROLE_VISION_PROVIDER=auto`. Existing explicit
roles and legacy VLM resolution retain precedence. With a role base override,
that named endpoint is authoritative; do not discover another destination.
Without a base override, prepare status tries available adapters in Hermes vision
order: selected main if an actual per-turn main route was supplied, then
OpenRouter, Nous and DeepInfra. The standalone image composer receives no selected
main route today; represent it as absent. Do not manufacture one from a configured
text model or ambient key. The text auxiliary discovery refusal is a separate
contract and must not suppress vision candidates.

OpenRouter uses its dedicated adapter and upstream privacy block, the pinned free
vision fallback model when no explicit role model exists, and a scoped canonical
key. Nous uses owned profile credentials, tier-aware public recommendations and
native wire. DeepInfra requires an explicit model or a positively served vision
model from its catalog. A key alone is not proof of model availability. Failed
metadata/absent credentials skip that candidate; malformed authority or policy
settings refuse the whole route rather than silently widening the provider set.

GET status prepares the candidate; POST reads current state without discovery or
OAuth refresh. The selected backend/model/endpoint and auto source enter the
existing destination binding and are displayed before image submission. A switch
of candidate, credential, model, wire or provider policy invalidates consent and
refuses before any image send. Existing independent destination, training and cost
confirmations and last HTTP request hook remain authoritative. Local-only
consumers and inherited video do not gain cloud discovery.

## Files and checks

- New `agents/core/llm/vision_auto.py`: ordered candidate preparation and pure
  resolution using live provider-scoped environment views; no new dependencies.
- `vlm.py`, `model_roles.py`: recognize the opt-in role and preserve source in
  `VLMConfig`; no changes to non-auto behavior.
- `vision_policy.py`, `composer_vision.py`: bind and disclose auto provenance;
  composer GET prepares, POST resolves purely.
- `frontend/src/composer-images.tsx`: show a bounded source label alongside the
  reviewed model and destination; reject malformed source metadata.
- `tests/test_h277_vision_auto.py` plus existing provider, H277, composer,
  selection and local-only suites: real GET→POST and final transport boundary
  with synthetic credentials and HTTPX transports, candidate order/refusal,
  explicit precedence, no discovery on POST, stale binding, policy and source.

Write failing consumer tests first. Run focused backend and frontend checks after
each implementation step, then combined route/OpenAPI/HUD/docs gates, TypeScript,
one frozen full backend suite and truthful records. Refresh Graft after source
edits. Roll back source, generated records and UI as one unit. Keep H277 partial
until the rest of its accepted contract is proven.
