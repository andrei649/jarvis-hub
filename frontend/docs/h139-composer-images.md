# H139 composer images implementation plan

Goal: explicitly describe owner-selected images from the shared browser composer.
Base: 3821c9c1d30d3996feebafc5244b0f8972be499c. Generated: 2026-09-15.
Head: enclosing source commit. State: browser increment verified. Next action: root integration.
Spec: frozen capability 139 (index 138), docs/research/2026-09-07-hermes-absorption-ledger.json.
Execution: inline writing-plans/TDD workflow, no additional agents; owner authorized.

Architecture: shared InputBar holds transient raster image drafts; a narrow user-
guarded composer vision route validates bounded data URIs and binds an explicitly
acknowledged status destination to one resolved backend snapshot. App owns one text
or vision turn at a time. A vision result has its own transcript type and actual
model/backend/destination provenance, without fabricated agent or plugin activity.
Existing text chat keeps its exact message/agent stream request. Existing generic
VLM URL/image APIs retain their historical compatibility; no filesystem reads added.

Verified existing seams: cockpit.tsx exports InputBar to ChatMode and cockpit;
App owns conversation/abort; apiFetchOnce supplies abortable one-attempt same-origin
transport. multimodal.py owns user-guarded status/describe. VLMBackend currently
returns a sentinel string on failure, so composer needs a checked generation method
while historical callers retain that sentinel contract. Current Console intake is
separate and will not be rewritten in this bounded increment.

## Contract and boundaries

- Choose, image paste and image drop, maximum eight files including pending reads;
  each at most 4 MiB. PNG/JPEG/GIF/WebP raster files only. Reject mismatched/invalid
  data URI encodings and MIME/signature mismatches on the server; never accept a path or remote image URL through
  the composer route. Existing Pillow validates parsed format, structural integrity
  and bounded decoding: static raster only, edge at most 8192 pixels and total at
  most 16 MiPixels. These limits allow 4K screenshots/panoramas while bounding one
  decode before allocation; the existing VLM bytes encoder subsequently downsizes
  to its 1024-pixel edge. Animated files are refused before frame decoding. No Pillow
  global limits/settings are mutated. Normal text paste remains untouched.
- Deduplicate items/files by file identity metadata within a draft. Show previews,
  pending/read errors, explicit removal; abort removed/unmounted FileReaders and
  revoke every object URL. Image bytes remain transient, never localStorage or
  automatically uploaded/stored/learned. Submission itself is explicit.
- Status is configuration truth, not a reachability probe. Display the public
  destination and actual configured model. Non-loopback requires an explicit
  destination-bound acknowledgement. Send an expected public destination and
  configuration binding; reject changes with 409 before constructing/calling a
  backend. Resolve once per POST and construct the backend from that same snapshot.
  Public destination excludes URL credentials/query/fragment; public binding is a random revision, not a credential-derived hash. One fixed
  Settings DB metadata row atomically associates a private configuration fingerprint
  (full URL/backend/model, no API key) with that random nonce. This survives worker
  boundaries/restarts and invalidates hidden URL changes without exposing a guessing
  oracle. GET may update this inert metadata, never images or agent context.
- One synchronous ownership ref prevents text/image/voice double submission before
  React rerenders. Abort/stop/context reset/unmount invalidate late vision results.
  Request failure is a structured error, not a successful '[VLM error]' transcript.
- Image turns are explicit VLM analysis, not ordinary agent chat or memory/context
  injection. No image persistence, native mobile integration, /learn seeding,
  arbitrary uploads or automatic cloud/provider configuration. H139 remains partial
  for those frozen behaviors. Browser provider traffic is intercepted in tests.

## Task 1 — bounded, destination-bound API

Files: agents/core/routers/composer_vision.py (new narrow route); agents/web.py
(router registration); agents/core/llm/vlm.py (checked generation method preserving
legacy wrapper); tests/test_composer_vision.py. GET /api/vlm/composer/status returns
configured, destination, binding, model, backend, local. POST /api/vlm/composer/describe
requires prompt, images, expected_destination, expected_binding and remote_ack.

- [x] RED: missing routes; deny absent user token; malformed/oversized/non-raster
  inputs; stale destination/model binding causes zero backend calls; remote without
  acknowledgement denied; same configuration used for checking and constructing;
  backend errors structured; successful response carries actual model provenance.
- [x] GREEN: strict fixed request schema; bounded base64/raster validation; stable random
  public configuration revision; checked model method with generic safe error body.
- [x] Verify existing VLM backend/status/describe tests retain legacy contracts.

## Task 2 — transient image intake and visible consent

Files: frontend/src/composer-images.tsx (new hook/control), cockpit.tsx InputBar,
frontend/src/test/composer-images.test.tsx. Hook provides drafts, addFiles, remove,
clear, ready images; control supplies file/paste/drop handling and status consent.

- [x] RED: choose/paste/drop, items/files duplicate, text-only paste untouched,
  eight pending reads cap, four MiB/type failures, removed reads cannot reappear,
  preview URL/read cleanup, no request merely from file intake, stale consent reset.
- [x] GREEN: reserve slots synchronously before reads; store handles in refs;
  allow submit only with ready images and current destination acknowledgement.
  Ordinary text calls onSubmit(text) exactly; image calls onSubmit(text, visionDraft).

## Task 3 — owned vision conversation turn

Files: app.tsx, cockpit.tsx Conversation, new frontend/src/vision-turn.ts as needed,
frontend/src/test/composer-vision-turn.test.tsx.

- [x] RED: real InputBar to App request; text payload unchanged; no parallel turn
  across rapid image/text/voice; explicit vision model label; structured failure;
  stop/unmount ignores late response; demo reset shares epoch invalidation; no automatic artifact/memory writes.
- [x] GREEN: shared ownership ref, abort controller and epoch checks; vision-only
  transcript branch with names and provenance, no image bytes retained in transcript.

## Task 4 — served browser and final evidence

Files: frontend/e2e/composer-images.spec.ts and dedicated Playwright config;
existing isolated server fixture can serve the real bundle with intercepted vision
provider flow; tracked agents/web/v2 output and this guide.

- [x] Desktop/phone choose/paste/drop, preview/remove, explicit remote acknowledgement,
  image request/vision reply, failed/cancelled response and normal text stream smoke.
- [x] Focused backend/frontend, both TypeScript checks, full frontend one worker,
  relevant route/asset guards, deterministic production rebuild; explicitly refresh
  scoped Graft graph without dependencies, secrets, hooks or committed cache.
- [x] Record exact tested counts and remaining scope, commit only module paths.

Rollback: revert this module and generated bundle; no persisted image schema or
provider changes to undo. The unused random-revision metadata row may remain inert. Root owns global backlog evidence, publishing and merge.

## Implementation evidence and intentional limits

Initial backend regressions failed on missing composer routes; nonce regression
failed against the unkeyed public fingerprint before replacing it with a random
revision. Intake regressions failed on absent file/paste UI; App turn regressions
failed because image submissions still entered text chat. Focused checks now pass:
27 new backend tests plus 23 legacy VLM tests; 179 affected backend/route/asset/
OpenAPI/auth tests passed. All 1,257 frontend tests passed (ten new), both TypeScript
programs and the native route manifest sync check passed. Four image-flow plus two
routing desktop/Pixel 7 browser checks passed. Two production builds matched across
all 16 files by SHA-256. The scoped Graft graph was explicitly rebuilt and checked
fresh; no hooks, deep context or generated dependencies were indexed. Browser provider/status routes
are intercepted, so this is UI/transport proof, not live model/provider proof.

Image bytes are cleared from the composer after accepted submission and never enter
conversation storage or agent memory. Transcript user entries retain image names;
completed vision entries retain answer and actual model/backend/public-destination
labels. Generic Console VLM intake remains unchanged. Missing image persistence,
native agent image context, native mobile intake and /learn seeding keep H139 partial.


Route/OpenAPI/auth snapshots were refreshed only after asserting exactly four
additions against base 3821c9c1: inherited H135 GET/PUT appearance and H139 composer
GET status/POST describe. All four classify as user-guarded; there are no removed
routes, changed prior guards or prior operationId drift. OpenAPI TypeScript was
regenerated with the existing cached 7.13.0 generator from an isolated no-lifespan
app schema. Root integration already has the H135 entries and will retain them.
The nonce stability test also launches a separate Python worker against the same
isolated metadata DB, proving the revision has no process-local signing dependency.
