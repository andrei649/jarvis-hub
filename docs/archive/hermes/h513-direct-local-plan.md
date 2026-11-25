# H513 direct local acquisition and presence calls

Status: implemented with 202 combined focused tests passing, 2026-09-27.
[Exact evidence](evidence/h513-direct-local-2026-09-27.json) records 22 new cases,
source hashes and the absence of a new full-suite/live-provider run. Base/head:
`bd2bb70ead1b493043a335e77713fc42c47d4013` plus the locally verified chat/auxiliary
milestone. Goal: reuse its internal data-policy guard for two additional direct
local call sites. Next action: design the separate approval-judge consent target,
whose endpoint/account may differ from the primary provider. No publication or
live provider requests.

## Acquisition

The admin acquisition drive route wires `draft_plan` and `generate_capability`
from `agents/core/acquisition/llm_synth.py`. Each function already retains the
actual router, selected `local_backend` and model, and permits two JSON attempts.
Wrap each generation await in `auxiliary_request_scope` with roles
`acquisition_draft` and `acquisition_capability`. Retain existing prompts, token
limits, temperature changes, parsing and downstream grounding/AST validation.
A refused policy check must not become a malformed-JSON retry or cloud fallback.
It propagates through existing failure handling. This prevents unauthorized
model I/O; research may already have performed its separately governed fetches.

## Presence explanation

`LocalPresenceExplainer` in `agents/core/house/presence.py` has a `from_router`
factory but currently discards the router. No production caller was found; this
change hardens the callable seam without claiming a connected product feature.
Retain the actual router through an optional keyword-only constructor parameter,
passed by `from_router`, and fail closed at explain-time when no binding exists.
Before model I/O also require the stored backend to remain the router's selected
local backend, so a supplied unrelated router cannot confer a false binding.
Wrap the awaited generation in the shared scope with role
`house_presence_explanation`. Preserve occupant-ID removal, the 128-token budget,
output cap, and deterministic inference. Do not add a new caller, provider,
fallback, consent route or house inference dependency on LLM availability.

## Ownership, tests and rollback

Writer A owns llm_synth.py, test_h32_llm_synth.py and focused new acquisition policy
tests. Writer B owns presence.py, test_h30_presence.py and focused new presence
policy tests. Coordinator owns this plan, shared coverage wording and records.
Both reuse the frozen helper; no helper/settings API changes are expected.

Reproduce refused off-loopback calls under copied owner context; verify explicit
audited consent, loopback success, unchanged output limits and actual physical
retry revocation. For acquisition also verify revocation between its two JSON
attempts and existing drive failure behavior. For presence verify absent or
mismatched router binding refuses before I/O, stripping identity stays intact,
and deterministic inference remains independent. Give synthetic backend fixtures
truthful profile/endpoint metadata without weakening expectations. Run existing
acquisition drive/pipeline and presence suites plus H513 regressions. Broaden only
for failures or the next milestone; no duplicate full suite for each small step.

Rollback removes only these scopes/router binding and tests. It does not alter
stored capabilities, private house data, inference rules, model settings or
consent. H513 stays partial for judge/VLM/embedding and other uncovered clients;
presence still has no verified production integration.
