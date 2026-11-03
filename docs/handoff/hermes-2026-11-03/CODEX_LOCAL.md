# Codex, working locally — setup and first task (2026-11-03)

Read this first, then `HANDOFF.md` in this folder (the state of Hermes batch 3 and what is left).
Repo rules for every assistant are in `AGENTS.md`; the code map is `docs/ARCHITECTURE.md`.

## 1. Bring the local repo up to date

```bash
git fetch origin --prune
git switch main && git pull --ff-only              # main = 68b351f6 (#1335) or newer
git switch claude/hermes-batch3 2>/dev/null \
  || git switch -c claude/hermes-batch3 --track origin/claude/hermes-batch3
git pull --ff-only                                  # head of draft PR #1336
git log --oneline -1                                # expect "Status counts and the batch 3 handoff…" or newer
```

PowerShell is the same commands (`git switch … ; if (-not $?) { git switch -c … }`).
Local leftovers from older sessions (`hermes/H*` branches) are not needed: everything is in
`claude/hermes-batch3`.

## 2. Environment (matches CI)

- **Python 3.12** (CI uses 3.12; 3.13 works for most of the suite but CI is the gate).
- **Node 22** for the HUD (`frontend/`).

```bash
python3.12 -m venv .venv
source .venv/bin/activate                           # Windows: .venv\Scripts\Activate.ps1
pip install --require-hashes -r requirements-beta.lock
pip install --require-hashes -r requirements-dev.lock
(cd frontend && npm ci)
```

Checks the CI runs on a PR (run the ones your change touches before every push):

```bash
ruff check .
JARVIS_TESTING=1 python -m pytest tests/<files> -q --timeout=90          # focused
JARVIS_TESTING=1 python -m pytest tests/ -n auto --dist loadfile --timeout=90 -q   # full
(cd frontend && npx tsc --noEmit && npx vitest run && npm run build)     # build output is committed: agents/web/v2
python -m bandit -r agents scripts -q -b .bandit-baseline.json
```

Notes:
- Run the full suite as a **normal (non-root) user**: root ignores file modes and hides failures.
- **Windows:** the Windows suite is broken on `main` (about 624 failures on 2026-10-29, and a 6 h
  hang on main pushes — an owner decision on a timeout + a WIN-2 task is pending). On Windows run
  focused suites; run the full suite in WSL/Linux, or let the PR's ubuntu CI be the gate.
- Environment-only failures you can ignore locally if your machine lacks docker/wasmtime/etc.:
  listed under "Test baseline" in `HANDOFF.md`.
- Never load `BACKLOG.md` (~1 MB) or `docs/hermes/assessment.json` raw; use
  `python scripts/backlog.py counts|open|show|sections|find` and
  `python scripts/hermes_status.py summary|list|show|check|write`.

## 3. First task: finish draft PR #1336 (Hermes batch 3)

Do these in order (details and the exact method are in `HANDOFF.md` → "What is left"):

1. Re-read the 29 ledger rows still `needs_review` (list in `HANDOFF.md`):
   `python scripts/hermes_status.py list --state needs_review` shows them plus the five built rows.
   Per row: `python scripts/hermes_restamp.py cite <ID>`, read `git diff origin/main...HEAD` for its
   changed evidence, correct only what the diff made false, then stamp with
   `python scripts/hermes_restamp.py stamp --patch <patch.json>`.
2. Write the new `equivalent` reviews for **H330, H389, H058, H202, H046** against
   `batch3-contracts.json` (this folder), with `path:line` citations into the current files.
3. `python scripts/hermes_status.py write && python scripts/hermes_status.py check`
   → expected **146/697**, `needs_review` 0.
4. `python scripts/status_sync.py --reuse-js-counts`.
5. BACKLOG: add the "Batch 3 (2026-11-03)" paragraph under HEQ-1, after "Batch 2 (2026-11-02)".
6. Full suite, push to `claude/hermes-batch3`, mark #1336 ready, get CI green, squash-merge,
   then refresh `BACKLOG.md` per `AGENTS.md` ("BACKLOG sync").

Commit messages and PR text in English; no model names in commits or PRs. Never skip, xfail or
loosen a test to get green; never force-push a shared branch.

## 4. After that

Next Hermes rows: `python scripts/hermes_status.py list --state partial` (or `--state missing`), in
the order `docs/prompts/BACKLOG_DRIVER.md` gives. The loop that worked is at the end of
`HANDOFF.md` (one worktree per row → fresh adversarial review per round → test that fails on the
old code → merge the rows → regenerate generated files → one review of the merged branch →
restamp every drifted ledger row → PR).

Owner-only items (do not start them): `docs/OWNER_TASKS.md`, the Windows CI decision, the B2B
questions D1–D7 (`docs/decisions/2026-10-14-nerva-business-suite-kickoff-questions.md`).
