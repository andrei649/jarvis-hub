# Hermes parity handover — 2026-10-06

**Goal:** Functional Nerva parity with every one of the frozen 697 Hermes capabilities, using donor implementations/tests and complete coherent batches with minimal repeated work. The goal is unfinished and development is paused at the owner's wrap-up request. Publication of all current repository work is explicitly authorized for this handover; merge, deployment, provider activation and paid/live calls are not requested.

**Freshness:** Prepared on 2026-10-06 in `/Users/andrei649/Projects/nerva-pr-worktrees/consent`. Development head before the snapshot: `a7ffad6676cfb28e7ac374d495b4a5889e5f4646`. Fetched GitHub `main`: `c21202c1` (four commits not present in that local head). Published snapshot branch: `codex/hermes-parity-handover-20261006`. The snapshot commit containing this document is the handover head; verify its exact SHA and live PR checks before further work. Do not infer mergeability or CI success from local checks.

## Current accounting

- 130/697 documented code-equivalent capabilities (18.7%); 227 partial, 56 missing, 284 needing review, zero excluded.
- Of the 130, 108 retain the September7 audit; 22 have current reviewed evidence. The 57 current reviews are not a full697 reaudit.
- The latest Krea Enhance work did not close whole H515. Five previously equivalent rows temporarily lost credit while shared frontend source changed; matching preimages were reviewed and refreshed after regressions. Unrelated pre-existing stale pins were preserved.
- Canonical status: `HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md`, `docs/hermes/assessment.json`; derive/check with `scripts/hermes_status.py`, never invent a progress percentage from code/file counts.

## Delivered latest batch

Krea Enhance now has an explicit separate source-bound factor2 POST approval, strict API/tool selector and owner-visible availability. It preserves the original artifact and uses saved-job GET continuation after interruption. Source artifact/hash, human execution, principal/configuration and current host admission are checked before dispatch and publication. The official Krea reference confirms the native endpoint and1024-character source URL limit; the documented `gen.krea.ai` origin is admitted explicitly in the default-off manifest.

Validated metadata-stripped Enhance output supports4096px/16MiB, with private completion/pixel proof for the opaque image route and generated gallery/binary ZIP/portable export. Ordinary generation, upload and edit-reference limits retain2048px. The responsive HUD keeps the original preview, shows immutable source approval, handles ambiguous submission once, and releases object URLs on reset/unmount. Reload opens the selected task alone. No nested Enhance or automatic migration of historical source completions is added.

Evidence: `docs/hermes/evidence/2026-10-06-krea-enhance/` and `docs/hermes/h515-krea-enhance-plan-2026-10-06.md`. Earlier batches remain under the dated evidence directories, including Krea continuation/xAI/DeepInfra, OpenRouter/Krea and OpenAI/Codex/FAL. The complete snapshot includes prior local implementation and evidence across the other capability families; the latest batch's scoped tests do not certify every earlier change.

## Verification and limits

- Latest affected backend union:956 tests, zero failures/errors/skips.
- Complete frontend suite:1976/1976 pass. Initial run had one obsolete exact-shape assertion; corrected without weakening private-field rejection, then the complete suite passed.
- Record/route/OpenAPI/schema guards:120 tests pass. Typecheck, build and scoped Ruff pass.
- Bandit:3601 analyzed lines, zero findings/errors. Graft source graph fresh with zero added/removed/changed/stale; authored context is intentionally absent. Its cache is outside the repository and must not be committed.
- Exact staged-content secret scan and published commit/PR state must be verified by the publishing session. This document does not claim future GitHub CI success.
- No full-repository backend suite was rerun for the entire accumulated snapshot in this wrap-up. Earlier batch receipts have their own scope and dates. Keep the aggregate PR draft until conflicts/review/checks and broader integration are resolved.

## First next actions

1. Verify the snapshot branch/commit, worktree status, latest `origin/main`, PR mergeability and reported checks. Preserve dirty state; no reset or automatic rebase. Review the four newer main commits before any integration. Do not merge merely because a local suite is green.
2. Read `docs/hermes/h515-managed-nous-map-2026-10-06.md` and the pinned donor files it identifies. The next implementation seam is managed Nous image selection/catalog/transport over a narrow encrypted OAuth access-token reader. Existing inference credentials may prefer an agent key and are not gateway Bearer credentials. Verify current gateway scope/audience/contracts; keep explicit per-tool selection, entitlement refusal, fixed origins and separate approvals. No activation/import/paid probe.
3. Complete remaining H515 contracts in coherent batches: managed Nous/FAL, other dynamic catalogs, FAL local artifact upload/Clarity, product-managed Codex OAuth, provider-specific/larger output bounds and xAI storage controls. Then close the existing local ComfyUI LLM restore/lease/authority/native/mobile requirements against the entire frozen row. Do not award equivalence for adapters alone.
4. Continue the whole697 queue, prioritizing closing existing work and complete usable capabilities. Reuse donor code/tests, avoid repeated broad exploration and refresh only reviewed matching evidence pins. The remaining requirements in each assessment row stay authoritative until verified.

## Local resources and execution discipline

- Python3.12: `/Users/andrei649/Projects/nerva-hub/.venv/bin/python`. The old `/tmp/nerva-pr-python-20261001/bin/python` is broken; do not use it.
- Existing Ruff: `/tmp/nerva-pr-python-20261001/bin/ruff`. Existing offline OpenAPI generator7.13.0 is cached at `/Users/andrei649/.npm/_npx/f1e70922fc87e24a/node_modules/openapi-typescript/bin/cli.js`; do not install dependencies just to regenerate.
- Donor archive source root: `/Users/andrei649/Projects/hermes-source-59b2aeef6c7a/hermes-agent-59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. It is an archive, not a Git checkout; don't claim a verified donor HEAD from `git rev-parse`.
- Batch preimages: `/tmp/nerva-h515-krea-enhance-baseline-20261006`. They are convenience rollback data; GitHub snapshot and source-bound receipts are the durable handover.
- Read current `AGENTS.md`. At most two implementation agents, `gpt-6-sol` High, exact disjoint file ownership, no child agents; coordinator owns shared integration and critical review. Focused regressions per step, one affected milestone union, expensive full suites serially. Repeat only for changes/failures/unresolved concerns. No exact per-agent resource claims.
- File evidence digests use `scripts.hermes_status.file_digest`, which normalizes UTF8 newlines. Keep manifest `source_entries` as path/hash objects. Graft has explicit refresh and no hooks or instruction-file edits.

[Prompt for the next session](RESUME_PROMPT.md)
