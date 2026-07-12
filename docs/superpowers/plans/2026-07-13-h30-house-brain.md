# H30 House Brain Implementation Plan

> Execute after H29 merges, using `superpowers:subagent-driven-development`, strict TDD, one
> implementation task at a time, and fresh spec/code-quality review for every task.

**Goal:** Complete all seven H30 items with a strict-local, read-first Home Assistant adapter,
queryable house model, governed actuation, browser/mobile visibility, room-aware media/voice, and
hermetic reality proof.

**PR declarations when wave-3 modules are touched:**

```text
unpark: wave-3
unpark: park-policy
```

## Task 1 — H30.1 normalized read-first Home Assistant adapter

**Create:** `agents/core/house/contracts.py`, `agents/core/house/home_assistant.py`, focused tests.

- [ ] Red tests: disabled/missing config, URL/host validation, secret redaction, entity/area
  normalization, malformed payloads, REST timeout, WebSocket auth/subscription/reconnect,
  duplicate/out-of-order events, bounded backoff/output, and no outbound call when disabled.
- [ ] Implement injected HTTP/WebSocket transports with explicit `JARVIS_HOUSE_BRAIN` and
  HA-specific host opt-in. Environment/settings precedence is explicit; Product Posture never
  wakes either flag. Resolve credentials through `SecretBroker`, never URL/query settings.
- [ ] Enforce LAN/allowlisted origin, redirect and DNS-rebinding protection, no cross-host auth
  header forwarding, bounded WebSocket frames/queues, flood handling, cancellation, reconnect
  shutdown, and token-free logs/support bundles.
- [ ] Emit immutable bounded `HouseEvent` and `HouseSnapshot` contracts with event/observed time,
  provenance, privacy class, and stable dedupe keys.
- [ ] Add honest health/state without persisting access tokens or HA raw payloads.
- [ ] Run focused tests, egress/security tests, Ruff/Bandit, review, and commit.

## Task 2 — H30.2 bi-temporal house graph and privacy lifecycle

**Create:** `agents/core/house/graph.py`, `agents/core/house/private_store.py`; modify only narrow KG seams
and focused tests.

- [ ] Red tests for room/device topology plus private occupant/presence facts, valid-vs-observed
  time, replay idempotency, stale correction, consent deletion, purge tombstones, keyed-id
  rotation, cache/history/restart purge, and prevention of deleted occupant resurrection.
- [ ] Project non-sensitive room/device topology into the existing KG. Keep occupant, presence,
  occupied-by, privacy context, and identity linkage in a separate encrypted/authenticated private
  bi-temporal store; generic KG list/history/as-of routes must never reveal them.
- [ ] Derive pseudonymous ids with a managed keyed secret, record privacy classification/consent
  version, and transactionally suppress replay of tombstoned source events.
- [ ] Publish read-only graph queries with confidence/freshness; no route yet.
- [ ] Test every generic KG API plus private caches/history after purge, then run house/KG/privacy
  tests, review, and commit.

## Task 3 — H30.3 local presence and privacy context inference

**Create:** `agents/core/house/presence.py`, focused tests.

- [ ] Red tests for sensor fusion, stale evidence, contradictory rooms, unknown identity, vacancy,
  privacy-mode override, consent revocation, clock skew, restart persistence, and strict-local LLM
  routing assertions.
- [ ] Implement deterministic bounded evidence scoring first; optional local-only model seam may
  explain but cannot override hard rules or invent identity.
- [ ] Bypass the generic cloud-capable router for presence processing and prove with the egress
  monitor that occupant/presence payloads cause zero external calls.
- [ ] Return unknown/ambiguous instead of guessing. Store confidence, evidence categories,
  freshness, and privacy context without raw device identifiers.
- [ ] Emit typed presence `HouseEvent` values for later H33 consumption.
- [ ] Run focused/local-routing/privacy tests, review, and commit.

## Task 4 — H30.4 governed HA actuation and strong confirmation

**Create:** `agents/core/house/actuation.py`, confirmation challenge/store module, capability
manifests and focused action/kernel tests.

- [ ] Red tests for allowlisted domains/services, parameter bounds, live-state precondition,
  dry-run/approval card, action-kernel invocation, kill-switch, budget/loop denial, verification,
  rollback, partial actuation, driver loss, retry idempotency, and no direct service-call path.
- [ ] Add explicit action kinds for narrow reversible house control and security-sensitive control.
  Do not use one generic payload that can smuggle arbitrary HA domains/services.
- [ ] Define durable task kinds and register explicit TaskExecutor handlers. Server-side validation
  persists only a bounded canonical payload; intake/acceptance never executes inline. New and
  low-confidence reversible controls remain blocked. Only bounded lights/climate actions with
  sufficient H27.7 outcome evidence may become policy-auto-approved. Security-sensitive actions
  are forced blocked regardless of confidence or autonomy mode. Both paths use the same executor.
  At task execution, revalidate payload and fresh HA state, then re-authorize through Action
  API/kernel.
- [ ] Implement a server-minted challenge bound to task id, capability, target, intended state,
  nonce, and expiry. Only an explicit admin-authenticated owner surface can answer the exact
  preview challenge; autonomous ToolRPC/runtime callers cannot access it. Store only a receipt
  hash and consume atomically once at execution.
- [ ] Test forgery, wrong target/state, expired/edited task, stolen receipt, concurrent replay,
  restart, and double-submit. Also prove low-confidence reversible actions stay approval-gated,
  evidence-qualified lights/climate auto-approve only within declared bounds, and locks/doors/
  alarm/security never auto-approve. Earned autonomy cannot lower the security floor.
- [ ] Verify from a fresh HA state read; rollback uses an explicit recovery capability that still
  respects the kill switch but records `manual_recovery_required` when compensation cannot run.
  Test policy change/halt/connection loss between mutation and rollback. Never claim success from
  a transport 200 alone.
- [ ] Run action-auth/manifest/kernel/reality/security tests, review, and commit.

## Task 5 — H30.5 house API, HUD, and mobile parity

Mobile read parity is an intentional program-level addition required by the repository's
browser-to-mobile parity rule; the literal H30.5 story names only the HUD.

**Create:** `agents/core/routers/house.py`, frontend House panel/component/tests, mobile House read
surface/client tests. Modify route/OpenAPI/auth snapshots and ledgers.

- [ ] Red route tests for default-off, empty/degraded/live state, privacy filtering, user/admin
  guards, bounded response, and actuation/confirmation response honesty.
- [ ] Add `GET /api/house/state`, narrow proposal endpoints, and an admin-only owner confirmation
  ceremony in the domain router; mount via `web.py` only. The confirmation endpoint is excluded
  from agent tools and cannot mint a challenge from arbitrary action data.
- [ ] Add browser state/rooms/devices/presence panel and governed controls that distinguish
  queued/denied/unverified/verified results.
- [ ] Add mobile read parity and approval handoff; never put security-device strong confirmation
  behind a weak one-tap mobile control.
- [ ] Update HUD/mobile parity, regenerate OpenAPI TS, run backend/frontend/mobile gates, review,
  and commit.

## Task 6 — H30.6 room-aware voice/media and controlled wave-3 unpark

**Modify:** narrow `voice/wyoming.py`, `satellite_hub.py`, H29 target resolver, park policy and
focused tests. Avoid `node_mesh`/`e2e_sync` unless a proven requirement appears.

- [ ] Red tests proving paired satellite identity maps to one configured room, spoofed/unknown
  ids, replayed frames, expired credentials, and wrong transport peers do not select a target;
  ambiguity refuses, privacy context is respected, and no device call occurs before H29.
- [ ] Carry the verified satellite principal through the voice event contract over an
  authenticated local pairing/token or certificate boundary with nonce/timestamp replay
  protection. Resolve room server-side, then resolve the unique default Media Director target.
- [ ] Keep voice/satellite host dependencies default-off and local-only.
- [ ] Add reality cases for room routing and fail-closed unknown/ambiguous identity.
- [ ] Graduate only `wyoming`/`satellite_hub` entries whose real execution seam is exercised by the
  hermetic kernel/zero-bypass pack; keep unused `node_mesh`/`e2e_sync` entries parked. Owner
  hardware remains a separate operational proof, not a false automated pass.
- [ ] Run voice/media/park-guard tests, review, and commit.

## Task 7 — H30.7 simulator, reality pack, truth sync, and PR

**Create:** hermetic HA simulator/reality tests; modify canonical reality harness and final truth
files only now.

- [ ] Prove adapter read/reconnect, graph projection, presence, privacy purge, reversible action,
  strong confirmation floor, kernel halt, verification/rollback, room output, offline HA, and zero
  ungoverned actions.
- [ ] Make the reality pack fail on any HA transport call not emitted by the registered approved
  task executor/broker and assert the real kernel trace for every mutation/compensation.
- [ ] Add optional live probe behind explicit owner environment variables; absence is a named
  skip/degraded state, not a pass.
- [ ] Run all H30 plus H27-H29 adjacency, route/OpenAPI/auth/HUD parity, full frontend/mobile,
  full Python, Ruff/Bandit/diff-check/status-sync.
- [ ] Fresh final review; resolve every Critical/Important finding with TDD.
- [ ] Mark H30.1-H30.7 complete with exact hermetic versus live evidence, update generated status,
  commit, push draft PR, monitor CI, merge, then rebase H31/H33 work.
