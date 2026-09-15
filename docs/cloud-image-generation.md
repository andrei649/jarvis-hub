# Approved cloud image generation

This API increment supports one OpenAI `gpt-image-1.5` image per fresh approval. The existing Images HUD still requests local generation; cloud authoring in that UI and additional providers remain outside this increment.

Configure the existing `OPENAI_API_KEY` through the normal server environment, enable the action kernel with enforced signed task mediation, and use a profile with heavy features enabled. Missing configuration fails closed. This implementation does not provision credentials or make an automatic test request.

Send an authenticated user request to `POST /api/media/generate` with `kind: "image"`, `cloud: true`, and `prompt`. Optional `size` is `1024x1024` (default), `1536x1024`, or `1024x1536`; `quality` is `low` (default), `medium`, or `high`. An explicit `backend: "openai"` is accepted. Seeds, local dimensions, steps, edits, upscaling, additional outputs and arbitrary endpoints are rejected. The model and PNG format are fixed.

Known secrets in the exact prompt are screened through the existing broker before queue persistence and again before dispatch. A changed result or failed screening refuses the request; it never silently rewrites the approved prompt.

HTTP 202 contains `reason: "approval_required"` and a task ID; it is not an artifact success. Approve that exact task through the existing owner approval flow. The queued payload binds the prompt/options and a random configuration generation, never the API key. Changing the credential or adapter invalidates pending approval. The worker uses the existing signed one-use execution permit, rechecks authority immediately before dial, and sends a single POST without redirects or retries. This is a potentially billed operation only after approval.

The admin-guarded `GET /api/media/generation-tasks/{id}` returns the existing image task projection. A ready artifact can be read through the user-guarded generated-image route. Validated pixel data is stored under the canonical generated-media root; provider metadata is discarded. A transfer is limited to 24 MiB and 180 seconds; the validated output is limited to 16 MiB and the approved dimensions.

With `JARVIS_MEDIA_CATALOG=1`, completion adds one stable cloud catalog record, readable and exportable through the existing gallery. Catalog finalization may recover locally after interruption; it never repeats a provider call. A finalized record intentionally removed from the catalog is not recreated by polling. With catalog opt-in off at completion, no catalog prompt record is created.

A crash, cancellation, timeout or uncertain provider response after dispatch is not automatically replayed: the durable attempt marker preserves uncertainty. Queue completion alone is not proof of a usable image. A new generation requires a new explicit request and approval; do not delete attempt records to retry an ambiguous submission. Error responses omit provider exception text and response bodies.

Verification used an injected HTTP transport and isolated test storage, including actual guarded routes, signed worker approval, generated-artifact retrieval and ZIP export. No live or billed provider call was made. H515 remains partial: broader image controls/providers and cloud HUD authoring are not delivered here.
