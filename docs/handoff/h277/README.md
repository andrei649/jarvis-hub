# Handoff — H277 in progress on PR #1207 (2026-09-27)

## Exact-image review continuation (2026-10-02)

The selected browser review now binds the one-use token to the SHA-256 digests
of the exact ordered data-URI images. A changed image or order is refused before
transport and burns the token. The full backend suite completed 21,177 cases:
21,142 passed, 35 skipped and none failed or errored on the prior source
checkpoint. The added reordering regression passed separately. The
[exact-commit mutation report](../../hermes/evidence/h277-exact-image-review-mutations-2026-10-02.md)
records three valid assertion kills, a 15/15 baseline before and after, and
4,402 restored tracked regular files. H277 remains partial.

## Local configured-chain continuation (2026-10-02)

The [provider-chain report](../../hermes/h277-video-provider-chain-2026-10-02.md) tracks
explicit fallback configuration, independent consent and runtime integration. Earlier
receipts below retain their original source scope; H277 remains partial.

## Local video continuation (2026-10-02)

An approved native `video_analyze` consumer and independent video-role consent are
implemented locally, including bounded inheritance from the effective vision route.
See the [current implementation and verification report](../../hermes/h277-video-analysis-2026-10-02.md).
The later [video mutation campaign](../../hermes/evidence/h277-video-mutations-verified-2026-10-02/report.md)
on `92905443` detected 29 of 31 validated mutations, with two documented survivors,
zero invalid cases and 168 passing baseline tests. All 4,130 source hashes were restored.
H277 remains partial: broader auxiliary routing and live native-video model acceptance
are unfinished. The dated sections below retain their
original snapshot scope.

## Current-source verification (2026-10-01)

After PR #1207 and the dependency/reliability updates reached main, the 14 shared
judge mutations were rerun on commit `9d5b3add`: all 14 were killed, with 203 baseline
tests passing and all 3,982 snapshot file hashes restored. A separate current H277
selection passed 310 tests. See [the new exact-snapshot report](../../hermes/evidence/h277-current-2026-10-01/report.md).
The old mutation campaigns below retain their original scope and fingerprints.
H277 remains partial: the video-analysis consumer and broader auxiliary routing
are unfinished at this snapshot. This continuation is local only.

## Local Codex continuation (2026-09-27)

The original Claude handoff below is preserved as dated history. Round2 is now
fixed locally. Its 74 mutation cases produced 73 kills and one documented
observational equivalence; the shared-runner follow-up killed all14 mutations.
See [round2 verification](verification/report.md) and
[post-refactor verification](verification/post_refactor/report.md).
Decision Inbox tasks now use the advisory judge alongside action cards, with
separate annotation storage and shared capacity. The HUD shows opinions and a
read-only role list. VLM describe checks locality/model policy before dispatch.
H277 records are refreshed as **partial**, not equivalent: video/provider depth,
native opinions and live acceptance remain open. Full-suite results and portability
repairs are tracked in `docs/hermes/h277-completion-plan.md`. No push or PR edit.

Separate H513 judge consent now covers actual HTTP identity, revocation and
redirect/reused-request refusal. The next local full milestone passed 18,919
backend tests/35 skips and 1,804 frontend tests; see
[the exact evidence](../../hermes/evidence/h513-judge-integration-2026-09-27.json).
Older mutation evidence above remains bound to its original snapshot.

The later H487 task-expiry milestone adds fresh deadline checks to task judging
and clears newly expired pending keys even while e-stop holds durable effects.
It passed 19,054 backend tests/35 skips and 1,809 frontend tests; see
[the expiry snapshot](../../hermes/evidence/h487-task-expiry-integration-2026-09-27.json).
This is separate from the older mutation campaign and does not close H277.

The later H513 direct-transport milestone passed 19,088 backend tests/35 skips.
Owned judge clients ignore environment proxies; actual selected routes are checked
freshly, and borrowed ACTIVE clients remain unchanged. See
[transport evidence](../../hermes/evidence/h513-direct-transport-integration-2026-09-27.json).

The following interactive VLM milestone passed 19,122 backend tests/35 skips
and 1,815 frontend tests. Role/model selection remains enforced while the two
strict-local HTTP consumers gain scoped dispatch, sanitized status and honest
failure reporting. See [interactive evidence](../../hermes/evidence/h513-interactive-vision-integration-2026-09-27.json).
The next Telegram-image milestone passed 19,156 backend tests/35 skips and
1,819 frontend tests, with typecheck/build/scoped scans green. Its independent
role consent preserves judge scopes and refuses stale native dispatch. See
[media-reader evidence](../../hermes/evidence/h513-media-reader-integration-2026-09-27.json).
The camera milestone passed 19,194 backend tests/35 skips and 1,822 frontend
tests, with typecheck/build/scoped scans green. H513 is now code-equivalent to
the frozen inventory contract; H487 remains partial. See
[camera evidence](../../hermes/evidence/h513-camera-integration-2026-09-27.json) and
[the acceptance review with separate unfinished follow-ups](../../hermes/h513-code-equivalence-review.md).

The later generic model-grouping milestone passed 19,226 backend tests/35 skips,
then 101 focused integration tests after the scan correction. Grouping retains
independent signed receipts and does not fan out approval. H487 remains partial;
see [model grouping evidence](../../hermes/evidence/h487-model-grouping-2026-09-27.json).

The bounded human-wait milestone passed 19,285 backend tests/35 skips with scoped
scans/Graft green. Earliest queue decision metadata now prevents defer/accept history
from inflating Company Mode's capped wait credit. H277 signed authority is unchanged;
see [human-wait evidence](../../hermes/evidence/h487-human-wait-2026-09-27.json).
The following H517 local-provider slice passed 19,363 backend tests/35 skips and
1,829 frontend tests, with typecheck/build/scoped scans green. It adds declarative
loopback image registration, real approved dispatch and backend-specific HUD
controls. Directory-durable attempt records now refuse unsupported filesystems.
H518/H523 shared-source contracts were re-reviewed; H517 remains partial and
H516 video remains missing. See [provider review](../../hermes/h517-local-provider-review.md)
and [video checkpoint](../../hermes/h516-video-design-checkpoint.md).

This is the state of the Hermes integration PR #1207 (branch `claude/cto-session-recovery-qinvkg`) at
handoff. H613 is finished and recorded; **H277 is built and one review round is fixed, but it is not
finished** — follow the steps below before calling it done.

## Where the PR stands

- Last fully recorded row: **H613** (equivalent, headline **190/697**), records at `d35fa380` / `a10f564a`.
  CI was green on `a10f564a` except `github-advanced-security` (a repository setting; the owner fixes it).
- **H277 commits on top** (code, tests and docs only — no ledger/BACKLOG records yet):
  - `feat(H277): model roles table and an advisory approval judge`
  - `fix(H277): review round — key scoping, leaf-level injection flags, per-value cap, deep taint, bounded judging, runtime-true vision row`
- Because H277 changed files other ledger rows cite, `tests/test_hermes_sprint_status.py` (and CI's
  test job) is expected **red until the records step below is done**.

## What H277 is

A named role table (`agents/core/llm/model_roles.py`: main, deep, vision, video, approval_judge from
`JARVIS_ROLE_<NAME>_PROVIDER/_MODEL/_BASE_URL`, legacy `JARVIS_VLM_*` / `JARVIS_DEEP_MODEL` byte-identical),
vision and deep routed through it, and an optional **advisory** approval judge
(`agents/core/autonomy/approval_judge.py`, wired in `agents/core/autonomy/action_approvals.py`) that
annotates a pending `ActionApprovalQueue` item with a score and a one-line rationale, off the request
path, never changing status. The HUD shows it in `agents/web/static/tools.js` as a muted "model
opinion … advisory only" line. Full design: `design.md`.

## Done so far

1. Build, red-first: `tests/test_h277_model_roles.py`, `tests/test_h277_approval_judge.py`,
   `tests/frontend/tools.test.js`.
2. Four-lens adversarial review: 13 confirmed findings (1 MAJOR: an openai-compatible judge sent
   `OPENAI_API_KEY` to any base URL) — `review_findings.json`.
3. Fix round 1: all 13 fixed, each pinned (verified: reverting a fix fails its test).

## Left to do (in order)

1. **Fix round 2** — the verification of round 1 (`verify_round1.md`) found 7 defects the round
   introduced. The binding decisions are in `fix_round2_brief.md`:
   - **N1 (treat as MAJOR):** an item waiting for a judge slot (up to ~16 min) is sent to a remote judge
     even after remote judging was revoked or the item was decided — re-check at send time.
   - N2 HUD re-poll budget shorter than the slot wait; N3 per-value cap truncates ordinary 1.6 KB
     writes (false high-risk); N4 injection scan fails open past depth 64; N5 look-alike quote/dot
     characters in the rationale; N6 bytes/set values scanned as repr; N7 unguarded import and taint
     mark with no judge configured; plus two NIT notes (F4 deep-scan pin, F6/F7 LAN label).
   Work red-first, then have an independent reviewer verify each item is closed and pinned.
2. **Mutation run** over `mutants.json` (49 mutants: `{label, file, a, b, tests, run}`; `a` occurs
   exactly once at the round-1 head — re-validate `text.count(a) == 1` after round 2 and add mutants
   for the round-2 code). Kill every survivor with a test or record it as equivalent.
3. **Full suites**: `python -m pytest tests/ -n 3 --dist loadfile` with a scratch `JARVIS_HOME`, then
   `cd frontend && npx vitest run` (not concurrently). Known pre-existing failures:
   `test_bootstrap_script::test_real_interpreter_runs_the_floor_check` (Python 3.11 container),
   `test_tool_result_taint::test_recall_taint_survives_the_orchestrators_agent_gather`, and vitest
   `desktop.test.tsx` "floating app renders…".
4. **Records** (per `AGENTS.md` → BACKLOG sync):
   - ledger row H277 in `docs/hermes/assessment.json` (status stays **partial**: video has no
     consumer; kernel/ToolRPC approvals are not judged — protected `agents/core/kernel/**`; judge
     speaks only lm-studio/ollama/openai-compatible; no roles GET route; picking a vision model does
     not run the H378 guards and `/api/vlm/describe` has no local-only check);
   - restamp every row whose evidence file drifted, keeping line citations on the same content;
   - `python3 scripts/hermes_status.py write` then `check`;
   - `BACKLOG.md` bullet + test counts, `docs/ARCHITECTURE.md` rows (model_roles, approval_judge),
     a test-manual row, `docs/hermes/build-queue.md` entry, `python scripts/status_sync.py`
     (`--check` after), `scripts/check_test_manual.py`, `scripts/gen_api_sweep.py --check`;
   - ruff, bandit (`-b .bandit-baseline.json`), gitleaks.
5. Update the PR body (the "Rows built" table and "How verified").

## Owner decisions still open for H277

- Judge kernel/ToolRPC approvals too (needs a protected kernel edit)?
- Allow a remote (cloud) judge at all, or local only?
- More judge providers than lm-studio / ollama / openai-compatible?
- Every `decide()` now writes one intent-log row even with no judge — intended; keep?

## After H277 — the Hermes queue

Next rows: **H487**, then the rest of `docs/hermes/build-queue.md`. The owner asked for security work
to go last: rows that need `agents/core/security/**` (e.g. **H512**) and the `github-advanced-security`
check are the owner's. H696 / H334 need network access; H427 waits on owner decision P30.2
(`docs/OWNER_TASKS.md`).

## Fresh N1–N7 verification — 2026-10-04

The [focused mutation refresh](mutation-refresh-2026-10-04.md) and its
[structured result](mutation-refresh-2026-10-04.json) record11 behavioral kills:
10 assertion failures and1 intended runtime ImportError, with successful Python
and browser baselines, zero setup errors/timeouts/survivors, and complete snapshot
restoration. The six named source/test fingerprints match local milestone
cc4618a1. This updates the named handoff regressions only; H277 provider/routing,
other accepted dependencies and live acceptance remain unfinished. Historical
receipts retain their original source scope and are not rewritten.


## Original prepared49 current-source verification — 2026-10-04

The [current-source campaign](prepared49-current-2026-10-04.md) and
[structured result](prepared49-current-2026-10-04.json) preserve all original49
cases:41 assertion kills,6 behavioral exception kills and2 survivors. Python
350/350 and browser40/40 baselines and final runs passed. All3,003 snapshot inputs
were restored. The remote-URL survivor retains an independent sanitizer; the
late-annotation survivor exposes missing direct-API test coverage, while current
source already refuses it. Its proposed regression passed baseline and killed
that fault in the disposable snapshot; integration remains a separate step.

The separate [integrated backend receipt](../../hermes/evidence/h487-h277-inline-full-2026-10-04.json)
records22,360 passes,34 ordinary skips,1 existing xfail and zero failures/errors
for the inline-outcome and promotion-audit source checkpoint. New provider work
and broader H277 acceptance remain unfinished. The earlier handoff instructions
above are historical; the owner's later local/kernel authorization applies.
