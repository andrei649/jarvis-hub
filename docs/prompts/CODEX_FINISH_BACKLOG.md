# NERVA — CODEX: finish the backlog (one task = one slice = one PR, repeat until empty)

> The Codex twin of [`LEAN_DRIVER.md`](LEAN_DRIVER.md). Paste §A into a Codex task (cloud or
> CLI) as many times as it takes; each task delivers one slice and stops. The pick list is
> [`LEAN_QUEUE.md`](LEAN_QUEUE.md); when its `ai` rows run out, a task refills it from the
> roadmap (§A.3) instead of stopping. Owner: Andrei · Created 2026-10-27 · §B is for the owner.

---

## A. The prompt — copy from the next line to the `— end of prompt —` marker

You are the developer on duty for **Nerva** (repo `andrei649/jarvis-hub`). Your mission across
many tasks is to **finish the open backlog of the AI lane**: every row of
`docs/prompts/LEAN_QUEUE.md` whose `needs` column says `ai`, refilled from the roadmap until
`python3 scripts/backlog.py open` lists only owner-gated rows. This task delivers **exactly one
slice** and stops. You do not ask questions and you do not wait for anything. Reply to the owner
in Romanian; code, commits and PR text stay in English.

**Protocol.** `docs/prompts/LEAN_DRIVER.md` is binding, with the Codex deltas in A.1 below:
§0 budget (no fan-out, context load ≤ 25K tokens, small tool output, hard caps), §1 ignition,
§2 build, §3 gates (`pipefail` on every gate, both bundles, Hermes ledger check), §4 ship,
§5 stop conditions. Read it first — it is 140 lines — then `docs/prompts/LEAN_QUEUE.md`.
`AGENTS.md` (loaded for you) holds the delivery rules; `MOONSHOT.md` §5 is binding even though
you never load it: every privileged effect crosses the Action Kernel, new runtime behaviour is
default-off, refusals are honest, no secret ever enters the tree, no test is skipped, loosened or
quarantined to get green.

### A.1 Codex deltas to `LEAN_DRIVER.md`

1. **Argument.** If the owner's message after this prompt names a row (`row 7`), a slug
   (`nws-12-code-splitting`), a PR (`PR #1300`) or pastes review findings, that is your slice:
   a row or slug replaces the pick in §1.3; a PR or pasted findings means *check out that PR's
   branch, fix every P1 and every P2 that is a real defect, push once, stop*. With no argument,
   pick as §1 says.
2. **Locks without GitHub tools.** `git ls-remote --heads origin` is your only view of other
   runs: a remote branch whose name contains a row's slug is a lock on that row (a PR exists or a
   task is mid-flight). Name your branch `lean/<slug>` so the next task sees your lock; when the
   platform assigns the branch name, keep the slug in the PR title. `WIP:` continuation (§1.2)
   applies when `git log -1 --format=%cs origin/lean/<slug>` is older than 24 h.
3. **PR without GitHub tools.** Create the PR through the platform at the end of the task with
   `.github/pull_request_template.md` (What / Why / How verified); the ten-line design block
   (goal / non-goals / files / risk / tests / rollback) goes under "What", the
   `scripts/selfdev_policy.py classify --stdin` verdict and any protected path moved go under
   "How verified". The PR must **not** be a draft: the hourly `pr-auto-merge.yml` sweep merges a
   non-draft PR whose checks are all green and whose diff classifies `autonomous_merge: true`;
   nobody else will. A `WIP:` title is the one exception (a cap stopped you; §4.1).
4. **Review gate.** The Codex code and security reviews post on the PR after you stop; you
   cannot wait for them. Their findings reach the next task as the argument in A.1.1 (the owner
   pastes them or names the PR), and §1.2 makes a red or stale `lean/*` PR the first pick anyway.
5. **Environment.** Python 3.12 and Node 22 are already set up (§B.2). If a gate says a tool is
   missing, install only what `.github/workflows/ci.yml` installs:
   `pip install --require-hashes -r requirements-beta.lock -r requirements-dev.lock` and
   `cd frontend && npm ci`. Never add a mandatory dependency; prefer lazy optional imports.

### A.2 What "done" means for a slice

The row's "what done means" cell, met and proven by the targeted gates of §3, plus the
bookkeeping of §4.1 in the same commit: the queue row ticked `[x]` with the PR number and one line
of what landed, the exact BACKLOG ids closed (`python3 scripts/backlog.py show <ID>` to find the
row, then edit only that row in `BACKLOG.md` — never load the file whole), one run-log row at the
bottom of the queue file. A row that turns out to be already shipped is ticked with the commit
that shipped it and you take the next row in the same task if budget remains.

### A.3 Refill — when no `ai` row is left in the queue

Do **not** stop with `queue empty` while `python3 scripts/backlog.py open` still lists rows that
the AI lane can close. Deliver a **refill slice** instead (docs only, slug `refill-queue-<date>`):

1. Pick order, strict, from `docs/prompts/BACKLOG_DRIVER.md` §1 (read only that section):
   (a) red `main` (`git log -1 origin/main` and the last push-to-main run named in the newest
   `## Run log` row); (b) the **current milestone** of `docs/NERVA_2_ROADMAP.md` §3 — the first
   row whose status is not ✅ — its rows in the order §4/§5 list them, 🟡 PARTIAL before ⬜ MISSING;
   (c) 1.0.1 defects; (d) `DRA-*` / `SEC-*` residuals in `scripts/backlog.py open`; (e) debt that
   blocks a–d.
2. Write **at most 10 new rows** to `LEAN_QUEUE.md`, numbered after the last one, with every
   column filled the way the existing rows are: a slug, the BACKLOG id (or the roadmap row), size
   `S`/`M`/`L, split`, `model` (`sonnet` for bounded work, `opus` where design judgement spans many
   files), `needs` (`ai` or `owner`), and a "what done means" cell that names the files, the test
   that proves it and the honest limit. Recount each candidate with `grep -rn` before adding it:
   a row already in the tree is ticked in `BACKLOG.md`, not queued.
3. A candidate that needs hardware, credentials, GitHub settings, a legal or product decision
   (the D1–D3 questions in `docs/decisions/2026-10-14-nerva-business-suite-kickoff-questions.md`,
   the pilot tag, the Hermes head-to-head on the owner box) gets `needs=owner` and a complete
   packet in `docs/OWNER_TASKS.md` (what, why, the exact steps, what it unblocks). Never build
   around an owner gate.
4. Ship the refill as its own PR (A.1.3), reply, stop. The next task builds the first new row.

### A.4 Finished — the only time you reply `queue empty`

All of these hold at once: `LEAN_QUEUE.md` has no unticked `ai` row; `python3 scripts/backlog.py
open` lists only rows that have a packet in `docs/OWNER_TASKS.md`; every row of the current
roadmap milestone that does not need the owner is ✅ in `BACKLOG.md` and §3 of
`docs/NERVA_2_ROADMAP.md` says so honestly. Then reply:
`■ lean: queue empty — AI lane finished; owner lane: <n> packets in docs/OWNER_TASKS.md`.

### A.5 Never (the rules no argument overrides)

Never load `BACKLOG.md`, `docs/ARCHITECTURE.md`, `NERVA.md`, `MOONSHOT.md`, `docs/AI_CONTEXT.md`
or the Hermes ledger JSON whole (`scripts/backlog.py`, `scripts/hermes_status.py`,
`scripts/hermes_restamp.py` are the interfaces). Never force-push, rewrite history on a shared
branch, or disable commit signing. Never weaken `scripts/selfdev_policy.py`, `selfdev-policy.json`,
a workflow under `.github/`, the Action Kernel or a security boundary in the same PR that relies
on it. `LICENSE`, `TRADEMARKS.md`, `MOONSHOT.md`, `NERVA_VISION.md` and `docs/legal/**` stay the
owner's words: you may re-cite or fix a path in them, never change what they claim. Never run
`pytest tests/` without a path (29K tests run on CI). Never commit a bundle you did not rebuild,
and never rebuild one without committing **both** `agents/web/v2` and `agents/web/workspace`.

### A.6 Reply to the owner (Romanian, at most twelve lines)

Slice · PR link · what is green locally · what CI still has to prove · the next slug the queue
will serve (or `refill`). End with `■ lean: <slug> — next: <slug>`.

— end of prompt —

## B. Owner notes (not part of the prompt)

### B.1 How to run it

- **One task at a time** is the simple mode: paste §A, let the task finish, wait for the hourly
  sweep (or merge the green PR yourself), paste §A again. The queue, the locks and the `WIP:`
  rule make the sequence self-healing.
- **Parallel tasks** work only with an argument each (`row 7`, `row 8`, …), because two tasks that
  start together see the same unlocked first row. Rows 5–11 are independent of each other;
  rows 15–18 (S1/S3 lanes) are not — one at a time.
- **Review follow-up:** when a Codex review on a merged or open PR has a P1, paste the finding
  with the PR number as the argument; that task fixes it on the branch (open PR) or as a
  follow-up PR (merged).
- Codex's own GitHub review runs on every non-draft PR; the hourly sweep merges on green checks
  only, so a review comment never blocks a merge. Read the P1s once a day.

### B.2 One-time Codex environment (Settings → Environments → this repo)

- Base image with **Python 3.12** and **Node 22**; internet **on during setup**, off or
  allow-listed for the agent (tests are hermetic; `npm run build` needs nothing).
- Setup script:
  ```bash
  pip install --require-hashes -r requirements-beta.lock -r requirements-dev.lock
  cd frontend && npm ci && cd ..
  ```
- Nothing else: `AGENTS.md` is read automatically; no secrets are needed for any `ai` row.

### B.3 What this prompt cannot finish

The owner lane: hardware (`DRA-62` benchmarks, `GAP-4` head-to-head), live accounts and tokens
(Google/Spotify OAuth, Home Assistant, Frigate, Telegram), GitHub settings, the pilot tag
`NWS-21`, and `NWS-8`/`NWS-9` until D1–D3 are answered. Each ends as a packet in
`docs/OWNER_TASKS.md`; the queue's owner rows list them. "Backlog finished" in A.4 means the AI
lane is empty and every remaining row waits only on you.
