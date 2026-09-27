# Handoff — H277 in progress on PR #1207 (2026-09-27)

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
