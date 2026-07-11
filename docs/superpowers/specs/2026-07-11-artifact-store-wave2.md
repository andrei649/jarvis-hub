# Artifact store — wave 2 (binary artifacts) · design spec (H12.26)

> Design note for the **next** reviewed slice of the visual-artifact lane. Wave 1
> (H12.18 frontend + H18.20 mobile) shipped the **governed text Canvas** — no binary
> storage. This spec scopes the binary follow-up so it can be built as one reviewed,
> security-gated PR. **Not implemented yet** — this is the plan, not code.

## Why this is a separate slice

Wave 1 deliberately stopped at the safe visual substrate (typed, sanitized, text-only
Canvas elements). Binary artifacts (user-uploaded or agent-produced audio/video/PDF/image/
doc files) are a materially larger security surface: raw bytes on disk, content-type
spoofing, unauthenticated fetch, unbounded growth, and new data-rights obligations. Each of
those needs an explicit contract before a single byte is stored.

## Goal

Let the user attach / upload a **bounded, validated** binary artifact and browse, stream,
and delete it from the Artifacts workspace — over the same governance discipline as the text
Canvas (default-off, attributed, inspectable, purgeable).

## Non-goals (wave 2 first slice)

- No transcoding / thumbnailing pipeline (that's the 0.46–0.50 Media roadmap).
- No cloud object storage — local-first, on the data root only.
- No inline execution/preview of active content (no HTML/SVG-as-markup, no PDF JS).
- No sharing / external links.

## Required contracts (all must land in the slice)

1. **MIME validation** — allowlist by **magic-bytes sniff**, not extension or client-sent
   `Content-Type`; reject anything not on the allowlist (start: `image/png|jpeg|webp|gif`,
   `application/pdf`, `audio/mpeg|wav|ogg`, `video/mp4|webm`). Executable/active types
   (`text/html`, `image/svg+xml`, scripts) are **never** allowed.
2. **Authenticated delivery** — blobs stream through a `user_guard`'d route that resolves an
   opaque id → on-disk path server-side; the host filesystem path is **never** exposed to the
   client (same rule wave 1 kept for `MediaCatalog.path`). `Content-Disposition: attachment`
   + `X-Content-Type-Options: nosniff`; images may render inline, everything else downloads.
3. **Quotas** — per-store byte cap **and** item-count cap, oldest-unpinned evicted first
   (mirror `CanvasStore._evict`); a single-upload size cap rejects oversized bodies before
   they hit disk.
4. **Retention** — a TTL/retention default that the H23.10 retention sweep can act on
   (default off / generous; opt-in tightening via a setting).
5. **Export** — binaries join the data-export bundle (H23.9 / #303) so "download my data"
   is complete; the manifest records id/kind/size/hash (reuse `media_export.build_manifest`).
6. **Purge / forget** — the store joins the forget-me flow (like `canvas.json` did in wave 1):
   at-rest blobs are deleted and the live index cleared **before** the pre-forget backup is
   allowed to matter (reuse the `clear_memory(persist=False)` + `PURGE_JSON`/dir pattern).

## Proposed shape

- `agents/core/artifact_store.py` — `BinaryArtifactStore` (index = a `JsonStore` of
  `{id, kind, mime, size, sha256, agent, created_at, pinned}`; blobs under
  `<data_root>/artifacts/<id>`), with `put(bytes, mime, agent)` (validates + quota-evicts),
  `get_meta`/`open_blob`/`remove`/`clear`/`clear_memory`. Default-off (opt-in setting).
- New per-domain router `agents/core/routers/artifact_store.py` (CLN-3 pattern):
  `POST /api/artifacts` (multipart, `user_guard`, size-capped), `GET /api/artifacts` (index),
  `GET /api/artifacts/{id}/blob` (authenticated stream), `DELETE /api/artifacts/{id}`,
  `POST /api/artifacts/{id}/pin`. Route/OpenAPI/auth snapshots reseeded **in the slice**.
- Data-purge: add the artifacts dir to `PURGE_MEMORY_DIRS`-style handling + live-store clear.
- HUD: the existing Artifacts tab gains an upload affordance + a typed blob card (image inline
  via the authenticated blob route; audio/video via native `<audio>/<video>` pointing at the
  same route; pdf/doc = download chip). No new center tab.
- Mobile: follow-up parity row (H18.2x), not in the first slice.

## Reconcile with 0.46 Media Library

`MediaCatalog` (0.46) records **generated** media (prompt/backend/path). This store is
**user-supplied/attached** binaries. They should converge on ONE authenticated blob-delivery
route and ONE purge/export path rather than growing two — the slice should either extend the
media delivery surface or explicitly document why they stay separate.

## Test plan (sketch)

- RED-first backend: magic-byte allowlist rejects a spoofed `.png` that's really HTML; oversized
  upload rejected pre-disk; quota eviction drops oldest-unpinned; blob route needs the user
  guard and never returns a host path; forget-me deletes blobs + clears the live index before
  backup; export manifest lists the blob with its hash.
- Frontend: upload posts multipart; image renders via the blob route; non-image shows a
  download chip; delete removes the card; honest loading/empty/error states.

## Rollback

Additive + default-off behind a setting; revert the PR. No wave-1 behavior changes.
