# H517 declarative local image provider slice

Generated 2026-09-27. Goal: register a compatible third-party image service
without editing core and use it through the real approved image workflow.
Base/head: bd2bb70ead1b493043a335e77713fc42c47d4013 plus preserved local work.
Next action: implement Tasks 1–3 and verify integration. This is partial H517.

## Design and global constraints

Ruling: use a data-only protocol registry for this first production slice,
superseding the installed-Python proposal in h517-provider-registration-design.md.
No executable plugin loading, host-code acknowledgment system or extension network
permission is necessary for services speaking a supported wire protocol. This
provides a useful register-without-core-edit path now; arbitrary request builders
and other media kinds remain work, not equivalent functionality.

Local work only, no commit/push/merge/deploy, live network/provider or paid calls.
Preserve dirty state. No subdelegation; two Sol High implementers, distinct files.
Keep socket and timeout guards. Use focused failing regressions then implementation
and existing suites. One serial full backend milestone run after integration.

Config contract: existing ComfyUI environment and aliases remain unchanged.
Add `JARVIS_LOCAL_IMAGE_PROVIDERS`, bounded JSON object (8192 bytes, at most 8
entries), mapping IDs to exactly `{protocol,url,models}`. Protocol initially
`openai_images`; ID pattern `[a-z][a-z0-9_-]{0,31}`. Reject duplicate JSON keys,
collisions with configured ComfyUI aliases, reserved `comfyui`/`openai`, unknown
fields/protocols. Models are unique nonempty lists (1–32), each a printable model
ID matching `[A-Za-z0-9][A-Za-z0-9_./:-]{0,172}`; models are JSON strings, never
paths. URLs accept only HTTP literal 127.0.0.1 or [::1] with an explicit port,
no credentials, query, fragment or path except `/`. No DNS, redirects or proxy.
`JARVIS_LOCAL_IMAGE_DEFAULT_BACKEND` defaults to `comfyui`. Configured providers
can work with no ComfyUI checkpoint when an explicit default is selected.
`JARVIS_LOCAL_IMAGE_GENERATION` remains the master default-off flag.

Production seam: `agents/core/media_backends/registry.py` owns `resolve_config`,
`normalize_options(prompt, options, config)` and pure `configuration_status`.
`LocalImageRuntime` selects a ComfyUIConfig or LocalOpenAIImageConfig. Existing
ComfyUI monkeypatch seam and approval semantics stay compatible. Provider config
fingerprint binds effective endpoint/model/root/protocol/limits and actual loaded
implementation/registry source bytes. Configuration/code drift refuses queued
authority; unchanged restart preserves stable fingerprints.

For openai_images, accept prompt, backend, model, width/height (default 512,
64..1024 multiples of 64). Refuse seed, steps, edit/references/strength/upscale
explicitly, never silently drop them or manufacture a seed. One POST to
`/v1/images/generations` with exactly model,prompt,size,n=1,response_format=b64_json.
No auth/header from config or arguments. One bounded JSON response containing
exactly one data item with b64_json; reject URLs, malformed/duplicate JSON,
non-identity content encoding, redirects, invalid/oversize base64 or PNG, and
dimensions inconsistent with requested canvas. Bound whole operation (120s),
response bytes (24 MiB) and decoded PNG (16 MiB). No retries of uncertain POSTs.
Core atomically saves validated PNG by opaque UUID, never a service-supplied path.
Reuse/extract existing validated artifact writer without changing ComfyUI behavior.
Fresh runtime/config/approval/kernel checks immediately before physical send and
publication. Consume existing durable attempt once before transport, never again
for rechecks. Revocation during response prevents artifact publication.

Status stays metadata-only (`reachable: null`). Each backend row has id, models,
protocol (`comfyui` or `openai_images`), edit, max_references, upscale; root backend
names the configured default and root capabilities describe that default. HUD
uses selected-backend capabilities, not assumptions that every backend is ComfyUI.
No new routes or body fields. Native mobile controls remain separate work.

Rollback: revert only this slice's localized source/test/docs changes; disable
the master image flag or remove new provider config. Keep existing artifact and
approval records. Source changes intentionally invalidate pending approvals.

Ruling after bounded review: the existing image attempt writer must synchronize
directory entries as well as file bytes before allowing a POST. A strict local
helper will sync the containing directory and ancestors, retain markers on any
failure and refuse dispatch when directory durability is unavailable. This fixes
a shared image-approval crash boundary. Cost: platforms/filesystems without this
primitive require a separately verified equivalent and will refuse generation;
Windows durability is not inferred from successful POSIX tests. Tests can verify
OS call ordering/failure behavior, not certify storage hardware under power loss.

## Task 1: Backend, registry and governed runtime

Read Design and global constraints above (copied into the task brief).
Own only `agents/core/media_backends/registry.py`,
`agents/core/media_backends/local_openai_image.py`,
`agents/core/media_backends/comfyui.py`,
`agents/core/image_generation_runtime.py`, and
`tests/test_h517_local_provider.py`.
Implement the exact configuration/protocol/authority contract above. Add focused
RED→GREEN unit regressions for parsing, normalization, valid transport/artifact,
invalid endpoint/output/size, status purity, source drift and pre-send/publication
guards. Existing ComfyUI runtime/transport tests must pass. Report exact commands,
counts and concerns in `/tmp/h517-task-1-report.md`; no full suite or records edits.
Coordinate the stable `LocalOpenAIImageBackend(config, transport=...)` test seam
with Task 2; runtime imports that class alongside ComfyUIBackend.

## Task 2: Independent production integration tests

Read Design and global constraints above (copied into the task brief).
Own only `tests/test_h517_provider_integration.py`. Use real coordinator/kernel,
TaskQueue, worker and HTTP route with a MockTransport substituted solely at
`image_generation_runtime.LocalOpenAIImageBackend`. Mirror existing local image
fixtures without editing them. Build matching requested-size PNG fixtures locally.
Exercise proposal with zero I/O, human acceptance, one POST, canonical artifact
and gallery/HTTP readback; revoked/changed config zero I/O; changed config during
response zero artifact; malformed response leaves consumed uncertain attempt;
replay/restart, unsupported edits/options and pure status. Do not weaken assertions
to fit implementation. Run a RED baseline then final focused suite after Task 1
is ready. Report `/tmp/h517-task-2-report.md`; no full suite or shared docs edits.

## Task 3: HUD, review and milestone (coordinator)

Own `frontend/src/api/images.ts`, `frontend/src/panels/images.tsx`, their focused
tests and generated frontend build output. Show protocol/model choices and hide
unsupported edit/upscale controls. Reset obsolete selection state on backend
change. Test switching from edited ComfyUI to generate-only provider and exact
submitted payload, plus general model parsing and honest default capabilities.
Review final source/authority diff independently, run focused/frontend/full backend
suites, scan touched source, refresh scoped Graft, and update only actually
reviewed Hermes records, evidence and status counts. No H517 equivalence claim.
