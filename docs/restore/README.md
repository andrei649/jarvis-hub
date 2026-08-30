# Restoring the development gates removed in #981

On 2026-08-30 the owner de-gated the development workflow: every PR-blocking CI gate and
scan was removed so PRs stop waiting on ~20-minute check runs
([PR #981](https://github.com/andrei649/jarvis-hub/pull/981), squashed to `824ff18`).

This directory keeps that change **reversible**. If any gate is wanted back — one of them,
or all of them — everything needed is in
[`dev-gates-restore-2026-08-30.zip`](dev-gates-restore-2026-08-30.zip).

| | |
|---|---|
| De-gating commit on `main` | `824ff18` (squash of #981, merged 2026-08-30 09:09 UTC) |
| Last state with all gates present | `824ff18^` = `5e6e184` |
| Patches apply to | `7eb8772` — if `main` has drifted, use `git apply -3` (see below) |
| Scope | 58 files — **30 deleted**, 28 modified · **25,629 lines removed** |
| Archive contents | 12 per-gate patches, 1 full-restore patch, pristine copies of all 30 deleted files, JSON manifest |

Nothing here is wired into CI or the test suite — it is a dormant archive.

---

## Using it

```bash
unzip docs/restore/dev-gates-restore-2026-08-30.zip -d /tmp/restore
cd /tmp/restore/nerva-gates-restore-2026-08-30
cat 00-README.md          # full instructions, group table, caveats
```

`git apply` resolves the patch path relative to your **current directory**, and the archive
unzips outside the repo tree — so keep `$ARCHIVE` around and pass full paths:

```bash
ARCHIVE=/tmp/restore/nerva-gates-restore-2026-08-30
cd /path/to/jarvis-hub && git checkout -b restore/security-scans
```

**Restore one gate** (the usual case — patches never conflict with each other, so order
does not matter):

```bash
git apply "$ARCHIVE/groups/A-security-scans.patch"
```

**Restore everything:**

```bash
git apply "$ARCHIVE/restore-ALL.patch"
```

If `main` has drifted enough to conflict, use `git apply -3` for a 3-way merge (every diff
carries its blob index lines, so `-3` always has what it needs), or copy files straight out
of `deleted-files/` — those 30 were deleted outright, so there is nothing to merge.

---

## What each group brings back

| Group | Restores | Lines | PR checks re-added |
|---|---|--:|---|
| **A** `security-scans` | gitleaks, semgrep, pip-audit, bandit — all four **blocking** | 6,985 | `Secret scan (gitleaks)`, `SAST (semgrep)`, `Dependency audit (pip-audit)`, `SAST (bandit — blocking gate)` |
| **B** `ai-review` | 3 AI reviewers per PR | 79 | `review (correctness)`, `review (boundary)`, `review (tests)` |
| **C** `autonomy-boundary` | tier classifier holding "loosening" PRs for the owner, + per-PR auto-merge enable | 590 | `boundary`, `auto-merge` |
| **D** `nerva-movement-roadmap` | roadmap/ledger validation + all `check_nerva_*` scripts and tests — **the largest** | 16,393 | `validate` |
| **E** `lockfile-drift` | fails a PR editing `requirements*.txt` without regenerating the lock | 35 | `in-sync` |
| **F** `park-guard` | blocks PRs touching parked modules without an approved unpark | 48 | `parked-modules` |
| **G** `pre-commit-hooks` | local commit hooks: gitleaks, ruff, EOF fixer, large-file check | 32 | *(local only)* |
| **H** `ai-policy-pr-template` | R0–R3 risk policy + checker, evidence-receipt PR template, AGENTS.md ceremony | 1,314 | *(process only)* |
| **I** `codeowners` | owner review required on `.github/` and the gate scripts | 14 | *(needs branch protection)* |
| **J** `ci-full-pr-matrix` | puts Windows + sandbox + frontend + HUD + OpenAPI lanes **back on the PR path** | 72 | `test (windows-latest)`, `nerva-movement`, `sandbox-isolation`, `signal-layer-smoke (…)`, `frontend`, `hud-v2-build`, `openapi-types` |
| **K** `pr-triggers-7-workflows` | re-adds `pull_request:` to CodeQL, code-health, e2e, eval-nightly, smoke, thirdparty-drift, worldview | 45 | `Analyze (python)`, `analyze`, `e2e`, `server-boot`, `drift`, eval + worldview jobs |
| **L** `docs-and-counters` | the prose: "CI must be green before merging", maintainer review, no-direct-push, the OWNER_TASKS de-gate checklist, test counter 6832→7089 | 22 | — |

**Group J is what makes PRs slow again** — it moves the 20-minute `test (windows-latest)`
lane plus five other jobs off post-merge and back onto the PR critical path.

### Dependencies between groups

Patches never conflict with each other — no two groups touch the same file — but two groups
are **functionally** coupled:

- **D and J need each other; restore them together.** J's `nerva-movement` job runs
  `scripts/check_nerva_issue_movement.py`, which lives in D — without D the job exists but
  fails on a missing script. In the other direction, three tests in D's
  `tests/test_nerva_issue_movement.py` read the real `.github/workflows/ci.yml` and assert
  the `nerva-movement` job, `test.needs == ["nerva-movement"]` and the two-OS matrix, so
  restoring D alone leaves three failing tests. To take only one: restore J and delete its
  `nerva-movement` job, or restore D and delete those three tests.
- **G degrades without A (soft, not fatal).** The pre-commit gitleaks hook runs with no
  `--config`, so it auto-discovers `.gitleaks.toml` from group A. Without A the hook still
  runs but falls back to gitleaks' default ruleset, losing the `tests/`, `docs/` and
  `stark_ga4_property_id` allowlist — expect false positives on fixtures.

No other cross-group coupling exists: C, F and H are self-contained.

---

## The other half: branch protection

**Patches only restore files.** A restored workflow will run and post its check, but it
cannot *block* a merge until that check is marked required again under
**Settings → Branches / Rules for `main` → Require status checks to pass**. Re-add only the
check names from the groups you restored (the table above lists them per group).

The same applies to **Require review from Code Owners** (group I) and the CodeQL
merge-protection ruleset (group K).

While nothing is required, the hourly `pr-auto-merge.yml` sweep squash-merges any non-draft
PR GitHub reports as clean — keep work-in-progress as drafts.

---

## What the de-gating did *not* remove

- **Runtime/product security** — API auth, token store, sandbox containment, path-traversal
  guards, CSP headers. Untouched; only development-process gates were removed.
- **Kept automation** — `pr-auto-merge.yml`, the `@claude` bot, release, soak, reality,
  nightly evals, Dependabot, hash-pinned lockfiles.
- **`scripts/park_guard.py`** and **`scripts/lock_deps.sh`** — the scripts survive; only
  their CI enforcement workflows were deleted (groups F and E).
- **The heavy test lanes** — Windows tests, sandbox isolation, frontend/HUD suites, OpenAPI
  drift and CodeQL still run, just post-merge on `main` or on a schedule instead of on PRs.
