# H30-H33 AI-OS Program Design

**Date:** 2026-07-13  
**Scope approved by owner:** finish H30, H31, H32, and H33 autonomously after H28/H29.

## Outcome

Deliver four composable, governed subsystems rather than four silos:

1. **House Brain (H30)** owns a strict-local model of rooms, devices, occupants, presence, and
   Home Assistant actuation.
2. **Camera Intelligence (H31)** turns privacy-filtered local Frigate events into bounded sensor
   events and temporal retrieval; it never becomes an NVR or a continuous VLM stream.
3. **Capability Acquisition (H32)** closes the explicit capability-miss → reuse/research →
   quarantine → isolated verification → approval → registry → rollback loop.
4. **Ambient Intelligence (H33)** consumes typed house/camera/digital events through declarative
   monitors and the six-rung decision ladder.

## Program invariants

- All four subsystems have independent master flags and remain default-off. Product posture does
  not silently enable them.
- Family, occupant, room, camera, and presence data are strict-local. Raw frames, audio,
  credentials, arbitrary source payloads, and private addresses never enter prompts, logs, KG
  facts, HUD responses, or cloud routes.
- H30/H31 are typed producers and do not import H33. H33 owns adapters into a bounded common event
  contract.
- Every side effect is re-authorized at execution time through the existing Action API and
  kernel; prior approval, earned confidence, ambient policy, and signing cannot bypass it.
- Locks, doors, alarms, security, money, and irreversible actions have a permanent strong-
  confirmation floor. They never earn silent autonomy.
- `training/` and `rust/` stay frozen and owner-only.
- Hardware/network integrations have hermetic simulators and honest disabled/degraded states.
  Hermetic proof may graduate code from the park policy only when it exercises the real execution
  seam, kernel, and zero-bypass assertions. Owner-hardware proof remains a separate operational
  gate and is never faked by a test double.

## Shared event boundary

H30 and H31 publish strict dataclasses/protocols. H33 normalizes them into:

```text
AmbientEvent {
  event_id, source_kind, source_id, occurred_at, observed_at,
  subject_id?, room_id?, event_type, previous_state?, current_state?,
  severity, confidence, correlation_key, dedupe_key,
  provenance {adapter, source_event_id, trust, taint},
  privacy {classification, consent_version, redactions},
  attributes  # schema-specific allowlist, bounded
}
```

No executable expression or arbitrary source dictionary is accepted. Idempotency keys and
observed/event timestamps are mandatory so restarts and reconnects do not duplicate actions.

## Dependency order

```text
H28 operator rail
  -> H29 media fabric
      -> H30.1 HA adapter
          -> H30.2 house graph -> H30.3 presence -> H30.5 surfaces
          -> H30.4 actuation -> H30.7 reality
          -> H30.6 room-aware voice/media
      -> H31.1 privacy -> H31.2 Frigate -> H31.3 detection/rules
          -> H31.4 index -> H31.5 retrieval -> typed camera-event producer sink
      -> H33.1 monitor core (consumes H30/H31 typed events) -> H31.6 integration complete
          -> H33.2 ladder/K3 -> H33.3 situation memory
          -> H33.4 reality -> H33.5 night metrics -> H33.6 surfaces

H32 isolation preflight -> H32.1 request plane -> H32.2 reuse -> H32.3 research -> H32.4 quarantine/test
  -> H32.5 approval/install + rollback floor -> H32.6 ledger -> H32.7 S2 proof
```

H32 is functionally independent of the physical-world chain, but begins only after H28 runtime
and H29 registry/reality changes merge to avoid touching the same ToolRPC, registry, snapshot,
and orchestrator seams concurrently.

The H32 isolation preflight must find a genuine Docker or WASM backend before implementation is
allowed to claim an end-to-end acquisition proof. A mock exercises contracts but does not satisfy
H32.4/H32.7 completion.

## H30 architecture

- A dependency-lazy Home Assistant REST/WebSocket adapter normalizes entity/area/state events,
  redacts secrets, reconnects with bounded backoff, and emits typed `HouseEvent` values.
- A house projection service owns a private authenticated bi-temporal store for occupant,
  presence, and privacy facts. Only non-sensitive room/device topology may be mirrored into the
  generic KG. This prevents the existing generic KG reads from exposing personal house state and
  prevents deleted occupant facts from being resurrected by history or replay.
- Presence inference consumes allowlisted sensor evidence locally, records confidence and
  freshness, and refuses identity/room claims when evidence is ambiguous or stale.
- A governed actuation broker maps narrow intent to allowlisted HA services through one durable
  lifecycle: request -> governed TaskQueue intake -> policy decision -> registered TaskExecutor
  handler -> fresh state/confirmation -> Action API/kernel -> HA driver -> verification/rollback.
  New or low-confidence reversible device actions remain blocked for approval; bounded
  lights/climate actions may earn auto-approval only through H27.7 evidence. Security-sensitive
  actions are always forced blocked and require a
  server-minted, admin-confirmed, short-lived, scope-bound, single-use strong-confirmation
  challenge consumed at execution time. No autonomous tool can mint or answer that challenge.
- Room-aware voice carries a paired, replay-protected satellite identity across an authenticated
  local transport to a server-owned room mapping, then resolves the H29 output device. It never
  accepts a caller-provided room or configured-but-unverified satellite id as authority.

## H31 architecture

- Integrate Frigate's authenticated event/snapshot surface rather than building an RTSP decoder,
  NVR, or detector. Optional ONVIF is discovery/onboarding only.
- The privacy rail executes before persistence, local VLM, API, or event publication: versioned
  consent, per-camera kill, masks/zones, face-recognition off by default, no cloud/Frigate+.
- Store metadata in a dedicated encrypted camera event vault with bounded retention. Store
  snapshots only when policy permits and for at most 24 hours; default metadata retention is 30
  days. Continuous clips stay off.
- Local VLM description is event-triggered and on-demand only. Detection remains Frigate's local
  structured events plus deterministic zone/line rules.
- Retrieval searches normalized event metadata first, then returns consent-filtered evidence. It
  never searches raw video through an LLM.
- A typed camera-event producer sink lands before integration. H31.6 closes only after the House
  Brain consumes privacy-filtered anonymous occupancy/sensor state and H33.1 consumes the same
  typed sink. Cameras never write house KG or ambient internals directly.
- Situation memory may correlate repeated anonymous observations by place/time, but cannot claim
  they are the same person. Re-identification remains absent unless a future separately approved,
  strict-local, consent-gated capability is designed and reviewed.

## H32 architecture

- Capture only explicit bounded tool/capability misses. A stable goal fingerprint deduplicates a
  durable runtime request; normal unanswered conversation is not a gap.
- Search live registry, installed local skills, and reviewed marketplace packages before any
  network or generation work. Measure terminal reuse versus generated resolutions.
- Governed research retains taint, URL/source hashes, injection results, and a non-empty fully
  grounded implementation plan. No implicit DuckDuckGo fallback.
- Generate into a runtime quarantine directory, never repository `skills/`. Require a shipped
  verification test and Docker/WASM isolation; host subprocess and disabled sandboxes fail.
- A hash-bound receipt ties sources, plan, code, tests, backend, output, and result. Promotion
  rechecks every hash, then follows kernel approval, signing, reviewed marketplace installation,
  sandbox-bound ToolRPC execution, low-confidence registry entry, and immediate revoke/uninstall.
- Promotion uses a managed-key canonical manifest covering every package member and a dedicated
  non-root, capability-dropped, digest-pinned hostile-code sandbox profile.
- Acquired packages install into a runtime store outside repository `skills/`, carry persistent
  `execution_mode=acquired_sandbox`, and execute only through a ToolRPC sandbox runner. The normal
  SkillLoader must never import them. Signing proves integrity/provenance, not safety.

## H33 architecture

- A new additive `agents/core/ambient/` package owns bounded contracts, SQLite state, monitor
  registry, engine, health, debounce/hysteresis, backpressure, and decision journal.
- Monitor definitions contain only a constrained schema: stable identity, feed, enabled state,
  match/clear predicates from an allowlist, hold/cooldown, privacy scope, severity mapping, and
  ladder rules. No Python/eval.
- Ladder semantics:
  - `ignore`: count decision only; retain no event content.
  - `remember`: persist a sanitized situation fact with provenance/decay; no notification.
  - `monitor`: update durable monitor state and wait.
  - `act_silently`: reversible allowlisted capability only, kernel + verification + rollback.
  - `ask`: Decision Inbox/digest item; no unsolicited push.
  - `interrupt`: blocked item plus immediate push through one durable atomic global K3 budget;
    exhaustion/quiet hours downgrade to `ask`, never drop or auto-act.
- Quiet-hours and night-shift metrics count verified ambient results by rung; no-op work does not
  count as productive overnight work.
- Existing observer/watchers are adapted into named digital monitors or explicitly disabled when
  the ambient engine is enabled. They never run as a second task/push producer alongside an
  equivalent H33 monitor.

## Program delivery strategy

- One horizon branch/PR at a time, with smaller logical commits and fresh review per task.
- Rebase-first at each horizon and before shared integration commits.
- Additive packages carry most implementation; serialize `orchestrator.py`, ToolRPC, registry,
  reality harness, route/OpenAPI/auth snapshots, `gap.tsx`, parity ledgers, and truth files.
- H30/H31 may publish their event types before H33 exists; H31.6 closes only when H33.1 consumes
  the camera sink.
- Each horizon ends with focused reality cases, full cross-horizon tests, browser/mobile parity,
  code-health checks on touched files, a draft PR, CI monitoring, and merge before the next
  dependent horizon rebases.

## Program completion evidence

The program is complete only when:

- H30's simulator proves read, projection, presence, actuation, strong-confirmation, rollback,
  room routing, and fail-closed HA loss.
- H31 proves privacy-before-frame, masks/retention, local event handling, retrieval, and zero raw
  frame leakage across API/log/KG/event boundaries.
- H32 proves one net-new capability end to end, refuses every missing gate, immediately revokes,
  and reuses the installed capability on the second request.
- H33 proves 1/10/100-monitor bounded behavior, persistent interrupt allowance across restart,
  ask/interrupt separation, taint containment, kill-switch, hard floors, and honest HUD/mobile
  transparency.
- The full repository, frontend, and mobile suites pass after all merges.
