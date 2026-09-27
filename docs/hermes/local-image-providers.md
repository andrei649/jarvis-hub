# Register a compatible local image service

Nerva can register a local service speaking its supported `openai_images` subset
without editing core code. This is configuration, not Python plugin installation.
The service must already be installed separately and listening on the same host.
No service is installed, started or probed by reading status.

Configure the hub process environment (the example values are placeholders):

```sh
JARVIS_LOCAL_IMAGE_GENERATION=1
JARVIS_LOCAL_IMAGE_DEFAULT_BACKEND=studio
JARVIS_LOCAL_IMAGE_PROVIDERS='{"studio":{"protocol":"openai_images","url":"http://127.0.0.1:8765","models":["studio/image-v1"]}}'
```

The image feature also requires the existing Action Kernel and a system profile
allowing heavy features. Existing ComfyUI configuration and backend aliases remain
supported. Selecting a compatible provider as the explicit default does not require
a ComfyUI checkpoint. Provider IDs must not collide with ComfyUI aliases or the
reserved `comfyui`/`openai` IDs. At most eight new providers and 32 model IDs per
provider may be configured, within an 8192-byte JSON document.

Use **Console → Build → Images**, select a backend/model, write a prompt and
propose one image. Approve its exact request in the existing Decision Inbox.
The worker sends one request and stores a validated PNG under an opaque artifact
ID. The Images panel supports preview/download; the opt-in media catalog exposes
the same file in the gallery. Status says connection untested until a request is
actually executed; configured is not a successful service check.

## Wire contract

Only HTTP literal loopback addresses `127.0.0.1` or `[::1]` with an explicit port
are accepted. Do not include `/v1` in the configured URL. Authentication, proxy
environment variables, arbitrary URL paths, redirects and returned image URLs
are not supported by this local protocol. The hub does not send API keys.

One `POST /v1/images/generations` contains:

```json
{"model":"studio/image-v1","prompt":"A blue boat","size":"512x512","n":1,"response_format":"b64_json"}
```

The service returns JSON with one `data` item containing `b64_json`: a base64 PNG
matching the requested dimensions. No follow-up URL is fetched. Responses are
bounded to 24 MiB JSON and 16 MiB PNG with a 120-second operation deadline.
Width and height default to 512; each must be a multiple of 64 from 64 to 1024.
Seed, step count, references, editing, strength and upscale are refused for this
protocol. ComfyUI retains its existing edit/upscale capabilities; the HUD adapts
controls to the selected backend.

Changed endpoint/model/implementation invalidates old proposals. Removing the
provider or disabling the master flag refuses later dispatch; a change while
the response is pending prevents publication. An uncertain request consumes its
attempt and is never automatically retried. Check the task before submitting a
separate proposal.

Approval records require successful file and directory synchronization before
dispatch. A filesystem that cannot provide directory synchronization refuses
generation; there is no best-effort fallback for attempt authority. The local
verification covers POSIX behavior. Windows needs a separately verified native
durability implementation before this guarantee can be claimed there.

## Current limits

This is partial H517: a finite local image protocol, not arbitrary executable
adapters or a shared video/TTS/STT registry. Offline tests exercise the real
approval/worker/artifact path with a simulated HTTP service; compatibility with a
particular installed service must be checked separately. No live provider or GPU
acceptance, remote service support or native mobile image controls is claimed.
