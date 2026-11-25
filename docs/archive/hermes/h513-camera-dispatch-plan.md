# H513 camera description dispatch (next local slice)

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus local sprint changes. Goal: bind the existing camera inference path to a
separate audited role and the actual native request. Next action: implement after
the Telegram milestone is frozen and its full verification is recorded.

## Verified architecture and decisions

CameraRuntime reads one global camera VLM configuration via orch.get_setting.
The orchestrator refreshes its runtime settings map periodically, but the camera
runtime is cached by orchestrator identity. Therefore a fresh posture descriptor
alone cannot authorize a stale bound camera client: compare the runtime snapshot
with live configuration at every dispatch and refuse until rebuilt when changed.
Do not silently replace the running pipeline or weaken household consent/privacy.

The current endpoint is a custom OpenAI-compatible endpoint with an empty API key.
Its declared policy stays unknown even on loopback. No new provider selector or
unsubstantiated no-training claim. Preserve exact local endpoint validation,
masked PNG limits, anonymous bounded output, kill switch and privacy leases.

The native standalone screen-locator builder has no production caller: default
desktop construction passes no locator. Do not spend this slice hardening or
claiming live functionality for that unwired library seam.

## Shared interfaces

Add the closed role ID role:camera_descriptions, label Camera descriptions,
mode dedicated, to the existing role store and Trust target rendering. Preserve
all existing judge/media scope material and acknowledgment behavior. Scope binds
the normalized camera configuration and effective native wire/policy identity.
The descriptor is pure: never build camera runtime, open storage/source clients,
probe devices or resolve private frames while rendering posture or granting consent.

Pass explicit optional orchestrator context through posture/acknowledge and their
role resolver; existing callers without it retain existing behavior and cannot
resolve a camera target. Camera configuration uses one shared pure resolver for
runtime and descriptor. Omit unavailable/disabled camera targets; acknowledgment
never enables cameras, event descriptions, remote destinations or household consent.
Audit re-resolves the same context after its blocking write before committing.

A native camera request must authorize only its own role. Factor the existing
unattended native vision scope with an explicit target descriptor/notice purpose,
without fabricating a web principal or borrowing grants. Recheck live selection,
configuration, consent and effective URL/model/auth/native route before each send
and retry; discard stale results through awaited cleanup. Own and close clients
explicitly, including entry refusals. Pure injected callback libraries remain
separate; production native wiring must exercise the real scope in offline tests.

Live disabling of camera/VLM/event-description eligibility must stop inference.
Keep household capture authorization separately enforced by the privacy pipeline;
this role does not attest or replace the household consent system. Configuration
mismatch refuses boundedly rather than restarting a cached runtime automatically.

## Ownership, tests and delivery

Backend writer owns cameras/vlm.py, cameras/runtime.py, llm/vision_policy.py,
llm/data_handling.py, routers/security.py, a focused H513 camera test module and
narrowly affected camera fixtures declared before editing. The backend writer also
owns the narrow pipeline change that threads the original household privacy lease
check into physical dispatch; a new lease must never replace the original one.
Frontend writer owns
panels/data-handling.tsx and its governance-posture tests only. Coordinator handles
API schema/build, integration review, manual/native gaps and truthful records.

RED/GREEN cases: pure secretless status, independent finite grant/revoke, failed
or racing audit, native actual dispatch, stale cached runtime configuration,
disabling/revocation before physical request and during cleanup, proxy/selector
substitution, output sanitation, exact local endpoint validation, closed owned
clients, preserved household lease checks and old judge/media behavior. Run
focused regressions before serial full milestone suites. No live cameras/model
providers, publication, paid calls or unrelated settings changes.

## Explicit remaining provisioning gap

Camera settings are absent from settings_db.DEFAULTS, and the standard category
write route cannot create unknown keys. This slice does not invent an undocumented
provisioning mechanism or claim the whole camera product operational. Supported
owner provisioning for the complete camera configuration is a separate H31
integration requirement, including household consent and credentials; adding only
four VLM defaults would not solve that requirement. Keep the gap in final evidence.
Native controls and real configured-camera acceptance also remain open.

Rollback only this slice's localized hunks; preserve all preceding local work.

## Reviewed fixture and lifetime decisions

Camera reality probes run inside the application process. The coordinator owns
observability/camera_reality.py and tests/test_h31_camera_reality.py: retain their
pure synthetic masking/privacy callback explicitly, label provider consent and
transport as untested there, and never grant owner consent or change global stores.
The governed production runtime rejects opaque injected provider adapters. Native
provider behavior is covered by the new isolated H513 tests instead.

Default native clients are owned per description and closed on every path. The
existing injected native runtime backend is borrowed: each call remains guarded,
but the adapter must not close that caller-owned client or break a second call.
The full Telegram milestone preceding this slice passed 19,156 backend tests with
35 skips, and 1,819 frontend tests; its evidence is an immutable prior snapshot.
