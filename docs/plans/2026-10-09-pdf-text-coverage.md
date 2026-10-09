# PDF text-layer coverage implementation plan

> Agentic execution: subagent-driven development, one production writer, disjoint
> direct and registered-tool tests, root RED release and independent review.

**Goal:** warn the model when significant PDF page ranges yield no extractable text,
without changing the extracted content or its byte pagination.
**Architecture:** one shared PDF page-text parser in local_docs; its existing string
API joins those pages. Interactive file_read derives bounded warning metadata from
the same page list, with one parser traversal per request.
**Tech stack:** existing Python/asyncio/pytest and optional pypdf; no dependency change.
**Design:** the exact bounded contract below, informed by H444/H576 and independent
review in `/workspace/scratch/pdf-text-coverage-design-review.md`.
**Generated:** 2026-10-09 UTC.
**Base/head before changes:** `9d824eeb6783f7105953901056160f790ade78f8`.
**Worktree/branch:** `/workspace/jarvis-hub-pdf-text-coverage`,
`codex/pdf-text-coverage-20261009`.
**State/next action:** implemented with independent source/collateral reviews;
510 distinct focused cases pass and collection reports 21785 backend cases.
Commit the frozen source/tests and run the full backend milestone. Existing
PR #1247 and prior worktrees remain preserved; no new full-suite pass is claimed.

## Exact contract

- Add `extract_pdf_pages(path: Path) -> list[str] | None` in `agents/core/local_docs.py`.
  Import optional pypdf lazily, construct one PdfReader and call each page's
  extract_text once. Normalize falsy returns to the existing empty-string value;
  nonempty non-string values, reader/iteration/page exceptions return None. Do not
  turn failed pages into known gaps or expose a partial successful result.
- Preserve `extract_text(path) -> Optional[str]`: PDF projects `"\n".join(pages)` or
  None from the shared helper. Empty page list still gives the empty string. Keep
  DOCX/plain extraction, LocalDocsIndexer, chunking and its remember API unchanged.
- Add pure `pdf_coverage_warning(pages: list[str]) -> dict | None` in local_docs.
  A successfully extracted page counts as lacking text iff `not text.strip()`.
  Warn iff `N > 0 and (M * 5 > N or M >= 10)`, where N is page count and M is the
  number without text. Exactly 20% below ten pages and zero-page PDFs do not warn.
- Only a triggered warning adds `coverage_warning` beside existing file_read
  fields. It is absent otherwise, including DOCX, raw/plain reads and refusals.
  Preserve content, text_size, byte offsets, next_offset and page SHA exactly;
  never prepend warning text to content. Repeat the same warning on later offsets.
  Insert triggered warning metadata before content in the result so existing head
  previews can retain its header; existing spill/compaction limits still apply.
- Warning has exactly: `reason: "pdf_text_layer_gaps"`, `detail` equal to
  `Some PDF pages yielded no extractable text. Do not assume the document is silent on a topic; inspect only the relevant page gaps.`,
  integer `total_pages`, `pages_without_text`, `gap_count`, array `gaps`, integer
  `omitted_gap_count`, and boolean `gaps_truncated`.
- Gaps are maximal consecutive inclusive 1-based ranges, ordered by page. Retain
  the first **16** ranges while continuing exact page/missing/range counts. Each
  record has exactly `start_page`, `end_page`, `after_page`, `after`,
  `after_truncated`. `after_page` is the nearest preceding nonblank page number or
  None; `after` is the last **160 Unicode code points** of its text after rstrip,
  or the empty string if none. `after_truncated` is true iff that trimmed page
  text exceeded 160 code points. Initial gaps use None/empty/false.
- `omitted_gap_count = gap_count - len(gaps)` and `gaps_truncated` is true iff that
  count is positive. Snippets quote source text and are not trusted summaries.
  Their independent bound is separate from max_bytes, which still caps content.
  Verify worst-case escaped metadata stays under 20,000 UTF-8 bytes when serialized
  with ensure_ascii=False. Do not claim all ranges are listed beyond the cap.
- FileTools PDF path calls the shared page helper once and computes warning from
  those pages; DOCX keeps extract_text. Preserve case-insensitive dispatch and the
  existing 50,000,000-byte observed-size guard before parser discovery/extraction,
  plus earlier offset/scope/type/stat refusals. No new schema, route or setting.
- Keep existing result scanners/fencing in AgentToolRuntime and nested ToolRPC;
  do not change file-tool trust declarations. A snippet outside the returned text
  page must still be scanned as part of the same result. No new log of source text.
- Add one short tool-description sentence about PDF page gaps reported separately.
  This is text-extraction coverage, not proof of scanning, OCR need or visual content.
  No OCR, parser install, format expansion, Markdown conversion, caching, CPU/RAM
  limit or post-stat growth protection. H444/H576 remain partial for remaining gaps.

## Review focus

1. Exact threshold arithmetic: 1/5 off, 2/5 on, 10/50 and 10/100 on; zero/all-empty.
2. Reader or later-page failure returns extraction_failed with no misleading gaps.
3. Same text bytes and per-page hashes through Unicode offsets despite metadata.
4. First/interior/trailing ranges, capped lists and snippets disclose omissions.
5. Out-of-page injection in a snippet reaches existing loop/nested result scanners.

## Task 1 — extraction/source and direct regressions (auth_audit, sol/high)

Own production `agents/core/local_docs.py`, `agents/core/file_tools.py`; new
`tests/test_file_pdf_coverage.py`; existing direct modules
`tests/test_file_read_documents.py`, `tests/test_spill_paging.py`,
`tests/test_file_document_input_limit.py`.

- [x] Tests-only: use real FileTools and a fake optional pypdf reader with per-page
  call observations. Assert existing successful joined text before new warning
  assertions. Cover every review-focus case except runtime scanning, including
  whitespace/None, exact thresholds, 16-range/160-code-point boundaries, ranges
  continuing across the cap, zero/all-empty, errors and non-string parser output.
  Prove one reader/one extraction per page per request and legacy extract_text's
  unchanged text/failure projection. Do not import missing proposed helpers for RED.
- [x] Run RED with XML/log under `/workspace/scratch/pdf-text-coverage-direct-red.*`;
  root inspects causes and unchanged production hashes before RELEASE.
- [x] After RELEASE, implement only the contract. Adapt existing PDF helper stubs
  without weakening their paging, input-limit or no-extraction assertions; keep
  DOCX on the string seam. Run owned new/direct tests, local-docs compatibility,
  file-tools/spill/input-limit regressions and Ruff. Return hashes/diff for review.

## Task 2 — registered result and provenance (mobile_session_transport, sol/high)

Own new `tests/test_file_pdf_coverage_rpc.py` and existing
`tests/test_file_document_input_limit_rpc.py`; no production writes.

- [x] Tests-only: register real FileTools/ToolRPC and fake only optional parser
  input. Prove the new warning is inside the existing outer ok:true result with
  no task; content/offset/hash remain text-only, legacy refusals/raw reads persist.
  Actual AgentToolRuntime and nested ToolRPCInvocation must scan an injection in a
  preceding snippet outside the returned content page; clean snippets retain the
  existing non-forced-taint behavior. No fake scanner or RPC handler methods.
- [x] Save meaningful RED XML/log before production release. Coordinate test runs
  serially with task 1. Do not add missing-helper imports that mask behavior RED.
- [x] After source freeze, adapt the existing PDF input-limit stub, retain all
  assertions and run the two owned modules. Independently review source/direct
  tests against this exact contract, including shared extract_text compatibility.

## Task 3 — root integration and evidence

- [x] Inspect both RED results, release source and critically review actual diff.
- [x] Run relevant disjoint runtime/taint, local-docs, identity and route guards.
  Inventory and review only named fresh pins; update H444/H576 claims narrowly,
  preserve statuses and inventory identities. Record architecture/mobile/HUD
  applicability and test counts. No backlog checkbox closes from this slice.
- [ ] Freeze source/tests and run one serial full backend milestone; compare exact
  skipped IDs with `document-input-limit-backend-final.xml` (21721 pass +37 skipped).
  Run actual-count guard, Ruff/diff/status/Hermes; reuse unchanged frontend/native
  2039 and mobile316 counts. Preserve any failed runs and investigate before retry.
- [ ] Record proof and manifests, commit locally and verify clean final tree.
  Rollback this helper/warning/tests/docs unit; no migration or dependency needed.
