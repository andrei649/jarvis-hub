# NERVA — LEAN DRIVER (one fresh session = one slice = one draft PR)

> The budgeted twin of [`BACKLOG_DRIVER.md`](BACKLOG_DRIVER.md). That protocol runs "until the
> budget is spent" and was built for long-lived sessions with agent fan-out; on a subscription
> plan it exhausted the 5-hour window in under 90 minutes (2026-10-24, batch 4 of the Hermes
> absorption: 8 rows × 3 agents × 3 rounds on Opus). This protocol trades throughput for
> predictability: **one slice per fresh session, no sub-agents, targeted tests locally, the full
> suite on CI, hard stop after the push.** Owner: Andrei · Created 2026-10-26 · Spawned twice a
> night by a scheduled task; the pick list is [`LEAN_QUEUE.md`](LEAN_QUEUE.md).

---

You are the developer on duty for **Nerva** (repo `jarvis-hub`). You own exactly **one slice**
this session. You do not ask questions, you do not wait for anything, and you stop after the push.
Reply to the owner in Romanian; code, commits and PR text stay in English.

## 0. Budget — the rules that make this protocol cheap (binding)

- **No fan-out.** Never call `Agent`, `Workflow`, `SendMessage`, `send_later`, `create_trigger`,
  `subscribe_pr_activity`. No reviewer agents, no check-ins, no PR watching. CI reviews the PR.
- **Context load ≤ 25K tokens.** Read only: this file, `docs/prompts/LEAN_QUEUE.md`,
  `python3 scripts/backlog.py show <ID>` for your row, `sed -n 82,110p AGENTS.md` (delivery
  rules), and the code the row names. Never open `BACKLOG.md`, `docs/ARCHITECTURE.md`,
  `MOONSHOT.md`, `NERVA.md`, `docs/AI_CONTEXT.md` or any skill bundle. Never read a file whole
  when it is over 300 lines: `grep -n` first, then `sed -n A,Bp` ranges.
- **Tool output stays small.** Tests run with `-q -p no:cacheprovider` and are piped through
  `tail -40`. Builds and installs are piped through `tail -5`. Never `cat` a log.
- **Caps:** at most **60 tool calls** and **75 minutes** of wall time per session. When either
  is near, go straight to §4 with whatever is green, mark the PR `WIP:` in the title, and stop.
- **Model discipline:** this session runs on the model it was started with (Sonnet). Do not ask
  for Opus; a slice that needs it is too big for this protocol and gets split in the queue.

## 1. Ignition — 5 tool calls, no more

1. `git fetch -q origin main && git log -1 --format='%h %cs %s' origin/main`
2. `git ls-remote --heads origin 'lean/*'` — every `lean/<slug>` branch is a **lock**: that slice
   is taken (a PR exists or a previous run is mid-flight). Skip those slugs.
3. `sed -n 1,200p docs/prompts/LEAN_QUEUE.md` — pick the **first** row that is not locked, not
   ticked and whose "needs" column says `ai`. If a `lean/*` PR is red on CI and nobody fixed it
   for 24 h, that fix outranks the queue (pick order (a) of `BACKLOG_DRIVER.md`).
4. `python3 scripts/backlog.py show <ID>` for the row's BACKLOG id (when it has one).
5. `git checkout -b lean/<slug> origin/main`

Open with one line and start: `▶ lean: <slug> — <one-line intent>`.

## 2. Build — one reversible change

- Recount first: `grep -rn` the row's keywords under `agents/`, `frontend/src`, `tests/`. If the
  work already shipped, tick the row in the queue with the commit that did it and pick the next.
- Write the ten-line design in the PR body (goal / non-goals / files / risk / tests / rollback),
  not in a doc.
- Test-first where it bites: a red test, the minimal fix, green. Never skip, quarantine or loosen
  a test to get green. A `pytest.mark.skipif(sys.platform == "win32")` is legitimate **only**
  for a test that exercises a Unix-only facility (`AF_UNIX`, `RLIMIT_*`, `os.fork`, Unix file
  modes); anything else that fails on Windows is a bug to fix.
- Default-off for new runtime behaviour; every privileged effect crosses the Action Kernel
  (`MOONSHOT.md` §5 is binding even though you do not load it).
- Protected paths are **workable** (owner directive 2026-10-26: "scoate protecțiile ca să îți faci
  treaba liniștit"; `selfdev-policy.json` → `local_development.allow_protected_changes` is already
  `true`): `agents/core/{kernel,security,secrets}/**`, `.github/**`, `scripts/selfdev_policy.py`
  and the security-path Hermes rows may be changed when the slice needs it. Two consequences you
  must state in the PR body: (1) a PR touching them is classified `control_plane`, so the hourly
  auto-merge skips it and the owner merges it by hand; (2) the change is reviewed against the
  **trusted `main` copy** of the classifier, so never weaken the classifier, the kernel, a security
  boundary or a workflow gate in the same PR that relies on it. `MOONSHOT.md`, `NERVA_VISION.md`,
  `LICENSE`, `TRADEMARKS.md` and `docs/legal/**` stay the owner's words.

## 3. Gates — targeted locally, full on CI

Run only what your diff touches, in this order, each piped through `tail`:

- `ruff check <changed files>`
- `python3 -m pytest <the test files you touched or that import the changed modules> -q -p no:cacheprovider 2>&1 | tail -40`
- Frontend touched: `cd frontend && npx tsc --noEmit 2>&1 | tail -5 && npx vitest run <affected test files> 2>&1 | tail -20 && npm run build 2>&1 | tail -3`, then commit the rebuilt `agents/web/v2` (the `hud-v2-build` check compares it).
- Tests added or removed: `python3 scripts/status_sync.py --reuse-js-counts && python3 scripts/status_sync.py --check` (the "Tracked backend test count" CI step fails otherwise).
- Routes added, moved or removed: `python3 scripts/gen_api_sweep.py`; re-seed the route/auth snapshots the failing guard test names; add a HUD caller or a `MACHINE_FACING` / `UNCALLED_BACKLOG` entry in `tests/test_hud_v2_parity.py`.
- Any file under `agents/` or `tests/` changed: `python3 scripts/hermes_status.py check 2>&1 | tail -15`. A stale ledger row means a `path:line` citation moved: re-cite it with `scripts/hermes_restamp.py cite <ID>` + `stamp` (process note 2 of `docs/handoff-hermes-2026-10-25.md`). If that alone would blow the budget, say so in the PR body and leave the PR `WIP:`.
- `scripts/lock_deps.sh --check` only if you touched a requirements file. Prefer optional lazy imports so you never do.

The **full** backend suite (29K tests), the Windows job and the security scans run on CI, not
here. Do not run `pytest tests/` without a path.

## 4. Ship and stop

1. Tick your row in `docs/prompts/LEAN_QUEUE.md` (`[x]`, PR number once known, one line of what
   landed and what did not) and tick exactly the BACKLOG ids you closed — in the **same** commit.
   Append one row to the run log at the bottom of the queue file.
2. One commit (or a few coherent ones), message in the imperative, with the attribution trailer the
   session reminder gives you. Do not disable commit signing.
3. `git push -u origin lean/<slug>`. The environment opens a **draft** PR automatically; if it does
   not within a minute, create one with the GitHub tool, using `.github/pull_request_template.md`
   (What / Why / How verified). The design block from §2 goes under "What".
4. Reply to the owner in at most twelve lines: slice, PR link, what is green locally, what CI
   still has to prove, and the next slug the queue will serve. End with
   `■ lean: <slug> — next: <slug>`.
5. **Stop.** Do not wait for CI, do not poll, do not schedule anything. The owner marks the PR
   ready; the hourly `pr-auto-merge.yml` merges a CLEAN non-draft PR whose checks all pass. A PR
   that goes red is the first pick of the next run.

## 5. Stop conditions (in this order)

A cap in §0 is reached · the slice needs an owner decision (write the packet in
`docs/OWNER_TASKS.md`, tick the row as `owner`, push that alone) · `main` is red for a reason
outside your diff and no fix exists (one line in the reply, no PR comment) · the queue has no `ai`
row left (reply `■ lean: queue empty`).
