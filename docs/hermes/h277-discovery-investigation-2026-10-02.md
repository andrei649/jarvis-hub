# H277 next increment: auxiliary provider discovery

Goal: continue full local Hermes parity beyond native response normalization.
Generated 2026-10-02; inspected Nerva head
`f58948f189b86c21d6f0c60f0102c3c6ab38bb6b`, branch
`codex/h277-vision-normalization-20261002`. No runtime edit or provider call in this
investigation. Pinned Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.

## Verified requirements from source

For text, Hermes `agent/auxiliary_client.py::_resolve_auto_route` prefers the selected main
provider/model, then the task's configured fallback chain, then the main fallback
chain. Its `_discovery_chain_allowed` explicitly refuses to guess another logged-in
provider when a concrete main provider was selected but is unavailable. Built-in
discovery is only the final convenience when the main provider is absent/auto and
no explicit policy resolves a client. `_try_discovery_chain` skips known unhealthy
provider/base identities and uses its fixed provider chain. A simple scan for any
available API key would contradict this upstream text behavior.

Vision has a distinct contract: `_vision_auto_route` first tries the selected main
provider with a vision-capable default, then its dedicated aggregator order
(OpenRouter, Nous, DeepInfra). It does not apply the text discovery gate. Preserve
this distinction when adapting discovery to Nerva; do not infer image support
from a text route or from the presence of credentials.

`_to_async_client` preserves adapter kind and configured headers/credentials when
converting clients, disables SDK-internal retries, and handles Codex, Anthropic,
Bedrock and native Gemini separately. Discovery alone cannot establish those
adapter contracts. Do not copy credentials between hosts/profiles or introduce
paid-provider spend during local verification.

Nerva `agents/core/llm/providers/__init__.py` explicitly describes its registry as
declarative: profiles carry auth/base/capability/fallback hints but do not themselves
create clients or change routing. `model_roles.py::resolve` leaves the main role
outside environment selection; vision/video use explicit role/environment rules.
`auxiliary_text.py` covers six fixed tasks and binds a strict-local backend through
`prepare_local_auxiliary`; it is not the general upstream main-provider auto chain.
Job-pin exclusions, task-specific models and streaming compression remain separate
existing contracts. Presence explanation still lacks production wiring.

## Next action

Inspect the runtime provider factory/catalog (`hybrid_router.py::provider_catalog`),
settings routing (`provider_routing.py`) and vision/main-model capability selection
before designing the resolver. Specify an immutable candidate identity with source
provenance and explicit precedence. Integrate it into a real consumer's existing
status/approval preparation, so the resolved endpoint/model is disclosed and bound
before dispatch. Preserve strict-local unattended tasks; remote selection must keep
existing per-destination/role consent and key-to-host scoping. Discovery after an
approval cannot silently change its endpoint, provider, credential or send budget.

Use synthetic provider availability and real consumer boundaries to test explicit
overrides, text main-selected/unavailable refusal, vision aggregator fallback,
declared fallback ordering, no-policy
discovery, stale selection, no paid/unconsented side-effect and final HTTP authority.
Do not deliver only an unused resolver helper. Separate broad SDK adapter/credential
recovery from route discovery if their ownership or acceptance tests differ, while
keeping both in the full objective. The next concrete contract must follow the
runtime seams actually found; this source note alone is not implementation proof.
