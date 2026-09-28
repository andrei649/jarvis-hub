# Hermes parity: close the PARTIAL rows (ultracode)

You are working in `andrei649/jarvis-hub` on branch `claude/cto-session-recovery-qinvkg` (draft PR #1207). Your job is to move rows whose **live** status is `partial` to `equivalent`. A row becomes equivalent only when every open item is built and verified. When you cannot get a row that far, rewrite its `remaining` so it is shorter and exact.

You cannot see any earlier conversation. Every number in this prompt dates from 2026-09-28 and is only for orientation. Compute everything from the live repo.

Up to three other ultracode sessions may push to the same branch at the same time. They cover the `missing`, `equivalent` and `needs_review` buckets. Stay inside the partial bucket, and follow §7 for coordination.

## 0. Sync and load context (before any triage)

1. **Shell state does not carry over between Bash calls.** Start every command with `cd <repo root>` and `S=<your session scratchpad, absolute path>`. The snippets below assume both. Keep all scratch files in `$S`, outside the repo.
2. **Branch.** Run `git status` first. The tree must be clean, and you must never discard changes you did not make. Then:

   ```bash
   git fetch origin claude/cto-session-recovery-qinvkg
   git switch claude/cto-session-recovery-qinvkg      # or: git switch -c claude/cto-session-recovery-qinvkg --track origin/claude/cto-session-recovery-qinvkg
   git merge origin/claude/cto-session-recovery-qinvkg
   ```

   Never rebase and never force-push. If the harness started you on another branch, do not push that branch.
3. **Interpreters.** Check `python3 --version` and `python3.12 --version`. Here, `python`/`python3` is 3.11. Use **python3.12** for pytest, `status_sync.py` and `hermes_status.py`: `agents/core/media_providers.py:46` uses PEP 695 syntax, which 3.11 cannot parse. Bandit is installed only for 3.11.
4. **Starting headline.** Run `python3.12 scripts/hermes_status.py summary` and `python3.12 scripts/hermes_status.py check`, record both, and note the HEAD SHA as `BASE`.
5. **Context.** Load it the way `CLAUDE.md`, `AGENTS.md` and `docs/AI_CONTEXT.md` prescribe: Tier 0 + Tier 1, then one task bundle per row. Use the `jarvis-load-context` skill, and use `docs/ARCHITECTURE.md` to find where code lives. Never load the raw repo.
6. **Required reading:**
   - `docs/HERMES_SPRINT.md`: the definition of done (~:66-94) and the hash-refresh rule (~:238-260).
   - `docs/hermes/build-queue.md` :1-78, plus the `## HNNN` section and every linked critic note for any row you pick. Its "Now" column is not synced with the ledger, so trust `hermes_status.py`.
   - The known gaps in `docs/handoff/2026-09-28-codex-review/README.md` (~:75-99).
   - `docs/OWNER_TASKS.md` P27–P31. Use `grep -n '^## P2[7-9]\|^## P3[01]\|^### P' docs/OWNER_TASKS.md` and read only those sections.
   - `tests/test_hermes_sprint_status.py`.
7. **Querying.** Never load `BACKLOG.md` whole. Use `python3.12 scripts/backlog.py show HEQ-1`, `sections` or `find REGEX`. For the frozen inventory, use `python3.12 scripts/hermes_status.py show HNNN`. `scripts/ledger.py show` takes a name, not an id.

## 1. Hard rules (stop rules)

**Remote actions**
- Never merge, deploy, enable auto-merge, open a new PR, or mark PR #1207 ready.
- Push only with `git push origin HEAD:claude/cto-session-recovery-qinvkg`.
- `AGENTS.md:21-22` ("keep this sprint local") and the `selfdev-policy.json` description forbid pushing during this sprint. Both were added by Codex on 2026-09-27 (commit `beb2ee5a`) and are waiting on an owner decision (`docs/handoff/2026-09-28-codex-review/README.md` ~:103-111). The owner pasting this prompt is a publication request for this one branch and nothing else.
- The Codex resource plan (`AGENTS.md` ~:124-145) names Codex models, which do not apply to you. Keep its portable rules:
  - one writer per file;
  - subagents never commit or push; only the coordinator does;
  - full suites run serially at milestones;
  - no paid providers.

**Protected paths.** Never edit the paths listed in `selfdev-policy.json` → `protected_paths`:
- `selfdev-policy.json`, `scripts/selfdev_policy.py`
- `.github/**`
- `AGENTS.md`, `MAX.md`, `MOONSHOT.md`, `NERVA_VISION.md`
- `LICENSE`, `TRADEMARKS.md`, `docs/legal/**`
- `agents/core/kernel/**`, `agents/core/security/**`, `agents/core/secrets/**`, `agents/core/secret*`

`AGENTS.md` allows local edits to these paths, but a PR that touches them is `control_plane` and never auto-merges. The security rows belong to the owner.

- Before every commit, run `git diff --cached --name-only | python3.12 scripts/selfdev_policy.py classify --stdin`. It must report `"protected_hits": []`.
- If an item needs a protected path (for example, a new approval family in `kernel/registry.py`), classify it `security-protected` and record it for the owner.
- Privileged effects must go through `kernel.authorize` without changing kernel code.

**Skips**
- Skip items whose closure needs network, real hardware, macOS, a live paid or cloud service, or an owner decision. Record why, and cite the `docs/OWNER_TASKS.md` P-item if there is one.
- Building opt-in provider code with local tests is allowed. What you cannot claim is live-service proof: a code verdict is not a live proof (`HERMES_SPRINT.md` ~:90-94).
- Add a new owner task only when an item is truly owner-only.
- Do not add dependencies. If one is truly needed, classify the item `owner-decision`. A new dependency would also need a lock regeneration and the `in-sync` check.
- The failing `github-advanced-security` check (P29) belongs to the owner. Do not try to fix it.

**Ledger integrity**
- Never write `excluded`.
- Never add, remove or edit `scope_reopenings` or any `skip` decision.
- Never edit the frozen inventory `docs/research/2026-09-07-hermes-absorption-ledger.json`.
- Never hand-edit generated files (`HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md`, `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `project-status.json`). Regenerate them.

**Test pins**
- `tests/test_hermes_sprint_status.py` pins H515, H598, H566, H660 and H595 as `partial`. Promote one only with evidence that closes its whole contract, a closure verifier that explicitly confirms it, and an edit to that test in the same commit with a justification.
- The same file requires H456, H477 and H510 to each keep at least one citation that resolves in a still-intact pinned file. It also requires at least 50 rows with basis `reviewed`. If you rewrite H510, keep such a citation.

**Git hygiene**
- Stage only files you changed (`git add <paths>`, never `git add -A`). Preserve other sessions' work.
- Never use `git checkout -- <file>`, `git restore`, `git stash` or `git reset --hard` on files that hold uncommitted work.

**Local-first** (`MOONSHOT.md` §5)
- Cloud stays opt-in.
- `frigga`, `ultron` and `howard` stay strictly local, with no cloud fallback (`agents/core/llm/hybrid_router.py`).
- Every feature ships with tests.

## 2. Build the live listing (never hardcode rows)

Run from the repo root:

```bash
python3.12 - <<'PY' > "$S/partial.json"
import json, sys, collections; sys.path.insert(0, "scripts")
import hermes_status as hs
ledger, data = hs.load(); rows = hs.assess(ledger, data)
caps = ledger["capabilities"]
pins = collections.Counter(e["path"] for r in rows for e in r["evidence"])
out = [dict(r, original=caps[int(r["id"][1:]) - 1],
            pin_load={e["path"]: pins[e["path"]] for e in r["evidence"]})
       for r in rows if r["status"] == "partial"]
print(json.dumps(out, ensure_ascii=False, indent=1))
PY
```

There are two kinds of partial row:

- **`reviewed`**: `remaining` names the gaps.
- **`baseline_2026-09-07`**: there is no evidence, and `remaining` is only a placeholder. Take the requirement from the original row (`hermes`, `nerva_state`, `nerva_evidence`, `rationale`, `governance`, `depends_on`, `effort`) and re-read the code. `nerva_evidence` may cite paths that no longer exist.

Recording an honest review of a baseline row counts as progress even when its status stays partial, because its basis becomes `reviewed`. Such a review needs at least one evidence file. If a baseline row is honestly `missing`, record it as `missing`.

Rows that are `needs_review` (`stale_evidence` or `scope_reopened`) belong to the needs_review session. Leave them alone, except the ones your own edits demote (§4). Recompute the listing after every merge from origin: rows can enter or leave the bucket as other sessions push.

Take a stale snapshot now and again after every merge from origin:

```bash
python3.12 scripts/hermes_status.py list --state needs_review --limit 697 > "$S/stale_before.txt"
git rev-parse HEAD > "$S/snap_sha"
```

## 3. Method (ultracode: orchestrate with workflows)

1. **Triage fan-out (read-only, parallel).** Split each row's open requirement into atomic items. Classify every item as one of:
   - `buildable-now`
   - `owner-decision`
   - `network`
   - `hardware`
   - `security-protected`
   - `depends-on-row:HNNN`

   Each item carries a `path:line` that was verified by opening the file, an S/M/L estimate, and the frozen requirement it serves. A skeptic agent re-checks every item that claims "already done".

2. **Ranked plan** (`$S/plan.md`).
   - Group rows by cluster and by shared target code or shared evidence files, so coupled rows are built together.
   - Put **closest to equivalent** first: all items buildable, fewest items, lowest cost.
   - Rows with any blocked item come later, and only to shrink their `remaining`.
   - Prefer designs that do not edit heavily pinned files (`pin_load`), because each such edit demotes every row that pins the file (§4). Never put code in the wrong place just to avoid a restamp.
   - For each row or cluster, record the goal, non-goals, likely paths, tests, rollback and dependencies (`AGENTS.md`, Delivery workflow).

3. **Per row, or per tightly coupled cluster, one at a time:**
   - **Design.** S/M: inline design. L/XL: a judge panel scores at least 2 independent designs against three criteria: the frozen requirement, local-first, and the Action Kernel rule.
   - **Red-first build.** Write the tests first and watch them fail for the right reason, then implement. Use the `jarvis-write-test` skill. For any HTTP change, use `jarvis-add-route`: new routes go in `agents/core/routers/<domain>.py`, never inline `@app.*`, and they must be auth-guarded. `tests/_snapshots/route_auth.json` has no updater and is edited by hand. Never add a route to `INTENTIONALLY_OPEN` without a written reason.
   - **Definition of done** (`HERMES_SPRINT.md` ~:66-94). The whole accepted contract must be implemented, including a usable entry point (CLI, HUD or API with a client) and its authority limits. A class, adapter, manifest, route without a client, or demo with fake data does not close a row.
   - **Closure verifier.** An independent agent checks every open item against the frozen requirement and cites `path:line` locations it has content-verified.
   - **Adversarial hunter.** An independent agent attacks the new code: edge cases, governance bypass, retries and idempotency, error paths.
   - **Fix rounds** until neither agent reports a MAJOR or MINOR regression. If a row does not converge after 4 rounds, stop on it: put the open findings into its `remaining` and move on.
     - Record NITs and rare pre-existing issues as known gaps, in the row's build-queue section if it has one and in the final report.
     - A gap inside the row's contract keeps the row partial.
   - **Mutation testing.** For each new guard or branch, apply a targeted mutant, confirm that a new test fails, then revert. Run mutants in a disposable worktree (`git worktree add "$S/mut" HEAD`, then `git worktree remove "$S/mut"`), or save a copy of the file to `$S` and restore it from there. Report how many mutants were killed and how many survived.

## 4. Ledger honesty (`docs/hermes/assessment.json`)

**Review format.** Change status only on evidence. A review has exactly these keys:

```
{id, row_sha256, status, summary, remaining, evidence:[{path, sha256}]}
```

- `row_sha256 = hs.digest(ledger["capabilities"][n-1])`.
- Each evidence `sha256 = hs.file_digest(hs.REPO / path)`. It takes a `Path`, not a str.
- `status` must be `equivalent`, `partial` or `missing`.
- Keep reviews sorted by id.
- Serialize with `json.dumps(d, ensure_ascii=False, indent=2) + "\n"`.
- Set `base_sha` to the 40-hex HEAD you read and `assessed_at` to the current UTC time, ending in `Z`.
- Write `summary` and `remaining` in the language of the row's existing entry. The file mixes English and Romanian, and recent reviews are English.

**Pin choice.** Pin the narrowest files that actually support the claim. Every pin in a hot file makes the row fragile.

**Equivalent requires:**
- source evidence (`agents/`, `frontend/src/`, `mobile/src/` or `desktop/`, not under `/test/`);
- test evidence (`tests/…` or `/test/`);
- `remaining == ""`.

A row that stays partial gets a precise `remaining` that lists each open item with its class. Never use a whitespace-only `remaining`.

**Citations**
- Verify every `path:line` citation by content. The checker only confirms that the first cited line exists and is not blank.
- A citation to a pinned file that does not resolve is fatal: every `hermes_status.py` command exits 2. Run `check` after every ledger edit.

**Drift.** Do this after each of your changes and before the next merge from origin. List the rows your edit made stale:

```bash
python3.12 - "$(cat "$S/snap_sha")" <<'PY'
import sys, subprocess; sys.path.insert(0, "scripts")
import hermes_status as hs
changed = set(subprocess.run(["git", "diff", "--name-only", sys.argv[1]],
                             capture_output=True, text=True, check=True).stdout.split())
ledger, data = hs.load()
for r in hs.assess(ledger, data):
    if r["basis"] != "stale_evidence": continue
    hit = [e["path"] for e in r["evidence"] if e["path"] in changed and not (
        (hs.REPO / e["path"]).is_file() and hs.file_digest(hs.REPO / e["path"]) == e["sha256"])]
    if hit: print(r["id"], *hit)
PY
```

Cross-check the result against a diff of the current `needs_review` list with `$S/stale_before.txt`. Each listed row may be in any bucket, equivalent included. You own it, so for each one:

1. **Find the pinned version.** For each evidence path, find the version whose digest equals the pinned `sha256`. Usually `git show HEAD:<path>` (before your edit) matches. Otherwise walk `git log --format=%H -- <path>` and hash `git show <sha>:<path>` after decoding UTF-8 and normalizing `\r\n` and `\r` to `\n`. The matching version can be older than the last restamp base (lesson from the 2026-09-28 recovery). If no version matches, re-review the row from scratch.
2. **Map citations.** Map each cited line by content from that version to the current file.
3. **Re-read the claim.** Then restamp the hashes and line numbers, rewrite the entry, or downgrade it honestly.

Leave rows that were already stale, or that a merge from origin made stale, to their authors or to the needs_review pass. Before restamping a row, fetch and check that another session has not already done it. Never refresh a hash without re-reviewing the row.

## 5. Records (in the same commit as the code)

- **Ledger reports.** Update the assessment, then run `python3.12 scripts/hermes_status.py write && python3.12 scripts/hermes_status.py check`.
- **`BACKLOG.md`.** Add a dated bullet under `## Current sprint: Hermes capability equivalence — 2026-09-09`.
  - Find the heading with `grep -n '^## Current sprint: Hermes capability equivalence' BACKLOG.md` (~line 15). Do not rely on `backlog.py sections`: its `L1817` is the section's first checkbox row, not the heading.
  - Dated bullets sit directly under the heading, newest first.
  - The bullet gives rows moved, the test-count delta and the new headline.
  - If you touch HEQ-1's own text (~`BACKLOG.md:1865`), correct its outdated "590 accepted and 107 intentionally excluded" to the live numbers.
- **`docs/hermes/build-queue.md`,** for rows that appear there:
  - reduce closed rows to a one-line stub and remove them from the queue table;
  - update the "Now" column;
  - update critic-note **Done** for rows you touched.
- **Test manual.** In the matching chapter under `docs/test-manual/`, add manual steps for any behavior a user can see.
- **Endpoint or HUD changes.** If a user-facing endpoint or HUD capability changed:
  - update `mobile/PARITY.md`, or record the mobile gap;
  - wire the HUD V2 surface, or update `docs/design/HUD_V2_REMAINING.md`.
- **Generated status.**
  - Run `python3.12 scripts/status_sync.py --reuse-js-counts`. It re-collects backend tests. Do not run it inside pytest.
  - Then run `python3.12 scripts/status_sync.py --check --reuse-test-counts`.
  - If frontend or mobile tests changed, run `npm ci` in both `frontend/` and `mobile/` first and drop `--reuse-js-counts`, because it runs both vitest and jest.
- **Test manual check.** Run `python3.12 scripts/check_test_manual.py`. It always exits 0, so read the output. Only the 2 pre-existing flagged groups may remain: `06-standalone-pages.md` worldview paths and `08-security-privacy.md:130`.

## 6. Gates (report honestly what actually ran)

```bash
ruff check .
python3.11 -m bandit -r agents scripts -q -b .bandit-baseline.json
mkdir -p "$S/tmp"
JARVIS_TESTING=1 TMPDIR="$S/tmp" python3.12 -m pytest <targeted tests> -q
python3.12 -m pytest tests/test_hermes_sprint_status.py -q
# serially, at milestones and before each push:
JARVIS_TESTING=1 TMPDIR="$S/tmp" python3.12 -m pytest tests/ -n auto --dist loadfile --timeout=90 -q --tb=short --junitxml="$S/pytest-junit.xml"
python3.12 scripts/status_sync.py --verify-test-count backend --test-result "$S/pytest-junit.xml"
# if routes changed: regenerate the sweep and snapshots, then check
python3.12 scripts/gen_api_sweep.py && python3.12 tests/test_route_parity_guard.py --update && python3.12 tests/test_openapi_parity_guard.py --update
python3.12 scripts/gen_api_sweep.py --check && python3.12 -m pytest tests/test_route_auth_matrix.py tests/test_api_sweep_current.py -q
# if frontend touched (commit the rebuilt agents/web/v2, then the diff must be empty):
cd frontend && npm ci && npx tsc --noEmit && npm run typecheck:e2e && npx vitest run && npm run build && cd .. && git diff --exit-code -- agents/web/v2
# if mobile touched:
cd mobile && npm ci && npm test && cd ..
```

`conftest.py` gives each test process its own `JARVIS_HOME`. `desktop/src-tauri` changes need `cargo check` if the toolchain is present; otherwise report it as not run. Gitleaks, semgrep and pip-audit run in CI. Never describe a suite you did not run as passing.

## 7. Shared branch, push and CI

Before every push:

1. Run `git fetch origin && git merge origin/claude/cto-session-recovery-qinvkg`. Never rebase or force-push.
2. **Resolve conflicts:**
   - `assessment.json`: merge reviews by id and keep them sorted. Re-read any id that both sides changed. Keep `scope_reopenings` exactly as it was, and take the newest `base_sha`/`assessed_at`. Then run `hermes_status.py summary`, which fails on duplicates and schema errors.
   - `HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md`: regenerate with `hermes_status.py write`.
   - `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `project-status.json`: regenerate with `status_sync`.
   - `BACKLOG.md`, `build-queue.md`: keep both sides' bullets and notes.
3. Re-run §5 and §6. Then re-take the stale snapshot (§2), because rows the merge made stale are not yours.

Commit once per row or cluster, and push soon after each commit to keep conflict windows short. Commit messages end with the attribution trailers your session's system prompt specifies.

After pushing, watch PR #1207's checks with `gh pr checks 1207` or the GitHub MCP tools. Drive every check that your commits affect to green, except `github-advanced-security`. If another session's push broke a check, report it and do not fix their code. If one of your commits breaks CI and you cannot fix it, revert it with a new commit.

Post one PR comment, "How verified", saying what you ran. Do not rewrite the shared PR body.

## 8. Final report

- Freshness: goal, `BASE`, final HEAD SHA, changed paths, next action, generation time.
- Starting headline and new headline (`hermes_status.py summary`). Note that the headline also includes other sessions' work.
- Rows you moved, as `HNNN from→to`, with evidence files.
- Rows that stayed partial, with their new `remaining`. Baseline rows you reviewed without moving them.
- Blocked items grouped by class, with the reason and any OWNER_TASKS P-item.
- Rows your edits demoted, and whether each was restamped or downgraded.
- Owner decisions needed.
- Known gaps.
- Mutation results (killed and survived).
- Exact gate and CI results, with counts. List anything not run as not run.