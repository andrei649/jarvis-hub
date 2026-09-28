# Hermes ledger: re-assess every `needs_review` row (records only)

You coordinate a records-only pass over the Hermes capability ledger in `andrei649/jarvis-hub`. You work on branch `claude/cto-session-recovery-qinvkg`, which has draft PR #1207. Up to three other sessions may run at the same time on this branch, handling the `missing`, `partial` and `equivalent` rows. So assume the branch moves under you.

**Goal.** Every row whose live status is `needs_review` ends up with a current, truthful assessment, or is recorded as blocked with a reason. The bucket has two parts:
- rows with basis `stale_evidence`: an existing review whose pinned files changed;
- rows with basis `scope_reopened`: former `skip` rows that have never been reviewed.

**What you may build.** No features and no product-code fixes. The only new code is a restamp helper and its tests.

**How to run.** Use ultracode and orchestrate with workflows. Subagents are read-only and never spawn agents. You are the only writer of every shared file.

## 0. Load context (never the raw repo)
1. **Check the worktree.** Run `git status` and `git branch --show-current`. Preserve any changes that are not yours: never reset, stash-drop, reformat or stage them.
2. **Get full history.** Run `git rev-parse --is-shallow-repository`. If it prints `true`, run `git fetch --unshallow origin`. Then run `git fetch origin '+refs/heads/*:refs/remotes/origin/*'` so every branch is local. Pinned blobs can sit deep in history or only on another branch, and a shallow clone would falsely report them as unrecoverable.
3. **Bring in the latest branch.** Run `git merge origin/claude/cto-session-recovery-qinvkg`.
4. **Read the instructions.** Read `CLAUDE.md` and `AGENTS.md`, then Tier 0 from `docs/AI_CONTEXT.md` (for `STATUS.md`, the header block only).
   - `AI_CONTEXT.md` has no Hermes bundle. Use its "Query before you load" Hermes note.
   - Per row, load only the files that row cites, plus their matching tests (the "Backend work" bundle rule).
5. **Also read:**
   - `docs/HERMES_SPRINT.md`: completion rules, and "Cum se menține statusul" for hash refresh;
   - `docs/hermes/full-parity-2026-09-27.md`: the owner directive, execution sequence steps 2–3;
   - `docs/hermes/scope-reopening-plan-2026-09-27.md`;
   - the header of `docs/hermes/build-queue.md` (lines 1–48);
   - `docs/handoff/2026-09-28-codex-review/README.md`. Its headline numbers are dated; never edit dated reports.
6. **BACKLOG.** Never open `BACKLOG.md` whole. Query it with these three separate commands:
   - `python3.12 scripts/backlog.py sections`
   - `python3.12 scripts/backlog.py find 'HEQ-1'`
   - `python3.12 scripts/backlog.py show HEQ-1`
7. **The frozen requirement.** Run `python3.12 scripts/hermes_status.py show HNNN`. It prints `assessment` (the derived row) and `original` (the row from `docs/research/2026-09-07-hermes-absorption-ledger.json`).
   - Never edit that ledger file. Any change breaks `inventory_sha256`, and then every `hermes_status` command fails with exit 2.
   - For query-only access, use `python3.12 scripts/ledger.py stats|clusters|list|show`.
8. **Derived text in `show`.**
   - **Stale rows:** `show` replaces `remaining` with a derived placeholder. Read the recorded review in `docs/hermes/assessment.json` instead.
   - **Reopened rows:** `show` replaces both `summary` and `remaining` with the reopening reason and a placeholder, because there is no review yet.
   - **The old `skip` `rationale`** and the 2026-09-07 `nerva_state`/`nerva_evidence` fields are leads, not evidence.
9. **Upstream sources, all local.** Use:
   - the frozen row;
   - the inventory entries its `hermes` text cites, in `docs/research/hermes-inventory-v2026.8.31/<section>.md`. This directory is 18 MB, so grep for the cited entry ids and never load it whole;
   - `docs/hermes/upstream-reference-2026-09-27.json`, which pins upstream `59b2aeef…` and 8 inspected sources. Its metrics and row lists are dated; never use them as the work list.

   Never fetch Hermes upstream from the network. If a verdict truly needs more upstream detail than these give, the row is blocked (network).

## 1. Hard rules
- **Git and PRs.**
  - Never merge a PR, merge into `main`, deploy, or change a PR's state. Keep #1207 a draft: auto-merge only takes non-draft PRs.
  - Never edit #1207's title or body; other sessions share it.
  - Push only to `claude/cto-session-recovery-qinvkg`. Never rebase, force-push or rewrite pushed history.
  - The only outbound calls are git/GitHub operations for this branch and PR, and package installs (`npm ci`) for test runners. No provider or paid calls.
- **Pending owner decision: two Codex-added `AGENTS.md` sections** (commit `beb2ee5a`; see "For the owner" in the handoff README). `AGENTS.md` is protected; do not edit it and do not settle the decision.
  - **"Keep this sprint local…" (Safe task start).** The owner pasting this prompt is the publication request that note waits for. It covers pushes to this branch only, not merge, deploy or PR state changes. You do not rely on that section's "local development on every path, including kernel/security" clause (see Protected paths below).
  - **"Owner-approved resource plan (2026-09-27)".** It names Codex models (`gpt-6-sol`/`gpt-6-luna`) and a four-agent cap. The owner chose ultracode for this run. Keep the plan's model-agnostic rules:
    - subagents never delegate;
    - one writer per file, which is you;
    - a short self-contained brief per agent, naming exact files and acceptance checks;
    - one full suite at a time;
    - record per batch what ran, the results and the unfinished work.
  - If `git log origin/claude/cto-session-recovery-qinvkg -- AGENTS.md` or `docs/OWNER_TASKS.md` shows the owner has decided either question, follow that decision.
- **Protected paths.** Never edit any path in `selfdev-policy.json` → `protected_paths`. That includes `agents/core/kernel/**`, `agents/core/security/**`, `agents/core/secrets/**`, `agents/core/secret*`, `AGENTS.md`, `MAX.md`, `MOONSHOT.md`, `NERVA_VISION.md`, `.github/workflows/**`, `.github/actions/**`, `docs/legal/**` and the policy files.
  - Reading them, and pinning them as evidence, is fine.
  - Rows whose evidence or `remaining` touches them go in the last batch.
  - Anything that would need a change there goes on the owner list. Security is the owner's.
  - Before every commit, run `git diff --cached --name-only | python3.12 scripts/selfdev_policy.py classify --stdin` and confirm `"protected_hits": []`.
- **Records, not code.** When a re-read shows a buildable gap, write it concretely into the row's `remaining` (the partial and missing prompts consume it) and list it in the report.
  - If a cited test fails, do not fix product code. The row cannot be `equivalent`: record the failure in `remaining` and report it.
- **When to skip a row.** Skip only when the assessment itself cannot be made without network, hardware or an owner decision, and record why.
  - First grep `docs/OWNER_TASKS.md` for the row id. If no entry covers it, add a dated entry in that file's `## PNN — …` format, using the next free number.
  - A row that honestly stays `partial` with "needs hardware proof" or "waits on P30.1" in `remaining` can be re-recorded without the hardware or the decision. Never promote such a row.
- **Scope decisions are fixed.**
  - Never mark a row `excluded`.
  - Never edit or remove a `scope_reopenings` entry: `tests/test_hermes_sprint_status.py` requires exactly the 107 `skip` ids there.
  - Never change a `skip` decision or anything else in the frozen ledger.
  - New upstream capabilities (an inventory migration) are out of scope.
- **Owner-only checks.** `github-advanced-security` (P29) is the owner's.
- **Honesty.**
  - Never refresh a hash without re-reading the row. A hash-only restamp is exactly what `docs/HERMES_SPRINT.md` forbids.
  - Never describe an unrun suite as passing.
  - Never "fix" numbers in dated reports (`docs/research/*`, `docs/handoff/*`, `docs/hermes/upstream-reference-*.json`, `docs/hermes/evidence/*`).

## 2. Compute the bucket live (row lists go stale; never hardcode them)
Run from the repo root with `python3.12`. In this sandbox `python`/`python3` are 3.11.
```python
import sys; sys.path.insert(0, "scripts")
import hermes_status as hs
ledger, data = hs.load(); rows = hs.assess(ledger, data)
bucket   = [r["id"] for r in rows if r["status"] == "needs_review"]
stale    = [r["id"] for r in rows if r["basis"] == "stale_evidence"]
reopened = [r["id"] for r in rows if r["basis"] == "scope_reopened"]
assert set(bucket) == set(stale) | set(reopened)
print(len(bucket), len(stale), len(reopened), hs.metrics(rows))
```
Record a baseline in your scratch directory, not the repo:
- the output of `python3.12 scripts/hermes_status.py summary --json`;
- the three lists;
- the flagged groups from `python3.12 scripts/check_test_manual.py`;
- the backend test count, i.e. the last line of `JARVIS_HOME=$S/home TMPDIR=$S/tmp python3.12 -m pytest tests/ --collect-only -q`, alongside `tests.backend` in `project-status.json`;
- any test that already fails on the merged origin head. These are pre-existing failures (see §7).

## 3. Restamp helper first (red-first)
**Coordinate first.** Run `git fetch origin`, then `git ls-tree -r --name-only origin/claude/cto-session-recovery-qinvkg scripts tests | grep -iE 'stamp|drift'`.
- If another session already pushed a helper, merge and extend it instead of writing a second one.
- If you write it, commit the helper and its tests on their own and push that commit early (after the §7 gates), so the other sessions reuse it.

Otherwise write `scripts/hermes_restamp.py` and `tests/test_hermes_restamp.py`. The helper imports `hermes_status` and never re-implements its rules. It takes `--root` (default `hs.REPO`) so tests can run against a fixture. It is read-only by default.

**`drift ID…|--all-stale`.** For each evidence path, report:
- the pinned sha and the current digest;
- the commit(s) whose blob matches the pin.

Rules for finding that commit:
- **Hash rule.** Hash exactly as `hs.file_digest` does: decode the blob as UTF-8, translate `\r\n` and lone `\r` to `\n` (universal newlines), re-encode as UTF-8, then SHA-256. Never use raw `sha256sum`, because a CRLF blob would differ. Report a non-UTF-8 blob as such.
- **Where to search.** Use `git log --all --full-history --format='%H' --raw -- <path>`. Hash each distinct blob once, for example through `git cat-file --batch`. Use `--follow`, or `--diff-filter=R --name-status`, to find where a deleted or renamed path went.
- **The pin can be older than you expect.** It may predate the last restamp's `base_sha` (the lesson of the 2026-09-28 recovery), or it may exist only on another branch.
- **No match.** Report `unrecoverable` only after the unshallowed, all-branches search. The pin may have been an uncommitted working tree in another session. That row needs a full re-read, not a remap.

**`cite ID`.** Find citations with `hs.CITATION` and resolve each pinned path the same way `hs._cited_lines` does: an exact path, or a unique `/`-suffix match among pinned paths. Unpinned citations are ignored, as `hs` ignores them.
- Show the cited lines from the pinned version, with candidate HEAD locations found by content: an exact unique match first, then a context-anchored `difflib` match.
- Classify each citation as `unchanged`, `moved`, `edited`, `deleted` or `ambiguous`. Never guess an ambiguous one.
- Print the `git diff <pinned-commit> HEAD -- <path>` hunks that overlap cited ranges.

**`stamp --patch FILE`.** This is the only write path, and it takes an explicit reviewed patch: a list of `{id,status,summary,remaining,evidence:[paths]}`.
- Compute `row_sha256` as `hs.digest` of the ledger row.
- Recompute every evidence sha from the working tree with `hs.file_digest`.
- Insert or replace only the patched reviews and keep `reviews` sorted by id. Leave `scope_reopenings` and every other review byte-identical.
- Set `base_sha` to `git rev-parse HEAD` and `assessed_at` to `date -u +%Y-%m-%dT%H:%M:%SZ`, unless flags override them.
- Serialize with `json.dumps(d, ensure_ascii=False, indent=2) + "\n"` and write atomically (temp file, then rename).
- **Refuse to write when any of these holds:**
  - `hs.assess()` on the in-memory result would raise;
  - a patched row would not come out with basis `reviewed`;
  - a `partial`/`missing` row has a whitespace-only `remaining` (a loophole `hs` does not close);
  - the patch names `excluded` or `needs_review`.

**Tests** use a temporary git repo fixture, modelled on the `sample` fixture in `tests/test_hermes_sprint_status.py`.
- Isolate the fixture from global git config: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, an explicit identity and `commit.gpgsign=false`. This sandbox signs commits globally.
- Cover:
  - a pin in an older commit;
  - a pin only on another branch;
  - an unrecoverable pin;
  - CRLF and lone-CR blobs;
  - moved, edited, deleted and ambiguous lines;
  - unpinned citations, ignored exactly as `hs` ignores them;
  - refusal of an invalid review, a whitespace-only `remaining`, and a row that would come out stale;
  - `scope_reopenings` untouched;
  - a byte-identical serialization round-trip.

**Mutation-test the helper.** Seed mutants by hand: flipped comparisons, dropped newline normalisation, off-by-one line mapping, a skipped ambiguity guard, a dropped refusal. Each mutant must be killed, or the gap is documented.

**Lint and bandit.** The helper must pass `ruff check .` and the bandit gate.
- Call `subprocess` with argv lists and never `shell=True`.
- Annotate each call like the existing scripts do (`# nosec B404/B603/B607 - fixed argv, no shell`).
- Never add entries to `.bandit-baseline.json`.

Add one line for the helper next to the `hermes_status` commands in `docs/HERMES_SPRINT.md` → "Cum se menține statusul".

## 4. Read-only triage, then a ranked plan
Fan out read-only agents, feeding each the helper's `drift`/`cite` output:
- over stale rows, grouped by shared drifted file (a tightly coupled cluster);
- over reopened rows, grouped by cluster.

Each agent returns:
- the row, its effort, the drifted files and the pinned commit;
- the class of each citation;
- whether the drift touches any claim in `summary` **or addresses any item in `remaining`**, since code landed since the pin may have closed a gap;
- protected-path, owner, network and hardware flags;
- a proposed class:
  - **A: restamp.** The drift touches no claim and closes no `remaining` item, so the status is kept. The row is still re-read and verified (§5).
  - **B: re-assess.** The drift touched claims or `remaining` items, so the status may move either way.
  - **C: full re-read.** The pinned version is unrecoverable, or the file was deleted or renamed.
  - **D: fresh assessment.** A reopened row with no review. Judge it against the full frozen requirement and the ledger's `adaptation_rule`: privileged effects must land behind the Action Kernel.
    - A governed Nerva equivalent counts. The absence of Hermes's ungoverned mechanism is not a gap.
    - If nothing exists, record `missing`. Use the governed shape from the rationale's "Re-open path" as a concrete `remaining`.
  - **E: last or owner.** Evidence or `remaining` on a protected path goes last but is still assessed. The row is blocked only when the assessment itself needs an owner decision, network or hardware.

Rank the plan as A (batched per file) → B → C → D (S/M before L/XL) → E. Keep the plan in your scratch directory.

## 5. Per batch: one row, or one tightly coupled cluster, at a time
1. **Assess.** The assessor reads the requirement and the current code, and proposes a review in which every `path:line` citation is content-checked at HEAD.
   - L/XL rows get a judge panel: three independent assessors, and a judge who reconciles them by re-reading the code, never by vote alone.
   - **Pinning.** Pin the narrowest files that carry each claim. Every review needs at least one evidence path, including `missing` rows: pin what you read to establish the absence. Avoid pinning high-churn files (`agents/cli/nerva.py`, `agents/core/orchestrator.py`, `agents/web.py`, `frontend/src/gap.tsx`, `settings_db.py`) unless the claim lives there, because each edit to them demotes every row that pins them.
   - **Citations.** Cite claims in pinned files: `hs` checks only that a pinned citation's first line exists and is non-blank, and a bad one is fatal (exit 2) for every command.
2. **Verify closure.** The verifier:
   - opens every cited line and confirms it says what the sentence claims;
   - checks the evidence standard;
   - runs the tests the row cites, each with its own runner, and records the counts:
     - `tests/`: `JARVIS_HOME=$S/home TMPDIR=$S/tmp python3.12 -m pytest <files> -q`;
     - frontend: `cd frontend && npm ci && npx vitest run <files>`;
     - mobile: that package's jest.

   If a cited suite cannot run here, the row cannot be recorded `equivalent`. Record a lower status only if it is honestly supported; otherwise leave the row stale and list it as blocked (environment).
3. **Hunt.** An adversarial hunter tries to refute every kept or promoted status: uncovered requirement clauses, stubs, untested paths, regressions the drift introduced.
4. **Fix rounds.** Repeat until neither reviewer reports a MAJOR or a MINOR. NITs and rare pre-existing issues become documented known gaps.
5. **Apply.** Write the patch to your scratch directory, apply it through the helper, then run `python3.12 scripts/hermes_status.py write && python3.12 scripts/hermes_status.py check`.
6. **Diff the stale list against the previous one.** Handle every newly stale row, whether your change drifted it or a merge from origin did.
   - If a merged commit from another session already restamped it, do not redo it.
   - Map its citations by content from the version its digest pins, which may be older than the last restamp base.
   - Then re-read and restamp it in the same commit, or downgrade it honestly.

**Status rules**
- **`equivalent`** requires all of the following:
  - the whole accepted contract is implemented;
  - the evidence pins at least one source path (`agents/`, `frontend/src/`, `mobile/src/` or `desktop/`, with no `/test/`) and at least one test path (`tests/` or containing `/test/`);
  - the cited tests passed in this session;
  - `remaining` is exactly `""`.
- `scripts/` and `docs/` paths are not code evidence. A code verdict is not live proof.
- **`partial` or `missing`** rows must name concretely what is left.
- **Pinned rows.** Read `tests/test_hermes_sprint_status.py` before touching any row it pins:
  - H515, H598, H566, H660 and H595 are fixed at `partial`;
  - H456, H477 and H510 must each keep at least one intact pinned file whose citation resolves.

  Changing a pin needs a justified test edit in the same change.
- **Header fields.** `base_sha` is the HEAD you assessed against, and `assessed_at` is UTC `Z` time. The helper sets both.

## 6. Records in the same change
- **Ledger.** `docs/hermes/assessment.json` (through the helper), then `hermes_status` `write && check`.
- **BACKLOG.** Locate HEQ-1 through `backlog.py` and edit only that section.
  - Add a dated bullet in the style of the existing HEQ-1 bullets: rows moved, kept and blocked; headline before → after; test count.
  - If origin has not already done it, correct HEQ-1's outdated scope text ("590 accepted and 107 intentionally excluded") to the live numbers: all 697 accepted, with the 107 former exclusions reopened on 2026-09-27.
- **Build queue.** In `docs/hermes/build-queue.md`:
  - sync the "Now" cell and the per-row section of every queue row you re-assessed;
  - when a row reaches `equivalent`, cut its plan to the page's one-line closed stub and remove it from the table;
  - add a dated history note.
- **Test manual.** In `docs/test-manual/`, adjust a case only where a re-assessed row's case cites changed behaviour or paths. Then run `python3.12 scripts/check_test_manual.py`. It always exits 0, so read the output and compare it with your baseline.
- **Owner tasks.** Add `docs/OWNER_TASKS.md` entries for new owner needs.
- **Status sync.** Run `python3.12 scripts/status_sync.py --reuse-js-counts`: it re-collects the backend count, which your new tests change. Then run `python3.12 scripts/status_sync.py --check --reuse-test-counts`. It writes `project-status.json`, `STATUS.md`, `README.md`, `NERVA.md` and `GO_LIVE_PLAN.md`.

## 7. Gates before every push (record the real results)
- `ruff check .`
- `python3.11 -m bandit -r agents scripts -q -b .bandit-baseline.json`. Bandit is installed only for 3.11; CI runs it on 3.12.
- `python3.12 -m pytest tests/test_hermes_*.py -q` per batch. The glob includes the helper's tests.
- **The full suite** at milestones and before each push. Run one full suite at a time, never two in parallel. `S` is a scratch directory outside the repo:
  ```
  mkdir -p $S/home $S/tmp
  JARVIS_HOME=$S/home TMPDIR=$S/tmp python3.12 -m pytest tests/ -n auto --dist loadfile --timeout=90
  ```
  Always use python3.12; 3.11 fails on PEP 695 syntax (`agents/core/media_providers.py`).
  - A failure your change causes blocks the push.
  - A failure that reproduces on origin's head without your commits is pre-existing. Record it with the reproduction and continue.
- `python3.12 scripts/gen_api_sweep.py --check`.
- `python3.12 scripts/hermes_status.py check` and `python3.12 scripts/status_sync.py --check --reuse-test-counts`.
- **Vitest.** Run it for every row whose cited tests are frontend tests (§5.2). Run the whole suite (`cd frontend && npm ci && npx vitest run`) only if frontend files changed; in a records-only pass they should not.

## 8. Commit, sync, push, CI
1. **Commit.** Commit once per batch, staging explicit paths only (never `git add -A`). Messages end with the attribution trailers your system prompt specifies.
2. **Sync before each push.** Run `git fetch origin && git merge origin/claude/cto-session-recovery-qinvkg`. Never rebase or force-push.
   - For generated files (`HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md`, `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `project-status.json`), regenerate instead of hand-merging.
   - Merge `assessment.json` by review id and never drop another session's entry.
     - If both sides changed the same review, resolve it by re-reading the code, never by picking a side.
     - Keep `scope_reopenings` byte-identical.
     - Keep the newer `base_sha`/`assessed_at`.
   - If your new `P`-number in `docs/OWNER_TASKS.md` collides with one merged from origin, renumber yours to the next free number and update your references to it.
   - Then recompute the stale list (§5.6), re-run `write && check`, status_sync and the gates. If the merge brought code, re-run the full suite; if it brought only records or docs, the fast gates suffice.
   - **If `hermes_status` exits 2 after a merge because of another session's row:**
     - If the error is a citation position you can verify by re-reading, correct only the position and name it in your report.
     - Otherwise stop and report.
3. **Push.** Run `git push origin HEAD:claude/cto-session-recovery-qinvkg`. If it is rejected as non-fast-forward, repeat step 2 and retry. Never force.
4. **Watch CI.** Use `gh pr checks 1207 --watch` if `gh` is installed. Otherwise use the GitHub MCP tools: `pull_request_read` with `get_check_runs`, then `get_job_logs`.
   - Drive every required check in `selfdev-policy.json` → `merge.required_checks` green by fixing root causes in files this session changed. Those checks include `test (ubuntu-latest)`, `hud-v2-build`, gitleaks, semgrep, pip-audit, bandit and `in-sync`; `AGENTS.md` calls the last one `lockfile-drift`.
   - A failure caused by another session's code, or one that is pre-existing, is reported, not chased.
   - A failing `github-advanced-security` check is noted, not chased.
5. **Post the verification.** After your final push, post one comment on #1207 with what you ran and the results, as `AGENTS.md` → "Evidence and completion" requires.

**Stop** when every bucket row is handled or blocked. Also stop and report when a gate cannot pass without going out of scope.

## 9. Final report
- **Counts that actually ran.**
  - tests passed, failed and skipped per suite, and pre-existing failures with their reproduction;
  - mutants killed and survived;
  - CI check states.
- **Rows moved.** For each: row, from → to (e.g. `needs_review` with recorded `partial` → `partial`), class, and a one-line reason.
- **Rows restamped** with their status kept.
- **Rows still `needs_review`.** This list must equal the blocked list. Give each reason: protected path, owner decision with its P-number, network, hardware or environment.
- **Owner decisions needed,** including a reminder that the two Codex-added `AGENTS.md` sections are still pending.
- **Buildable gaps found,** for the partial and missing prompts.
- **Documented known gaps.**
- **The new headline:** `python3.12 scripts/hermes_status.py summary`, before → after.
- **Links:** the commit SHAs you pushed and the #1207 comment.