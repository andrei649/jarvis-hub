# Local image generation (Hermes HA-4i)

Nerva can propose one image through the existing `image_generate` ToolRPC and
Decision Inbox. An owner must approve the exact request before the worker submits
it to a local ComfyUI instance. The feature is disabled by default. This delivery
does not install ComfyUI, start a service, download weights, enable the feature or
prove generation on the owner's GPU.

## Owner configuration

Use an already installed ComfyUI instance and a compatible checkpoint present in
its `models/checkpoints` directory. The fixed workflow uses the standard
CheckpointLoaderSimple, CLIPTextEncode, EmptyLatentImage, KSampler, VAEDecode and
SaveImage nodes. Models requiring a different workflow (for example separate
text encoders or diffusion loaders) are outside this slice. Configuration:

```dotenv
JARVIS_LOCAL_IMAGE_GENERATION=1
JARVIS_COMFYUI_URL=http://127.0.0.1:8188
JARVIS_COMFYUI_CHECKPOINT=your-checkpoint.safetensors
JARVIS_ACTION_KERNEL=1
```

The endpoint must use HTTP, a literal `127.0.0.1` or `[::1]` host and an explicit
port. DNS names, remote/LAN endpoints, credentials, paths, query strings,
fragments, proxies and redirects are refused. Checkpoint names are bounded
basenames ending in `.safetensors`; neither a request nor a model can select a
backend URL, checkpoint, workflow or output path. A loopback listener itself is
owner-managed trusted infrastructure; ComfyUI must not be configured to proxy
this fixed workflow to a remote provider.

The Action Kernel must be enabled and bound, and the active system profile must
permit heavy features. Nerva does not unload the LLM or otherwise coordinate GPU
memory in this slice. A missing/incompatible model or insufficient GPU memory is
a generation failure, never a success placeholder.

**Mediation limitation:** the current protected canonical registry does not map
`toolrpc.image_generate` (nor the other existing `toolrpc.*` queued kinds) to the
`tool.rpc` action kind. A queue configured with mediation `enforce` or `hold`
therefore refuses/holds this feature. This delivery does not change that
registry, issue its own mediation receipt or reduce the mediation mode. A
separate governed registry integration is needed for those deployments. The
hermetic approved-worker proof uses the existing default queue mediation mode.

## Propose, approve, retrieve

The existing generic model tool loop offers `image_generate` to the operator
owner under its normal profile. The loop itself remains subject to its existing
enable setting. Inbound and unattended tool profiles do not gain actuation by
default. There is no new standalone image composer in HUD V2 or mobile.

An authenticated API client can also propose the same task:

```http
POST /api/media/generate
Content-Type: application/json

{"kind":"image","prompt":"O barcă albastră pe lac","seed":7,"width":512,"height":512,"steps":20}
```

The response is HTTP 202 with `ok:false`, `reason:"approval_required"` and the
durable `task_id`; it does not mean an image exists. Approve that task in the
existing Decision Inbox. Omitting seed chooses one at proposal time. Width and
height must be 64–1024, multiples of 64; steps 1–40; seed 0–2^63−1. Batch size is
one, sampler Euler, scheduler normal, CFG 7 and denoise 1. Prompt length is
1–4000 characters. Thumbnail, video and cloud generation are not implemented by
this backend; the pre-existing cloud queue behavior is unchanged.

The completed task result contains an opaque artifact ID and a relative URL
`/api/media/generated/{artifact_id}`. That endpoint uses the existing user guard,
serves validated PNG bytes with `no-store` and `nosniff`, and accepts no host
path. Artifacts live in `media/generated` under the configured Nerva data root
(`JARVIS_HOME` and the existing data-path resolution). The optional media catalog
still requires `JARVIS_MEDIA_CATALOG`; without it no catalog prompt history is
added. The approval queue itself necessarily stores the proposed prompt.

`GET /api/media` reports `local_image.configured` and `reachable:null`. It reads
configuration only; it does not probe ComfyUI or claim model/GPU readiness.

## Approval and failure behavior

The server records the proposal's task ID, complete payload, origin, risk tier,
agent and backend/runtime fingerprint before returning the task ID. Execution
requires the exact human-approved running row and a second Action Kernel check.
DENY, an absent/invalid verdict, missing proof or an exception refuses execution.
As with FileTools, QUEUE can proceed only because that exact durable human
approval already exists; the verdict is not rewritten and risk, taint and
inbound origin are retained. Editing request bytes or changing backend settings
requires a new proposal and approval. Source changes require a restart, and old
backend bindings no longer authorize the new code.

Before the single POST, an exclusively created, flushed attempt record in
`media/image_approvals` consumes the approval. It doubles as durable pre-effect
audit and prevents concurrent calls or a process restart from resubmitting.
Missing/unwritable records fail closed. Do not delete these records to retry a
task: create and approve a new proposal after reconciling ComfyUI's job history.

The runtime allows 120 seconds total, with bounded individual requests and
response sizes. It never retries submission. After timeout, cancellation, a
lost response or a crash, ComfyUI may still finish its job; Nerva preserves the
consumed marker and reports uncertainty. It does not call ComfyUI's global
interrupt endpoint, which could cancel someone else's work. Finished artifacts
that were not retrieved by Nerva need owner reconciliation in ComfyUI.

History/JSON is bounded to 1 MiB, image bytes to 16 MiB. HTTP compression is
refused. PNG framing, CRC, bounded pixel decompression, dimensions and scanlines
are checked. This first backend accepts standard noninterlaced 8-bit grayscale,
RGB and alpha variants, including uncompressed metadata for Romanian prompts;
palette/interlaced/animated PNG and compressed metadata are refused. Output is
staged, flushed and published without replacement through an atomic hard link;
filesystems without hard-link support fail closed. Existing artifacts are never
overwritten on an ID collision.

## Verification and rollback

Focused tests use a mocked HTTP transport with the real ComfyUI protocol, queue,
worker, Action Kernel, approval and user-guard routes. They exercise negative
authority changes, concurrent/restarted execution, timeout/cancellation, hostile
response paths, redirects, compression, invalid/oversized PNG and write errors.
No real image was generated in this delivery: the owner's default loopback
ComfyUI endpoint was unavailable during the earlier read-only readiness probe.

Unset `JARVIS_LOCAL_IMAGE_GENERATION` to stop new proposals/execution, or revert
the single delivery PR. Existing generated files remain readable through the
guarded endpoint while it is installed. Preserve approval/attempt records when
restoring or migrating the queue; they are part of its replay protection.
