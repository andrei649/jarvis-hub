# H277 presence explanation production wiring

Pinned Hermes reference: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Starting Nerva boundary: `LocalPresenceExplainer` exists, but no production caller
uses it. The House panel exposes pseudonymous deterministic presence state.

## Contract

An owner may explicitly request an optional explanation for one pseudonymous
occupant already present in the private house store. The server reads the
current deterministic decision from that store, with its established freshness
and private-room suppression, and returns that decision alongside a bounded
explanation. The model cannot change the decision or start a house action.
The request is refused when the writer/store is disabled, the house snapshot is
not live, the pseudonym is absent or stale, or the model is not proved local.
No periodic state read invokes the model. The stored raw identity is not
interpolated into the prompt or deterministic response. Model text remains
untrusted and could invent a name; the browser labels it as model text and
keeps the deterministic status visible.

The route is owner-authenticated and uses the existing selected local backend.
Both the selected backend endpoint and the final physical HTTP request must
remain on loopback; a late backend edit, redirect, or inherited owner consent
must not authorize a remote URL. Existing H513
auxiliary guards still reauthorize each request. A refused or failed explanation
does not modify the stored presence decision.

## Implementation and verification order

1. Add red tests for pseudonym lookup and privacy/staleness parity with
   `current_presence`, then implement a bounded private-store lookup by
   pseudonym and reuse one decision decoder.
2. Add red tests for local-only physical request binding, including a changed
   endpoint and an off-loopback final request, then extend the existing
   auxiliary scope and presence explainer with an opt-in strict-local rule.
3. Add red route tests for live explicit requests, disabled/unavailable/unknown
   conditions, no model call on `/api/house/state`, and no identity disclosure;
   wire the route to the real store and model.
4. Add the House panel's explicit Explain control and UI tests. Regenerate
   API snapshots and HUD assets using the repository's existing workflow.
5. Run focused backend/frontend suites, the full backend suite, Graft refresh,
   status checks, and update only H277's truthfully supported evidence. No
   remote provider call, deployment, push, or merge is part of this milestone.

This closes one named H277 gap; it does not by itself make H277 equivalent.

## Local verification

The focused backend and API union passed 66 tests. The House panel passed 13
component tests; the full frontend suite passed 1,874 tests. TypeScript
typecheck, HUD build, route/auth/OpenAPI snapshots, scoped Ruff, the strict
staged-source scan, and Graft build/check passed. The first full backend run
stopped on stale Hermes report hashes after the source/schema change. The
affected rows were reviewed and restamped against the exact source revision,
returning the documented total to 180/697; the Hermes status test then passed
48 tests. The full backend rerun exited 0: 21,218 passed, 34 skipped and one
expected failure (`xfail`). No live Home Assistant or local-model service was
exercised.

Strict-local checks cover the configured and final HTTP URL; independent
socket-level or proxy-environment proof is still outstanding.
