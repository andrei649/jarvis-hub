# Workbench — a direction for the next Nerva interface

Files: `cockpit.html` (home, called *the bench*), `secondary.html` (Trust · Overview), `offline.html`
(extra frame: the bench when the hub stops answering), `tokens.css`, `workbench.css`, `shots/`.
Default theme **dark**; `?theme=light` shows the designed light theme.

---

## 1. The idea

Every serious agent product converged in 2025–26 on one shape: work sorted by whether it needs the
human, one conversation in the centre, and a context rail for plan, results and provenance.
Workbench is that shape built for one owner and eighteen local agents, and drawn in the language of
a real instrument instead of a film prop: DIN lettering, a machine nameplate that says where work
ran and on what basis, and a safety code in which yellow means exactly one thing — *it is your move*.
Nothing on the bench is decoration: every mark is a claim the hub can back, and when it cannot back
it, the mark changes its stroke and says so.

**Promise:** you always know what is waiting for your hand, where the work ran, and how hard it is
to undo.

---

## 2. Identity sheet

### Name
- The interface is **Workbench**; the home screen is **the bench**. "HUD" and "cockpit" retire.
  Areas keep plain names (Home, Work, Agents, Memory, Trust, Build, Connect, Observe, Settings).
  The product stays **Nerva**; agents keep their names as role labels.

### Logo
- The neural N, undressed: three strokes and four nodes, in ink on the ground. No tile, no ring, no
  glow, no blue. 22px in the bar beside the word *Nerva* (DIN, 600). Clear space: one node diameter.
  Minimum 16px.
- **The mark is a path.** Classify → Route → Gather → Synthesize are its four nodes. While a reply
  is being made, the mark is drawn only as far as the work has got: done strokes solid, the current
  node enlarged, the remaining stroke dotted and the next node hollow. It is the working indicator,
  and it never spins or pulses.

### Palette (OKLCH; one token set, two grounds)

| Role | Token | Dark (default) | Light |
|---|---|---|---|
| Desk (page ground) | `--ground-0` | `0.158 0.004 85` | `0.938 0.005 88` |
| Sheet, card (where you work) | `--ground-1` | `0.192 0.004 85` | `0.995 0.002 90` |
| Well (your turns, inputs, open row) | `--ground-2` | `0.226 0.005 85` | `0.962 0.004 90` |
| Selected, pressed | `--ground-3` | `0.268 0.005 85` | `0.918 0.005 90` |
| Hairline between regions / inside / control edge | `--line-1/2/3` | `0.262` / `0.335` / `0.53` | `0.892` / `0.835` / `0.60` |
| Ink: primary / secondary / quiet (all ≥ 4.5:1) | `--ink-1/2/3` | `0.945` / `0.80` / `0.68` | `0.20` / `0.39` / `0.47` |
| **Yellow — your move** (fill) | `--signal-yours` | `0.865 0.17 92` | `0.865 0.17 92` |
| Ink on yellow / yellow edge | `--on-signal-yours` / `--signal-yours-edge` | `0.2 0.03 85` / = fill | `0.2 0.03 85` / `0.58 0.12 85` |
| **Red — cannot be undone, failed, stopped** | `--signal-stop` (mark) / `--signal-stop-fill` | `0.70 0.19 27` / `0.50 0.20 27` | `0.53 0.20 27` / `0.50 0.20 27` |
| **Green — sealed, intact, verified** | `--signal-proven` | `0.77 0.15 152` | `0.48 0.13 152` |
| The plate (nameplate ground; dark in both themes) | `--plate-ground` | `0.118 0.004 85` | `0.225 0.005 85` |

Rules: ground and ink carry a faint warm cast (hue 85–90, chroma ≤ 0.006). Signals are fills or
marks, never text colour; every signal is paired with a word or a shape. **Yellow is the only accent**
and appears only where something is held for the owner's decision: the hold tag, the count of
decisions, the enabled Approve. Red and green are status, not accent.

The colour decision that makes it Nerva: *safety yellow on a quiet bench, rationed to the owner's
move.* When nothing waits, the screen has no yellow at all.

**Default theme: dark.** The bench is on all day beside other tools, probably on an OLED panel: a
dark desk with small, rationed light marks is easier on the eyes and on the panel, the only large
static element (the plate) is the darkest thing on screen, and the owner's newest tools are dark.
**Light is designed for daylight, not inverted:** paper-white sheets on a bench-grey desk, a darker
yellow edge so the tag holds its shape on white, deeper red and green for 4.5:1 on paper, a 1–2px
shadow where a sheet leaves the desk, and the nameplate kept dark on purpose — it belongs to the
machine, not to the page.

### Typefaces

| Role | Mockup face (installed) | Production face (open licence, self-hosted) |
|---|---|---|
| Content: what was said, what will happen | Bahnschrift, normal width | Barlow (SIL OFL 1.1) |
| Meta voice: who, when, where, on what basis | Bahnschrift at `font-stretch: 87.5%` | Barlow Semi Condensed (SIL OFL 1.1) |
| What the machine named: addresses, hashes, tool and model ids | JetBrains Mono (already vendored) | JetBrains Mono |

Both production families cover Romanian (ă â î ș ț with comma below).

| Step | 1920 | 2560 (owner's screen) | Used for |
|---|---|---|---|
| micro | 11/14 | 12/15 | plate cell labels, `kbd` (the floor) |
| meta | 12/16 | 13/17 | the meta voice |
| small | 13/18 | 14/19 | controls, dense rows, facts |
| ui | 14/20 | 15/21 | default |
| read | 15/24 | 17/27 | the conversation |
| title | 18/24 | 21/27 | the open decision |
| head | 22/28 | 25/30 | the count, page titles |
| figure | 34/36 | 34/36 | the one figure on a page (locality) |

Weights: 350 reading, 400 labels and your own words, 600 headings and the figure that matters
(Barlow 400 / 500 / 600). Sentence case everywhere; tabular figures everywhere; no tracked capitals.

**The typographic habit:** content is set at normal width, and everything *about* the content — who,
when, where, basis — is set semi-condensed. You can tell a statement from its provenance by the width
of the letters.

### Signature devices
1. **The hold tag** — a yellow safety tag with a punched eyelet: *Held for you*. Used for the count
   of decisions, the open decision, a decision raised inside the conversation, a payment that waits.
2. **The gates** — risk drawn as three bars, filled by tier: ▯▯▯ read only, ▮▯▯ reversible,
   ▮▮▯ external, ▮▮▮ irreversible or money (in red). The number of filled bars is the number of
   deliberate acts the owner must make. The Trust page carries the legend ("Friction follows risk").
3. **The evidence stroke** — how sure a reading is, drawn as its stroke: solid = verified or measured,
   outline = declared (by route, derived), dashed = unknown. The "this machine" square is outlined
   today because the basis is the route; it becomes solid only when the hub can verify it.
4. **The plate** — the machine's nameplate along the bottom of every page, dark in both themes, with
   the verdict and the seven trust signals. It never leaves at any width.
5. **The run plate** — under every reply: where it was sent · model · basis (`▣ On this machine ·
   gemma-4-31b · by route`).

### Shape, elevation and motion
- Radii 3 / 6 / 10, concentric: chips, tags and glyph cells 3; controls, rows and wells 6; sheets
  and cards 10. Controls 24 / 28 / 32px tall; the emergency stop on Trust is 40px.
- Elevation is lightness, not shadow: in dark the work surface is lighter than the desk; in light it
  is whiter. Hairlines separate regions. Only light sheets get a 1–2px shadow; floating layers
  (search, menus) get one deeper shadow and stay opaque. No glass, no blur.
- Motion: none by default. One 120–200ms ease-out when a state changes because the owner acted.
  Streaming text appears as it arrives; the caret does not blink; nothing pulses, spins or scrolls by
  itself. `prefers-reduced-motion` sets every duration to 0.

### Voice of the chrome — before → after
| Before | After |
|---|---|
| `SITUATION · ALL NOMINAL` (hard-coded, beside a red pulsing dot) | `Degraded · Working, with 4 local services down` — `since 08:14 · checked 10:50` |
| `% LOCAL 100%` | `Runs on this machine · 100% · 41 of 41 runs today · by route` |
| `Needs approval · irreversible` (the same red pill on 36 cards) + `Dismiss` | `▮▮▮ Irreversible · typed confirmation · cannot be bulk-approved` + `Type restart to approve once for all 4` |
| `queue clear ✓` (also when the feed refused) | `Nothing is waiting for you.` — or, when the feed did not answer, `Unknown — the hub is not answering` |
| `TRANSMIT` / `Speak or type a command…` | `Send` / `Message Jarvis…` with `To Jarvis · orchestrated` and `Approval mode Ask` above it |
| `NEURAL NETWORK · live telemetry · click an agent` | (removed) — agents appear where they act: `Jarvis with Pepper, Stark · step 3 of 4` |

Voice rules: a status is a sentence, not a code; say what happened, then since when and how we
know; name the consequence on every irreversible control (verb + object: *Approve once for all 4*,
*Reject group*); never say *nominal*, *all clear* or *secure* unless the hub measured it.

### Three things this identity never does
1. **Never spends yellow on anything that is not waiting for the owner** — not for the brand, not for
   warnings, not for hover, not for the next meeting.
2. **Never draws a reading it does not have** — no default as a value, no solid "this machine" mark
   without verification, no zero for "not measured", no "all clear" when the feed did not answer.
3. **Never moves on its own** — no pulse, no spin, no ticker, no glow, no orb; and no keyboard
   shortcut or gesture ever approves or rejects.

---

## 3. Layout and navigation

### The bench at 1920 × 1080

```
┌ N Nerva  Home  Work [9 need you]  Agents  Memory  Trust  Build  Connect  Observe [4 services down]  Settings ─────
│                          [⌕ Search every area, panel, agent and action  Ctrl K]  EN|RO  ◐  ▭  Mon 23 Nov 10:51  [■ Stop all agents]
├─ SPINE 416 ──────────────────┬─ SHEET: the one conversation ─────────────────┬─ INSPECTOR 488 ───────────────
│ Approval mode  Auto|Ask|Off  │ Jarvis · Prime Orchestrator · today since 08:02│ [◦ Held for you]  Decision 1 of 6 ‹ ›
│ Interruptions today 3 of 4   │                                                │ ▮▮▮ Irreversible · typed confirmation
│ [9] need you                 │ 08:05  › draft the churn slide [QBR-deck.docx] │ Restart 4 local services that
│ 9 actions in 6 decisions ·   │ 08:05  Stark  pulled the numbers — +6.2% WoW … │   stopped responding
│   from 18 requests           │        ▸ 2 tool calls  web_search ✓ file_write ◆│ Steve · raised 08:14, repeated 3×
│ ▮▮▮ 3 irreversible or money  │        [▣ On this machine | gemma-4-31b | by route]│ #402 lmstudio 127.0.0.1:1234 …
│ ▮▮▯ 1 external ▮▯▯ 2 reversible│ 08:07  › sweep idle cash                      │ Preview · Run a dry run
│ ▮▮▮ Restart 4 local services ›│ 08:07  Gecko  … [◦ Held for you] Sweep €4,200 │ Undo · Deadline (then blocked)
│ ▮▮▮ Sweep €4,200 …          › │ 10:48  › Ce proiecte sunt de terminat acum?   │ Recorded ✓ c03e…1d9f
│ ▮▮▮ Delete logs …           › │ 10:51  Jarvis  [N-path] Gathering — asking …   │ Type [restart] [________]
│ ▮▮▯ LinkedIn draft [Review]   │        ● Classify ● Route ◉ Gather ○ Synthesize│      [Approve once for all 4]
│ ▮▯▯ Reply to Raiffeisen [Approve]│     ◌ Pepper  Checking this week's deadlines│ Edit then approve · Defer · Reject group
│ ▮▯▯ Move research sync [Approve] │     ◌ Stark   Pulling project status  [Stop]│ No keyboard shortcut approves or rejects.
│ Running 1 · 3 agents working │        Trei proiecte au termene … și|          │ Today        București · 9 °C · Mist
│ Finished while you were away │ ┌ To Jarvis · orchestrated   Approval mode Ask ┐│ 09:30 Standup ── now ── 11:00 1:1
│   7 rows, newest first       │ │ › Message Jarvis…                            ││ 14:00 Raiffeisen quarterly review
│ 18 agents · exceptions       │ └ + Attach  Options  / commands @ files  Voice · Send┘│ 16:30 · 19:00
├─ PLATE: the state of this machine (dark in both themes) ──────────────────────────────────────────────────────
│ ▲ Degraded · Working, with 4 local services down │ ▣ 100% · 41 of 41 · [by route] │ 🔒 Sealed │ Mic On │
│ gemma-4-31b loaded on Ollama │ ● Live · every section │ ◌ Latency p50 — unknown │ RAM 19% VRAM 96% GPU 3%
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

### On the owner's screen, 2560 × 1353 at 1.5×
The room goes to the job the conversation could not show before — **the run rail**, a pane inside
the sheet with the plan, results and provenance of the answer being made: the question, the four
steps with who is doing what, files and tool calls in this conversation, the decision it raised, and
the audit entries it sealed (`10:49 Jarvis · Routed your question to Pepper and Stark · 9f2c…a41b`).
Columns: spine 480 · sheet (thread + run rail 420) · inspector 540. Type moves up one step (reading
17/27), the reading measure is 680px (~90 characters) and never grows, spine rows gain their "why"
line, and the plate adds Channels. Tier-3 decisions are still shown **one at a time** — showing
three typed confirmations side by side would invite batch-approving irreversible work.

### Areas and panels
- **Nine areas** in the bar, navigation dimmer than content. Only two carry badges, and only when
  something is wrong or waiting: Work (yellow: decisions held for you) and Observe (outlined:
  problems). The bar is the same on every page and always ends with the one-click stop.
- **Every area page has the same frame** (shown by `secondary.html`): the left column becomes that
  area's second-level navigation — panels grouped by the question they answer, with a count or state
  beside a panel only when it says something, and a filter — then the page, then the plate. The 137
  Console panels become these second-level pages; the Console stops being a place.
- **Trust's 21 panels** are grouped: *Stop and prove* (Emergency stop, Audit chain, Audit anchors,
  Retention) · *Who may act* (Capabilities, Permissions, Skill switches, Desktop allowlist, Security
  skills) · *Money and secrets* (Payments, Secrets, Credential shares, Pairing) · *Data and posture*
  (Data handling, Posture, Signal governance, Trust ops, and 3 more). Regrouped because a flat list
  of 21 hides that four of them are about stopping and proving.
- **Search and command** (Ctrl K, always in the bar) finds every area, panel, agent and action, and
  can run navigation and "Stop all agents"; it cannot approve or reject.
- Approvals have **one home**: the Work area holds the whole queue; the bench shows the same queue
  sorted by what needs you. The thread only links to a decision; it never decides.

### What collapses
| Width | What changes |
|---|---|
| ≥ 2240 (owner, 2560) | Run rail opens inside the sheet; spine "why" lines; Channels on the plate; type +1 step. |
| 1800–2239 (1920) | Three columns. The run rail folds into the inspector, opened from the working strip or any run plate. Today sits under the decision. |
| 1400–1799 (1440) | Same columns, narrower. Today's next commitment moves into the bar (`Next 11:00 · in 9 min`). Decision members drop their impact lines. Meters leave the plate (Observe keeps them). Language, theme and glance fold into one View menu. |
| 1280 × 800 (shell default) | Spine 296 · sheet · inspector 340. Secondary meta drops. The plate keeps all seven trust signals: verdict, on this machine **with its basis**, egress, microphone, model, data on screen, latency. |
| 420 × 620 floating chat | The sheet alone: thread and composer, `To Jarvis` and `Approval mode` above the box. A one-line plate at the top: `[9] · ▣ 100% by route · 🔒 Sealed · Mic On · Live`. The count opens decisions as a sheet over the chat; tier 3 still needs typed confirmation. A stop button sits in the window's title bar. |
| Phone (< 760, if the owner picks it) | One column. Home is the spine (needs you first); Chat, Trust and Search are one tap away. The plate becomes a two-line strip at the top. No swipe-to-approve: a gesture is a shortcut, and shortcuts never decide. |

---

## 4. How each job is served

**Talk.** The sheet is the only lightest surface on the screen and sits in the centre at every width.
The reading measure is capped (~90 characters) instead of following the window. Your own turns sit
in a well behind the same `›` prompt as the composer; replies are headed by the agent that actually
answered (Jarvis routes; Stark, Gecko answer under their own names). Every reply ends with a run
plate — where it was sent, model, basis. A reply takes 4–60+ seconds, so *working* is designed: the
N-path mark drawn to the current step, a plain line (`Gathering — asking Pepper and Stark`), the four
steps, who is doing what right now (`Pepper · Checking this week's deadlines`), and Stop. On the
owner's screen the run rail adds the plan, results and sealed provenance beside the thread. The
composer is a multi-line box that always shows who receives the message and the approval mode;
attachments and options are one click away instead of four rows of controls; voice says it runs
locally. The newest finished reply shows Copy · Save · Read aloud · Create task; older ones keep
them behind More.

**Decide.** One list, sorted by what needs you: 18 raw requests grouped by the hub into 6 decisions
(9 actions), irreversible first. Each row shows its gates, tier word, agent and time. **Friction
follows the tier on the row itself:** reversible rows carry a real one-click `Approve` (undo
available); the external row opens its review step (`Review the draft`); irreversible and money rows
open in the inspector, which shows members, why it waits, preview with a dry run, undo, deadline
("then it is blocked, never auto-approved"), the sealed audit entry, and a typed confirmation that
names the target (`Type restart to approve once for all 4`; for money, the amount). Typed decisions
cannot be bulk-approved; group approval exists only for same-shape members and says how many.
Approve, Edit then approve, Defer and Reject are always the real actions. No keyboard shortcut
approves or rejects, and the card says so. A decision raised in conversation (Gecko's sweep) is
linked from the reply with the same hold tag, so the owner never wonders whether "sweep available"
means it happened. Every row opens its own card in the inspector, one at a time: the ‹ › arrows page
through all six, and the address names the card (`cockpit.html#d-g2` is the sweep), so the spine
row, *Open the decision* in the reply and Trust › Payments all land on the same card.

**Check.** The plate answers "is everything healthy" in one cell — a computed verdict with since and
checked times — and keeps the seven trust signals beside it at every width, each with a word, a
shape and, for locality, its basis. *Finished while you were away* replaces the ticker: time, agent,
result, newest first, never moving. *Running* shows what is running now. Agents appear by exception
(working, waiting, finished in the list; *Athena unavailable while egress is sealed* and *Oracle
cannot run* below it). The verdict's causes are the members of the open decision, each with its
impact, and Observe carries the badge.

**Find.** Search and command is in the bar at every width and reaches all ~150 destinations — areas,
panels, agents, actions. Each area page has a panel filter. Nine areas replace 16 rail modes, a
hidden Console and three floating buttons; nothing floats over content.

---

## 5. States

| State | How it is drawn | Where |
|---|---|---|
| **Waiting** (held for you) | The yellow hold tag; the count; the enabled Approve turns yellow only after the typed confirmation matches | bench hero, inspector, Gecko's reply, Trust › Payments, Trust nav (`1 waits`) |
| **Working** | N-path mark drawn to the current step, step list, who is doing what, Stop; a thin still caret; run plate reads *Running on this machine* | bench thread; run rail on the owner's screen; spine *Running* |
| **Unknown** | Dashed stroke + the word *unknown*; never a zero, never a green default | plate *Latency p50 — unknown*; Trust ladder *Unknown — no route was recorded*; `offline.html` throughout |
| **Stale** | The last value keeps its place but drops to the outline stroke and quiet ink, with *last read 10:50* beside it; controls that would act on it are withdrawn | `offline.html` |
| **Empty** | A plain sentence in place of the list: *Nothing is waiting for you.* The count becomes 0 and **the screen has no yellow** | rule; the empty sentence comes from the hub's own copy |
| **Demo** | A section that is not live says *Demo sample* in its header with a hollow dot; the plate's *Data on screen* reads *Demo sample* while any section is | rule (source labels exist on every Trust section and in the plate) |
| **Error / problem** | Red diamond + plain cause and consequence: *file_write failed — nothing was changed*; *lmstudio, qdrant, neo4j and n8n stopped responding* | thread, spine log, Trust › Audit chain |
| **Blocked / unavailable** | Circle with a bar / circle with a slash, in ink, with the reason | *SSRF attempt blocked*; *Athena · unavailable while egress is sealed*; *Oracle · n8n is down* |
| **Offline** (hub unreachable) | Every reading turns stale or unknown with its last-read time; the queue says *Unknown — the hub is not answering* instead of *all clear*; Approve controls are withdrawn, Stop stays | `offline.html` |

Every section states its source: the plate says *Data on screen: Live · every section*; a section
that differs (demo, empty, offline) carries its own label. Trust shows a source on every panel.

---

## 6. What was removed, and where its information went

| Removed from the current screen | Where it went |
|---|---|
| Neural-network graph (30% of the screen) and the roster listed twice | Agents appear as attributes of work (who raised, who runs, who answered) plus an exceptions line; the full list lives in Agents. Routing policy per agent lives in Trust. |
| 40px glowing clock | 12px date and time in the bar. |
| Marquee ticker and `SITUATION · ALL NOMINAL` | *Finished while you were away* (still) and one computed verdict in the plate. |
| Seven top-bar badges | Seven plate cells with words, states, times and a basis. |
| 36 identical decision cards with `Dismiss` | 6 grouped decisions with real verdicts and tier-graded friction. |
| Decision inbox 137 links away, first ten only | Work area (whole queue) and the bench spine (same queue). |
| 16 rail modes, hidden Console with 137 panels, 3 floating buttons | Nine areas in the bar, second-level pages with grouped navigation, search that finds everything. |
| Four always-visible rows of composer options and help sentences | Attach and Options menus, one hint line (`/ commands · @ files`), recipient and approval mode above the box. |
| Eight buttons on every reply | Four on the newest finished reply, *More* on the rest. |
| System panel (RAM, VRAM, GPU, BACKEND unknown, LATENCY —) | Three compact meters on the plate (≥1800px); Observe holds history. `BACKEND unknown` (never populated) is gone; latency shows *unknown* honestly. |
| Weather panel and Heartbeat panel (never has content) | One line in Today's header; Heartbeat removed. |
| Cognition and Artifacts tabs | The run rail (plan, results, provenance) on the owner's screen; the inspector below it. |
| One green `LIVE` chip over mixed data | The plate's *Data on screen* plus a source on every section that differs. |
| Cyan on navy, glow, corner brackets, chamfers, scanlines, spinning logo, uppercase tracked mono | Near-neutral grounds, one rationed yellow, DIN in sentence case, a still mark, mono only for machine names. |

---

## 7. Building it

**Tokens only** (no markup change): colour, type scale, spacing, radii, motion. `tokens.css` is a
drop-in layer of `light-dark()` pairs on role names. The HUD's 29 flat tokens map onto it
(`--ink`, `--ink-2`… → `--ink-1/2/3`; panel and void colours → `--ground-0/1`; cyan → retired;
amber/red/green → the three signals). The Workspace `--ws-*` set (light-first, 8px grid, radii
6/10/14) converges by adopting the ground/line/ink names and the 3/6/10 radii (its 14 becomes 10).

**New CSS** (no new data): the bench grid and its four width tiers; the plate; the hold tag (an
eyelet pseudo-element, no image); the gates and evidence-stroke glyph sets (SVG symbols); the
working strip; run plates; the run rail; the area-page frame (second-level navigation, panels,
tables); the meta voice (`font-stretch: 87.5%`, needs the production family's semi-condensed cut).

**New markup and data:**
- *Spine* — uses the hub's existing grouping and `counts`/`by_tier`; rows render friction by tier.
- *Inspector decision card* — `fe/confirm.tsx` already exists; needs preview, rollback, deadline
  (`approval_deadline_at`) and the audit hash on the card.
- *Plate* — every cell needs `value`, `state`, `checked_at`, and for locality a `basis`.
- *Run plate* — per-reply provider and model are measured today; the basis word comes from the route.
- *Working strip and run rail* — need step events (Classify/Route/Gather/Synthesize) and sub-agent
  activity lines streamed with the reply, and audit entries linked to the turn.

**Riskiest part:** the honesty data, not the drawing. Per-step progress, sub-agent lines, `checked_at`
on every value and a verified locality basis do not all exist in the hub yet. Where a field is
missing the design shows *unknown* — correct, but the bench will look emptier than this mockup until
the backend slice lands (the locality research names it: catalog truth, then evidence in the receipt).
Second risk: Bahnschrift ships only with Windows; Barlow is slightly wider, so `--measure` and column
widths need one re-check after the font swap.

**Suggested order:** (1) tokens and fonts behind a flag; (2) the plate — it replaces seven badges,
the marquee and the meters and fixes most of the 18 honesty defects at once; (3) the spine and
inspector with real verdicts — the biggest win for the owner; (4) the sheet: multi-line composer,
run plates, working strip; (5) the area frame, migrating Console panels area by area, Trust first;
(6) the run rail for the wide tier; (7) light-theme QA; (8) floating chat and phone.

---

## 8. Self-critique

1. **The skeleton is the 2026 template.** Bar, list, conversation, inspector: at thumbnail size the
   bench could pass for any well-made agent tool. The identity lives in details you only see at
   reading distance — DIN letters, the tag, the gates, the evidence stroke, the nameplate. If the
   production font swap or a hurried build flattens those details, nothing distinctive is left.
2. **1280 is good, not great.** The desktop shell's default window keeps three columns; the spine and
   inspector each scroll, and at 1280 × 800 the owner scrolls the decision card to reach *Defer* and
   *Reject*. A two-pane mode (list + conversation, the decision as a sheet over the conversation) may
   serve that window better; I kept three columns so the decision stays visible beside the chat.
3. Smaller: on the owner's screen the run rail and the Trust page end with empty space at the bottom
   — honest (there is no more content) but not yet beautiful; the run rail's plan and sub-agent lines
   depend on events the hub does not stream yet; and the plate stays dark in the light theme, which
   is a deliberate nameplate but a heavy band in a bright room.
