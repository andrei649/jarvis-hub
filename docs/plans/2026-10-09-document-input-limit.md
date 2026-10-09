# H444 document input limit implementation plan

> Agentic execution: subagent-driven development, one source writer, disjoint
> direct and registered-tool tests, root RED release and independent review.

**Goal:** refuse parser-backed PDF/DOCX extraction when the observed file size
exceeds the documented 50 MB ceiling, before probing or invoking a parser.
**Architecture:** one constant and an early `_read_document` result; preserve the
existing path/stat/offset checks, raw byte paging, optional parsers and output cap.
**Tech stack:** existing Python/asyncio/pytest, no new dependency.
**Design:** the bounded contract below.
**Generated:** 2026-10-09 UTC.
**Base/head before changes:** `d12e6f2d20862d69b8c128f5c625c83fb96bfd16`.
**Worktree/branch:** `/workspace/jarvis-hub-document-input-limit`,
`codex/document-input-limit-20261009`.
**State/next action:** complete locally. Tested source commit
`9a51a01f2f5dfea743448448eaaa9a3c79b32a46`: 21721 backend passed, 37 JUnit-skipped,
zero failures/errors, 292.459 s, exit 0; unchanged skip identities. The first run's
H595 test race is reproduced and corrected; 503 distinct focused cases pass.
Source/test hashes match the tested commit. The closing proof/plan commit changes
documentation only; continue the backlog from this verified local checkpoint.

## Contract and global constraints

- Define `MAX_DOCUMENT_BYTES = 50_000_000`: decimal 50 MB, explicit bytes, matching
  the repository's existing decimal page-limit convention. Exactly the limit is
  allowed. This is an observed on-disk input-size admission check.
- First branch of `_read_document(target, size, limit, offset=0)`: if `size >
  MAX_DOCUMENT_BYTES`, return exactly `ok: False`, `reason: document_too_large`,
  `size: size`, `max_document_bytes: MAX_DOCUMENT_BYTES`, and `detail` equal to
  `document extraction is limited to 50000000 bytes (50 MB); raw=true returns a bounded byte page`.
  This precedes `_parser_available` and `extract_text`. No path/content echoed.
- Preserve all existing branches for at/below-limit documents. PDF/DOCX suffix
  matching remains case-insensitive. Offset still counts extracted UTF-8 bytes;
  max_bytes still caps the output page separately. No parser/caching redesign.
- Keep raw=true and plain-file byte pages available regardless of this document
  extraction limit; preserve seek, EOF and next_offset behavior. Do not change
  LocalDocsIndexer, shared extract_text, supported formats, reachability, schema,
  preflight, route, permissions, runtime, task queue or clients.
- Add a short file_read tool-description sentence naming 50 MB (50,000,000 bytes)
  and keep its existing paging/raw guidance. Update the helper docstring precisely.
- Bad offset, path/scope/secret, missing/non-file and stat-error checks stay before
  the new guard. Oversized documents refuse even if a parser is missing; smaller
  ones keep parser_missing/extraction_failed exactly as before.
- Registered ungated ToolRPC retains its outer ok:true envelope for this handler
  refusal, with inner ok:false. No approval task or new result event is created.
- This does not bound decompression, parser RAM/CPU, fully materialized extracted
  text, or a file growing after stat. It does not add scan-coverage warnings/OCR,
  avoid reparsing or change bulk ingestion. H444/H576 remain partial.
- Local only. Existing PR #1247 and all prior worktrees remain preserved.

## Review focus

1. Above-limit files never reach parser discovery or extraction, including uppercase
   suffixes and later-page requests. Use real sparse files and call observations.
2. Equality and below-limit reads preserve extracted UTF-8 paging and named parser
   refusals. Tests use an explicit literal byte boundary, not the source constant.
3. Raw/ordinary large-file reads remain bounded byte pages, including near/past EOF.
4. Invalid offsets/scope/missing/directory/stat errors retain precedence and reason.
5. Real registered ToolRPC exposes the nested refusal and raw success without
   changing intake authority or outer envelope; no real optional parser required.

## Task 1 — direct guard/source (auth_audit, gpt-6-sol/high)

Own `agents/core/file_tools.py` and new `tests/test_file_document_input_limit.py`.

- [x] Add real sparse-file tests above/equal/below 50,000,000 for both formats and
  uppercase variants. Before receipt/result assertions, demonstrate actual stat
  size. Over-limit RED must show parser invocation/current success, not merely a
  missing constant import. Assert no discovery/extraction after implementation.
- [x] Test raw and ordinary large byte pages near EOF, extracted UTF-8 page limits,
  and relevant legacy refusals without allocating full 50 MB buffers. Keep tests
  independently reaching their claims; avoid bundled assertions blocked by RED.
- [x] Run tests-only RED to scratch `document-input-limit-direct-red.xml/log`.
  Root checks all failure causes and production hashes before source RELEASE.
- [x] Implement only constant, early result, helper docstring and description.
  Run direct + existing document/read/paging tests; report exact final source hash.

## Task 2 — registered tool boundary (mobile_session_transport, sol/high)

Own new `tests/test_file_document_input_limit_rpc.py`, tests only.

- [x] Register real FileTools in ToolRPC. Sparse oversized PDF/DOCX yields nested
  document_too_large with unchanged outer ok:true/tool; no queue/task. Assert the
  observed size and parser calls before the missing refusal during RED.
- [x] Cover valid raw near EOF and exact-boundary extracted-text paging, bad raw/
  offset preflight and legacy scope/missing-parser refusals as controls. Preserve
  inner/outer distinctions; do not monkeypatch FileTools or ToolRPC methods.
- [x] Save RED XML/log before source release. Run owned module after freeze, then
  independently review source and direct tests for contract compliance/quality.

## Task 3 — evidence/integration (root)

- [x] Inspect RED/source hashes, release, review actual diff and execution scope.
- [x] Refresh only named base-fresh pins after collateral review; H444/H576 size
  clause changes narrowly, preserve scanned-coverage/format/reparse/paging limits.
  Add test evidence, update architecture/parity/counts, keep stored statuses
  and inventory identities unchanged. No backlog checkbox closure from this guard.
- [x] Freeze source/tests, run focused adjacent tests and one serial full backend
  milestone; compare skip identities to mutation-receipts-backend-final.xml and
  run executed-count guard. Parent baseline 21696 pass +37 JUnit-skipped. Reuse
  unchanged frontend/native2039 and mobile316 counts. Ruff/diff/status/Hermes.
- [x] Record proof/manifests and clean local commit. Rollback this additive guard
  and tests/docs; no migration. Report observed-size limits without a RAM claim.

## Full-suite test synchronization correction

- [x] Preserve the first full-run failure. Confirm the H595 test and sandbox were
  unchanged from the base; reproduce empty final PID reads for both native and
  simulated WASM by delaying the real child's write with a scratch-only plugin.
- [x] Change only that test to close a sibling temporary PID file before atomic
  replacement, and use the cached PID for cleanup. Keep bounded startup waiting
  and actual cancellation/reaping assertions. Same injected race passes 2/2 and
  the full H595 module passes 14/14; no permanent test-count increase.
- [x] Independently review the test correction, refresh its one previously fresh
  H595 evidence pin, freeze the new commit and repeat the serial backend milestone.
