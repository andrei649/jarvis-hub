# Document extraction input limit — local H444/H576 slice

Generated 2026-10-09 UTC. Base `d12e6f2d20862d69b8c128f5c625c83fb96bfd16`;
branch `codex/document-input-limit-20261009`. Local only; original draft PR #1247
continues to contain only its earlier published mobile-session work.

Parser-backed file_read now refuses PDF/DOCX files whose observed on-disk size
exceeds **50,000,000 bytes**. This explicitly defines the documented 50 MB ceiling
in decimal bytes, consistent with the existing decimal output-page convention.
Equality is admitted. The new first `_read_document` branch runs before parser
discovery and extraction; suffix matching remains case-insensitive.

The handler returns `ok:false`, `reason:document_too_large`, the observed `size`,
`max_document_bytes:50000000` and fixed guidance that `raw=true` returns a bounded
byte page. No path or content enters the new detail. Registered ungated ToolRPC
keeps its existing outer `ok:true` envelope with the refusal nested under `result`;
there is no approval task or new transport shape. The tool description states the
limit and preserves its paging guidance.

Earlier bad-offset, scope/secret, missing/non-file and stat-error decisions keep
their precedence. Admitted documents retain parser_missing/extraction_failed,
UTF-8 extracted-text offsets, output caps and next_offset. Raw large-document and
ordinary file reads retain bounded byte paging, including near/past EOF. Shared
extract_text, LocalDocsIndexer, runtime, ToolRPC, mutations, permissions, input
schemas, routes, settings, dependencies and clients are unchanged.

This is admission against one observed stat size, not a hard parser resource
bound. File growth after stat, decompression, parser RAM/CPU, full extracted-text
materialization and repeated parsing remain possible. It does not add OCR,
scanned-page coverage warnings, line pagination, Markdown conversion or formats.
H444 and H576 stay partial; their other documented gaps remain open.

## Verification

- Tests-only direct RED on unchanged source: **18 cases, five real oversized
  parser-path failures and 13 controls**, zero errors/skips, 1.269 s. Actual sparse
  50,000,001-byte files reached parser discovery/extraction for both formats and
  suffix casings, first/later pages and the missing-parser case.
- Registered ToolRPC RED: **7 cases, four failures and three controls**, zero
  errors/skips, 1.235 s. The real handler produced parser_missing after probing,
  retaining the expected outer envelope rather than the new nested size refusal.
  Root read both test modules/all nine failure messages and verified three
  unchanged production hashes before releasing implementation.
- Focused direct/file-tool/spill suite: **129/129**, 2.408 s. Existing document
  module: **5/5**, 1.127 s. Independent registered-tool suite: **7/7**, 0.993 s.
  Sparse files exercise the literal boundary without allocating 50 MB buffers;
  optional parsers are stubbed, so this is admission/paging proof, not real-parser
  throughput or memory measurement.
- Root disjoint integration: **348/348**, 8.386 s across 11 modules, including
  recent mutation receipts, instruction approvals, code guidance, project context,
  identity and route/OpenAPI parity. Combined focused evidence is **489 distinct
  cases**, zero failures/errors/skips.
- The complete file-tools module AST equals the base outside the explicit
  constant, first size guard, helper docstring and file_read description. Named
  independent source/collateral reviews found no Critical/Important issue.
  A bounded test note remains: the stat-error control intercepts the current
  third Path.stat call, so a future harmless probe refactor may require updating
  that control. It does not weaken the oversized-file regressions.
- Collection: **21758 backend** (25 added), **2039 frontend/native**, **316 mobile**,
  555 routes and 18 agents. Client counts are reused from unchanged verified source.
  Full backend verification is pending; collection is not a passing full run.
  No live provider/device or real large-document parser run was performed.

Twelve exact-base-fresh pins refresh after named review: eleven file-tools claims
and H670's architecture identity-band claim. H444/H576 remove only the obsolete
missing-size-refusal clause and retain other limits; H303/H536 read wording now
qualifies admitted/parseable inputs. Both primary rows gain the two new test pins.
H507/H661/H670 coordinates map to the same statements. All 226 stored statuses,
row identities and the inventory hash remain unchanged. No backlog checkbox closes.

Artifacts `/workspace/scratch/document-input-limit-*` retain RED/green/integration,
source/AST/line maps and reviews; initial design/pin inventory use the
`document-size-*` prefix. Two gpt-6-sol/high agents owned source/direct tests and
registered-tool tests/review; gpt-6-luna/medium performed read-only inventory.
Root owned scope, RED release, critical integration, metadata and git; maximum
four active, no nested delegation.

Rollback is this guard/test/docs unit; no migration is needed.
