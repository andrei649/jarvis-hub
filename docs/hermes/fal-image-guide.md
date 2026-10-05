# FAL images in Nerva

FAL uses the existing signed cloud image approval, durable single-attempt marker,
bounded network client and opaque local artifact/catalog completion. The separate
`cloud-image-fal` plugin is disabled by default; it needs owner configuration and
`FAL_KEY` in the server environment. This sprint enabled no provider or credential.
`GET /api/media` exposes configured status and catalog IDs without a network probe.

The registered `image_generate` tool and authenticated `POST /api/media/generate`
accept `cloud=true, backend=fal`, a prompt, catalog model and optional size, seed,
steps or references. Local defaults are unchanged. Size maps the existing square,
landscape and portrait choices to each model's native field. Seed/steps work only
where the selected catalog model supports them. References are explicit HTTPS
`fal.media` or subdomain URLs, within the model cap (at most 16); local artifact
IDs cannot silently become uploads. A missing or disabled credential refuses a
proposal before enqueue or dial. Every accepted proposal still needs approval.

Catalog and payload rules are reused from Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. The frozen inventory describes 21
models; the pinned donor source actually contains 25. All 25 rows are retained.
Only Python 3.12 typing/import style was adapted; catalog values compare equal to
that source. Existing MIT attribution is retained in
`docs/hermes/licenses/hermes-code-execution-MIT.txt`.

Transport deliberately uses the documented direct synchronous FAL API instead of
the donor queue SDK, with a 180-second request deadline and no automatic replay.
FAL documents the direct endpoint in its
[synchronous inference reference](https://fal.ai/docs/documentation/model-apis/inference/synchronous).
The POST includes `X-Fal-No-Retry: 1`. A timeout or uncertain response after dial
stays unknown. Downloads use only the returned permitted FAL media URL, no
credential header, no redirects, pinned public DNS, byte/dimension bounds and
pixel-only PNG re-encoding before local publication. Provider/model/input and
credential generation remain bound to approval and rechecked before dispatch.

External-message provenance is retained: the server-added `taint_source` marker
is accepted only with a true taint flag and an untrusted source label. It remains
in the signed task and the kernel approval path; it is not sent to the provider.
This fixes the prior OpenAI inbound task refusing after approval too.

Verification uses real routes, registered ToolRPC and the composed worker with
synthetic HTTP responses. No live FAL generation or paid request was made. The Images HUD now offers the FAL provider/model picker and catalog-bounded URL
references, alongside OpenAI and Codex; see [provider guide](openai-codex-image-guide.md).
Local reference uploads, asynchronous queue recovery, Clarity, the remaining
providers, native pickers and the existing ComfyUI VRAM lifecycle remain H515 work.
