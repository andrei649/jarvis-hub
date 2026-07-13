# H31 Camera Intelligence Implementation Plan

> Execute after H30's event contracts and private house-state boundaries merge. Use
> `superpowers:subagent-driven-development`, strict TDD, and fresh review per task.

**Architecture decision:** integrate Frigate as the local NVR/detector. Jarvis does not build an
RTSP decoder, recorder, NVR, or object detector. Optional ONVIF is discovery/onboarding only.

## Non-negotiable privacy floor

- Master feature flag and versioned household consent are required before any polling or snapshot
  fetch. Frigate must resolve to loopback/LAN; the VLM must resolve to this host's loopback.
- No Frigate+, cloud camera/VLM fallback, continuous video, or Jarvis clip recording.
- Raw snapshot bytes exist only transiently between local fetch and privacy-mask transform. They
  never reach disk, logs, API, VLM, memory, audit, or event subscribers.
- Missing mask support, invalid masks, or transform failure discards the frame. Face recognition,
  identity inference, biometrics, plates, and Frigate sublabels are absent/off by construction.
- Allowed event classes are bounded to person, vehicle, animal, and package. A person event means
  anonymous occupancy, never identity.
- Masked encrypted snapshots expire in at most 24 hours; encrypted metadata in at most 30 days.
  These ceilings are mandatory even if general retention cleanup is disabled.
- Kill-switch and consent are checked before fetch and again before inference/store/publication.
- Credentials remain SecretBroker references and never appear in event fields, URLs, logs, or
  support bundles. Default browser/mobile responses are metadata-only.

## Task 1 — H31.1 privacy contract first

**Create:** `agents/core/cameras/models.py`, `agents/core/cameras/privacy.py`,
`docs/CAMERA_PRIVACY.md`, `tests/test_h31_camera_privacy.py`.

- [x] Red tests: no/mismatched consent, global/camera kill, disabled camera, invalid/missing masks,
  raw-byte fingerprint non-propagation, rejected identity/face/plate fields, TTL ceilings, and safe
  default configuration.
- [x] Implement immutable bounded camera config/consent/mask/event contracts and staged
  `CameraPrivacyPolicy` checks. `apply_masks` produces a new buffer and never exposes raw input.
- [x] Prove pixel-level coverage of every polygon and strip EXIF/GPS/embedded thumbnails by
  deterministic re-encoding. Reject out-of-bounds masks, decompression bombs, oversized pixel
  counts/dimensions, animated/malformed/truncated input, unsafe modes, decoder temp/cache files,
  and any transform that cannot prove full coverage.
- [x] Revocation first stops polling/detaches publishers, atomically advances a consent generation,
  refuses or drains stale in-flight work, then immediately logically purges camera records. Test
  revoke-during-fetch, mask, store, and publish races plus no-poll proof.
- [x] Run privacy/kill-switch/retention tests, Ruff/Bandit, review, and commit.

## Task 2 — H31.2 read-only Frigate adapter

**Create:** `agents/core/cameras/source.py`, `agents/core/cameras/frigate.py`, focused tests;
modify narrow plugin/egress manifests and lazy orchestrator wiring.

- [x] Red tests: default-off, LAN validation, bounded cursor/idempotency, timeout/backoff, list does
  not fetch snapshots, allowlisted normalization, offline health, egress/kill denial, hard
  transport-byte limits, and zero mutating Frigate requests.
- [x] Enforce an owner-allowlisted origin with bounded scheme/port, redirect refusal/revalidation,
  DNS-rebinding resistance and connection-time address pinning, and no cross-host authorization
  header forwarding. These hard checks remain active even when global strict-egress is disabled.
- [x] Stream event JSON and snapshot responses under separate hard received-byte budgets; never
  trust `Content-Length`, abort chunked overflow, and release the response, connection, and partial
  buffers on overflow/truncation/cancellation. Test missing/false length and oversized chunks.
- [x] Implement `CameraEventSource.list_events(after, limit)`. Keep raw snapshot fetch on a private
  source object owned only by the privacy pipeline: do not expose it through orchestrator, tools,
  routers, capabilities, or subscribers. Add an Agent Runtime/subscriber bypass test. Discard raw
  payload fields, credentials, paths, sublabels, faces, and plates at normalization.
- [x] Add a short ADR recording the Frigate-over-custom-RTSP/NVR spike decision.
- [ ] Add optional live local-Frigate probe as a named owner-gated check, never a fake pass.
- [x] Run HTTP/egress/security/adapter tests, review, and commit.

## Task 3 — Optional ONVIF discovery, never ingest

**Create:** `agents/core/cameras/onvif.py`, `tests/test_h31_onvif_discovery.py`.

- [x] Red tests: admin/default-off gate, lazy missing dependency, bounded results, secret references,
  stripped RTSP/passwords, LAN-only devices, deterministic duplicates, and zero stream opens.
- [x] Map discovered devices to owner-curated Frigate camera ids only; Frigate remains the sole
  event/snapshot source.
- [x] Run discovery/security tests, review, and commit.

## Task 4 — H31.3 deterministic rules and on-demand local VLM

**Create:** `agents/core/cameras/rules.py`, `pipeline.py`, `vlm.py`, focused tests.

- [x] Red tests: duplicate idempotency, deterministic zones/line crossing, outside-zone behavior,
  no VLM when metadata suffices, masked-only qualifying VLM, loopback-only VLM, safe failure, forbidden
  identity/biometric/plate output, mid-flight consent/kill, and buffer release.
- [x] Enforce order: normalize -> deterministic rules -> privacy recheck -> one snapshot fetch ->
  in-memory mask -> optional strict-local VLM -> bounded event -> release buffers.
- [x] Cap the re-encoded masked image bytes handed to the local VLM in addition to decoded pixel
  and dimension limits; oversize fails before the model call.
- [x] VLM may add non-identifying description only; deterministic event survives VLM failure.
- [x] Run VLM/local-routing/privacy tests, review, and commit.

## Task 5 — H31.4 encrypted event vault, retention, and health

**Create:** `agents/core/cameras/vault.py`, `health.py`, focused tests; extend narrow retention,
purge, scheduler, and support-bundle seams.

- [x] Red tests: ciphertext at rest, no raw/sensitive index fields, exact 24h/30d boundaries,
  scheduler delay, restart after expiry, linked/orphan cleanup, byte/item caps, tamper/corruption,
  disabled general retention, redacted health, and complete purge.
- [x] Build a strict camera-domain wrapper around the hardened core `Vault`; do not implement new
  encryption/storage. Source keys through the existing managed secret path, define rotation, and
  use tighter quotas/projections. Store metadata and optional masked snapshots as separate records
  linked by opaque internal ids; API projections never expose vault ids or paths.
- [x] Refuse expired records before decrypt/read, filter them from list/search/index, and sweep on
  startup before service, before reads/searches, and on a bounded frequent schedule. Expiry means
  immediate logical inaccessibility; physical ciphertext is removed at the next sweep. Document
  that separately retained old encrypted backups may still contain logically deleted ciphertext.
- [x] Run vault/hardening/retention/purge tests, review, and commit.

The metadata-only health projection and bounded domain scheduler are complete here. Task 6 wires
that injected runtime into the router and support-bundle surfaces; the vault is never made global.

## Task 6 — H31.5 privacy-safe temporal event retrieval, API, HUD, and mobile parity

**Create:** `agents/core/cameras/retrieval.py`, `agents/core/routers/cameras.py`, camera HUD/mobile
surfaces and tests; update route/OpenAPI/auth/type/parity artifacts.

- [x] Red tests: temporal label/zone/room/camera queries, bounded deterministic NL parsing,
  ambiguity/empty/degraded states, user/admin guards, and absence of bytes, vault ids, paths,
  RTSP URLs, credentials, or private snapshot URLs.
- [x] Add metadata-only status/events/search endpoints plus admin-only ONVIF discovery. H31 v1 has
  no raw snapshot endpoint.
- [x] HUD/mobile render time, type, camera/zone, confidence, and local-description provenance;
  tests assert no image/video element or background fetch is created.
- [x] Run backend/frontend/mobile parity and type gates, review, and commit.
- [ ] Update the H31.5 backlog text truthfully from “clip retrieval” to consent-safe temporal event
  retrieval. Jarvis does not proxy/persist clips or expose Frigate private URLs in v1.

## Task 7 — H31.6 typed feeds into H30 and H33

**Create:** `agents/core/cameras/feeds.py`, focused tests; touch orchestrator only for injected
publishers.

- [ ] Red tests: convert to shared `HouseEvent` without bytes/private ids, update only allowlisted
  anonymous occupancy/sensor facts, idempotent delivery, consent/kill recheck, metadata-only
  subscribers, and honest missing-sink health.
- [ ] Publish through an interface; cameras never import/write house KG or ambient internals.
- [ ] Give every subscriber a bounded queue, per-sink failure isolation/backpressure, delivery
  counters, and restart-safe idempotency; one broken sink cannot block or duplicate another.
- [ ] Land the producer sink after H30.2. Mark H31.6 complete only after both H30 consumption and
  H33.1 monitor consumption are proven.
- [ ] Run H30/H33 contract tests, review, and commit.

## Task 8 — H31 reality pack, truth sync, and PR

**Create:** in-process Frigate simulator and `tests/test_h31_camera_reality.py`; modify the canonical
reality registry and final truth files only now.

- [ ] Prove no-consent zero calls, bounded poll, one qualifying snapshot, mask-before-consumer,
  deterministic/on-demand local processing, encrypted storage, retrieval, 24h/30d expiry,
  stage-by-stage kill, offline degradation, typed feeds, and zero ungoverned/external/raw-frame
  actions.
- [ ] Promote camera readiness only from the full hermetic real-seam pack. Live local Frigate is a
  separately named optional probe.
- [ ] Run all H31 plus vault/privacy/H30/H33 contracts, route/OpenAPI/auth/HUD parity, full
  frontend/mobile/Python, Ruff/Bandit/diff-check/status-sync.
- [ ] Fresh final review; fix all Critical/Important findings with TDD.
- [ ] Update H31.1-H31.5 and reality evidence; close H31.6 only after H33.1 integration. Push draft
  PR, monitor CI, merge, then rebase the dependent horizon.

## Rollback

Disable the camera master flag to stop polling and detach subscribers. Explicit purge removes all
Jarvis camera data. Frigate/NVR configuration and recordings are never modified by Jarvis.
