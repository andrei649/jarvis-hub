# H277 governed auxiliary fallback — implementation design

Status: implemented and locally verified in the [configured-chain report](h277-video-provider-chain-2026-10-02.md).
This bounded increment does not complete H277 or redefine full Hermes parity.
The baseline discussion below records the state when this design was written.

## Goal and evidence

The owner requested all accepted Hermes capabilities in Nerva, with autonomous local
implementation and preserved existing work. This increment adds real failure recovery
to the approved video consumer. No push, deployment, provider login, paid call or live
model probe is part of implementation or verification.

Pinned reference: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
`tools/vision_tools.py` sends video through the auxiliary `vision` task.
`agent/auxiliary_client.py` resolves a configured fallback chain and classifies the
failure before selecting another lane. Its hashes remain recorded in the earlier
[resolution-fallback plan](h277-video-fallback-plan-2026-10-02.md). At the design baseline, Nerva
resolved one destination before approval and sent once, without a provider-failure
chain. Current video tests and their limitations are in the
[milestone report](h277-video-analysis-2026-10-02.md).

## Chosen contract

1. Keep existing primary-route resolution unchanged. Add an owner-configured,
   bounded JSON array `JARVIS_ROLE_VIDEO_FALLBACKS`, with up to four fallback records
   containing only `provider`, `model` and `base_url`. Only the two implemented native
   Chat Completions adapters can execute initially. Unknown fields/providers,
   unsupported protocols and malformed routes refuse the entire configured chain.
   Future adapters remain required work; their absence is not a scope exclusion.
2. Fallback credentials come only from fixed, per-position variables
   `JARVIS_ROLE_VIDEO_FALLBACK_1_KEY` through `_4_KEY`. Empty keys remain valid for
   compatible keyless servers. No request-supplied environment name, primary/vision
   key or implicit main-model credential is borrowed. Status and repr omit keys.
3. Reuse the flat, finite role-consent store. Preserve `role:video_analysis` for the
   primary and add `role:video_fallback_1` through `_4` for configured fallbacks.
   Each has its own current descriptor, secret-keyed scope, audit and revoke path.
   Other role entries and legacy primary acknowledgments keep their existing shape.
   Reordering or changing a candidate invalidates the affected consent. Unconfigured
   fallback rows are hidden from posture. The API's finite target union and HUD
   labels/schema must change together; no nested-store migration is needed.
4. Bind the ordered complete identity list, source identity/hash, question, roots
   and per-call remote/cost flags into the signed task class. The approval notice
   lists every candidate's provider/model and a sanitized destination without
   credentials or query data. One accepted card permits only that exact chain.
   Existing task receipt, kernel and persisted-decision checks remain authoritative.
   With no configured fallback, preserve the existing single-route class material
   and primary consent scope exactly. Adding/removing/reordering a chain is an
   intentional configuration change that invalidates old approval; merely upgrading
   code with the same primary and no chain must not invent that change.
5. Every candidate must pass its own privacy, cost, protocol and consent checks
   before intake succeeds. A remote fallback requires the remote per-call flag and
   role opt-in even with a local primary. Safe mode, strict-local, local-only agents
   and `cloud_fallback=never` retain their restrictions. Recheck the full chain for
   configuration/authority changes at source access, transitions, physical sends
   and result disclosure; record actual role usage only for attempted sends.
6. Materialize the approved source once, then try each configured candidate at most
   once in order. Buffer each response, close its owned client before moving on,
   retain exact native URL/auth/body/direct-transport guards, and use a single
   monotonic deadline with bounded per-attempt timeouts. Do not retry on policy,
   approval, consent, selection, source-validation or cancellation failures.
   Transport and provider failure categories must be explicitly derived from the
   pinned Hermes implementation; arbitrary malformed data or generic exceptions
   must not silently choose another destination. Return bounded attempt categories
   and the successful provider/model without raw URLs, credentials or failed content.

The reference's `_FALLBACK_REASONS` includes authentication, payment/quota, rate
limit, narrowly classified model incompatibility, specific invalid/structured SDK
response shapes, timeout and connection failures. Explicit-provider authentication
failure requires its configured task chain. Generic 5xx belongs to same-provider
transient retry, not unrestricted provider switching; plain 400 and arbitrary JSON
or empty-answer errors are not fallback permission. The initial native HTTPX chain
must test those distinctions. SDK-specific translations and same-provider retries
remain explicit follow-up requirements until implemented and verified.

## Implementation sequence and ownership

1. Finish the current mutation campaign, add meaningful missing boundary regressions,
   commit the tests and repeat the relevant mutants on a fresh immutable snapshot.
2. Implement pure route-set parsing and candidate descriptors with red-first tests.
   Likely paths: `agents/core/llm/model_roles.py`, `video_policy.py`, and a focused
   `tests/test_h277_video_provider_chain.py`. Preserve no-chain behavior.
3. Extend finite role consent in `agents/core/llm/data_handling.py`, the security
   endpoint and HUD. Test independent acknowledgment/revocation, current-scope CAS,
   audit/store failures, preservation of other role entries and hidden credentials.
4. Add bounded sequential native attempts in `agents/core/video_analysis.py`.
   Exercise real signed ToolRPC-to-worker dispatch with offline HTTPX transports:
   primary success, eligible primary failure then approved fallback, exhaustion,
   state changes between attempts, client cleanup and final disclosure.
5. Update environment documentation, OpenAPI/schema/build artifacts and the partial
   H277 record. Run focused checks after changes and full suites once the coherent
   integration is stable. Keep exact source hashes and separate local/live evidence.

The coordinator assigns one writer per path before implementation. At most two Sol
High implementation agents may run concurrently. The coordinator owns shared
interfaces, review, records, generated artifacts and local commits.

## Acceptance and rollback

- No fallback configuration preserves the current single-send behavior.
- A configured, individually consented fallback receives the same approved media
  only after an eligible failure; an unconfigured destination receives no bytes.
- A remote fallback cannot inherit the local primary's permission or another role's
  acknowledgment. Candidate order/model/URL/key changes stale the approved task.
- Physical URL/method/auth/body/cookie/transport rewrites refuse. Revocation during
  failure cleanup prevents the next attempt; late revocation withholds the answer.
- Ordinary validation errors, cancellation and policy refusals never cause failover.
- Every model attempt is bounded, closed and auditable; no live or paid call is
  needed to prove the offline contract.

Rollback is the coherent local fallback integration, preserving the prior video
consumer and historical evidence. Never remove the existing permission ledger,
signed execution or privacy checks to make a fallback test pass.

Still required beyond this increment: the wider auxiliary provider and native
adapter contracts, shared vision/judge failure routing, Hermes auto discovery and
same-provider retry/credential recovery behavior, and live model acceptance where
appropriate. Inbound media and mobile controls remain separately tracked. Passing
the configured video-chain tests alone cannot establish full H277 equivalence.
