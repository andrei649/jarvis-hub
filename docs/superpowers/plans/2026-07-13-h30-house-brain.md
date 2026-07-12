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
  HA-specific host opt-in. Use existing governed HTTP/egress primitives where compatible.
- [ ] Emit immutable bounded `HouseEvent` and `HouseSnapshot` contracts with event/observed time,
  provenance, privacy class, and stable dedupe keys.
- [ ] Add honest health/state without persisting access tokens or HA raw payloads.
- [ ] Run focused tests, egress/security tests, Ruff/Bandit, review, and commit.

## Task 2 — H30.2 bi-temporal house graph and privacy lifecycle

**Create:** `agents/core/house/graph.py`, `agents/core/house/store.py`; modify only narrow KG seams
and focused tests.

- [ ] Red tests for room/device/occupant vocabulary, contains/located-in/observed-by/occupied-by,
  valid-vs-observed time, replay idempotency, stale correction, consent deletion, purge tombstones,
  and prevention of deleted occupant resurrection.
- [ ] Project normalized house events into a strict-local bounded store and bi-temporal KG using
  pseudonymous stable occupant ids. No raw HA attributes or secrets.
- [ ] Require privacy classification/consent version on occupant facts and enforce read filters.
- [ ] Publish read-only graph queries with confidence/freshness; no route yet.
- [ ] Run house/KG/privacy tests, review, and commit.

## Task 3 — H30.3 local presence and privacy context inference

**Create:** `agents/core/house/presence.py`, focused tests.

- [ ] Red tests for sensor fusion, stale evidence, contradictory rooms, unknown identity, vacancy,
  privacy-mode override, consent revocation, clock skew, restart persistence, and strict-local LLM
  routing assertions.
- [ ] Implement deterministic bounded evidence scoring first; optional local-only model seam may
  explain but cannot override hard rules or invent identity.
- [ ] Return unknown/ambiguous instead of guessing. Store confidence, evidence categories,
  freshness, and privacy context without raw device identifiers.
- [ ] Emit typed presence `HouseEvent` values for later H33 consumption.
- [ ] Run focused/local-routing/privacy tests, review, and commit.

## Task 4 — H30.4 governed HA actuation and strong confirmation

**Create:** `agents/core/house/actuation.py`, confirmation receipt/store module, capability
manifests and focused action/kernel tests.

- [ ] Red tests for allowlisted domains/services, parameter bounds, live-state precondition,
  dry-run/approval card, action-kernel invocation, kill-switch, budget/loop denial, verification,
  rollback, driver loss, retry idempotency, and no direct service-call path.
- [ ] Add explicit action kinds for narrow reversible house control and security-sensitive control.
  Do not use one generic payload that can smuggle arbitrary HA domains/services.
- [ ] Implement single-use, short-lived, scope/action/target/expected-state-bound strong
  confirmation. Recheck it and current HA state immediately before locks/doors/alarm/security
  actuation. Earned autonomy cannot lower this floor.
- [ ] Verify from a fresh HA state read; rollback through the same broker/kernel path. Never claim
  success from a transport 200 alone.
- [ ] Run action-auth/manifest/kernel/reality/security tests, review, and commit.

## Task 5 — H30.5 house API, HUD, and mobile parity

**Create:** `agents/core/routers/house.py`, frontend House panel/component/tests, mobile House read
surface/client tests. Modify route/OpenAPI/auth snapshots and ledgers.

- [ ] Red route tests for default-off, empty/degraded/live state, privacy filtering, user/admin
  guards, bounded response, and actuation/confirmation response honesty.
- [ ] Add `GET /api/house/state` and narrow action/confirmation endpoints in the domain router;
  mount via `web.py` only.
- [ ] Add browser state/rooms/devices/presence panel and governed controls that distinguish
  queued/denied/unverified/verified results.
- [ ] Add mobile read parity and approval handoff; never put security-device strong confirmation
  behind a weak one-tap mobile control.
- [ ] Update HUD/mobile parity, regenerate OpenAPI TS, run backend/frontend/mobile gates, review,
  and commit.

## Task 6 — H30.6 room-aware voice/media and controlled wave-3 unpark

**Modify:** narrow `voice/wyoming.py`, `satellite_hub.py`, H29 target resolver, park policy and
focused tests. Avoid `node_mesh`/`e2e_sync` unless a proven requirement appears.

- [ ] Red tests proving authenticated satellite identity maps to one configured room, spoofed or
  unknown ids do not select a target, ambiguity refuses, privacy context is respected, and no
  device call occurs before the H29 action rail.
- [ ] Carry satellite id through the voice event contract and resolve room server-side. Resolve
  the room's unique default output device through Media Director.
- [ ] Keep voice/satellite host dependencies default-off and local-only.
- [ ] Add reality cases for room routing and fail-closed unknown/ambiguous identity.
- [ ] Graduate only wave-3 entries actually proven live; keep unused entries parked until H33 or a
  later justified slice.
- [ ] Run voice/media/park-guard tests, review, and commit.

## Task 7 — H30.7 simulator, reality pack, truth sync, and PR

**Create:** hermetic HA simulator/reality tests; modify canonical reality harness and final truth
files only now.

- [ ] Prove adapter read/reconnect, graph projection, presence, privacy purge, reversible action,
  strong confirmation floor, kernel halt, verification/rollback, room output, offline HA, and zero
  ungoverned actions.
- [ ] Add optional live probe behind explicit owner environment variables; absence is a named
  skip/degraded state, not a pass.
- [ ] Run all H30 plus H27-H29 adjacency, route/OpenAPI/auth/HUD parity, full frontend/mobile,
  full Python, Ruff/Bandit/diff-check/status-sync.
- [ ] Fresh final review; resolve every Critical/Important finding with TDD.
- [ ] Mark H30.1-H30.7 complete with exact hermetic versus live evidence, update generated status,
  commit, push draft PR, monitor CI, merge, then rebase H31/H33 work.
