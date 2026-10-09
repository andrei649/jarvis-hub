# PDF text-layer coverage — local H444/H576 slice

Generated 2026-10-09 UTC. Base `9d824eeb6783f7105953901056160f790ade78f8`;
branch `codex/pdf-text-coverage-20261009`. Local only; original draft PR #1247
continues to contain its earlier published mobile-session work.

Interactive PDF file_read now returns a separate `coverage_warning` when more
than 20% of successfully inspected pages or at least ten pages yield no text.
Empty/None and whitespace-only extracted pages count. Exactly 20% below ten pages
and a valid zero-page PDF produce no warning. The warning describes extracted
text coverage; it does not identify scanned pages, visual content or OCR need.

A shared `local_docs.extract_pdf_pages` performs one optional pypdf traversal per
request. Existing `extract_text` callers receive the same newline-joined string
or None; DOCX/plain extraction, bulk indexing and chunking are unchanged. Reader,
iteration, page or nonempty non-string failures refuse the entire extraction and
retain the existing `extraction_failed` result, without partial gap claims.

Warning metadata reports exact page/missing-page/gap counts and the first **16**
maximal inclusive one-based ranges. Each range names the nearest preceding
nonblank page and quotes its last **160 Unicode code points** after trailing
whitespace removal. Initial gaps have no preceding page and an empty quote.
Excerpt truncation and omitted-range counts are explicit. Counts continue across
omitted ranges. These metadata bounds are separate from max_bytes, which still
caps only the returned text page.

Warnings sit before content fields in the result; content itself, UTF-8 offsets,
next_offset, text_size and page hashes are unchanged. Later page requests repeat
the warning and still reparse the PDF. Raw/DOCX/plain reads and refusals omit it.
The existing 50,000,000-byte observed-size admission remains before parser checks,
and earlier offset/scope/type/stat refusals retain precedence.

The normal model loop and nested ToolRPC invocation scan the complete result,
including preceding-page quotes outside the returned content window. Injected
quotes trigger the existing fence/taint behavior; benign quotes do not force all
local files to become declaration-untrusted. No scanner, trust declaration,
runtime, ToolRPC, route, schema, setting, dependency or client code changes.
file_read remains pinned never to spill its own result; ordinary compaction and
context limits still apply, so metadata ordering is not a visibility guarantee.

## Verification

- Direct tests-only RED on unchanged production: **21 cases, ten missing-warning
  failures and eleven controls**, zero errors/skips, 1.342 s. Successful original
  text reads precede every missing-warning assertion. No proposed helper import
  causes RED. An initial DOCX fixture error and the intermediate 19-case run are
  preserved separately; source remained unchanged throughout RED.
- Registered-tool RED: **6 cases, five failures and one control**, zero
  errors/skips, 1.476 s. Actual ToolRPC, model loop and nested Python sandbox
  demonstrate absent warning metadata and absent taint from the not-yet-present
  preceding quote. Root read both test bodies/failure causes and checked five
  unchanged production hashes before implementation release.
- Direct/new and adjacent file-tools, document paging, admission and local-docs
  compatibility suite: **160/160**, 3.836 s. Registered coverage plus existing
  input-limit RPC modules: **13/13**, 1.419 s. These use an observed fake optional
  pypdf reader; they are not real-parser throughput or memory measurements.
- Root disjoint integration: **337/337**, 7.871 s over nine runtime/taint,
  route/OpenAPI/auth-parity, identity, project-context and code-guidance modules.
  Combined focused evidence is **510 distinct cases**, zero failures/errors/skips.
- Coverage tests exercise strict/absolute thresholds, all-empty and zero-page
  PDFs, grouped first/interior/trailing gaps, a multi-page sixteenth retained range
  followed by a multi-page omitted seventeenth, Unicode paging/hash reconstruction,
  reader/page failures and old string-API projection. Emoji and six-byte JSON
  escapes verify metadata remains below 20,000 UTF-8 bytes with ensure_ascii=False.
- AST comparison confirms the complete file-tools module is unchanged outside
  the named imports, PDF document projection/warning and description; original
  admission/parser checks are identical. The complete local-docs module is
  unchanged outside its two new helpers and PDF string-projection branch.
  Independent source review found no Critical/Important issue.
- Collection: **21785 backend** (27 added), **2039 frontend/native**, **316 mobile**,
  555 routes and 18 agents. Client counts are reused from unchanged verified source.
  Full backend verification is pending; collection is not a passing full run.
  No live provider/device or real PDF/OCR acceptance run was performed.

Twenty-six exact-base-fresh pins refresh after named collateral review: 25 across
file_tools and four adapted PDF test seams, plus H670's unchanged architecture
identity-band claim. H444/H576 gain the local-docs helper and two new test pins
(six new pins), replacing only the obsolete missing-warning claim. Their other
remaining gaps stay open. Two H661 coordinates map to the same source statements.
All 226 stored statuses, row identities and the inventory hash remain unchanged;
no backlog checkbox closes. Independent collateral review found no
Critical/Important claim or metadata issue.

Limits remain: no OCR, nonblank-but-incomplete text detection, broader formats,
Markdown conversion, line pagination or caching. The input admission does not
bound decompression, parser CPU/RAM, full extracted-text allocation or file growth
after stat. Bulk ingestion retains its existing string API without these warnings.

Artifacts `/workspace/scratch/pdf-text-coverage-*` retain RED/green/integration,
source/AST/line maps and reviews. Two gpt-6-sol/high agents owned the production/
direct-test and registered-test/review tasks; gpt-6-luna/medium inventoried pins.
Root owned scope, RED release, integration, metadata and git; maximum four active,
no nested delegation. Rollback this helper/warning/tests/docs unit; no migration.
