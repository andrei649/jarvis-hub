# H277 Video Provider Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. The coordinator owns integration and records; one writer per path.

**Goal:** Execute an owner-configured, approved ordered video fallback chain after a recognized provider failure, preserving each candidate's authority and privacy controls.

**Architecture:** Reuse the signed video task and existing flat finite role-consent store. Resolve the complete chain before approval, bind every candidate into the task class, and perform bounded sequential native requests with fresh checks at each transition and physical send.

**Tech Stack:** Python 3.12, existing HTTPX/SQLite/FastAPI interfaces, React/TypeScript HUD; no new dependencies.

**Spec:** [H277 governed auxiliary fallback design](../../hermes/h277-provider-fallback-design-2026-10-02.md).

## Global Constraints

- Local only: no push, merge, deployment, live model calls or paid provider calls.
- Use `/tmp/nerva-pr-python-20261001/bin/python`; preserve repository pytest addopts.
- At most two Sol High implementation agents; coordinator owns shared interfaces, generated artifacts and commits.
- Existing primary resolution and no-chain behavior remain compatible.
- Four explicit fallback slots maximum; no provider or credential discovery from the main model.
- Unsupported native adapters remain required future work and refuse explicitly now.
- Full H277 parity is not established by this bounded chain increment.

## Review Focus

- A malformed unused fallback must not disappear from posture and silently leave a usable primary-only approval; test full-chain refusal in Task 1/3.
- Reordering two candidates with the same provider/model but different addresses must stale approval and affected consent; test in Task 2/3.
- A store/kernel exception that happens to be a TimeoutError must not be misclassified as model timeout; test exception origin in Task 3.
- Client cleanup may revoke authority after a provider failure; test no second request and no stale disclosure in Task 3.
- Updating another role's acknowledgment must preserve all configured video candidate grants without making unknown target IDs valid; test in Task 2.

## Task 1: Pure ordered configuration and route identities

**Files:** Create `agents/core/llm/video_routes.py`, `tests/test_h277_video_routes.py`; consume the existing primary resolver in `model_roles.py`. Keep public candidate identity construction in `video_policy.py` in Task 2 to avoid a role-consent import cycle.

**Interfaces:** `VideoFallbackRoute` is frozen and contains `slot`, `provider`, `model`, `base_url`, and `api_key` with secret fields excluded from repr. `resolve_video_fallbacks(env=None) -> tuple[VideoFallbackRoute, ...]` reads only the bounded JSON list and the fixed slot-key variables through env_config (or the supplied mapping). It raises a sanitized `VideoRouteConfigError` for invalid configuration. It creates no clients and reads no main/vision credentials.

- [ ] Write failing parser tests: absent/empty list, four ordered keyless/custom routes, dedicated keys, invalid JSON/extra keys/types, blank/auto models, unsupported providers, invalid URLs and oversized input. Include whitespace/default-port normalization without changing the primary route's native URL convention.
- [ ] Run `python -m pytest tests/test_h277_video_routes.py -q` and retain the expected missing-behavior failures.
- [ ] Implement the pure parser and frozen records. Reject credential-bearing URL/query/fragment, non-loopback LM Studio and remote HTTP; permit valid keyless endpoints. Bound raw JSON before parsing and each field's length; never log input values.
- [ ] Run the new suite, existing H277 role/fallback tests and scoped Ruff. Report exact diffs and tests for coordinator review; do not stage another writer's files.

## Task 2: Independent candidate identity, consent and posture

**Files:** Modify `agents/core/llm/video_policy.py`, `agents/core/llm/data_handling.py`, `agents/core/routers/security.py`, `frontend/src/panels/data-handling.tsx`. Add focused `tests/test_h277_video_candidate_consent.py` and extend `frontend/src/test/governance-posture-panel.test.tsx`. Coordinator regenerates `frontend/src/api/schema.gen.ts` and HUD assets at integration.

**Interfaces:** `describe_video_route_set() -> tuple[VideoIdentity, ...]` returns the primary then all validated fallbacks or refuses; a missing primary cannot create a fallback-only tool. `describe_video_data_target(target_id=VIDEO_TARGET)` preserves the old call while resolving a finite configured candidate. The primary target remains `role:video_analysis`; fallback targets are `role:video_fallback_1` through `_4`. `authorization_check` resolves the descriptor by its target ID. All candidates retain separate actual-use accounting.

- [ ] Write red tests for distinct candidate scopes, independent acknowledgment/revocation, stale configuration during audit, missing/unreadable store, unknown target IDs, key secrecy, and preservation of other role entries.
- [ ] Run the focused tests to demonstrate missing candidate behavior.
- [ ] Extend the finite target map and API literal without changing the flat stored-map shape. Resolve every candidate from current server configuration; refuse stale scope before and after audit. Hide unconfigured fallback rows while retaining existing primary/unrelated role posture behavior.
- [ ] Add clear HUD labels and per-candidate controls; reuse the existing acknowledgment request shape. Test that acknowledging a fallback sends its target ID and cannot authorize another candidate.
- [ ] Run candidate-consent, H513 role-consent/security API and targeted HUD tests. Coordinator reviews authority changes before consumer integration.

## Task 3: Signed full-chain approval and bounded native attempts

**Files:** Modify `agents/core/video_analysis.py`, `agents/core/llm/video_policy.py`; create `tests/test_h277_video_provider_chain.py`. Introduce a small adjacent failure-classification helper only if needed to keep native request and source logic readable; do not refactor unrelated LLM consumers.

**Interfaces:** The approved class binds the ordered full identity tuple. The notice names every candidate with sanitized destination information. An internal attempt receives one frozen identity plus the immutable media/prompt; it returns a complete buffered answer or a typed eligible model failure. Guard/source/cancellation failures do not become model failures. Existing no-chain result fields stay compatible; additional attempt metadata is bounded and contains no failed response text or secrets.

- [ ] Write red signed ToolRPC/worker tests for local primary failure followed by approved fallback, primary success without a second call, exhaustion and full-chain configuration changes. Use offline HTTPX transports and actual queued decisions.
- [ ] Write refusal tests before implementation: unconsented remote fallback, missing allow_remote, strict-local/local-only/safe-mode restrictions, policy or source failure, changed route/key/order during close, arbitrary validation/JSON/empty-response failures and generic HTTP 503. Include an injected kernel/store TimeoutError that must not trigger failover.
- [ ] Verify the tests fail for absent chain behavior.
- [ ] Resolve/authorize the entire chain before intake and before source/model sends; HMAC all identities with existing source/args/roots. Reuse one materialized source. Execute candidates sequentially, close each before transitioning and retain physical URL/auth/body/cookie/direct-transport checks.
- [ ] Classify bounded HTTPX status/body evidence using pinned Hermes predicates: connection/transport timeout, payment/quota and rate-limit failures, recognized model incompatibility, and authentication only onto an explicitly configured next lane. Do not classify arbitrary HTTP 400/403/5xx or exception text as permission to switch. Record the exact supported categories and any still-untranslated SDK semantics.
- [ ] Bound total execution by one monotonic deadline and each attempt by a smaller timeout; at most one send per configured lane in this increment. Distinguish an expired owned timeout from unrelated exceptions. Reject over-limit bodies before classification or disclosure.
- [ ] Run chain tests plus all video, role, consent, signed mediation and image-dispatch regressions. Add red regressions for concrete review findings before correction.

## Task 4: Coherent integration, evidence and continuation

**Files:** `.env.example`, `docs/FLAGS.md`, H277 assessment/reports, `BACKLOG.md`, the current local handover, generated schema/HUD/status artifacts, and a new exact-snapshot verification receipt.

- [ ] Document the owner configuration and fixed per-slot key variables, independent consent, actual failure categories, limits and unsupported providers. Do not claim paid-provider or subscription entitlement.
- [ ] Regenerate OpenAPI/schema, build HUD and run its full tests/typecheck when frontend changes are final.
- [ ] Re-read affected Hermes rows and stamp only reviewed evidence. Preserve partial status while native adapters, shared auxiliary routing, auto discovery, retries/credential recovery or live acceptance remain outstanding.
- [ ] Freeze source, record hashes, and run the full backend suite once with normal guards. Fix actual failures, then repeat the necessary verification. Verify generated counts and source identity independently of test return code.
- [ ] Scan the exact committed/staged scope; include docs/tests in the evidence scan rather than relying solely on the repository's broad path allowlist. Keep synthetic/hash false-positive adjudication explicit.
- [ ] Commit the coherent local implementation and resumable report. Rollback preserves the prior single-destination consumer, signed receipts, permission ledger and historical evidence.

The next implementation begins only after the current mutation regressions are frozen and the coordinator assigns non-overlapping files. This plan is an implementation dependency, not a completion claim.
