# Nerva finish line — owner decision, 2026-11-25

**Decision.** "Done" for Nerva means *the owner's vision works*, not *parity with Hermes on 697
rows*. The owner agreed to this on 2026-11-25 to finish the project in weeks instead of months.
This document supersedes the completion goal of the Hermes campaign
(`docs/hermes/autonomous-development-objective.md`) and of BACKLOG row HEQ-1.

## Why

On 2026-11-25 the Hermes ledger stood at 187 equivalent, 474 partial and 36 excluded of 697. Between
2026-11-11 and 2026-11-25 it moved from 161 to 187 equivalent, about 13 rows a week. At that pace
the remaining rows take most of a year, and many cannot close without hardware or accounts the
agents do not have. Meanwhile the repo carries 316 `JARVIS_*` switches, 118 router files and 74 HUD
panels, much of it default-off code the owner does not use.

## The finish line

Nerva is finished when each item below has a passing acceptance test in the repo, or a dated owner
decision that drops it. Each test must exercise the real path end to end on the owner's machine
profile (local models, no paid service).

| # | Vision item | Accepted when |
|---|---|---|
| 1 | Many AIs in one place, local and cloud | One conversation can route turns to a local model and, with consent, to a cloud model; the HUD shows which ran where |
| 2 | Long-term, human-like memory tied to the Obsidian vault | A fact stated in one session is recalled in a later one with its source; the owner can forget it; vault notes are searchable from chat |
| 3 | Several tasks at once | Two agent tasks run in parallel, each with visible status, and one can be stopped without stopping the other |
| 4 | Self-improvement | A reviewed lesson or skill written by Nerva changes a later run's behaviour, inside `selfdev-policy.json` |
| 5 | Learns and develops new skills | A new `SKILL.md` skill can be authored, reviewed and used without a code change |
| 6 | Uses a device | A browser task runs end to end through the governed operator, with approval where the action has a side effect |
| 7 | Basic tools: Word, Excel, browser | A document and a spreadsheet are created and edited from chat |
| 8 | Professional tools: Blender, Adobe, game engines | One working Blender path; the others reach Nerva through MCP servers, each with one smoke test |
| 9 | Calm, visual interface | The Ledger HUD is on main with green CI; themes other than Ledger are best effort |

Plus the hygiene line: CI on main green, `scripts/status_sync.py --check` passing, and every
agent-closable BACKLOG row closed or re-scoped.

## What changes

### Hermes: the ledger becomes a reference, not a checklist

- No more work whose only purpose is to move a Hermes row from `partial` to `equivalent`.
- A row is worked on only when a finish-line item needs it. Statuses stay honest: `partial` rows
  stay `partial`, with their remaining work recorded. Nothing is relabelled to look finished.
- Areas that serve the finish line and may still receive work (241 partial rows on 2026-11-25, of
  which only the ones a finish-line test needs are in scope): memory, agent-core, tools, skills,
  providers, automation, media, mcp, security, web.
- Areas frozen as they are (233 partial rows): cli, tui, gateway, platforms (Telegram stays
  maintained), env, config, editor-acp, agent-interop, extensions, feature-pages, user-journeys,
  upstream-delta, and the Tauri-shell rows of desktop.
- BACKLOG row HEQ-1 is re-scoped to this decision.

### Reuse before building

| Need | Use | Instead of |
|---|---|---|
| Tools and integrations (browser, files, Office, Blender, Figma, Adobe) | existing MCP servers, through Nerva's MCP client | one hand-written connector per tool |
| A new skill | the `SKILL.md` format already in `skills/` | new Python modules |
| Device use | Playwright MCP and provider computer-use tools behind the governed operator | extending the custom operator |
| What Hermes already does well | the governed Hermes sidecar | re-implementing it row by row |

Replacing the model router (LiteLLM, OpenRouter) or the memory stack (mem0, Letta, Graphiti) is
**not** decided. Each needs a short evaluation of how deeply the current code is wired before
anyone starts; do not begin either without that note and the owner's yes.

### Frozen until the desktop finish line is reached

- **Mobile app.** No new mobile work. A HUD change records "mobile: frozen, 2026-11-25" in
  `mobile/PARITY.md` instead of porting.
- **Themes.** Automated visual gates cover Ledger (default) and Classic Obsidian. The other looks
  stay installed and switchable; a defect in them is recorded, not gated.
- **New channels and surfaces.** No new messaging platform, SSO, business connector or house/camera
  work.

### Proposed for removal — needs one owner yes before any code is deleted

Nothing is deleted by this decision. These default-off areas are candidates; an agent proposing a
removal lists the switches, routes, panels and tests it would delete, and waits for the owner:

- house brain and camera intelligence;
- messaging platforms other than Telegram (SMS, Matrix, Slack, Discord);
- native OIDC sign-in and the business connectors (NWS-8, NWS-9);
- worldview and other surfaces the owner confirms unused.

### Documents

426 historical plans, handoffs and run notes moved to `docs/archive/` on 2026-11-25 (see
`docs/archive/README.md`). They are history, never instructions.

## Working rules that keep this short

1. Before a unit of work, name the finish-line item it serves and the test that proves it. No item,
   no work.
2. Verify once, on the surface changed. A finding outside the promise is recorded, not fixed in
   another round.
3. Three failed fixes of the same check: stop and report.
4. Anything that needs the owner (hardware, accounts, tokens, GitHub settings, a decision) goes to
   `docs/OWNER_TASKS.md` with exact steps, and work moves on.
