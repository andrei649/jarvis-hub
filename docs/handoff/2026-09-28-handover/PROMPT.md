# Handover prompt: continue the Hermes integration (paste into a new session)

Paste everything below the line into a new Claude Code session on `andrei649/jarvis-hub`, with ultracode on
(`/effort ultracode`, or include the word "ultracode").

---

ultracode. You are continuing the Nerva ↔ Hermes capability integration on `andrei649/jarvis-hub`. All work goes on the
branch `claude/cto-session-recovery-qinvkg`, which is draft PR #1207. You have none of the earlier conversation.
Everything you need is on that branch.

## 0. Get onto the branch (before reading anything)
1. Run `git status` and `git branch --show-current`. Preserve changes that are not yours: never reset them, drop them from
   a stash, reformat them or stage them.
2. Run `git fetch origin '+refs/heads/*:refs/remotes/origin/*'`. A shallow clone is single-branch, so a plain
   `git fetch origin` may never create `origin/claude/cto-session-recovery-qinvkg`. Use this refspec for every fetch.
3. If `git rev-parse --is-shallow-repository` prints `true`, run `git fetch --unshallow origin`. Restamping from a pinned
   file version needs the full history.
4. Run `git switch claude/cto-session-recovery-qinvkg`. If it does not exist locally, run
   `git switch -c claude/cto-session-recovery-qinvkg --track origin/claude/cto-session-recovery-qinvkg`. Then run
   `git merge origin/claude/cto-session-recovery-qinvkg`.
   The handover files exist only on this branch, not on `main`.
   If the session's own instructions assign a different development branch, work locally and ask the owner before
   pushing anywhere.
5. Confirm #1207 is still a draft: use `gh pr view 1207 --json isDraft`, or GitHub MCP `pull_request_read` with method
   `get`. If it is not a draft, push nothing: the hourly auto-merge takes every non-draft PR. Report to the owner instead.

## 1. Load context
Read, in this order:
1. `CLAUDE.md`, then `AGENTS.md`.
2. `docs/handoff/2026-09-28-handover/README.md`: the state, the owner items and the gotchas.
3. `docs/handoff/2026-09-28-codex-review/README.md`.
4. `docs/prompts/hermes/README.md`.

For anything bigger, follow the tiers in `docs/AI_CONTEXT.md`. Never load the raw repo, and never load `BACKLOG.md`
whole: query it with `python3 scripts/backlog.py`.

## 2. Rules that do not bend
- **Branch and PR.**
  - Push only to `claude/cto-session-recovery-qinvkg`.
  - Keep #1207 a draft. Never merge it, never merge into `main`, never deploy, and never change the PR's state, title or
    body.
  - Never rebase, force-push or rewrite pushed history.
  - Other sessions may push to this branch too.
- **Before every push:**
  1. Confirm #1207 is still a draft (§0.5).
  2. Fetch with the §0.2 refspec.
  3. `git merge origin/claude/cto-session-recovery-qinvkg`.
  4. Merge `docs/hermes/assessment.json` by review id:
     - never drop another session's entry;
     - resolve a review that both sides changed by re-reading the code;
     - keep `scope_reopenings` byte-identical;
     - keep the newer `base_sha` and `assessed_at`.
  5. Regenerate the generated files rather than hand-merging them. They are `HERMES_STATUS.md`,
     `docs/HERMES_CAPABILITIES.md`, `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `project-status.json`,
     `docs/test-manual/14-api-surface-sweep.md` and `tests/_snapshots/*`. Run:
     - `python3 scripts/hermes_status.py write`;
     - `python3.12 scripts/status_sync.py --reuse-js-counts`;
     - if routes changed, `python3.12 scripts/gen_api_sweep.py` and the snapshot updaters.
  6. Re-run the gates (§5).
- **Protected paths.**
  - Never edit any path in `selfdev-policy.json` → `protected_paths`: `agents/core/kernel/**`, `agents/core/security/**`,
    `agents/core/secrets/**`, `agents/core/secret*`, `AGENTS.md`, `MAX.md`, `MOONSHOT.md`, `NERVA_VISION.md`,
    `LICENSE`, `TRADEMARKS.md`, `docs/legal/**`, `.github/workflows/**`, `.github/actions/**`, `.github/CODEOWNERS`,
    `selfdev-policy.json` and `scripts/selfdev_policy.py`.
  - Reading them and pinning them as evidence is fine.
  - Before every commit, run `git diff --cached --name-only | python3.12 scripts/selfdev_policy.py classify --stdin`
    and confirm it shows `"protected_hits": []`.
  - Security rows (e.g. H512) and the `github-advanced-security` check (P29) belong to the owner and go last.
- **Skip and record** any row that needs network access, hardware, or an owner decision (`docs/OWNER_TASKS.md`: P29,
  P30.2, P31.1–3). Never mark a row `excluded`, and never change a `skip` decision.
- **`AGENTS.md` is a pending owner decision.** Do not edit it or settle it. Commit `beb2ee5a` added two sections on
  2026-09-27:
  - **"Keep this sprint local…" (Safe task start).** The owner pasting this prompt is the publication request that note
    waits for. It covers pushes to this branch and comments on #1207 only. It does not cover merges, deploys or PR state
    changes. Do not rely on that section's "every repository path, including the kernel, security" clause; the protected
    paths above still apply.
  - **"Owner-approved resource plan (2026-09-27)".** It names Codex models and a four-agent cap. The owner chose
    ultracode for this run. Keep its model-agnostic rules:
    - subagents never delegate;
    - one writer per file;
    - a short, self-contained brief per agent that names exact files and acceptance checks;
    - one full suite at a time;
    - for each batch, record what ran, the results and the unfinished work.
  - If `git log origin/claude/cto-session-recovery-qinvkg -- AGENTS.md docs/OWNER_TASKS.md` shows the owner has decided
    either question, follow that decision.
- **Honesty.**
  - Put a row at `equivalent` only when its evidence has a source path and a test path, its cited tests passed in this
    session, and `remaining` is exactly `""`.
  - Verify every `path:line` citation by content. The checker only checks that the line is non-blank.
  - When your change drifts other rows' evidence, re-read and restamp them. Map from the file version their sha256
    pins, which may be older than the last restamp base.
  - Report exactly what ran.

## 3. First: the state of PR #1207
- **Check runs.** Read them on the current head: `gh pr checks 1207` if `gh` is installed, otherwise GitHub MCP
  `pull_request_read` with `get_check_runs`, then `get_job_logs`.
- **Red checks.** Drive every red check green by fixing root causes outside the protected paths. Report these rather
  than chase them:
  - a failing `github-advanced-security` check (P29, owner);
  - a failure that needs a protected-path edit;
  - a failure that reproduces on `origin/main`.
- **Merge conflict with `main`.** Merge `origin/main` into the branch.
- **Review comments.** Deal with every open one.

## 4. Then: H464 round 3
Run:

    git log origin/claude/cto-session-recovery-qinvkg --oneline -i --grep "grade after the task lands"

- **If it prints nothing:** do `docs/handoff/2026-09-28-handover/h464-round3-brief.md`. Put the phrase "grade after the
  task lands" in your commit subject. Method:
  1. a red-first build;
  2. a closure verifier and an adversarial hunter in parallel;
  3. fix rounds until no MAJOR or MINOR regression remains;
  4. records, push, then CI.
- **If it prints a commit:** read that commit's message and skip this step.

## 5. Then: the buckets, one at a time
Run them in this order, following each prompt's own procedure exactly:
1. `docs/prompts/hermes/needs-review.md`: records only. It turns stale rows back into truthful assessments.
2. `docs/prompts/hermes/equivalent.md`: audits the 108 inherited 7 September rows first.
3. `docs/prompts/hermes/partial.md`: closes rows that are nearest to equivalent.
4. `docs/prompts/hermes/missing.md`.

The bucket prompt's procedure, records and gates are authoritative. The summary below is for §3–§4 work; where the two
differ, the bucket prompt wins.

**Method** (ultracode):
1. read-only fan-out triage;
2. a ranked plan;
3. per row, or per tightly coupled cluster:
   - design, using a judge panel for L/XL rows;
   - a red-first build;
   - a closure verifier and an adversarial hunter;
   - fix rounds;
   - mutation testing of the new code;
4. records in the same change:
   - `docs/hermes/assessment.json`, then `hermes_status write` and `check`;
   - a BACKLOG bullet via `scripts/backlog.py sections`;
   - `docs/hermes/build-queue.md` and the test manual;
   - `status_sync`.

**Stopping rule for fix rounds:** once only NITs or rare issues that predate your change remain, record them as known
gaps in the row's `remaining` or a handoff note.

**Gates** before each push:
- `ruff check .`, which is what CI runs.
- `python3.11 -m bandit -r agents scripts -q -b .bandit-baseline.json`
- The affected pytest files with **python3.12**, with `JARVIS_HOME` and `TMPDIR` in a scratch directory `$S` outside the
  repo.
- At each milestone and after merging `origin/main`, the full suite, one at a time:
  `JARVIS_HOME=$S/home TMPDIR=$S/tmp python3.12 -m pytest tests/ -n auto --dist loadfile`
- `python3.12 scripts/gen_api_sweep.py --check`
- `python3.12 scripts/status_sync.py --check --reuse-test-counts`
- `python3 scripts/hermes_status.py check`
- `python3.12 scripts/check_test_manual.py`. It always exits 0, so read its last line. At handover it prints
  `2 flagged item groups`, both already on `main` (06: missing worldview paths; 08: one broken table row). Add none.
- `git diff --name-only origin/claude/cto-session-recovery-qinvkg HEAD | python3.12 scripts/selfdev_policy.py classify --stdin`,
  with `protected_hits` equal to `[]`.
- `cd frontend && npx vitest run`, if the frontend changed.

**After pushing:** watch CI and drive it green. If the session can schedule messages, schedule one check-in an hour after
each push, not a recurring routine. Delete any schedule you created before you stop.

**Stop and report** when any of these holds:
- #1207 is no longer a draft;
- a gate cannot pass without a protected-path edit or going out of scope;
- all four buckets are handled or blocked;
- your context is running low. In that case, first commit, run the gates and push. Then write a dated
  `docs/handoff/<date>-hermes-driver/README.md` with the fields in §6 and where to resume.

## 6. Reporting
Post reports as comments on #1207: one per milestone, and one at the end. Each report says:
- rows moved (from → to);
- rows blocked, with the reason;
- owner decisions needed;
- the new headline from `python3 scripts/hermes_status.py summary`;
- CI state;
- how it was verified: what ran, and the results.

Do not edit #1207's title or body; parallel sessions share them. List any body change you think is needed under owner
items.
