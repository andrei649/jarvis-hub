# H523 media-serving contract reassessment

- Goal: verify the accepted generated/cache media delivery contract against the shared reader and gallery.
- Generated: 2026-09-15.
- Original read-boundary audit base: `91f595c3f932682516394e7199e5c28bcd9de94d`.
- Scheduled-media integration reviewed at: `6301356ef2d23515bb0285b11ee325d6a12e3cba`.
- This reassessment combines the original unchanged reader audit with the new scheduled-media implementation and independent review. Integrated full-suite verification passed before final status publication.

## Original contract and earlier review

Frozen H523, capabilities index 522 in `docs/research/2026-09-07-hermes-absorption-ledger.json`, is **“Serve a generated or cached media file back to a client”** (`copy`, row digest `a0fab30d78e84c7347418373ea736c26ee895f31fe9a9fbec2e274fab2b3dd62`). Its concrete symptom was a gallery listing paths which clients could not open. The accepted adaptation explicitly replaces Hermes's caller-supplied path with a catalog ID resolved server-side, behind `user_guard` and a bounded media root.

The original review in `docs/hermes/assessment.json` was partial: a selected generated PNG was downloadable, but a unified gallery and delivery of other generated/cache media remained. The current derived `needs_review` state also reflects changed evidence hashes. Native gallery authoring, new generation providers and recovery of deleted media are not requirements of this read boundary. However, the frozen Hermes description explicitly includes a total cron media-send deadline. The path-to-ID adaptation does not explicitly exclude that element, so proving the HTTP reader alone cannot establish full-row equivalence.

## Evidence drift inspected

The recorded versions were located by matching their stored SHA-256 values to Git history, then compared with this base:

- `agents/core/image_generation_runtime.py`, recorded at `afb07b8f40b3`: backend/model selection, multiple references and upscale options, with repeated approved-configuration binding checks. The actual local manager still receives `default_catalog_if_enabled()`.
- `agents/core/image_generation_view.py`, recorded at `e73ebee36ad5`: the safe projected option names expanded. No arbitrary host path was added to delivery.
- `agents/core/media_backends/comfyui.py`, recorded at `afb07b8f40b3`: configured backend registry and reference/upscale workflows expanded; accepted PNG dimensions increased from 1024 to 2048 per edge. `artifact_bytes` retains the opaque-ID, same-root, symlink and 16 MiB checks.
- `agents/core/routers/multimodal.py`, recorded at `afb07b8f40b3`: generation option schema and catalog pagination changed. The authenticated generated-PNG route remains; the current general reader is additionally exposed through `agents/core/routers/artifact_store.py`.

These changes were reviewed semantically, rather than refreshing hashes alone.

## Contract mapping

| Accepted behavior | Current implementation |
| --- | --- |
| Catalog entry can be opened without a caller path | `GET /api/artifacts/{artifact_id}/blob` delegates to `artifact_store.resolve_blob`. `md-` catalog IDs resolve through `media_library.read_catalog_blob`; `ba-` attachment IDs use `BinaryArtifactStore.read`; existing generated 32-hex IDs retain their PNG reader. |
| Bounded generated/cache roots | `media_library.catalog_path` requires an absolute canonical path within `data_root/media/generated` or `data_root/media/cache`, rejects symlink ancestry and rechecks paths even with metadata snapshots. `_read_bytes` requires a regular file, uses no-follow opening where available, and enforces 16 MiB before returning bytes. |
| Browser-reachable authorization boundary | The artifact router has a router-wide `Depends(user_guard)`; the generated-PNG route also has `user_guard`. Attachment operations honor the attachment switch. The catalog flag controls recording/listing/export; it is not treated here as a credential or a guarantee that existing generated IDs become unreadable when recording is disabled. |
| Correct delivery rather than exposed host paths | Responses contain bytes with detected MIME, `nosniff`, `no-store` and safe ID-derived disposition filenames. Images are inline; other supported media are attachments. The shared blob response adds a restrictive CSP. Unknown/unsafe/missing IDs fail without returning paths. |
| More than the selected PNG | `sniff` supports PNG, JPEG, GIF, WebP, PDF, WAV, Ogg, MPEG audio, MP4 and WebM. The same catalog reader applies it to generated/cache bytes, not just uploads. |
| Unified gallery access | `MediaGalleryPanel` in `frontend/src/gap.tsx` and `frontend/src/media-gallery.ts` traverse retained generated/attachment metadata with bounded search pages. Available items render `BinaryCard`; unavailable items are labeled. Preview is explicit, authenticated and abortable; image/audio/video presentation and individual download use the fetched object URL. Other formats remain downloadable. |
| Inbound attachment cap | `artifact_store.py::artifacts_upload` rejects oversized declared bodies and enforces the streaming multipart bound; `BinaryArtifactStore.put` enforces the 16 MiB file cap before persistence. |
| Total cron media-send deadline | `ScheduledMedia` delivers owner-bound opaque IDs through the shared reader and real Telegram binary/text adapter. One absolute deadline covers lookup, reading, all files and final text, including held delivery. The validated setting is `jobs.media_send_timeout_seconds`, 1..300 seconds, default 300. |
| Resource lifecycle | `frontend/src/panels/binary-artifacts.tsx` checks MIME and 16 MiB size, owns/revokes object URLs, aborts on card unmount, and suppresses late fetch/body continuations. It never substitutes a returned remote URL for the authenticated blob request. |

## Concrete limits

The reader serves retained records in producer-owned roots, not arbitrary filesystem paths or remote URLs. Evicted metadata, missing files, unsupported types and oversized bytes are not promised to be recoverable or deliverable. Catalog pagination is bounded and does not certify bytes until download. See `frontend/docs/h518-gallery-pagination.md` for retained counts, continuation and watermark semantics.

MIME checks have different depths: PNG uses the existing structured validator; other formats use signature/container markers. This audit does not claim full codec validation, safe playback of every malformed audio/video file, or native decoder verification. Browsers perform final rendering/decoding. The 16 MiB byte cap is a delivery bound, not a universal decoded-memory bound.

The generic generated-PNG route and the shared catalog/attachment route intentionally coexist for compatibility. No provider was called, no cloud-generation completion was certified, and no native UI was added for this reassessment.

## Fresh verification

Backend commands used the existing Python 3.12 runtime and repository pytest fixtures, which isolate runtime data and constrain network access:

1. `/tmp/nerva-python-runtime/bin/python -m pytest tests/test_binary_artifact_routes.py tests/test_binary_artifact_store.py tests/test_media_library.py tests/test_media_gallery_pagination.py tests/test_media_catalog.py tests/test_media_export.py --junitxml=/tmp/nerva-h523-backend.xml`: **93 passed**, one pre-existing Starlette/httpx deprecation warning. Covers real route guards, byte delivery/disposition, upload bounds/spoof refusal, storage integrity and symlinks, generated/cache resolution, export and complete bounded traversal.
2. `/tmp/nerva-python-runtime/bin/python -m pytest tests/test_image_generation_api_flow.py tests/test_image_options_extended.py --junitxml=/tmp/nerva-h523-image.xml`: **8 passed**. Exercises composed approved-image HTTP flow and changed generation options with simulated ComfyUI; not a live provider test.
3. `cd frontend && ./node_modules/.bin/vitest run src/test/media-gallery-panel.test.tsx src/test/attachment-preview-lifecycle.test.tsx --maxWorkers=1`: **13 passed**, nine gallery cases and four preview lifecycle cases.

An additional temporary, isolated route probe exercised **20 successful deliveries**: ten supported MIME types through both uploaded `ba-` IDs and cache-backed `md-` IDs. It checked exact bytes, MIME, `no-store`, `nosniff`, and inline-versus-attachment disposition. PNG/JPEG/GIF/WebP fixtures were small Pillow-generated rasters; PDF/audio/video fixtures tested the existing signature classification and byte-delivery contract only, not playback. The probe used a disposable resolved data root and a test user-guard override; authentication was tested separately by the permanent route suite. This is supplementary evidence, not twenty additional committed regression tests. Script/log: `/tmp/nerva-h523-mime-probe.py`, `/tmp/nerva-h523-mime-probe.log`.

Other local logs: `/tmp/nerva-h523-backend.log`, `/tmp/nerva-h523-image.log`, `/tmp/nerva-h523-frontend.log`. Existing merged browser evidence in `frontend/e2e/media-gallery.spec.ts` and `frontend/docs/h518-gallery-pagination.md` is attributed to its original run; no browser/device run was repeated for this documentation-only audit.

## Original cron delivery trace and subsequent repair

The frozen source entry `docs/research/hermes-inventory-v2026.8.31/33-media.md:2115`, `media.gateway-media-limits`, names `cron.media_send_timeout_seconds` (default 300) and says it bounds how long a cron job may spend sending media. This is an explicit row element, not an inference from its title.

At the reviewed base, `agents/core/autonomy/jobs.py::JobRunner._send` (line 1340) directly awaits `adapter.send`. `_send_tracked`, `_deliver`, held-message flushing and ordinary `fire` do not apply a total send deadline. `agents/core/autonomy/jobs_scripts.py:452` does use `asyncio.wait_for(..., 30)`, but only for script-job output delivery. It does not establish the bound for ordinary reminder/ask/held deliveries.

`agents/core/channels/telegram.py` constructs an HTTP client with a 15-second timeout and sends text through `sendMessage`, potentially in multiple chunks. Per-request HTTP timeouts are not a whole-delivery wall-clock deadline. The channel and job paths inspected have no `MEDIA:` parser or binary sendPhoto/sendVideo/sendDocument transport. `agents/core/channels/base.py::send` and `channels/outbound.py::send_to_target` are text delivery interfaces.

The tests above freshly verify the existing read/upload boundary, catalog/gallery integration and selected generation regressions. They do **not** prove cron media transport or a total media-send deadline. Adding a timeout around the current text-only path would not by itself provide the missing media flow.

## Scheduled-media completion

The earlier partial judgment was correct at its source base. The new implementation adds actual `remind.media_ids` delivery for 1..8 opaque retained IDs, with a 16 MiB per-file and 32 MiB aggregate cap. It captures exact content hashes and the configured Telegram owner/bot binding before scheduling; it does not accept paths, remote URLs or model instructions as file authority.

Each media and final-text call crosses current binding, e-stop, deadline, rate and audit checks. Durable sending/sent state preserves partial or uncertain outcomes without automatic replay. Held receipts retain their original binding, are rechecked under a per-job process lock, and cannot replay from a stale snapshot. Paused jobs do not starve runnable held work. A cancelled or late acknowledgement cannot revive an abandoned delivery. Telegram text uses one acknowledged plain request without an implicit formatting fallback.

The exact frozen row and cited gateway-media-limits entry do not require a model-authored `MEDIA:` parser, dynamically generated output, every channel or native playback. An owner-authored reminder with opaque IDs is a genuine cron media flow. The existing authenticated reader, bounded roots and upload cap remain unchanged. Synchronous local I/O cannot be preempted; the deadline includes elapsed lookup/read time and prohibits subsequent dispatch after expiry. There is no live Telegram/provider or native codec proof.

Independent implementation review passed 98 backend and 16 frontend tests, and the rebased combined pins/media/CLI suite passed 127 tests. Original read-boundary tests above are attributed to their source run. Fresh integrated reader/upload/gallery/export/generation/scheduled-media verification passed all 148 tests. Full frontend passed 1,315 tests; all three TypeScript configurations and the Vite build passed. The complete backend release suite passed: 11,428 collected, 11,404 passed, 23 skipped and one expected failure, with zero unexpected failures (264 seconds).

## Conclusion

The ID-addressed read boundary, unified gallery access, inbound cap and now actual total-deadline cron media delivery support code-equivalence for H523 within the frozen adaptation. This does not certify arbitrary paths, unlimited exports, unsupported codecs or wider channel/provider integration. The final assessment follows the passing integrated verification and independent contract review; it does not rely on blanket evidence refresh.
