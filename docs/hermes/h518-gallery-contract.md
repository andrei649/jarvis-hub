# H518 gallery contract reassessment

- Goal: assess the original accepted browse/search/export capability without adding requirements from adjacent features.
- Generated: 2026-09-15.
- Reviewed source/base: `7f12bdf8fb2424957142b109b75261de758f7d7b`.
- Audit head: the commit containing this document; source is unchanged from the reviewed base.
- Changed path: `docs/hermes/h518-gallery-contract.md` only.
- Next action: parent review and a separate assessment/evidence refresh. This document does not change global status.

## Frozen requirement

Row H518 (capabilities index 517) in `docs/research/2026-09-07-hermes-absorption-ledger.json`, row digest `60e5175fefe3e3282fef3b3974fa23fd952d6c16bd6978617e2b59fd8ea114d7`, is **“Browse, search and export everything the assistant has generated.”** Its decision is `keep`, and the recorded Nerva state is `superior`.

The original evidence explicitly describes a **bounded**, atomically written, corrupt-safe catalog, search/stats, a ZIP manifest that reports vanished files, and provenance lineage. Its rationale calls the existing library finished. It identifies one conditional correctness debt: when cloud generation lands, the approved-task completion handler must catalog its output. The dependency explicitly points to the image-generation row.

There is no native-mobile requirement, recovery requirement for deleted/evicted history, exact concurrent snapshot requirement, or requirement for one unlimited ZIP. The word “everything” describes the library's retained authorized catalog, consistent with the bounded store praised in the same frozen row. Native gallery controls could improve the product, but are not a reason to keep this original contract unfinished.

## Current implemented behavior

| Contract | Source and evidence |
| --- | --- |
| Browse all retained metadata | `agents/core/media_library.py::gallery_page` unifies generated and attachment records, orders by descending timestamp/source/ID and exposes bounded continuation. `frontend/src/media-gallery.ts` follows continuation and deduplicates source/ID pairs. It is no longer confined to the newest 200 rows. |
| Search throughout that catalog | `agents/core/routers/multimodal.py::media_catalog` accepts bounded query/kind/cursor parameters. Each scan applies filters and returns continuation even with zero matches. The HUD exposes Continue search/Load more and resets stale searches. |
| Honest counts and unavailable files | `page.catalog_total` counts current valid retained metadata; page stats describe page matches, not a fabricated full filtered total. Missing/unsupported/unsafe files remain unavailable rather than being presented as downloadable. Invalid catalog metadata is reported separately. |
| Preview and individual download | `frontend/src/panels/binary-artifacts.tsx::BinaryCard` explicitly fetches the authenticated blob endpoint, validates MIME/size and owns transient object URLs. Unmount aborts fetch and rejects late response/body work. |
| Selected portable export | `agents/core/routers/artifact_store.py::media_export` resolves each opaque ID again and creates an in-memory ZIP with `manifest.json`, hashes and a `missing` list. `MediaGalleryPanel` in `frontend/src/gap.tsx` permits explicit selection across loaded pages and never silently truncates an oversized selection. |
| Authorization and filesystem boundaries | Catalog and blob/export routes use existing user guards and feature flags. `catalog_path`/`resolve_blob` reject unsafe paths and recheck symlinks. Cursor data is only a bounded position token, not path or authorization authority. |
| Existing retention and provenance | `agents/core/media_catalog.py` retains a bounded catalog and evicts oldest metadata; `agents/core/artifact_store.py` applies its configured quotas/retention. `agents/core/creative/provenance.py` preserves the existing lineage facility. No new claim of universal provenance across every producer is made. |

## Limits that do not create new acceptance work

Generated metadata is bounded to 10,000 retained records and a 10 MB file. Attachment storage has existing quotas and retention. Removed records are not promised to be recoverable. Each catalog request scans at most 200 candidates; it can be continued until the retained range is exhausted. Header hints do not certify full content: download revalidates bytes.

A timestamp/key upper watermark excludes newer appends, while later backdated/equal-time insertions below that watermark can appear. This is deterministic keyset traversal, not an exact ingestion snapshot. The UI tells the owner to refresh for newer media.

Exports accept at most 200 selected IDs and 128 MiB of resolved input; the browser checks a 129 MiB ZIP response bound. The owner can export further selections separately. Unsupported, oversized, missing or unauthorized file bytes are not made accessible to satisfy an unbounded reading of “everything.” ZIP construction uses an in-memory response; this route introduces no host-path file-write authority.

## Cloud generation dependency

`MediaGenManager._queue_cloud` in `agents/core/media_gen.py` evaluates the proposal and enqueues `media.{kind}` with `cloud=True`; it returns approval information before any generation or catalog write. The coordinator at this base has no cloud-image completion implementation for that legacy task. Its generic `_llm` fallback (`agents/core/autonomy_coordinator.py`) processes text through `orch.process`; it is not a cloud image backend, and an ordinary task result must not be treated as generated image bytes.

The real image path is `LocalImageRuntime.execute` in `agents/core/image_generation_runtime.py`: it constructs `MediaGenManager` with the ComfyUI backend and `default_catalog_if_enabled()`. The manager records successful local output through `_record_local_result`. The local approved ToolRPC image binding is distinct from the legacy cloud proposal.

Therefore this audit does **not** certify cloud generation, a live cloud provider, or cloud completion writeback. When H515 adds that executor, its successful completion must persist the artifact and catalog record before reporting a produced asset. That conditional producer-integration obligation should remain with H515. No present gallery traversal defect was established by the absence of a future producer.

## Fresh verification

All commands ran from the isolated audit worktree with unchanged production/test source. Existing pytest guards isolate runtime data and restrict network access. No live provider or production deployment was used.

- Backend: **88/88 passed** using `/tmp/nerva-python-runtime/bin/python -m pytest -q tests/test_media_catalog.py tests/test_media_export.py tests/test_media_library.py tests/test_media_gallery_pagination.py tests/test_binary_artifact_store.py`. A separate collection check confirmed 88 cases. These exercise persistence/retention/corruption, safe resolution, route guards, >200-record traversal, empty-match continuation, ties, deletion boundaries, source/filter cursor binding, retained counts and export limits/missing-file behavior. One pre-existing Starlette/httpx deprecation warning.
- Frontend: **13/13 passed** using `cd frontend && ./node_modules/.bin/vitest run src/test/media-gallery-panel.test.tsx src/test/attachment-preview-lifecycle.test.tsx` (nine gallery cases and four preview lifecycle cases).
- Browser acceptance is prior merged evidence, **not rerun for this documentation-only audit**: `frontend/e2e/media-gallery.spec.ts` and `frontend/docs/h518-gallery-pagination.md` record two desktop/responsive-phone tests against a disposable 220-record catalog and the actual selected ZIP response.
- Local logs: `/tmp/nerva-h518-contract-backend.log`, `/tmp/nerva-h518-contract-collection.log`, `/tmp/nerva-h518-contract-frontend.log`.

## Reassessment conclusion

The original H518 browse/search/export contract is supported by current source and focused verification. No additional native controls, history-restoration mechanism or unlimited export implementation is required by the frozen row. Recommend code-equivalent assessment, preserving retention/security/concurrency boundaries in its summary and the future cloud completion obligation with H515. The parent owns that status decision and evidence refresh.
