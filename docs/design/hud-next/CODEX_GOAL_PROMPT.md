# Goal prompt for Codex

Paste the block below into Codex as the goal. Written 2026-11-25.

```text
GOAL
Bring Nerva (jarvis-hub) to a finished, publishable state: every open BACKLOG row closed or
explicitly handed to the owner, the Hermes absorption objective complete, and the HUD redesign
merged into main with green CI.

READ FIRST (do not load whole large files)
- AGENTS.md — the rules. They override this prompt where they are stricter.
- docs/design/hud-next/CODEX_HANDOFF.md — state of the HUD redesign, open items, how to run things.
- docs/hermes/autonomous-development-objective.md and docs/hermes/CAMPAIGN_HANDOFF.md — the Hermes
  campaign. Verify the handoff against the current checkout before trusting it.
- Query, never load: `scripts/backlog.py counts | open | show <ID>` and
  `scripts/ledger.py stats | clusters | list | show`.

STARTING STATE (2026-11-25)
- origin/main is 3a482575.
- Draft PR #1380 (codex/harness-agent-selector): 10 commits ahead of main. Four checks fail:
  test (ubuntu-latest), hud-v2-build, SAST (bandit — blocking gate), vault-containment.
- Draft PR #1386 (claude/hud-redesign, commit 82f03d5f): the HUD redesign, stacked on #1380. The
  same four checks fail, and the redesign adds 10 lint problems.
- BACKLOG: 299 rows, 260 done, 39 open (22 without an id, 7 DRA, 4 NWS, 2 GAP, 1 each HA, HEQ, RB, SEC).
- Hermes ledger: 697 capabilities, 476 work rows (258 update, 218 copy).

WORK, IN THIS ORDER
1. Make #1380 green. Read each failing check's log, fix the cause, and do not weaken a check to
   pass it. Then take it out of draft so it can merge.
2. Finish the HUD redesign on #1386:
   a. Rebase it onto main once #1380 has landed; rebuild the bundle (`npm run build` in frontend/)
      and commit it so hud-v2-build passes; fix the 10 lint problems.
   b. Fix the demo-mode leak: with ?demo=1 the run foot shows live hub channel and session counts
      without a "Demo sample" label. Add a test that fails on the current code.
   c. Fix the Kanban section in Work › Projects, which lost its container in the card looks.
   d. Bring HUD_V2_REMAINING.md, PHASE_B_PLAN.md line 7 and PHASE_B_INTERFACES.md §7 up to date
      with the last docket change, and update BACKLOG H18.x and mobile/PARITY.md for this work.
   e. Go through the remaining open items in CODEX_HANDOFF.md. Fix what breaks a size or look the
      plan promises; record the rest in HUD_V2_REMAINING.md. Then take #1386 out of draft.
3. Complete the Hermes objective: follow the active workflow in
   autonomous-development-objective.md until the frozen 697-contract objective is met and
   `needs_review` is 0. If you touch orchestrator.py, web.py or telegram.py, re-pin the drifted
   ledger rows and their path:line citations in the same change.
4. Close the BACKLOG: take the open rows from `scripts/backlog.py open` in priority order. A row
   that needs the owner (GitHub settings, device tests, the demo video, paid services) is not
   yours: write exactly what the owner must do in docs/OWNER_TASKS.md and move on.
5. After each merged unit, refresh the generated status
   (`scripts/status_sync.py`, then `--check`) in the same PR.

RULES
- One coherent, revertible unit per branch and PR. Tests ship with the change; use a failing test
  first for bug fixes. Run the tests that cover what you changed and report honestly what ran.
- Never touch port 8080 or start serve.py against the owner's live hub; no POST or PUT to it.
- No paid activation, no resuming a paused schedule, no deploy, no clearing the 35 fixture cards
  in the approval queue, no personal data to external services.
- Do not overwrite another agent's open PR branch. Local-first stays: frigga, ultron and howard
  never get a cloud fallback.
- AGENTS.md currently marks the Hermes campaign as local only (no commit, push or merge). The
  owner has since pushed the HUD work and wants this finished; if that line still stands when you
  start, ask the owner once whether publication is now allowed for Hermes work, then follow the
  answer.

DO NOT LOOP
Polish has no natural end. Before each unit, write down what "done" means in tests or promised
sizes. Verify once, on the surface you changed. A finding outside what the plan promises goes into
the ledger of open items, not into another round. If the same check fails three times for
different reasons, stop and report instead of trying a fourth fix.

DONE WHEN
- `scripts/backlog.py counts` shows 0 open rows that an agent can close, and every owner-only row
  has a concrete entry in docs/OWNER_TASKS.md.
- The Hermes objective's own completion test passes and the ledger is in sync.
- #1380 and #1386 are merged into main, CI on main is green, and status_sync --check passes.
- A final report lists what was done, what was verified and how, and what remains for the owner.
```
