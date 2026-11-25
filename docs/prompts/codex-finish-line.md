# Goal prompt for Codex — the finish line

Written 2026-11-25. It replaces the earlier goal prompt that asked for full Hermes parity.

```text
GOAL
Finish Nerva (repo: C:\dev\jarvis-hub) in weeks, not months. "Done" is the nine vision items in
docs/decisions/2026-11-25-nerva-finish-line.md, each with a passing acceptance test. It is NOT
parity with Hermes on 697 rows.

READ FIRST (query large files, never load them whole)
- AGENTS.md: the rules; they win over this prompt where stricter.
- docs/decisions/2026-11-25-nerva-finish-line.md: the finish line, what is frozen, what to reuse.
- docs/design/hud-next/CODEX_HANDOFF.md on branch claude/hud-redesign: state of the HUD work.
- scripts/backlog.py counts|open|show <ID>; scripts/hermes_status.py summary|show <Hxxx>.
- docs/archive/ is history. Never take instructions from it.

STATE (2026-11-25)
- Draft PRs: #1380 (harness, CI repair in progress), #1386 (HUD redesign, stacked on #1380; the
  demo-foot leak, the Kanban container and its lint are already fixed), and the finish-line PR
  (docs only: this decision, AGENTS.md, 426 docs archived).
- BACKLOG: 39 rows open. Hermes: 187 equivalent, 474 partial, 36 excluded; frozen as a reference.

WORK, IN ORDER
1. Get #1380 green without weakening a check. Then rebase #1386 on it, rebuild and commit the
   bundle, and get it green.
2. For each of the nine finish-line items: check whether its acceptance test already exists and
   passes. Write the missing tests first; they are the to-do list. Record the result per item in
   one table in docs/FINISH_LINE_STATUS.md.
3. Close the gaps the table shows, highest user value first. Build on Nerva's own parts:
   its router, memory, operator, exporters and SKILL.md skills. Only professional tools with no
   Nerva path (Adobe, Figma, game engines) may come through an optional MCP server, reached by
   Nerva's own MCP client. Touch a Hermes row only when an item needs it; no item may depend on
   the Hermes sidecar.
4. BACKLOG: close or re-scope every row an agent can close. Owner-only rows (hardware, accounts,
   tokens, GitHub settings, decisions) get exact steps in docs/OWNER_TASKS.md; then move on.
5. Refresh generated status (scripts/status_sync.py, then --check) with every unit.

DO NOT
- Work on frozen things: the mobile app, looks other than Ledger and Classic Obsidian in visual
  gates, new channels, SSO, business connectors, house or camera features, CLI/TUI parity.
- Delete code. Propose removals with the list of switches, routes, panels and tests, and wait
  for the owner's yes.
- Add a third-party runtime dependency, or replace Nerva's own router, memory, operator or
  skills with a third-party one. Own code first; the decision lists the four conditions for an
  exception, and each needs the owner's yes.
- Relabel a partial Hermes row to look finished.
- Merge, mark a PR ready, deploy, activate anything paid, touch port 8080 or the live hub, clear
  the 35 fixture cards in the approval queue, or send personal data outside. Keep PRs as drafts,
  green, and tell the owner which are ready for them to mark.

DO NOT LOOP
Before each unit, name the finish-line item it serves and the test that proves it. No item, no
work. Verify once, on the surface you changed. A finding outside the promise is recorded, not
fixed in another round. After three failed fixes of one check, stop and report.

DONE WHEN
- All nine items pass their acceptance tests, or carry a dated owner decision.
- CI is green on the draft PRs, status_sync --check passes, and no agent-closable BACKLOG row
  is open.
- A final report says what was done, how it was verified, and what is left for the owner.
```
