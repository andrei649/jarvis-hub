# Lean queue — the pick list for `LEAN_DRIVER.md`

> Ranked 2026-10-26 from `scripts/backlog.py open` (44 open rows) and the Hermes handoff of
> 2026-10-25. One row = one fresh session = one draft PR. **Lock:** a remote branch
> `lean/<slug>` means the row is taken. **needs:** `ai` = a session may pick it; `owner` = never
> picked (hardware, credentials, GitHub settings, a decision D1–D3, or a security path the owner
> reserved on 2026-10-21: "leave the security at the end, I'll fix it"). Re-rank by editing this
> file in a PR; never reorder silently.

| # | slug | BACKLOG id | size | needs | what "done" means |
|---|------|------------|------|-------|-------------------|
| [~] 1 | `win-ci-unix-only` | — (red `main`, `test (windows-latest)`) | M | ai | The 16 `tests/test_h011_*` failures (`history_unsupported_platform`, missing temp paths, `IndexError`), the 3 `tests/test_backup_h010_review2.py` errors (`socket.AF_UNIX`) and `tests/test_h318g_skill_review.py` on Windows. Where the production code honestly refuses on Windows, the test asserts that refusal or is `skipif(win32)` with the facility named; where the test leaks a Unix assumption (`/tmp`, mode bits), fix the test. No production behaviour change. Verify with the push-to-main run after merge. |
| [ ] 2 | `win-ci-env-and-flows` | — (red `main`, `test (windows-latest)`) | M | ai | The remaining Windows failures: `tests/test_h507_code_guidance.py` (14 cases pass a megabyte through an environment variable — Windows caps one at 32,767 chars; pass the payload by file or stdin), `tests/test_image_generation_api_flow.py` (`enqueue_failed`), `tests/test_h453_transport_pipeline.py`, `tests/test_workspace_foundation_http.py`, `tests/test_job_url_executor.py`. Root-cause each; a real portability bug is fixed in code. |
| [ ] 3 | `roadmap-status-refresh` | — (`docs/NERVA_2_ROADMAP.md` §3) | S | ai | §3 still says 1.1.0 is "🔨 this PR" (it landed in #1039, 2026-09-06). Recount every milestone row against `scripts/backlog.py` and the merged PRs since; set 1.1.0 to its honest state, mark what 1.2.0 already has, and list in §5 what stays deferred. Docs only; BACKLOG wins on every disagreement. |
| [ ] 4 | `nws-11-killable-extraction` | NWS-11 | M | ai | PDF/DOCX extraction runs in a child process with `RLIMIT_AS` and a hard kill at the existing 60 s bound (pypdf has no in-page checkpoint). Windows: no `RLIMIT_AS`, so the child is killed on time only, and the limit says so in the result. Tests: a pathological page is killed and the document is marked `timeout` without a stuck pool thread. |
| [ ] 5 | `nws-13-sqlite-off-loop` | NWS-13 | M | ai | Decide workspace-wide and implement: `BEGIN IMMEDIATE` transactions and FTS queries in `agents/core/workspace/**` run via `asyncio.to_thread` (or one dedicated executor), so a 5 s busy timeout cannot stall the event loop. Keep the busy timeout; add a test that a held write lock does not block an unrelated request. Update `docs/business/WORKSPACE_PILOT_SPEC.md` in the same PR (spec and code change together). |
| [ ] 6 | `nws-12-code-splitting` | NWS-12 | S | ai | `React.lazy` + `Suspense` for the admin console and the reports views of `frontend/src/workspace/`; the first-load chunk shrinks measurably (record before/after sizes from `npm run build` in the PR). Rebuild and commit `agents/web/v2`. |
| [ ] 7 | `nws-23-residual-minors` | NWS-23 | S | ai | The frontend bullets of NWS-23 (reports list 768–1180 px, 320 px badge wrap, screen-reader announcement after "Rulează acum"). Leave the `agents/core/backup.py` wording bullet out unless the Hermes ledger re-read for H503 fits the budget; say which bullets remain. |
| [ ] 8 | `nws-10-ocr-scanned-pdf` | NWS-10 | M | ai | Optional, default-off OCR for PDFs without a text layer: lazy import of a local engine (`pytesseract` / `ocrmypdf` if present), per-page time and memory bounds reusing slice 4's child process, result marked `ocr` so a re-index works. No new mandatory dependency; `no_text` stays the answer when the engine is absent. Spec updated in the same PR. |
| [ ] 9 | `heq-next-row` | HEQ-1 (one Hermes row per run) | M | ai | Take the first row still `partial` from this list, in order: H019 H046 H047 H058 H120 H137 H258 H322 H336 H349 H367 H379 H381 H382 H411 H422 H434 H470 H491 H510 H519 H534 H577 H632 H646 H655 H697. Follow process notes 1–4 of `docs/handoff-hermes-2026-10-25.md` (implement → targeted tests → `hermes_status.py write && check`). Branch `lean/heq-<ROW>`. This row never ticks; it is re-served until the list is empty. Security-path rows (H481 H495 H502 H512) are the owner's. |
| [ ] 10 | `ha-4i-streaming-edits` | HA-4i | M | ai | Streaming edits on Slack and Discord replies, which the channel descriptors already claim: edit-in-place of the in-flight reply through the existing governed reply broker, bounded edit rate, honest fallback to a final message when the platform refuses the edit. Tests on the gateway with fake transports. |
| — | — | NWS-8, NWS-9 | — | owner | Native OIDC and ERP/CRM connectors wait for the owner's answers D1–D3 (`docs/decisions/2026-10-14-nerva-business-suite-kickoff-questions.md`). |
| — | — | NWS-21 | — | owner | The pilot release tag. |
| — | — | SEC-B5, SEC-B6, L3831 | — | owner | Security residuals and the kernel default flip: owner-reserved / criteria-gated. |
| — | — | DRA-08 … DRA-62, GAP-0, GAP-4 | — | owner | Hardware, live accounts, GitHub settings, measured benchmarks, the Hermes head-to-head on the owner box. |
| — | — | L6138 … L7431 (no id) | — | owner | Owner-wired integrations (Google/Spotify OAuth, Home Assistant, Frigate, Telegram token, engines install) and host-only proofs. |

## Run log (append-only; one row per session)

| date | slug | PR | landed | left open |
|------|------|----|--------|-----------|
| 2026-10-26 | win-ci-unix-only | (draft) | 23 `test_h011_*` cases (7 files) and 3 `test_backup_h010_review2` cases skip where history / `AF_UNIX` are unsupported, facility named; Hermes ledger restamped (H010 H011 H082 H138 H185 H643) | `tests/test_h318g_skill_review.py::test_a_failed_text_rollback…` (old and new `SKILL.sig` identical on Windows — cause not reproducible off-Windows); row stays `[~]` until a Windows log explains it |
