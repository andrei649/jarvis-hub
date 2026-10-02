# H277: runtime-aware vision discovery

Goal: advance the accepted Hermes parity backlog after reliability PR #1228.
Generated 2026-10-02. Base/head before this plan:
`9dbc0e2e518cc68d7aa54d919059133f4d4f3281`; branch
`codex/h277-provider-discovery-20261002`. Pinned Hermes:
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
This is a source-grounded implementation plan, not delivered auto routing.

## Verified constraints

- Nerva's effective main route comes from
  `agents/core/llm/hybrid_router.py::HybridRouter.select_backend(agent_id, prompt)`.
  It is per request, with policy and job/model pins. The `backend` property and
  declarative provider catalog cannot substitute for that selection.
- `agents/core/routers/composer_vision.py` currently has no conversation-agent
  selection. Status and describe independently resolve explicit vision settings.
  Represent main context as absent here; do not invent a selected main from global
  settings, a synthetic prompt or a provider with a configured key.
- Hermes text `_resolve_auto_route` and vision `_vision_auto_route` have distinct
  rules. Text refuses ambient discovery after an unavailable concrete main;
  vision tries its capable main route and then OpenRouter, Nous and DeepInfra.
  The text-only refusal must not accidentally suppress vision fallback.
- `VLMBackend` currently implements a compatible chat-completion wire contract.
  Provider metadata alone does not implement a native adapter, prove vision
  capability, or preserve provider-specific headers and privacy controls.
- Composer status already discloses a destination and binding. POST and the
  final HTTP request recheck identity and remote acknowledgement. Discovery must
  happen before those steps and participate in the same immutable binding.

## Implementation sequence

1. Specify candidate construction from explicit, provider-scoped configuration:
   provider, supported adapter, served vision model, normalized endpoint, source,
   policy and private credential binding. Preserve explicit role/legacy precedence.
   Auto selection is opt-in; configured credentials alone never authorize sending.
2. Implement the compatible provider adapters needed by the vision discovery
   order, preserving each provider's request contract. In particular, OpenRouter
   must retain its upstream privacy/routing controls; relabeling it as generic
   compatible transport would lose those controls. Missing adapter or model
   capability is an explicit unavailable result, never a speculative image send.
3. Integrate selection into actual composer status, POST preparation and physical
   request validation. Disclose the chosen provider/model/source before sending;
   any changed candidate or credential invalidates the previous acknowledgement.
   Do not deliver only an unused selector helper.
4. Extend signed video in a separate rollback unit. Candidate order, provenance,
   per-lane consent, source hash and request budgets must enter classification and
   approval before execution. Never discover another destination after approval.

Likely first-unit paths: `agents/core/llm/model_roles.py`,
`agents/core/llm/vlm.py`, `agents/core/llm/vision_policy.py`, provider adapters,
`agents/core/routers/composer_vision.py`, their tests, configuration documentation,
and composer UI/schema only when the public destination description changes.
Record mobile/HUD gaps with the implementation. Keep a single writer per shared
interface; delegate provider adapters only after the candidate contract is fixed.

Non-goals for the first unit: enabling remote unattended camera/Telegram media,
changing strict-local text tasks, copying credentials between hosts, live paid
provider probes, generic SDK credential recovery, or claiming full H277 parity.

## Acceptance and rollback

Use synthetic configuration and real consumer boundaries with HTTPX transports:
explicit precedence; opt-in/default-disabled behavior; absent main context;
vision-specific fallback order; unavailable/text-only models; preserved provider
privacy fields; status disclosure; stale acknowledgement refusing without a send;
key/base/model changes at the last request hook; and unchanged call budgets.
Test local-only media separately to prove it does not inherit remote discovery.
Demonstrate failing regressions before implementation, then targeted suites and
one full verification at the completed milestone. Live acceptance stays separate.

Rollback is a revert of each consumer integration PR; no credential migration or
persisted-settings rewrite is planned. Dependencies are the existing consent,
selection and exact-request guards. Next action: finalize the smallest adapter
contract against the pinned provider source and write composer-level red tests.

## Integration checkpoint

PR #1228 merged after its final CI succeeded. Canonical local `main` is clean and
has exactly the tested candidate's Git tree. Local verification: 20,746 backend
passed, 34 skipped, one expected failure; 1,847 frontend passed; 92 documentation
guards passed; typechecks, production build and strict secret scan passed.
Post-merge main workflows are separate runs and were still running when this plan
was prepared. Owner authorization now covers publication and merge of repaired
work; earlier local-only sprint restrictions are superseded. Deployment remains
outside the request. Existing source branches and worktrees remain preserved.
