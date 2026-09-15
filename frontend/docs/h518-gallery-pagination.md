# H518 Gallery Pagination Implementation Plan

**Goal:** Browse and search the complete retained authorized media catalog with bounded work per request.
**Base:** b96f0b690e4bfeda53e9ee0799bc812cace2474e. **Generated:** 2026-09-15. **Head:** the candidate source commit containing this guide (exact SHA in handoff). **Next action:** independent review and parent integration.
**Spec:** frozen H518 in docs/research/2026-09-07-hermes-absorption-ledger.json and accepted parent design. Implementation executes inline under the planning/TDD skills; no delegation or publishing.

## Accepted design

Keep existing user guards, flags, opaque media IDs and resolver checks. GET /api/media/catalog retains enabled/items/stats; stats remains the current response's matches. Older responses without page metadata are never labeled as the full retained total. Add page metadata with retained catalog count, scanned candidate count, has_more and next_cursor. A request scans at most 200 candidates and returns at most limit (1..200, default 200) matches. All filters use this same scan contract, including header-derived MIME search. Empty matching pages can still have continuation. No complete filtered count is fabricated.

Order by descending (created_at, source, id), retain a first-request upper key and advance by the last scanned key. The transport cursor is strictly bounded/versioned and bound to normalized q/kind/enabled sources; it is not confidential or an authorization credential. Every request rechecks flags and every file access uses the existing resolver. Newer appends are excluded; deleting a boundary does not invalidate keyset progress. This is a timestamp watermark, NOT an exact ingestion snapshot: later backdated/equal-time inserts below the watermark can appear. No ingestion metadata/index is added.

Generated catalog JSON is already capped at 10 MB/10,000 retained records; each page loads it once. Pagination bounds header reads (200 x 4096 bytes), response size and full blob avoidance, not the metadata JSON parse. Attachments use existing bounded metadata storage. Legacy gallery() callers retain their list return; no route removal or guard changes.

Frontend uses an abortable server query, deterministic reset on filter/refresh, epoch checks against stale responses, explicit Load more/Continue search and honest page/scanned totals. Export is explicit selection (maximum 200 IDs); never silently truncate. Existing 128 MiB ZIP input cap and 129 MiB browser response cap remain. Lazy BinaryCard preview lifecycle stays intact.

## Tasks and verification

- [x] Backend RED: add tests/test_media_gallery_pagination.py with 220 retained records. Assert first search page has zero matches but a cursor; the next page finds the oldest match. Assert <=200 headers and one JSON load. Add mixed-source ties, newer append and boundary deletion coverage; malformed/oversized/filter-mismatched cursors must fail without blob access. Verify old stats and exports remain unchanged.
- [x] Backend GREEN: add gallery_page(root, generated, attached, q, kind, limit, cursor) in agents/core/media_library.py and bounded query parameters in agents/core/routers/multimodal.py. Retain gallery() compatibility. Cursor decode strictly checks shape/types/order, source and ID domains. Run focused media library/catalog/export/artifact route tests, targeted Ruff/Bandit.
- [x] Frontend RED/GREEN: add frontend/src/media-gallery.ts hook and update MediaGalleryPanel in frontend/src/gap.tsx. Test continuation after empty pages, abort/reset/late responses, failure retry, and export selection cap in frontend/src/test/media-gallery-panel.test.tsx. Existing disabled and preview behavior remains covered.
- [x] Acceptance: add frontend/e2e/media-gallery.spec.ts for desktop/responsive browser fixture search beyond 200 and selected export. Run both frontend typechecks, affected tests then full frontend with one worker, deterministic production rebuild and asset integrity tests. Schema generation only if query parameter changes require it; parent handles global route/evidence integration.

## Boundaries and rollback

No native mobile changes: Media Director is not a gallery, and native catalog/export remains open. No deleted history recovery, missing cloud writeback, full filtered total, paid providers, new dependencies/indexes, host filesystem ZIP writes, kernel or admin changes. Source files above, directly generated agents/web/v2 assets and this module guide form one revertible unit. Parent owns global counts, reports, rebasing and publishing.


## Delivered browser/API behavior

`GET /api/media/catalog?limit=50&q=needle` returns the existing `enabled`, `items` and per-response `stats`. The additional `page` object reports `catalog_total` (current valid retained metadata for enabled sources, independent of filters or file availability), `scanned`, `matches`, `has_more`, `next_cursor` and `invalid_count`. Pass the returned cursor with the same q/kind and current source flags to continue. Case-normalized queries bind identically. Invalid/mismatched cursors return 400; parameter bounds return 422. These tokens contain no host paths and grant no authority. Clients must follow continuation even after an empty `items` list; there is no inferred global filtered total.

The browser requests 50 matches per page with at most 200 candidate header reads. Search/kind/refresh changes cancel the prior request and discard stale results and selections. Load more preserves loaded matches, deduplicated by source and ID; failed continuation can retry. Authorization/cursor errors clear stale rows and selections. Export selection is explicit and can cross loaded pages; at 200, additional unselected checkboxes are disabled. Select loaded media is disabled when more than 200 available rows are loaded, rather than truncating them. ZIP creation still revalidates IDs/files and includes the existing missing-file manifest.

## Verification (2026-09-15)

- Backend RED: the initial two pagination tests failed because gallery_page did not exist; actual route tests subsequently failed because pagination/validation was absent. Frontend RED: three new continuation, stale-query and selection tests failed against the prior panel.
- Backend: 95 affected tests passed, including 34 new pagination/route tests, existing catalog/library/export/artifact contracts and production asset integrity. One existing Starlette/httpx deprecation warning.
- Frontend: full suite 1,252/1,252 passed with one Vitest worker; gallery suite 9/9 (net +5). Both TypeScript configurations passed.
- Browser: 2/2 desktop/responsive-phone tests passed using the real application routes, disposable 220-record catalog and actual selected ZIP response. No live model/provider, native mobile or production deployment proof is claimed. Run with `NERVA_TEST_PYTHON=<existing-python> npx playwright test -c playwright.gallery.config.ts` from frontend.
- Security: whole-repository Ruff passed; Bandit over relative `agents scripts` against the existing baseline passed (existing comment-parser warnings only). Targeted changed Python files and browser fixture also passed.
- Build: two production builds produced identical hashes for all 16 output files. No new dependencies. Scoped Graft graph built under /tmp/nerva-h518-graft and explicit freshness check passed; no graph cache committed.
- Parent owns rebasing onto H139, regenerated global API schema/manual and global evidence/count updates. This branch changes only existing route query parameters, not route inventory or guards.
