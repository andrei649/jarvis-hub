# OpenAI, Codex OAuth and image provider selection

The registered `image_generate` tool, authenticated media API and Images HUD offer
OpenAI, Codex OAuth and FAL through the existing signed image approval and worker.
Local generation remains the default. No provider was activated, credential
imported or paid/live request made by this batch.

## Models and proposals

Use `cloud=true`, `backend=openai|openai-codex|fal`, an offered `model`, prompt
and one of `1024x1024`, `1536x1024`, `1024x1536` for `size`. OpenAI's existing
`gpt-image-1.5` default and low/medium/high `quality` controls remain compatible.
The `gpt-image-2-low`, `gpt-image-2-medium`, `gpt-image-2-high` model IDs derive
wire model `gpt-image-2` and quality from the selected tier. Supplying a separate
quality for those tiers is refused. Codex offers these three Image2 tiers only.
FAL uses its pinned model catalog, with no OpenAI quality control.

For Image2 edits, `references` is a list of up to 16 opaque IDs for generated PNG
artifacts already saved on this hub. The approval binds their content hashes.
The worker resolves those files again, bounds aggregate upload to 64 MiB and
checks the actual upload bytes against the approved hashes. OpenAI edits use
native multipart `images/edits`; Codex edits reuse the donor's native JSON image
inputs. File paths and arbitrary external URLs are not accepted as artifact IDs.
FAL edits instead accept explicit permitted media URLs within the selected
model's cap; see [FAL guide](fal-image-guide.md). No local artifact upload to FAL
is implied.

Each proposal requires approval in the Decision Inbox, which displays provider,
model, size, prompt and edit references and links back to the saved task. A
changed request needs a new proposal. Generated PNGs use the same authenticated
preview/download and optional local gallery as existing images. An ambiguous
submission is never retried automatically.

## Configuration and OAuth boundary

`GET /api/media` retains legacy OpenAI fields and adds an unprobed `providers`
catalog with enabled/configured flags and per-model edit/reference metadata.
Disabled or incomplete providers remain visible in the HUD but cannot submit.
Missing edit metadata never implies editing support. Once a catalog has been
offered, losing the selected provider after refresh blocks submission until the
owner explicitly selects an available one; it cannot switch to OpenAI silently.

OpenAI uses the existing `cloud-image` plugin and `OPENAI_API_KEY`. FAL uses its
separate default-off plugin. Codex uses a distinct default-off `cloud-image-codex`
plugin and an explicitly selected owner credential source. The default source
requires `NERVA_CODEX_IMAGE_OAUTH_ENABLED=1`,
`NERVA_CODEX_IMAGE_OAUTH_TOKEN`, and
`NERVA_CODEX_IMAGE_OAUTH_BASE_URL=https://chatgpt.com/backend-api/codex`.
An injected source must return the token and base together. The local resolver
requires the account ID and unexpired expiry field from the token; it does not
mint or refresh tokens. The remote service would perform authentication.

The source is never discovered from Hermes, Nous or another user's credential
files. Only the fixed official Codex base may receive that token. Account and
optional residency headers follow the pinned donor; credentials do not enter
task, gallery or response metadata. Credential rotation/expiry, plugin disable,
changed references or revoked execution authorization prevent dispatch. The
single native Codex attempt has a 300-second deadline; existing OpenAI/FAL
deadlines remain 180 seconds. No Responses API fallback was introduced.

Nerva still needs a product-managed Codex sign-in and refresh flow. Configuring
an existing valid credential is a working adapter seam, not proof that Nerva
manages OAuth sessions or that the live subscription supports these endpoints.

## Reuse and remaining scope

Payloads and tier definitions adapt Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`plugins/image_gen/_common.py`, `openai/__init__.py` and
`openai-codex/__init__.py`. Existing MIT attribution is retained. Verification
uses the actual routes, registered tool and composed worker with synthetic
provider responses, plus rendered HUD tests using the real API adapter.
Results and source hashes are in
[the batch evidence](evidence/2026-10-06-openai-codex-images/report.json).

H515 remains partial: Krea, OpenRouter dedicated images, xAI, DeepInfra images,
managed Nous FAL, Clarity, FAL artifact uploads, managed OAuth, native-mobile
interaction and the existing local VRAM/governance requirements remain open.
