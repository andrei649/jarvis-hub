# HUD Redesign Plan — human-friendly workspace

> ⚠️ **HISTORICAL — SUPERSEDED by the HUD V2 program** (shipped 2026-06-08 as the default UI):
> see [`docs/design/HUD_V2_BRIEF.md`](design/HUD_V2_BRIEF.md) and
> [`docs/design/HUD_V2_REMAINING.md`](design/HUD_V2_REMAINING.md). Kept as provenance.

> Goal (from user): the HUD has too many cryptic buttons, some don't work, and
> **most features have no UI at all** — "if it's not there, I can't work with it."
> Make it human-friendly and give **every** backend feature a discoverable home.

## Decisions (locked)
- **Agents stay on the LEFT rail** — remove the duplicate right-rail `AgentsGrid`.
- **NetworkBrain** (agent graph) → a **toggle** (off by default) and/or a faint
  background layer, so the **chat owns the center**.
- **Every feature gets a home** via a single **Console** overlay (below).
- A small **⚙ Settings** menu (top-right) holds prefs + admin token + version + a
  link to `/admin`. The 6 cryptic TopBar buttons (COG/SYS/FLOW/TRACE/🎨/RO-EN) go away.

## Architecture: additive, low-risk
Rather than rewrite the chat dashboard into a router (risky, untestable offline),
add **two entry points** in the top-right and keep the chat layout intact:

1. **⚙ Settings** — small dropdown: theme · density · scanline · language ·
   admin-token field · *Open Admin →* · real version (from `/status`).
2. **▦ Console** — a full-screen overlay (own left nav + content pane) that is the
   home for every feature. Opened by a button **and** ⌘K. The existing dev panels
   (Cognition/Systems/Workflows/Observability) move in here.

Each feature is a self-contained panel that calls its existing endpoint(s) and
renders results + actions. Shared helpers: `api()` (GET/JSON) and `adminFetch()`
(injects `X-Admin-Token`, surfaces 401s).

## Console information architecture (every feature has a home)

| Section | Panels (endpoints) |
|---------|--------------------|
| **Chat** | (the main HUD — Console closes to it) |
| **Workflows** | Visual Builder, Run, Hierarchical crew (`/api/workflows*`), traces |
| **Arena** | run blind comparison, vote, leaderboard (`/api/arena/*`) |
| **Observability** | Quality monitor (`/api/quality*`), Review queue (`/api/review/*`), Traces (`/api/traces`), Cost (`/api/analytics/cost`), Run history (`/api/agents/history`), Cognition, APM |
| **Autonomy** | Tasks/decision inbox, Action approvals (`/api/actions/*`), Escalation (`/api/autonomy/escalate`), Dry-run preview (`/api/autonomy/preview`), NL schedule (`/api/schedule/parse`), Learning propose (`/api/learning/propose`), Reflection |
| **Memory** | Search/recall/profile, KG facts + as-of (`/api/kg/*`), Entities, Consolidation (`/api/memory/consolidate`), Decay (`/api/memory/decay/*`), Eval (`/api/memory/eval`) |
| **Rooms** | Chat channels (`/api/rooms/*`) — create, @mention, history |
| **Notes** | Conversation notes (`/api/notes`, `/rewrite`) |
| **Tools / Dev** | Widgets (`/api/admin/widgets`), GBNF grammar (`/api/llm/grammar`), MCP server + token (`/api/mcp/*`), Secret broker (`/api/secrets/broker`), Webhooks (`/api/webhooks`), Skills marketplace, Local docs, Component health (`/api/health/components`) |
| **Settings/Admin** | the ⚙ menu + link to `/admin` |

## Slices (one PR each, app-boot + endpoint verified; rendering = manual test)
1. **Backend + plan** — add `version` to `/status`; this doc. ✅ (this PR)
2. **Foundation** — ⚙ Settings menu (prefs+admin-token+version+admin link);
   `api()`/`adminFetch()` helpers; remove fake "Memory online" badge; **#4** drop
   right AgentsGrid; **#5** NetworkBrain toggle; implement the 3 dead buttons;
   replace the 6 cryptic buttons with **⚙** + **▦ Console** (Console shell, empty).
3. **Console: Observability + Autonomy** panels.
4. **Console: Arena + Rooms + Notes** panels.
5. **Console: Memory + Workflows** panels.
6. **Console: Tools/Dev** panels (widgets, grammar, MCP, secrets, webhooks, health).

## Constraints / honesty
- No browser in this env → I verify JS parses, the app boots, and endpoints
  respond; **visual rendering is verified by the human manual-testing pass**
  (`docs/MANUAL_TESTING.md` §C).
- Frontend isn't covered by the offline test suite; slices stay small + additive
  so a bad panel can't break the core chat.
