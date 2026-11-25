# Briefing — Nerva as a brief you answer

Files: `cockpit.html` (Home, "The brief"), `secondary.html` (Trust › Overview), `tokens.css`
(the token sheet), `briefing.css` (shared components built only from tokens), and one extra
frame, `glance.html` (the idle and second-screen mode). Default edition: **Day** (light);
`?theme=dark` shows the **Night** edition. Glance alone defaults to Night, because it sits idle
for hours, often on the owner's OLED. Both required pages pass the kit's gates in both editions
at 2560 / 1920 / 1440 / 1280 (see `shots/report.json`).

> Continuity note. This direction was started by another designer and finished by me. I kept
> its idea, name, identity and layout. What I changed, and why, is listed at the end of §3.

## 1. The idea

Nerva's promise is "the AI that works while you sleep", so the home is what a superb chief of
staff hands you when you sit down: **one page, written in sentences, numbered and sourced, with
every item ending in the control that settles it.** The page is composed like the front of a
private newspaper (a headline that states the day, a lead item, digest columns), and the
conversation is the right-hand page of the same sheet: the morning brief is the thread's first
entry and the talk grows out of it. It is an instrument set in editorial type: ink does the work,
one marker colour says "this is yours to decide", and red is kept for what is actually wrong.

**Promise:** *Read one page, settle what is yours, get on with your day.*

## 2. Identity sheet

### Name

- The interface is just **Nerva**. "HUD" and "cockpit" retire with the sci-fi art direction.
- The home page is **the brief** (area label stays **Home**). The idle or second-screen mode
  stays **Glance**. The two themes are **editions**: *Day* and *Night*.

### Logo treatment

- The real neural N, redrawn as **line work in ink**: no tile, no ring, no glow, no blue. Stroke
  9/128 of the mark's box, round caps, four solid nodes.
- **The mark is also the progress indicator.** Its four nodes, in stroke order, are the four steps
  of a reply (Classify, Route, Gather, Synthesize). Done nodes are solid, the current node gets a
  ring, the steps ahead are hollow and the stroke to them is dotted (see the live reply tray). In
  the masthead the whole mark is drawn, and while a reply is running the current node is ringed.
- Sizes: 28 px in the nameplate next to "Nerva" set in the display serif (26 px, bold); 38 px in
  the reply tray. Clear space: one node diameter on every side. Night edition: warm paper-white
  ink. The mark is never coloured with the marker or the alarm red.

### Palette (one token set, two editions; measured in the browser against `--nv-paper`)

| Role | Token | Day | Night | Contrast (Day / Night) |
|---|---|---|---|---|
| The sheet | `--nv-paper` | oklch(0.985 0.003 95) `#FBFAF8` | oklch(0.190 0.006 265) `#121417` | — |
| Quiet fill (inputs, tray, past hours) | `--nv-paper-2` | `#F4F3F0` | `#1A1C1F` | — |
| Hover / pressed | `--nv-paper-3` | `#ECEBE7` | `#232529` | — |
| Transient layers only | `--nv-raised` | `#FFFFFF` | `#1F2024` | — |
| Text, heavy rules | `--nv-ink` | oklch(0.210 0.012 265) `#16181E` | oklch(0.935 0.008 95) `#EBE9E4` | 17.0 / 15.2 |
| Secondary text | `--nv-ink-2` | `#44484E` | `#BCBBB5` | 8.8 / 9.6 |
| Meta text (the dimmest text allowed) | `--nv-ink-3` | `#606369` | `#9D9B96` | 5.8 / 6.6 |
| Solid fill (primary action, top-tier chip) | `--nv-fill` | = ink | `#D6D4CE` (a step under the text white) | on-ink 17.0 / 12.5 |
| Hairline between items | `--nv-rule` | `#D8D9DC` | `#2B2D30` | — |
| Column rule | `--nv-rule-2` | `#B5B7BB` | `#3F4145` | — |
| Control border (UI boundary) | `--nv-rule-3` | `#7E8085` | `#696C71` | 3.8 / 3.5 |
| **The marker** — "yours to decide", attention | `--nv-mark` | oklch(0.905 0.170 98) `#FEE03F` | oklch(0.860 0.155 95) `#F1CF44` | ink on it 13.5 |
| Highlighter wash | `--nv-mark-wash` | `#FFF2AF` | `#3E3510` | — |
| The flag (numerals, refs, badge, verdict word) | `--nv-flag-*` | solid marker, ink numeral | lit outline: `#F1CF44` on `#362D0D`, edge `#B69D3A` | 13.5 / 8.9 |
| **Problem and Stop** — the alarm, never an accent | `--nv-problem` | oklch(0.520 0.200 27) `#C2181D` | oklch(0.740 0.155 27) `#FD8074` | 5.9 / 7.5 |
| Problem wash | `--nv-problem-wash` | `#FFE9E5` | `#451E1B` | — |

Status roles, always a shape plus a word, colour last: **ok** = ink and a check (never green);
**attention** = the marker and a triangle; **problem** = red and a diamond; **unknown** = ink-3,
a dashed ring and the word "unknown" in italics; **stale** = ink-3, a clock and the time it was
last checked. Focus: a 2 px ink ring, 2 px offset, on every control.

The **Night edition is designed, not inverted**: the paper goes near-neutral and slightly cool,
the ink turns warm (paper-white rather than blue-white), solid fills drop a step under the text
white so buttons never out-glare the headline, the highlighter stops being a wash behind words
and becomes gold words on a gold underline, and the flags become a lit outline that emits a
fraction of the light of the Day marker. That matters on the owner's OLED panel.

### Typefaces

| Role | Rendered here with | Production face (self-hosted, SIL OFL) | Sizes |
|---|---|---|---|
| **Voice** — headline, deck, item titles, the brief's sentences, replies | Sitka Banner / Display / Heading / Subheading / Text (optical sizes) | **Literata** (variable, optical sizes 7–72, Romanian ș ț with comma) | headline 46 (50 on the broadsheet) bold · deck 22 italic · lead item 27 bold · section 20 semibold · item title 18 semibold · reply 16 (17 on the broadsheet) · body 14.5 |
| **Instrument** — controls, labels, tables, the owner's own lines | Segoe UI Variable Text / Small | **Source Sans 3** (variable) | controls and cells 13.5 · owner lines 15 · meta 12.5 · floor 12 |
| **Machine** — identifiers, addresses, hashes, model and tool names | JetBrains Mono (already vendored) | JetBrains Mono | 12.5 |

Figures are lining and tabular everywhere (the serif's default old-style figures are switched
off). Sentence case throughout; nothing is set in tracked capitals. **Nothing is smaller than
12 px** (the kit's measured smallest on every page and width is 12 px).

### Shape, elevation and motion

- **Rules, not boxes.** A 3 px ink rule opens a section; 1 px hairlines separate items; 1 px column
  rules separate columns and run continuously from the standfirst to the foot of the page. Only
  controls are boxed (buttons, inputs, the composer) and nothing is a card inside a card.
- **Weight follows risk.** The tier chip is solid ink for irreversible-or-money, outlined for
  external, plain for reversible and read-only, with one to three pips. The same chip is used on
  Home, in the audit chain and anywhere else a tier appears.
- Radii 2 (chips, flags, keys) · 4 (buttons, inputs) · 8 (composer, menus, palette).
- Elevation: none on content; every work surface is opaque paper. One shadow token
  (`--nv-shadow-pop`) is reserved for transient layers: the command palette, menus, popovers.
- Motion: **still by default.** A state change gets one 160 ms ease-out on colour and border.
  The streaming reply grows in place. No spinner, no pulse, no marquee. `prefers-reduced-motion`
  sets every duration to 0.

### Voice on the chrome: before → after

1. "ALL NOMINAL" (hard-coded, beside a red pulsing dot) → **"Degraded · Working, with 4 local
   services down · since 08:14 · checked 10:50"**
2. "DECISION QUEUE 36" with a "Dismiss" button → **"Needs you now · 4 decisions · 7 actions"**,
   with "Approve…", "Reject", "Defer"
3. "% LOCAL 100%" → **"100% on this machine · by route"**
4. "TRANSMIT" and "Speak or type a command…" → **"Send"** and **"Message Jarvis…"**
5. "NEURAL NETWORK · live telemetry · click an agent" → **"At work · 18 agents, by exception"**

Rules: say the state, then the reason, then the time; name the agent and its role; numbers are
digits; the friction is named next to the control ("typed confirmation", "review, then confirm",
"one click, undo"); a verdict button says the verb, never "OK".

### Three things this identity never does

1. **It never draws a reading it does not have.** Unknown is a dashed ring and the word, never a
   zero, never a green, never a default.
2. **It never spends colour on decoration.** Yellow only means "yours to decide"; red only means a
   real problem or Stop. OK is ink and a check.
3. **It never boxes, glows or moves content for effect.** Structure is rules and type; nothing
   moves unless a state changed. (And no agent ever gets a face: agents are names with roles.)

## 3. Layout and navigation

### The home screen, standard edition (1920 × 1080; the page never scrolls, the brief may)

```
+------------------------------------------------------------------------------------------------+
| N Nerva  Home  Work[9 need you]  Agents  Memory  Trust  Build  Connect  Observe[4 down]  Settings |
|                               [Search or command  Ctrl K]  EN|RO  Night  Glance  [ Stop all agents ] |
+------------------------------------------------------------------------------------------------+
| [Degraded] Working, with 4 local services down  since 08:14 · checked 10:50                      |
|      Egress sealed | 100% on this machine · 41 of 41 runs · by route | Mic on | gemma-4-31b | Live  |
+----------------------------------------------------+-----------------------+-------------------+
| The brief  Monday, 23 November 2026 · 10:51         | Working, with 4 local | Conversation      |
| Nine actions need you.   (display serif, 46)        | services down ... the | ----------------- |
| Six decisions — three irreversible or money, ...    | restart is decision 1.| 06:00 Friday·brief|
|                                                     | Overnight: 4 done ... | You    Morning... |
|=====================================================|=======================| Jarvis Good mor...|
| Needs you now  4 decisions · 7 actions  [Auto|Ask|Off] | While you were away | You    draft ...  |
| [1] ### Irreversible  Steve · CTO / Builds          |  06:00 v Friday  ...  | Stark  Stark pu...|
|     Restart 4 local services that stopped responding|  07:48 " Ultron  [4]  |   2 tool calls x  |
|     #402 lmstudio 127.0.0.1:1234  Not blocking: ... |  08:14 * Steve   [1]  | You    sweep ...  |
|     Preview / Undo / Deadline                       |  4 done · 2 held · 1  | Gecko  ... [2] -> |
|     [Type "restart 4" | Approve once for all 4]     |=======================| You    Ce proie...|
|     [Reject group] [Defer] [Preview] [...]          | Today  Bucuresti 9°   | Jarvis +---------+|
| [2] ### Money  Gecko   Sweep €4,200 ...  [Approve…][Reject][Defer][...] | 11:00 ... in 9 min |  | N Gathering —||
| [3] ### Irreversible  Jarvis  Delete logs ...       |  14:00 the one that   |  | asking   [Stop]||
| [4] ##. External  Ultron  Veronica's draft ...  [Review the draft] ...  |   matters  |  | Trei proiecte||
|=====================================================|=======================|  +---------+|
| Can wait  2 decisions · reversible · held by Ask    | Agents  3 working ... | +---------------+ |
| (5) #.. Reversible  Draft a reply to Raiffeisen ... |  Athena  Oracle       | |To Jarvis  Ask | |
| (6) #.. Reversible  Move the research sync ...      |                       | |Message Jarvis…| |
+----------------------------------------------------+-----------------------+ +---------------+ |
                                                                              +-------------------+
 [n] = solid marker numeral (needs you now)   (n) = drawn numeral (can wait)   ### = tier pips
```

### The owner's screen: broadsheet edition (2560 × 1353 at 1.5×)

```
+--------------------------------- masthead + folio (as above, every signal at full length) --------------------------------+
| headline + deck (main column)            | standfirst, set in two columns: condition | overnight + next  | Conversation    |
|==========================================|===========================|==============================| (680 px, replies |
| Needs you now: every decision with its   | While you were away       | At work, by exception        |  at 17 px, about |
| full facts (context, preview, undo, why  |                           |  Working 3 / Waiting on you  |  66 characters a |
| it waits, the sealed audit entry)        |===========================|  3 / Finished 2 /            |  line; the head  |
|                                          | Today as a day ruler:     |  Unavailable 1 / Idle 9      |  of today's      |
|==========================================| 08 to 20, the past shaded,|==============================|  thread above    |
| Can wait: the same, with facts           | 10:51 marked, events      | Condition: verdict, RAM,     |  the first entry)|
|                                          | hanging from their ticks, | VRAM, GPU, latency unknown   |                 |
|                                          | the proposed 17:15 move   |==============================| composer: 3 lines|
|                                          | noted on the 16:30 sync   | Where it ran: 100%, 41 of 41,|                 |
|                                          |                           | the basis ladder, local-only |                 |
+------------------------------------------+---------------------------+------------------------------+-----------------+
  964 px                                     392 px                      392 px
```

The extra room carries more of the brief, never wider lines: a third column (agents at work, the
machine's condition, where work ran), every decision's full facts and its sealed audit entry, a
ruler of the day, and a size up for the conversation. Every measure stays under about 80
characters; all three brief columns end within a few lines of each other.

### How the nine areas and their panels are reached

- **The masthead names the nine areas** in a fixed order: Home, Work, Agents, Memory, Trust,
  Build, Connect, Observe, Settings. Navigation is dimmer than content (ink-2, 13.5 px); the
  current area is ink, semibold, with a 4 px rule under it. Only two areas carry a badge, and
  only because they hold something for the owner: **Work** (the marker flag "9 need you") and
  **Observe** ("4 services down" with the red diamond). Each area's tooltip says what it holds
  and how many panels it has.
- **Every area page has the same anatomy** (drawn for Trust in `secondary.html`): a contents
  column listing all the area's panels in named groups, with "Find in Trust" (`/` focuses it),
  counts and states beside panel names ("Audit chain 921", "Emergency stop armed", "Payments
  1 waits [2]"), and the current panel marked with a 3 px ink bar. The panel itself is composed
  like the brief: a verdict headline ("The chain is intact."), a deck, a standfirst called
  "What needs you here", then ruled columns. The 137 old Console panels become these second-level
  pages; the Console stops being a place.
- Trust's 21 panels are grouped as **Proof** (Overview, Audit chain, Audit anchors, Retention),
  **Control** (Emergency stop, Capabilities, Permissions, Skill switches, Desktop allowlist),
  **Money and secrets** (Payments, Secrets, Credential shares) and **Posture** (Posture, Data
  handling, Signal governance, Security skills, Pairing, Trust ops), plus "3 more panels" behind a
  disclosure. These group names are my proposal; they exist so 21 items scan as four short lists.
- **Search and command (Ctrl K)** runs over one registry: areas, every panel, the 18 agents and
  their actions. It is keyboard-first; verdicts are never bound to a key.
- **Decisions have one home**: the numbered list. Home prints its first page; Work › Decisions
  holds the whole queue and its history. The same item has the same number everywhere, and every
  other surface (the digest, At work, the conversation, Trust's payments and audit rows) points
  to it with a numbered flag instead of offering buttons of its own.
- Language EN/RO, the edition switch, Glance and **Stop all agents** live at the right of the
  masthead on every page. Stop is one click and reachable from every screen.

### What collapses

| Width | What changes |
|---|---|
| **2560 × 1353** (owner) | Broadsheet edition, above. Conversation 680 px. |
| **1920 × 1080** | Standard edition: brief in two columns (decisions 811 px, digest 372 px), conversation 641 px. Short windows (≤ 1040 px tall) tighten the leading between items, never the type. |
| **1440 × 900** | Compact edition: the digest drops under the decisions in two columns (away │ today and agents); headline 40 px. The folio keeps the five trust signals, drops channels, latency and the RAM/VRAM/GPU line; the nav badges become counts; Night/Glance become icons. |
| **1280 × 800** (desktop default) | As 1440, plus: conversation 430 px; search shortens to "Search Ctrl K"; the folio drops "since 08:14", "41 of 41 runs" and "Ollama" but keeps egress, on-this-machine with its basis, mic, model and live. The first screen shows the headline, the lead decision with its typed confirmation, two more decisions and the live reply. |
| **420 × 620** floating chat (not drawn) | The conversation alone. Above the thread, a one-line folio: verdict word, the "9 need you" flag, egress, on-this-machine with its basis, mic, live. A decision raised in the thread appears as its numbered flag and opens the decision in the main window; the small window never carries verdict buttons. Composer: recipient, mode, one line growing to four. |
| **Phone** (not drawn) | One column. Masthead: mark, the "9" flag, search, Stop. The folio becomes a two-line strip that keeps the five trust signals. The brief is the page: headline, then decisions with their controls stacked under the text at full width (the typed confirmation too); the digest folds under "While you were away". The conversation is a second tab with the composer docked. |

### Glance (idle or second screen) — `glance.html`

The brief's front page, read from across the room: the headline at 128 px with its deck, then
four values on one ruled line (the "9" flag that needs you, the verdict "Degraded · 4 services
down", "100% on this machine · by route", the next event "11:00 · 1:1 with Cosmina · in 9 min"),
and along the foot the reply in progress (the mark as progress) and the trust signals. The time
is there at 34 px, not as the hero. In the Night edition the ink drops one step, so an idle page is
never the brightest thing in the room. Nothing scrolls or animates; in production the frame would
also shift a few pixels every few minutes to spare the OLED (not drawn).

### What I changed from the draft I inherited, and why

- **The broadsheet edition is new.** At 2560 the inherited page stretched: decision sentences ran
  to 135 characters, buttons sat 600 px from their titles, and the lower third was empty.
- **Decision rows.** Row verdict buttons are now outlined with a heavier rule instead of solid
  ink, so the loudest marks on the page are the riskiest items and the lead's typed confirmation.
  Each control's icon names its friction (keyboard = typed, eye = review, check = one click) and
  a caption under the buttons says it in words. Sentences are capped at a reading measure.
  "Can wait" numerals are drawn instead of filled.
- **Night flags** (`--nv-flag-*`) as a lit outline; the conversation anchored to the composer;
  the standfirst split into two paragraphs (condition; overnight and next) so it can set in two
  columns on the broadsheet; the basis ladder for "on this machine".
- `secondary.html` (Trust) did not exist and is new.

## 4. How each job is served

**Talk.** The conversation owns the right-hand third of Home at every width and is anchored to
the composer: the newest words sit just above the box you type in. Replies are set in the reading
serif (16 px, 17 px on the broadsheet) with the owner's lines in the sans, so who said what reads
without bubbles. Every reply carries its provenance on a quiet line: "on this machine ·
gemma-4-31b". Its actions (Copy, Save, Read aloud, More) appear on hover or focus and stay visible
on the latest reply, instead of eight permanent buttons. A tool step shows as a line ("2 tool
calls · web_search done · file_write failed · Show"). **A reply in progress gets a tray of its own**,
because 4 to 60 seconds is a state you look at: the N mark is the progress (two nodes done, the
third ringed), with a status sentence ("Gathering — asking Pepper and Stark"), the step line
Classify → Route → Gather → Synthesize, the helpers and what each is doing, Stop as one button,
and the text growing in place with a steady caret. The composer is a ruled multi-line box: on its
top edge the recipient ("To Jarvis · orchestrated") and the approval mode ("Ask"); under the text,
Attach and Options (progressive disclosure for the five attachment kinds and four options), hints
for `/` commands and `@` files, local voice, and Send.

**Decide.** The headline counts what needs you; "Needs you now" and "Can wait" number every
decision: 18 raw requests, already grouped by the hub, become 9 actions in 6 decisions, and the
lead shows the grouping ("12 requests grouped into 4 actions") with one row per service. Every
item is decidable where it is read, and the friction follows the tier:

- **Irreversible or money (tier 3):** a typed confirmation in place. The lead shows the field
  open, marked with the highlighter: type "restart 4", then "Approve once for all 4" unlocks.
  Enter is swallowed so no key can approve. Decisions 2 and 3 show "Approve…" with a keyboard
  icon, which opens the same field in place. The hint says the typed confirmation covers these 4
  restarts only, never other decisions.
- **External (tier 2):** "Review the draft" opens the review, then confirm; "Redact and send" and
  "Reject" sit beside it.
- **Reversible (tier 1):** "Approve" is one click, and the caption promises the undo.
- Every item also offers Reject and Defer, and "…" holds Preview and Edit-then-approve. The
  approval mode (Auto / Ask / Off) sits in the head of "Needs you now" and again on the composer.
  Each decision carries its preview, its undo, its deadline and why it waits (in full on the
  broadsheet, as one or two sentences at 1920). No keyboard shortcut approves or rejects anywhere.

**Check.** The folio under the masthead is the verdict: one word with its shape ("Degraded" with
the triangle), the headline ("Working, with 4 local services down"), since when, and when it was
last checked. Then the trust signals that never hide at any width: egress, the on-this-machine
share with its basis, the microphone, the loaded model, and whether the data on screen is live.
At wider widths come channels, latency (unknown, drawn as unknown) and RAM/VRAM/GPU. In the
brief, the standfirst says the same thing as prose ("nothing is blocked; the restart is decision
1"), "While you were away" lists what the agents did overnight (time, agent, result, a kind icon,
and a numbered flag where it led to a decision), "Today" shows the day with the next meeting
highlighted, and agents appear by exception. On the broadsheet, **At work** lists every
non-idle agent by state, **Condition** draws RAM, VRAM, GPU and an empty dashed track for the
unmeasured latency, and **Where it ran** shows 100% on this machine, 41 of 41 runs and a **basis
ladder** (Unknown · Derived · By route · Verified) with today's rung marked and "Verified" drawn
as not reached yet. The Trust page is the deep version: emergency stop, locality, payments, the
audit chain drawn as a chain, capabilities, the local-only agents.

**Find.** Ctrl K from anywhere searches one registry of areas, panels, agents and actions. Each
area page lists its whole second level in a contents column with its own "Find in …" field (`/`).
Every brief item links to where it came from, and every flag points to the one numbered decision.

## 5. States

| State | How it looks | Where it is drawn |
|---|---|---|
| **Unknown** | Ink-3, a dashed ring, the word "unknown" in italics and the reason; a meter keeps its track but draws a dashed, empty line instead of a bar. Never a zero, a check or a default. | Folio "Latency p50 — unknown"; Condition meter "— unknown · Not measured by the hub yet" (broadsheet). |
| **Stale** | The value keeps its words but turns ink-3 with a clock and "checked HH:MM"; past three poll intervals the value is struck through and the verdict reads "stale since …". The data label becomes a half ring. | The folio always shows "checked 10:50". The stale styles (`.st-stale`, `.src-stale`) are in `briefing.css`; no stale value occurs in this moment. |
| **Empty** | The section says so in a sentence. The headline becomes "Nothing needs you." and the decisions collapse to one line. When the feed did not answer, the brief never says "all clear": "Unknown — sign in as the owner to see what is waiting." | Specified here; the "Empty" label is shown in the Trust legend. Not drawn as a full frame. |
| **Demo** | Every section names its source on its head: **Live** (solid dot), **Demo sample** (hollow ring and dashed underline: seed rows, never counted in a headline), **Empty** (dashed ring). | Every section of both pages carries "Live"; the legend at the foot of Trust shows all three. |
| **Error** | Red and a diamond, only for something that actually failed, with what it means. | "file_write failed" in Stark's reply; the 08:14 problem in the digest; the Observe badge; "Degraded" as the verdict. |
| **Working** | The live reply tray: the mark as progress, the status sentence, the step line, the named helpers, Stop. The masthead mark rings the current step. Nothing spins. | Jarvis at 10:51, mid-reply in Romanian. |
| **Waiting** | The marker flag: numbered decisions, the Work badge, the flags in the digest, At work's "Waiting on you", the conversation's "1 action waits for your decision", Trust's "1 waits [2]". | Throughout. |
| **Hub unreachable** | The folio verdict becomes "Hub unreachable · last answered 10:50" and every signal turns to unknown. The brief keeps the last edition under "as of 10:50", and its verdict buttons are disabled with the reason, because a control never pretends. | Specified. |

## 6. What I removed from the current screen, and where its information went

| Removed | Where it went |
|---|---|
| The decorative agent graph (30% of the screen) | Agents by exception in the digest; At work on the broadsheet; the full roster in Agents. |
| The 40 px glowing clock | The kicker line: "Monday, 23 November 2026 · 10:51". Time is not the hero. |
| The scrolling ticker | "While you were away": a still list with time, agent, result and kind, plus the folio verdict. |
| "ALL NOMINAL" and the always-red pulsing dot | One verdict word with its headline, causes, since, and last-checked time. |
| Seven top-bar badges | The folio's five trust signals (three more at wide widths), each a word with an icon. |
| The decision queue that could only "Dismiss" | The brief's numbered decisions with real verdicts and tiered friction. |
| 36 identical cards and duplicates | Six decisions grouped from 18 requests; group counts shown. |
| The roster column (every agent listed twice) | By exception: working, waiting on you, finished, unavailable; the rest as "9 idle". |
| 16 rail modes, a hidden Console of 137 panels, three loose buttons | Nine areas in the masthead; second level as each area's contents column; Ctrl K finds all. |
| The composer's four rows of options and two help sentences | One ruled composer: recipient and mode on top, Attach and Options menus, two hints. |
| Eight permanent buttons per reply | Provenance line, and four actions on hover, focus or the latest reply. |
| The system meter rows | Folio text (RAM 19% · VRAM 96% · GPU 3%); meters with bars in Condition on the broadsheet. |
| The weather widget | One line in Today's head: "București · 9° · Mist". |
| Cyan on navy, glow, chamfers, corner brackets, scanlines, the spinning logo | Nothing. |

## 7. Building it

- **Tokens only** (`tokens.css`): palette, type, spacing, radii, rules, motion. Names are
  role-first so both existing systems can converge: `--nv-paper*` ↔ `--ws-bg / --ws-surface*`,
  `--nv-ink*` ↔ `--ws-text*`, `--nv-rule*` ↔ `--ws-border*`, `--nv-mark*` ↔ `--ws-accent*`,
  `--nv-problem*` ↔ `--ws-danger*`, the same 4/8 px spacing grid and a 2/4/8 radius scale. The
  HUD's 29 flat tokens become aliases in one commit, which recolours the old screens before any
  markup changes.
- **New CSS** (`briefing.css`, about 300 lines, components only): masthead, folio and signals,
  section head with a 3 px rule, tier chip with pips, status marks, source labels, buttons
  (quiet, outlined verdict, primary, stop), segmented control, facts list, meters (including the
  unknown track), basis ladder, flags and refs. Page layout uses container queries for the three
  editions, so the brief adapts to its own width, not the window's.
- **New markup**: the brief (headline, deck and standfirst from live counts; the decision list
  with the typed-confirmation field and friction captions); the folio; the reply tray driven by
  the run's step events; the day ruler (broadsheet only); the area contents column, generated from
  the same panel registry that Ctrl K searches.
- **The riskiest part is the brief's sentences.** The headline, deck and standfirst must come
  from a deterministic template layer over hub counts, never from model prose, with honest
  fallbacks for every unknown ("The decision feed did not answer"), Romanian plural rules
  ("Nouă acțiuni te așteaptă"), and a rule for overflow when there are more decisions than a page
  holds. Second risk: the voice depends on the serif. Sitka and Segoe UI Variable are Windows
  system fonts and cannot ship, so Literata and Source Sans 3 (with latin-ext for ș and ț) must be
  vendored and checked on WebView2, WKWebView and WebKitGTK.
- **Suggested order:** (1) tokens and fonts, aliasing both old systems; (2) masthead and folio,
  which removes the dishonest status at once; (3) the decision list with real verdicts and the
  friction ladder, which fixes the biggest functional defect; (4) the conversation column and
  reply tray; (5) the digest; (6) area pages with contents columns and Ctrl K over one registry;
  (7) the broadsheet edition; (8) Night polish and Glance.

## 8. Self-critique

1. **The brief only fits because an editor cut it to fit.** At 1920 the page holds six decisions
   with one or two sentences each; the copy was chosen to land on the last line. With twelve
   decisions, long titles or Romanian (often 20–30% longer), "one page" becomes a scroll, and the
   power user's nightmare returns as a long document. The design needs a hard rule ("Needs you
   now" shows at most five; the rest fold into "and 4 more in Work", always counted in the
   headline) that I have described but not drawn.
2. **The voice rests on a serif the product cannot ship as drawn.** The editorial identity is
   carried by Sitka's optical sizes and Windows hinting. Literata is the right open replacement,
   but serif titles at 14–18 px on WebKitGTK may render softer, and a serif is slower to scan than
   a sans in dense lists. I kept tables and controls in the sans to limit this, yet item titles and
   replies are serif, so the risk is real until it is tested on all three webviews.

Smaller things I would fix next: the broadsheet's Condition section partly repeats the folio;
the conversation keeps a band of white above the first entry on the owner's screen; and a light
default on an OLED that is on all day is a choice the owner should be offered, not given. Night
by default after sunset, or following the OS, is the setting I would ship.
