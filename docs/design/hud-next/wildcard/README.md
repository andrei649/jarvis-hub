# Threshold — the wildcard direction for Nerva

Files: `cockpit.html` (Home), `secondary.html` (Trust · Overview), `quiet.html` (extra frame: the
line is a reading — your side when something waits, when nothing waits and when the feed did not
answer, with the stroke grammar), `tokens.css` (the token sheet), `threshold.css` (shared
components). Default theme: **dark**. Every page honours `?theme=dark|light`.

This direction was started by an earlier designer from the same brief (the idea, a draft identity
and the first cockpit) and finished here. What changed from that draft, and why, is listed at the end
of section 2.

## 1. The idea

Nerva makes two promises, and both are boundaries: nothing leaves this machine, and nothing with a
side effect happens without its owner. Threshold draws those two boundaries and puts everything in
its place relative to them — the machine is one bounded sheet whose outline *is* the egress state and
whose top edge carries the trust readings, and one line, the only coloured thing in the interface,
separates what Nerva does on its own authority from what waits for the owner. Every page is the same
picture, **Nerva ┃ you**, so the owner never has to work out whether something has happened, is
happening or is waiting on him: it is on one side of the line or the other.

**Promise:** nothing crosses the line without you — and you can always see where the line is.

## 2. Identity sheet

### Name and nouns

- **Interface:** *Threshold* (retires "HUD" and "cockpit"). The home page stays *Home*.
- Two nouns carry the chrome: **this machine** (the bounded sheet on the left: Nerva's side) and
  **the line** (the limit of Nerva's authority). Something that waits for the owner is *at the line*.
  Every pointer from Nerva's side to a decision reads "at the line →".

### Logo

The neural N with its geometry unchanged: no badge, no ring, no glow, never animated. The left
stroke and the diagonal are ink (Nerva); the right stroke and its two nodes are line yellow (you), so
the mark itself reads as the two sides and what passes between them. On daylight paper the yellow
stroke is keyed with an ink outline, like every yellow fill. Smallest size 16 px; it sits beside the
word *Nerva* set in the semi-condensed width at 600.

### Colour

Colour is computed in OKLCH and spent on meaning only. Three inks do all the talking — **ink** (what
Nerva knows and does), **line yellow** (what is yours to decide) and **red** (something failed, and the
one control that halts everything). There is no green: normal is drawn in ink, so "fine" never
competes with "yours". Hex values are the sRGB equivalents of the OKLCH source in `tokens.css`.

| Role | Token | Night (default) | Day |
|---|---|---|---|
| Window, your side | `--nv-ground` | `oklch(0.148 0.004 85)` #0b0b09 | `oklch(0.926 0.008 85)` #e9e6e1 |
| This machine | `--nv-machine` | `oklch(0.187 0.005 85)` #141311 | `oklch(0.985 0.004 85)` #fbfaf7 |
| Held at the line (cards) | `--nv-raise` | `oklch(0.226 0.006 85)` #1d1c19 | white #ffffff |
| Fields, own messages, hover | `--nv-raise-2` | `oklch(0.266 0.006 85)` #272522 | `oklch(0.952 0.006 85)` #f1efeb |
| Primary text | `--nv-ink` | `oklch(0.952 0.008 85)` #f2efe9 | `oklch(0.205 0.010 80)` #1a1712 |
| Secondary text | `--nv-ink-2` | #c2bfba | #44413b |
| Labels, metadata | `--nv-ink-3` | #9e9b96 (5.5:1 on the lightest surface) | #615d57 (5.3:1 on the darkest) |
| Non-text only | `--nv-ink-4` | #65635f | #95928d |
| Hairline / perimeter | `--nv-rule` / `--nv-rule-strong` | #2b2927 / #494744 | #dcdad6 / #b3b1ab |
| **Line yellow** (nodes, armed verdicts, the mode) | `--nv-line` | `oklch(0.868 0.170 92)` #fccf27 | #fccf20, keyed in ink |
| Yours as text and edges | `--nv-line-ink` | yellow #fccf27 (11.4:1 on cards) | ink #1a1712 over a yellow highlighter |
| **The line at rest** | `--nv-rail` | `oklch(0.560 0.105 86)` #906f1b | yellow #fccf20 with ink edges |
| Quiet band behind a held notice | `--nv-line-wash` | #28210d | #fbf2cc |
| Failure, the stop | `--nv-bad` | `oklch(0.725 0.160 28)` #fa7a6c (7.1:1) | `oklch(0.505 0.190 27)` #b91c1e (6.2:1) |

**The rail and the monitor.** The screen is on all day and may be OLED, so nothing bright is parked in
one place. At night the line itself is a dim ochre rail (4.2:1 against the ground, about a quarter of
the light of the yellow nodes, 13.2:1); full yellow is spent only on what changes — a node arriving,
a verdict, the mode. When nothing waits the rail turns to ink-4; when the decision feed did not
answer it is drawn dotted.

**The light theme is designed, not inverted.** At night yellow is *light*: yellow text and marks on
near-black. By day yellow is *a highlighter and a sign on paper*: what is yours is ink over a yellow
swipe (`--nv-line-hl`); yellow fills carry an ink keyline; the waiting count sits on a yellow plate;
held and attention marks sit on small yellow grounds; the line becomes a painted floor line with ink
edges; running text goes from weight 300 to 400. Same meaning, drawn for each medium.

**Why dark is the default.** Nerva is an all-day instrument beside other tools, often glanced at in a
dim room and possibly on an OLED panel; the night palette keeps total luminance low and lets the dim
rail do its job. Daylight is a peer, not an afterthought, and is the better choice in a bright room.

### Type

One DIN-family face in two widths; **width carries role**.

| Role | Size / line | Width · weight |
|---|---|---|
| Key hints, tags, column heads (the floor) | 12 / 16 | semi-condensed · 400 |
| Metadata, secondary text | 13 / 18 | either · 300 night, 400 day |
| Controls, lists, table cells | 14 / 19 | normal |
| Replies — read for a minute at a time | 15 / 23 | normal |
| A decision's title | 17 / 22 | semi-condensed · 600 |
| The health verdict, page headlines | 22 / 26 | semi-condensed · 600 |
| How many wait for you | 38 | semi-condensed · 600 |
| Glance numerals | 112 | semi-condensed · 300 |

- **Normal width** (100) for sentences you read; **semi-condensed** (87.5) for anything you scan:
  labels, titles, numerals, times. Tabular numerals everywhere. Sentence case everywhere.
- **Optical grade:** light type on dark spreads, so at night running text is 300 and returns to 400
  by day; 12 px text is always 400.
- **Mockup face:** Bahnschrift (installed; DIN 1451 drawing with a real width axis).
  **Production face:** **Barlow + Barlow Semi Condensed** (SIL OFL, self-hosted, Latin Extended with
  Romanian ș ț ă î â). **Mono:** JetBrains Mono (already vendored), only for identifiers, hashes,
  addresses, tool names and typed confirmations — never as a label style.

### Stroke grammar (certainty)

Every drawn line is the boundary of something, and its stroke says how sure Nerva is:
**solid = known · dashed = derived or not yet · dotted = unknown · filled = verified**. One rule,
used everywhere: the basis tag ("by route" solid, "derived" dashed, "unknown" dotted, "verified"
filled — reserved for later), the machine's outline (sealed / hybrid / unknown egress), the day ruler
(past solid, future dashed), a proposal not yet in the calendar (dashed), a verdict that is yours but
not yet armed (dashed with a lock), the section stamps (live solid, demo dashed, unknown dotted).

### Status vocabulary

Always a shape and a word; colour is the third cue. ok — solid dot, ink · attention — half-filled
node, yellow · problem — cross, red · unknown — dotted ring · stale — ring with a hand and "checked
hh:mm" · working — open arc, never spinning · held — two bars on yellow · blocked — slashed ring ·
done — tick.

### Shape, elevation, motion

- **Shape:** 4 px grid; a short concentric radius scale — 6 (controls, tags, fields), 10 (held cards,
  the composer), 14 (the machine). Hairlines 1 px; the line 3 px; the focused decision a 4 px edge.
- **Elevation:** opaque work surfaces in three steps (ground < machine < raise). By day the machine
  is paper on a desk (1 px / 2 px shadow). Blurred shadows only on transient layers (palette, menus).
  No glass, no glow, no gradients on surfaces.
- **Motion:** none at rest. One 140 ms transition when a state changes (a node arrives on the line, a
  verdict commits). "Working" never spins: progress is the step line advancing and the text
  arriving. `prefers-reduced-motion` sets every duration to 0.

### Voice on the chrome

Calm, specific, verb-plus-object on every control; sentence case; say what is known and how.

| Before | After |
|---|---|
| ALL NOMINAL (beside a red pulsing dot) | Working, with 4 local services down · Degraded since 08:14 |
| % LOCAL 100% | Runs on this machine · 100% · 41 of 41 runs today · by route |
| Dismiss (on a decision card) | Approve once for all 4 · Reject group · Defer |
| SITUATION ▸ marquee | While you were away · 4 done · 2 held or blocked · 1 problem |
| LATENCY p50 — | Latency p50 · Unknown — not measured by the hub yet |
| TRANSMIT | Send |

### Three things Threshold never does

1. **Never spends yellow on anything that is not yours to decide** — no yellow warnings, highlights,
   charts or brand flourishes. If it is yellow, it waits for the owner.
2. **Never draws a default as a reading.** No 0 %, no "MIC ON", no "all clear" when the feed did not
   answer: unknown is a dotted ring and the word *Unknown*, with the time it was last seen.
3. **Never moves or decides on its own.** No spinner, pulse, ticker or glow — and no keyboard shortcut,
   default button or Enter key that approves or rejects.

### What changed from the draft I inherited

- **The line at rest is now a dim rail at night.** The draft drew a full-height, full-yellow stripe:
  the brightest static object on the screen, which the brief rules out for an all-day, possibly
  OLED monitor. Bright yellow is now spent only on nodes, armed verdicts and the mode.
- **Three verdict weights** (armed / soft / locked) replace "every Approve is a yellow block", which
  had made the two reversible approvals the loudest things on the page. The decision in front of the
  owner is keyed instead (yellow outline, 4 px edge, ringed node).
- **Daylight theme reworked** around the highlighter-and-sign logic above.
- **2560 used, not stretched:** a third column (Today, to scale) and every decision fully open.
- **Production face:** Barlow instead of the draft's Sofia Sans — Barlow is closer to Bahnschrift's
  DIN 1451 drawing, so what ships looks like what was judged.
- Per-section live stamps, the working state's asks and the Trust page are new; the 1440 and 1280
  layouts are reworked (the draft's bar overlapped itself at both widths).

## 3. Layout and navigation

Home at 1920×1080:

```
 NERVA'S SIDE · this machine                                         ┃ YOUR SIDE
 N Nerva  Home  Work ‖9  Agents  Memory  Trust  Build  Connect       ┃ Andrei  [9] actions wait for you   EN RO ◐ ▭  [■ Stop all agents]
          Observe ×4  Settings              [⌕ Search and command ⌃K]┃
╭ Egress Sealed │ Runs on this machine 100% [by route] │ Mic On │ Model gemma-4-31b │ Live · checked 10:50
│ Health   Live │ Mon 23 Nov │ 09:30 │ 11:00 in 9 min │ 14:00 ◆ │ … ┃ [Auto|ASK|Off] Anything with a side effect waits for you  ●●●○ 3 of 4
│ ◑ Working, with 4      │                        Morning Jarvis…    ┃ |••• Irreversible or money 3 ··· typed confirmation
│   local services down  │ Jarvis  Good morning, Andrei…  [by route] ◉━┏━ Restart 4 local services ━━━━━━━━━━━━━━┓  ← the decision
│ × lmstudio … × n8n     │                     draft the churn slide ┃ ┃ 402 lmstudio … 411 n8n · what runs · undo ┃     in front of you
│ Restart waits ───────────────────────────────────────────▶ at the line [Type restart 4] [🔒 Approve once for all 4] ┃
│ RAM · VRAM · GPU       │ Stark  …MRR +6.2% WoW · 2 tool calls      ┃ ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
│ Latency  Unknown       │ Gecko  …€4.2k over buffer                 ●──┌ Sweep €4,200 …    [Review to approve] ┐
│ Agents, by exception   │  ║ 1 action waits — Sweep €4,200  at the line ▶──┌ Delete logs …      [Review to approve] ┐
│ ◔ Jarvis ◔ Pepper …    │            Ce proiecte sunt de terminat?  ┃ |•• External 1 ··· review, then confirm
│ ‖ 3 wait on you  ▶     │ ┌ Jarvis ◔ Gathering — asking Pepper and Stark ┐ ●──┌ Veronica's draft ① Review → ② 🔒 ┐
│ While you were away    │ │ ◔ Pepper … ◔ Stark …  · Trei proiecte…▌  │ ┃ |• Reversible 2 ··· one click, undo
│ 06:00 … 09:40 (7)      │ └ [■ Stop this reply]       asked 10:48     ┘ ●──┌ Draft a reply …  [Approve] [Reject] ┐
│                        │ ┌ To Jarvis · orchestrated   Mode Ask ▶ the line ┐ ●──┌ Move the sync …  [Approve] [Reject] ┐
╰────────────────────────┴─┴ Message Jarvis…                      [Send] ┘ ┃ ·| Read only does not wait → Audit chain
```

**How the nine areas and their panels are reached.**

- The nine areas sit in Nerva's bar, dimmer than content, in the product's order: Home · Work ·
  Agents · Memory · Trust · Build · Connect · Observe · Settings. Two carry flags because they hold
  something now: Work (‖ 9 need you, yellow — it is yours) and Observe (× 4 services down).
- Every area page keeps the same shell and adds its own **sub-navigation** inside the machine — the
  area's panels as second-level pages, with "Find a panel" scoped to the area. `secondary.html` shows
  Trust's 21 panels in three groups named by which side of the line they describe: *The record*
  (Overview, Audit chain, Audit anchors, Retention, Trust ops), *The line* (Emergency stop,
  Capabilities, Permissions, Payments, Skill switches, Desktop allowlist) and *The machine* (Posture,
  Data handling, Secrets, Credential shares, Pairing, Security skills, Signal governance), plus
  "3 more panels". The hidden Console stops being a place: its 137 panels are these pages.
- **Search and command (Ctrl K)** is in the bar on every page and finds every area, panel, agent and
  action. It can take the owner to a decision; it holds no verdict command.
- **Approvals have one home: your side**, on every page. Home shows the full cards; other pages show
  the same six groups as compact rows (drawn on Trust) whose Review opens the card in place.

**What collapses.**

- **2560×1353, the owner's screen:** your side widens to 820 px and *every* decision opens fully —
  what runs, undo and the typed field — so the owner reads all six without a click. The machine gains
  a third column, **Today to scale** (09:00–20:00; the past axis solid, the future dashed; the now
  line; Pepper's proposed move drawn dashed at 17:15 and pointing to the line). The thread is centred
  at an 820 px measure with its composer beneath; While you were away returns under the agents.
- **1440:** the report folds into a three-cell band (verdict, agents, away) above the conversation;
  each cell opens the full report as a drawer. Your side is 500 px; the owner's name and the request
  count's second line drop; language becomes one button; search keeps its icon and Ctrl K, and its
  label stays only as the button's spoken name.
- **1280×800 / 820 — the desktop shell's default:** band cells become single lines, past calendar
  events leave the strip, your side is 440 px and each group's request list folds into one line
  ("4 requests · 402 lmstudio · 409 qdrant …"); language, theme and glance go behind "⋯";
  *Stop all agents* keeps its label. The five trust readings stay, compacted.
- **420×620 floating chat:** the conversation alone, with the line as a 3 px rail down the right edge
  carrying the count (9) and the mode (Ask); a node appears on it when a reply creates a decision, and
  tapping it opens your side as a sheet. The plate shrinks to one row of words — Sealed · 100% by
  route · Mic on · gemma-4-31b · Live — and the stop stays as a labelled button in the title row.
- **Phone:** the line turns horizontal. Nerva's side scrolls above it; your side is a bottom sheet
  whose top edge is the line, showing "9 wait for you" and the mode at rest and the cards when
  pulled up. The plate is a single row under the title; areas live in search; the stop stays in the
  title bar.

## 4. How each job is served

**Talk.**
- One conversation, centred in the machine (43 % of the width at 1920; an 820 px measure at 2560),
  replies at 15/23, the owner's own messages in a quiet bubble on the right.
- **Provenance before the reply:** every reply header says where it ran and on what basis —
  "on this machine · gemma-4-31b · by route"; while streaming, "on this machine so far".
- **Working is designed for 4–60 seconds:** a status sentence ("Gathering — asking Pepper and Stark"),
  a four-step line (Classify, Route, Gather, Synthesize) with the current step ringed and the next
  dashed, the live asks to each specialist with what it is doing, the text arriving with a caret,
  *Stop this reply*, "Still writing. You can keep typing below." and "You asked at 10:48". It never
  spins and nothing pulses.
- **Composer:** multi-line; its header names the recipient (To *Jarvis · orchestrated* ▾) and the
  mode (*Ask*, linked to the line). Attach and Options hold the controls that used to fill four rows;
  typed shortcuts are one hint line; voice says "Voice ready · runs locally". Send waits in outline
  until there is text.
- Five reply actions (Copy, Save, Read aloud, Create task, More) on the latest finished reply only;
  earlier replies show them on hover. When a reply creates a decision, a yellow band inside it says
  so and points to the exact card: "1 action waits for your decision — Sweep €4,200 … at the line →".

**Decide.**
- **Your side** is always on screen, at the right edge of every page: 35 % of the width at 1920.
- 18 raw requests arrive as **9 actions in 6 groups**, sorted by tier from 3 to 1. Tier headings are
  rungs on the line and state their friction ("Typed confirmation · cannot be bulk-approved").
- **Friction follows the tier.** Tier 3: the typed field *is* the first step and carries the line's
  mark; Approve is locked (dashed, padlock) until the words match ("restart 4", "sweep 4200",
  "delete 312"); Enter in the field does nothing. Tier 2: two numbered steps, ① Review the draft →
  ② Redact and send, the second locked until the first is done. Tier 1: one-click Approve with the
  undo printed beside it ("Undo: Move it back."). Tier 0 never waits — a footnote says so and links
  the audit chain, so silence is legible.
- Every card names the agent and role, the tier, when it was raised and how often, why it waits, what
  would run, the undo and the deadline ("then it is blocked, never auto-approved"). Reject, Defer,
  Edit and Preview are on every card. A control is the real thing or absent.
- **The one decision in front of the owner is keyed:** yellow outline, a 4 px yellow edge and a
  ringed node on the line. Everything else on the side is quieter by construction.
- The mode (Auto / Ask / Off) heads your side — the only yellow control besides verdicts — with the
  interruption budget beside it (●●●○ 3 of 4). **Stop all agents** is red, labelled, one click, top
  right of every page; Trust also gives it a home panel.

**Check.**
- **The plate** across the top of the machine keeps the five trust readings at every width: Egress,
  Runs on this machine (with its basis tag), Microphone, Model, Data on screen (with "checked").
- **The machine's outline is the egress state:** solid while sealed, dashed when hybrid, dotted when
  unknown — the page itself says whether anything can leave.
- **One health verdict** with its shape, since when and when checked; the four causes with address
  and impact; the remedy pointing to the line; load meters (VRAM 96 % in ink, because it is expected);
  latency drawn as Unknown.
- **Agents by exception:** 3 working with what each is doing, 3 waiting (→ the line), 2 finished,
  1 unavailable with the reason, 9 idle as a count. **While you were away:** seven timed lines and
  their counts, still. **Today:** a strip at 1920, a to-scale ruler at 2560.
- Every section carries a stamp — Live / Demo sample / Nothing yet / Unknown — so a page that mixes
  live and seeded data says so section by section.
- **The line itself is a reading:** yellow rail with nodes, something waits; ink, nothing waits;
  dotted, the decision feed did not answer.

**Find.**
- Search and command (Ctrl K) on every page reaches ~155 destinations: 9 areas, 137 panels, 18
  agents and the actions; arrows move, Enter opens, Esc returns. It has no approve or reject command.
- Each area has its own sub-navigation and a scoped "Find a panel" (drawn on Trust).
- Area flags show where attention is before the owner goes looking; typed shortcuts in the composer
  (/new, /undo, /refine, /&lt;skill&gt;, @file:path) cover the conversation's commands.

## 5. States

- **Waiting** (drawn): a yellow node on the line and a card at it; the reply band "at the line →";
  the area flag "Work ‖ 9 need you"; the count 9 in the bar; the day ruler's dashed proposal.
- **Working** (drawn): the streaming block above; agents with the open-arc mark; static, no spinner.
- **Unknown** (drawn): latency p50 — dotted ring, the word, the reason ("not measured by the hub yet").
  The same grammar covers the rest: a dotted basis tag, a dotted machine outline when egress is
  unknown, plate values reading "Unknown · last seen 10:50", and a dotted line with your side saying
  "Unknown — sign in as the owner to see what is waiting." It never says "all clear" when the feed
  did not answer.
- **Stale:** the ring-with-a-hand mark, the value drops from ink to ink-2, and the stamp changes from
  "Live · checked 10:50" to "Stale · checked 10:41"; past its window it becomes Unknown. The
  "checked" times that make staleness visible are drawn on the plate and on Health.
- **Empty** (drawn in `quiet.html`, panel 2): "Nothing is waiting for you." The line turns to ink and
  loses its nodes; the side lists what runs on its own (the capabilities left of the line) and keeps
  the tier-0 footnote, so the quiet is explained; on Home the side then narrows and hands its width
  back to the machine. Sections with no data say "Nothing yet" with a hollow stamp.
- **The feed did not answer** (drawn in `quiet.html`, panel 3): the line is dotted, the count becomes
  a dotted ring and the word Unknown, the mode is shown as unknown, and the side says "Unknown — sign
  in as the owner to see what is waiting." The stop stays one click.
- **Demo:** a dashed "Demo sample" stamp on each section that shows seeded rows, a dashed tag on any
  seeded value, and "Data on screen · Demo sample" on the plate.
- **Error:** red only for a failure that happened, always with its consequence — "file_write failed —
  nothing was changed", the four services "not responding" with their impact. Hub unreachable turns
  the plate to Unknown with the last-seen time and draws the line dotted.
- **Locked and armed verdicts** (drawn): dashed with a padlock until the gate is passed, then filled.

## 6. What was removed, and where its information went

| Removed from today's screen | Where it went |
|---|---|
| Decorative agent graph (30 % of the screen) | Gone. Agents by exception in the report; the full roster is the Agents area; delegation is shown where it happens, in the working block ("asking Pepper and Stark"). |
| The roster, listed twice | Agents by exception (working, waiting, finished, unavailable; idle as a count), "All 18 agents →". |
| 40 px glowing clock | Times on everything; the Today strip; the now line at 2560; large time in glance mode. |
| "ALL NOMINAL" beside a red pulsing dot | One verdict sentence with causes, since and checked. |
| Marquee of warnings | While you were away: seven timed lines, still. |
| Seven top badges (AGENTS, LLM, DATA, GATEWAY, % LOCAL, EGRESS, MIC) | The plate: five trust readings with basis and time; Channels and Agents into the report. |
| Decision queue with only "Dismiss", 36 identical cards | Your side: 6 grouped cards with real verdicts and tier friction; Defer replaces Dismiss. |
| 16-mode rail, hidden Console, three floating buttons | Nine areas, per-area sub-navigation, search; "demo" becomes per-section stamps; Ambient becomes Glance mode; World signals live in Observe. |
| Four always-visible composer rows (~14 controls, two help sentences) | Recipient and mode in the composer header; Attach; Options; one hint line. |
| Up to eight buttons on every reply | Five, on the latest reply; the rest under More. |
| Conversation / Cognition / Artifacts tabs | Steps and tool calls inline in each reply; artifacts through search and Memory. |
| Cyan on navy, glow, brackets, chamfers, scanlines, spinning logo | Ink, one yellow, one DIN face. |
| System meters panel, BACKEND, LATENCY | Load meters inside Health; the model on the plate; latency as Unknown. |
| Weather widget | One line: "9° · Mist" (București). |

## 7. Building it

- **Tokens only:** colour, type, space, radii, elevation and motion are drop-in custom properties in
  `tokens.css`, written once with `light-dark()` so one token set serves both themes. The names are
  neutral (`--nv-*`) and the 4 px grid and 6 / 10 / 14 radii match the Workspace app's `--ws-*`
  sheet, so both can converge on it. Swapping tokens alone re-colours and re-types the product but
  does not change its structure.
- **New CSS on existing markup:** the status marks and stroke grammar, section stamps, the three
  verdict weights, the plate's layout, the area flags, the light-theme highlighter.
- **New markup and components:** (1) the **shell** — a two-sided grid (bar ┃ bar / machine ┃ your
  side) with the line, mounted once in the app frame; (2) **YourSide** — the grouped queue with tier
  sections and gated verdicts, plus its compact variant for other pages; (3) **the plate**, bound to
  posture, egress, route counts, microphone, model and data source; (4) **the working block**, bound to
  the stream's step, asks and partial text; (5) per-area **sub-navigation** generated from the panel
  registry, and the search index; (6) the **Today ruler** (wide screens only).
- **Riskiest part: honesty plumbing, not pixels.** The line, the plate and the stamps make claims —
  live, stale, unknown, by route, derived. Each needs a real field and timestamp from the hub, and
  the 18 places that draw defaults today must learn to render Unknown. The typed-confirmation gate and
  "no shortcut approves" must also be enforced by the hub, not only by the page. Second risk: the
  3,423 inline style attributes, which must go before the tokens can take effect.
- **Suggested order:** tokens and self-hosted Barlow → the shell with today's panels inside the
  machine → your side with real verdicts (delete Dismiss) → health verdict, agents by exception and
  While you were away (retire graph, roster and ticker) → composer and working block → areas,
  sub-navigation and search → the daylight pass → 2560 third column and 1280 compaction → glance
  mode and the 420×620 window.

## 8. Self-critique

1. **Yellow and ink carry a warning connotation.** Spent on "yours" rather than "danger", and dimmed
   at night, it reads as authority once learned — but by day the yellow line with ink edges is a
   strong graphic that a first-time viewer can read as hazard tape, and a direction about calm
   competence should not look alarmed. If testing shows that reading, the day rail should fall back
   to a quieter ochre and keep full yellow for nodes and verdicts only, as the night theme already
   does.
2. **The two-sided frame costs width and density.** Your side takes 35 % of a 1920 screen and 34 % of
   the 1280 window even when the queue is short, and it carries a lot of small text: six cards of
   12–17 px metadata are dense to scan, and at 1280 the typed-confirmation card still pushes two
   groups below the fold. `quiet.html` draws the empty and unknown states of the side, but I have not
   drawn Home with the side narrowed, nor the in-between case — one or two waiting groups — which
   needs a measured rule for how wide the side should be.

Smaller things I would fix next: Trust shows the stop twice (bar and its home panel); the Today ruler
is only as useful as the calendar is full; and the hub's "Approve once for all 4" sits awkwardly with
"tier 3 cannot be bulk-approved" — I treated a same-shape group raised by the hub as one action that
still needs the typed phrase, which the product owner should confirm.
