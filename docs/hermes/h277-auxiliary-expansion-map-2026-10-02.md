# Next auxiliary expansion: inspected seams and contract questions

Read-only follow-up on source aa4865b5 after the four-consumer implementation. This is not
an implementation plan or a delivered capability.

The four orchestrator consumers now have shared local invocation. Remaining
concrete producers are agents/core/acquisition/llm_synth.py:generate_capability
and draft_plan, and house/presence.py:LocalPresenceExplainer.explain.

Acquisition is a real product seam: each producer currently captures
router.local_backend and active_model (fallback "local") before a two-attempt
JSON-output loop. Both attempts use that same backend/model, with fresh existing
auxiliary_request_scope each time; malformed JSON changes temperature0.2 to0.0.
Capability uses2048 tokens, draft1024. Data-policy/provider errors are not JSON
retries. The current code has no job-selection exclusion, unlike the four
orchestrator consumers. Tests in test_h32_llm_synth and
test_h513_acquisition_policy preserve limits, sanitation and revocation between
attempts/physical requests; actual API failure leaves the acquisition request
blocked. Any shared adoption must settle job-pin behavior explicitly, not inherit
a new refusal by accident.

The new generate_local_auxiliary currently selects once per invocation. Calling
it separately for both acquisition attempts would re-read model/backend and could
silently change them mid-operation, unlike the existing code. A prepared/bound
shared route or another explicit captured-operation mechanism is required if the
original freeze semantics are retained. Reuse H513 fresh policy checking; do not
duplicate consent or permit an arbitrary backend/model bypass in a public API.
An independent acquisition model override adds real capability; merely moving
the two loops into a helper is not a delivery claim.

Presence is an optional seam, with no production caller recorded by its existing
H513 tests. from_router captures backend/model; explain refuses missing, changed
or unavailable router/backend identity. Its constructor also supports an explicit
model but an unbound instance cannot generate. It strips occupant_id from the
deterministic decision, sends128tokens/temperature0, truncates output to1000 chars,
and never mutates inference. A shared call-time selector must not discard that
saved binding. Adding a flag only to this unwired seam is not user-facing
integration; investigate a governed real consumer before prioritizing it.

Next practical step: design/adopt acquisition capability+draft routing as one
coherent batch with frozen operation identity and meaningful model overrides;
keep presence binding and its unwired status explicit. Broader automatic provider
discovery, remote auxiliary routes and SDK recovery remain separate full-goal work.
