# Presence — a direction for the next Nerva interface

Files: `cockpit.html` (Home) · `secondary.html` (Trust › Overview) · `glance.html` (the extra frame:
idle, second screen or wall) · `tokens.css` · `presence.css` (chrome shared by all three pages) ·
`mark-states.svg` (the mark's eight states, for the brand book). Renders are in `shots/`; files
starting with `_` are close-up probes.

Continuation note: another designer started this direction, and its idea, name, identity and
two-voice layout are kept unchanged. This pass:
- fixed the defects the renders showed: a collision at 2560, a wrapping search label at 1440, and
  truncated trust signals and an overflowing Send at 1280;
- made "while you were away" show by exception;
- moved each decision's tier into one aligned column;
- gave the light theme its own highlighter idiom;
- made all three decisions fit at 1280;
- added `secondary.html`, `glance.html` and the mark specimen.

## 1. The idea

Nerva is not a dashboard that happens to contain an assistant: it is one presence, Jarvis, that
listens, works, speaks, and turns to the owner when it needs him. So Home is a stage with two voices.
On the left is the exchange, set like a script, with the live turn at the size of speech. On the
right the presence turns to you, saying "I need you on three things.", with the real, tier-graded
decisions underneath. The logo stops being a badge and becomes the instrument: the neural N is the
path of a request (in, route, gather, out), the ring around it is the boundary of this machine, and
a single tungsten bead on the ring means something is held there for you.

**Promise:** one glance tells you what Jarvis is doing and what it needs from you, and anything
coloured on the screen is either yours to deal with or cannot be undone.

## 2. Identity sheet

**Name.** The interface is called **Presence**, replacing "HUD" and "Cockpit". The home screen is
**Home**, the idle and second-screen mode is **Glance** (replacing "Ambient"), and the product stays
**Nerva**.

**The mark.** The existing neural N inside its ring (`_kit/nerva-mark.svg`) is redrawn as a
monoline instrument, ink on ground, with no glow. It works at two cuts:
- **Small cut** (20–32 px, top line): heavy strokes and no halo. The bead still shows.
- **Live cut** (60–170 px: the live turn, Glance): thin ring and thick travelled path.

Grammar (see `mark-states.svg`):

| Part | Means |
|---|---|
| Ring | The boundary of this machine. Closed means egress is sealed. Broken where a route can leave means hybrid. Dashed means unknown. Red means stopped. |
| N path | One request: in, route, gather, out. Its four nodes are the steps Classify, Route, Gather, Synthesize. A thick stroke is the path already travelled, a thin one is the path still ahead. |
| Halo | The step it is on now. |
| Inner arc | Voice level, drawn only while the owner is talking (Listening) or Jarvis is talking (Speaking). |
| Bead | The only colour in the mark: something is held at the boundary for you. It composes with every state. |

Eight states: Idle, Listening, Working, Speaking, Needs you, Hybrid, Unknown, Stopped. Every state
is paired with one plain sentence ("Gathering — asking Pepper and Stark"). The mark never appears
without its sentence, except at the small cut in the top line, where the sentence is its accessible
name.

**Colour.** There are two inks and two signals, from one token set (`tokens.css`, `light-dark()`
pairs in OKLCH). There is no green. "OK" is quiet ink plus a glyph.

| Role (token) | Dark (default) | Light | Used for |
|---|---|---|---|
| Ground `--ground` | `oklch(0.165 0.004 78)` | `oklch(0.968 0.005 85)` | the page: a warm near-black, or warm paper |
| Surface `--surface` | `0.208 0.005 78` | `0.995 0.002 85` | plates: the open decision, the composer, the selected panel |
| Field `--surface-2` | `0.250 0.005 78` | `0.944 0.006 85` | fields, the chosen segment |
| Sunken `--sunken` | `0.138 0.004 78` | `0.946 0.007 85` | the instrument foot, second-level navigation (dimmer than content) |
| Hairline `--line` / `--line-strong` | `0.262` / `0.390` | `0.892` / `0.760` | structure; control borders |
| Ink 1 `--ink-1` | `0.955 0.008 85` | `0.215 0.012 70` | what you read now |
| Ink 2 `--ink-2` | `0.800 0.010 82` | `0.395 0.012 70` | what supports it; resting values; all static chrome |
| Ink 3 `--ink-3` | `0.690 0.010 80` | `0.495 0.012 72` | labels, meta, unknown (≥ 4.5:1 in both themes) |
| Ink faint `--ink-faint` | `0.470 0.008 80` | `0.700 0.010 80` | non-text only: the path ahead, ticks, the chain line |
| **Tungsten** `--yours` | `0.830 0.125 76` | `0.500 0.130 58` | "yours": text and glyphs for what waits on the owner |
| Tungsten fill `--yours-fill` | `0.830 0.125 76` | `0.860 0.145 84` | the primary action, and the highlighter on paper |
| Tungsten dot `--yours-dot` | `0.830 0.125 76` | `0.640 0.150 64` | the bead, waiting nodes, the "Needs you" dot (≥ 3:1) |
| **Signal red** `--danger` | `0.720 0.170 27` | `0.505 0.190 27` | cannot be undone, broken, the emergency stop |
| Red fill / line | `0.560 0.200 27` / `0.520 0.150 27` | `0.520 0.200 27` / `0.640 0.170 27` | the stop when pressed; its outline |

Status, always as a word plus a glyph: ok = ink, no glyph colour · attention = tungsten + triangle
· problem = red + triangle or the word "failed" · unknown = ink 3 + dashed circle · stale = ink 3 +
its age ("checked 10:50 · 6 min ago").

**The one colour decision.** Tungsten is the light of a desk lamp. It means "this is waiting for
you", and it is never spent on chrome, focus or decoration. In the dark the word itself is lit. On
paper a lamp means nothing, so the same tokens turn tungsten into a highlighter: ink stays ink and
a marker sits behind it ("three things.", the badges, "in 9 min") or under it (links to a
decision). That is the light theme's own idiom, not an inversion. Dark is the default: the screen
is on all day beside other tools and may be an OLED panel, tungsten reads as a lamp in the dark,
and the owner's own newest tool is dark. Light is fully designed for daytime and bright rooms.

**Type.** One DIN family with a width axis, plus a mono for identifiers.
- UI: **Barlow + Barlow Semi Condensed** in production (SIL OFL, self-hosted). It is rendered here
  with the installed stand-in **Bahnschrift** (a variable DIN, `wght` 300–700, `wdth` 75–100). It is
  the type of road signs and car clusters: legible at a distance, calm, not a "tech" face.
- Mono: **JetBrains Mono** (already vendored, OFL), only for identifiers, addresses, hashes, model
  names, times in tables, and typed shortcuts.
- Scale at the 16 px root: 12 labels · 13 secondary · 15 body and controls · 16 the transcript · 17
  titles · 21 the open decision · 26 the live turn · 32 the status sentence · 46 the statement.
  Glance uses 22–24 / 60 / 64 / 144 / 240. On the owner's 2560 screen the root steps to 18 px. At ≤ 1500
  px and ≤ 1320 px only the display sizes step down. Nothing is under 12 px.
- Weights: 300 for numerals at display size, 350 for text, 400 for foot values, 600 for names and
  titles. Sentence case everywhere, tabular numerals everywhere. Before anything is hidden, the foot
  and the area names condense on the width axis.

**Shape, elevation, motion.**
- Radii: 3 (tags, tier bars) · 6 (controls) · 10 (plates) · 14 (composer), concentric.
- Structure comes from hairlines and spacing (4/8 grid). Surfaces are opaque.
- Elevation in the dark: a plate is simply a lighter surface. On paper: a 1 px contact line.
  Transient layers (menus, Ctrl K) get `--layer-shadow` on an opaque surface. Nothing is frosted.
- Motion: still by default. One 180 ms ease-out when a state changes (a node fills, a decision
  closes). The only moving things are the streaming text and the voice arc while someone is
  talking. No pulsing, no breathing, no spinners. `prefers-reduced-motion` removes the transitions.
- Brightness rule: static chrome never rises above ink 2. Ink 1 and tungsten are spent on what is
  live or waiting, which changes or goes away. That matters on an OLED panel.

**Voice on the chrome.** Plain, specific, first person only where the presence speaks. Before → after:

| Before (today) | After (Presence) |
|---|---|
| `ALL NOMINAL` beside a pulsing red dot | Health · checked 10:50 — **Working, with 4 local services down** |
| `DECISION QUEUE 36` + `Dismiss` | **I need you on three things.** Three more can wait. — with Approve, Review, Defer and Reject that are real |
| `SITUATION` + a scrolling marquee | **While you were away: 4 done, 2 held or blocked, 1 problem.** |
| `LATENCY p50 —` / `0%` | **No time estimate — latency p50 is unknown, not measured yet** |
| `% LOCAL 100%` | **On this machine · by route — 100% · 41 of 41 runs today** |
| `TRANSMIT` | **Send** |
| `AMBIENT` | **Glance** |

**Three things this identity never does.**
1. It never draws a default as a reading. Unknown is a dashed glyph and the word "unknown", never
   OK, 0 or "on".
2. It never spends colour on decoration. Tungsten means yours, red means cannot be undone, and
   nothing else is coloured. No green ticks, no gradients, no glow, no cyan.
3. It never gives the presence a face or a performance: no eyes, no idle breathing, no orb as a
   hero. The mark changes only when the state changes, and no keyboard shortcut ever approves.

## 3. Layout and navigation

Home at 1920 × 1080: FIND above, TALK and DECIDE on the stage, CHECK below.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ (N•) Nerva  Home  Work 9 need you  Agents  Memory  Trust  Build  Connect  Observe 4 services down  … │ FIND
│                                              [⌕ Search and command  Ctrl K]  EN|RO  ◐  ▭ Glance  10:51 │
├──────────────────────────────────────────────────────────────┬──────────────────────────────────────┤
│ Monday 23 November · București, Mist 9°   Next 11:00 1:1 with Cosmina in 9 min · Live │ ● Needs you · Live   Interruptions 3 of 4  [Auto|Ask|Off] │
│ Since last night  While you were away: 4 done, 2 held…  Show all 7 │ I need you on three things.      │
│                   ⚠ 08:14 Steve  lmstudio, qdrant, neo4j…  decision 1 │ Three more can wait. 9 actions… │
│                   ⊘ 08:01 Ultron SSRF attempt blocked             │ ┌ 1 Restart 4 local services ───┐ │
│                   ‖ 07:48 Ultron 2 PII findings…       decision 4 │ │ ▮▮▮ Irreversible · Steve …    │ │
│ ─────────────────────────────────────────────────────────── │ │ 12 requests → 4 actions       │ │
│ 08:02 Jarvis  Good morning, Andrei. …        ◉ on this machine │ │ Preview · Rollback · Deadline │ │
│ 08:05 Stark   Stark pulled the numbers …     ‹› 2 tool calls   │ │ Type restart [____] [Approve] │ │
│ 08:07 Gecko   Gecko's watching the markets … ‖ 1 action waits  │ └───────────────────────────────┘ │
│               Read aloud · Copy · More                         │ 2 Sweep €4,200 …  ▮▮▮ Money [Review]│
│ ─────────────────────────────────────────────────────── TALK │ 3 Delete logs …  ▮▮▮ Irrev. [Review]│
│ 10:48 You     Ce proiecte sunt de terminat acum?               │ Three more can wait               │
│ (N•)  Jarvis · started 10:51 · on this machine · gemma-4-31b │ ◉ Pepper · Checking… │ 4 Veronica's draft  ▮▮▯ [Review the draft] │
│ mark  Gathering — asking Pepper and Stark    │ ◉ Stark · Pulling… │ 5 Draft a reply …   ▮▯▯ [Approve]  │
│       ● Classify ─ ● Route ─ ◉ Gather ─ ○ Synthesize [■ Stop] │ ◌ No time estimate │ 6 Move the sync … ▮▯▯ [Approve] DECIDE │
│       Trei proiecte au termene săptămâna aceasta: …▍           │                                   │
│ (mic) [ Message Jarvis…                  /new /undo /refine /<skill> @file:path ]               │
│ Voice [ To Jarvis · orchestrated ⌄ · Approval Ask ⌄ · + Attach · Options ⌄              ↑ Send ]  │
├──────────────────────────────────────────────────────────────┴──────────────────────────────────────┤
│ Health ⚠ Working, with 4 local services down │ 3 working · 3 waiting on you │ Egress ◉ Sealed │    CHECK
│ On this machine · by route 100% │ Microphone On │ Model gemma-4-31b │ Data ● Live │ [■ Stop all agents]│
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**The nine areas.**
- The top line carries Home · Work · Agents · Memory · Trust · Build · Connect · Observe ·
  Settings. Areas are dimmer than content, and an area carries a badge only when something in it
  needs the owner ("9 need you", "4 services down").
- Every area opens on its own second-level list of panels, shown in `secondary.html` as Trust's
  21 panels in four groups: the record, control, money and keys, posture. A panel list is never
  hidden at any width; at 1280 it narrows and drops its counts.
- The old Console stops being a place: its 137 panels are these second-level pages. Search and
  command (Ctrl K) finds every area, panel, agent and action by name.
- Decisions have **one** home, the queue in Work. Home shows the top of that same queue, the same
  component with the same real controls, not a copy. Everywhere else (a reply's margin note, the
  away list, the audit chain, Payments) only links to it ("decision 2").
- Language, theme and Glance sit at the right of the top line. The clock there is small, in ink 2.

**What changes with the width.**
- **2560 × 1353** (the owner's screen): the root steps to 18 px and a third column, **Today**,
  joins on the left. It holds the next event at speech size, the day's schedule with a "now" line,
  agents by exception (working 3, waiting on you 3, finished 2, idle 9, unavailable 1) and this
  machine's RAM, VRAM and GPU. The exchange keeps its margin, and all six decisions are visible
  without scrolling. The room is used for a new column of answers, not stretched into.
- **1920 × 1080** (designed): two columns. The transcript is a script with a margin for
  provenance, tool calls and waits.
- **1440 × 900** (≤ 1500 px): margin notes fold under the speech, and display sizes step down
  (the statement goes 46 → 36). The open decision's member table folds into one summary line
  ("…lmstudio, qdrant, neo4j and n8n — Oracle's workflows cannot run while n8n is down. Show the
  4"), so all three things stay in view. The foot condenses on the width axis and drops its
  optional words ("· 2 finished").
- **1280 × 800/820** (≤ 1320 px, the desktop app's default window):
  - the gutter stacks time over name;
  - the statement keeps only its first sentence, and the confirmation field moves under its label;
  - the no-shortcut note shortens to "No shortcut · no bulk approval";
  - foot labels shorten ("Model", "Data"), but no trust cell is removed or truncated;
  - area badges become counts, and search becomes an icon with Ctrl K.

  All three things remain visible: decision 1 open with its typed confirmation, decision 2 whole,
  decision 3's title and Review.
- **420 × 620** (the floating chat, not drawn): one column. At the top, the mark at the small cut
  with its status sentence. Then the transcript as a script with the margin folded, and the
  composer with the voice ring. One line says "I need you on three things →" and opens Home; the
  small window never carries approve buttons, so a verdict is always made at full size. A single
  tell-tale line stays at the bottom: Sealed · 100% by route · Mic on · Live · ■ Stop.
- **Phone** (not drawn): Home is a stack. First the presence line and "I need you on three things."
  with the three decisions (tier 3 opens the full plate with typed confirmation; tier 1 approves
  with undo). Then a "while you were away" list, with the conversation as its own tab. The trust
  tell-tales become a strip under the status bar, and Stop all agents stays one tap from Home.

## 4. How each job is served

**Talk.**
- The exchange is set as a script: who | what was said | margin. Older turns are at reading size
  (16 px). The live turn is at speech size: your question at 26 px, then the presence block (mark +
  "Gathering — asking Pepper and Stark" at 32 px + the four steps + **Stop this reply**), then the
  reply streaming at 26 px with a caret.
- Replies take 4 to 60+ seconds, so the working state is designed to be watched. It names the
  step, shows who is being asked and what each is doing ("Pepper · Checking this week's
  deadlines"), and says honestly "No time estimate — latency p50 is unknown". Stop is always beside
  the steps.
- Every reply carries its provenance in the margin ("on this machine · gemma-4-31b", tool calls,
  "file_write failed").
- The composer is a multi-line box that shows who receives the message (To Jarvis · orchestrated)
  and the approval mode (Ask). Attach and Options are menus. The typed shortcuts show only while
  the box is empty, and Send lights only when there is text.
- Voice is the ring to the left of the composer, the same ring as the mark ("Voice ready · runs
  locally"). Listening lights the ring and draws the level arc, and Read aloud is one of the three
  actions left visible on the latest reply (Read aloud · Copy · More).

**Decide.**
- The presence turns to you: **"I need you on three things."** The three are the
  irreversible-or-money groups; "Three more can wait."
- 18 raw requests are grouped into 9 actions in 6 numbered groups. Each line opens with its tier,
  three bars plus a word, so the risk words form one column: red for irreversible or money, ink for
  the rest.
- Friction follows the tier:
  - Tier 3: the open plate shows what would run, rollback ("None", in red), the deadline and the
    group's members, then **Type `restart` to approve** before **Approve once for all 4** wakes. It
    cannot be bulk-approved.
  - Money and the other tier-3 group: **Review** opens the same plate.
  - Tier 2: **Review the draft** (review what will be sent, then confirm).
  - Tier 1: **Approve**, one click with undo.
- Edit then approve, Defer and Reject sit quietly under the verdict. "No shortcut approves" is
  stated where the verdict is made. The approval mode (Auto | Ask | Off) and the interruption
  budget (3 of 4) are in the column head.
- Every control is the real one. There is no "Dismiss".

**Check.**
- The instrument foot holds, at every width:
  - one health verdict with since and checked ("Working, with 4 local services down"), linked to
    its causes and to the fix that waits in decision 1;
  - agents by exception;
  - the five trust tell-tales: Egress, On this machine with its basis, Microphone, Model, Data on
    screen;
  - **Stop all agents**, one click, armed.
- "While you were away" opens the transcript by exception: the problem, the block and the hold,
  each linking to its decision, with the four done items as a count.
- On the owner's screen the Today column adds the schedule, agents and machine meters.
- The Trust area says three plain things ("The chain is intact." "41 of 41 runs took the local
  route." "The stop is armed.") and then shows the evidence: the audit chain drawn as a chain, the
  friction ladder with what waits now, where work ran with its basis ladder, capabilities and
  payments.

**Find.**
- Nine areas on the top line, with badges only where something needs you.
- A second-level panel list inside every area, grouped and always visible.
- **Search and command** (Ctrl K) reaches every area, panel, agent and action. The keyboard is
  first for navigation and never for verdicts.
- The panels that do not fit a group's list say so: "and 3 more — Ctrl K finds every panel by name".

## 5. States designed

- **Working** (drawn): the mark's path fills node by node with a halo on the current step, and the
  status sentence names the step and who is being asked. Each agent's current task sits in the
  margin, with Stop this reply and streaming text with a caret. When latency is unknown, it says
  there is no estimate rather than inventing a progress bar. In production an elapsed time beside
  "started 10:51" updates once a second as text, with no animation. If the hub reports no steps,
  the mark falls back to "working" without nodes rather than faking progress.
- **Waiting on you** (drawn):
  - the tungsten bead on the mark (also at the small cut in the top line);
  - "I need you on three things." with numbered decisions;
  - margin notes ("1 action waits for your decision");
  - tungsten nodes in the audit chain, "1 waits" on Payments in the panel list, and "Waiting on
    you 3" in Today.
- **Unknown** (drawn): latency p50 appears as "unknown, not measured yet" with a dashed glyph,
  never 0. In the mark it is a dashed ring and a dashed path ("I can't reach the hub — last heard
  10:50"). A tell-tale that did not answer reads "Microphone · Unknown" in ink 3 with a dashed
  glyph, never "On". If the decision feed does not answer, the statement becomes "Unknown — sign in
  as the owner to see what is waiting", never "all clear".
- **Stale** (specified): a value past its refresh keeps its last reading in ink 3 with its age
  beside the label ("checked 10:50 · 6 min ago") and the word "stale". Health and the trust
  tell-tales show "checked" times even when fresh.
- **Empty** (specified): the statement becomes "Nothing is waiting for you." in ink (no tungsten),
  the bead leaves the mark, the Work badge disappears, and the column gives its room back to the
  exchange.
- **Demo** (drawn as a system): every section head carries its own data tag: a filled dot for
  Live, a half-filled dot for "Demo sample", an open dot for Empty. "Data on screen" in the foot
  says Live, Demo sample, Offline or Empty for the page as a whole. A page that mixes live and seed
  rows tags each section, never one chip for all.
- **Error** (drawn): "file_write failed — nothing was changed", in red with its consequence; the
  four services down, each with its impact and remedy; an outbound request blocked. Hub
  unreachable is specified as the mark's Unknown state.
- **Stopped** (specified in `mark-states.svg`): a red ring and the stop square, "Stopped. Nothing
  runs until you resume.", and Resume in the place of Stop.
- **Idle, listening, speaking, hybrid**: the mark's other states, in `mark-states.svg`. Hybrid also
  changes the Egress tell-tale ("Hybrid — a cloud route is reachable"), opens the ring in the
  Trust figure, and draws any cloud run as a tick outside the ring.

## 6. What was removed, and where its information went

| Removed from today's screen | Where it went |
|---|---|
| The decorative agent graph (30% of the screen) and the roster listed twice | Agents by exception: the foot ("3 working · 3 waiting on you"), the live turn's margin (who is being asked, doing what), the Today column at 2560, the Agents area. |
| The glowing orb, the spinning logo | The presence mark, which carries real state and has no glow. |
| The 40 px glowing clock | A 19 px clock in ink 2 on the top line; a large clock only in Glance, in the dimmest ink. |
| `ALL NOMINAL` + the pulsing red dot + seven badges | One health verdict in the foot with since and checked, and five trust tell-tales that never hide. |
| The `SITUATION` marquee | "While you were away", by exception, at the top of the transcript; it never moves by itself. |
| A decision queue that could only "Dismiss" (36 identical cards) | One grouped queue with real verdicts and friction by tier; Home shows its top. |
| 16 rail modes, the hidden Console (137 panels), three loose buttons | Nine areas; panels as second-level pages; Search and command; Glance, theme and language on the top line. |
| A one-line input wrapped in 4 rows of 14 controls | A multi-line composer: To, Approval, Attach, Options; shortcuts shown only while empty. |
| Up to 8 always-visible buttons per message | Read aloud · Copy · More on the latest reply; the rest behind More, and on hover or focus for older turns. |
| RAM / VRAM / GPU meters on every screen | Observe; on the owner's 2560 screen, the Today column. |
| The weather panel | One line in the column head ("București · Mist, 9°"). |
| Cyan on navy, glow, chamfers, corner brackets, scanlines, uppercase tracked mono | Gone. |

## 7. Building it

- **Tokens only.** Palette for both themes (`light-dark()` OKLCH pairs), type scale, weights,
  radii, spacing, the size steps, and the tungsten idiom (lamp in the dark, highlighter on paper,
  through `--yours-mark-*` and `--yours-ul-*`). The 29 flat tokens of today's stylesheet map onto
  these by renaming. The Workspace `--ws-*` set already shares the 4/8 grid and the 6/10/14 radii,
  so the two systems merge by renaming, not redrawing. Theme switching is one attribute that flips
  `color-scheme`.
- **New CSS, existing markup.** The top line and its nine areas, the instrument foot and its
  width-axis condensing, buttons and segments, tier bars, data tags, the sub-navigation, and the
  sentence-case and tabular-numeral type roles.
- **New markup.**
  - The Home stage: two columns at 1920, three at ≥ 2200.
  - The exchange as a script grid (gutter | speech | margin) with its fold rules.
  - The presence block, driven by the reply's run state.
  - The decision row and the open plate with typed confirmation.
  - The away summary.
  - The Trust overview: the chain ledger, the ring figure, the basis ladder.
  - Glance.
  - The mark as one SVG component with a class per state.
- **Data it needs.** Everything drawn exists in the shared content and the hub's shapes: grouped
  approvals, tiers, route per run, health causes, the steps Classify / Route / Gather / Synthesize.
  The one stretch is per-agent "doing" text during a run. Where the hub sends only "ready" or
  "idle", the margin shows nothing rather than an invented task.
- **Riskiest part.** The presence block. Its value is that it tells the truth in real time, so it
  needs an honest run-state stream: current step, which agents were asked, and a stop that really
  stops the run. Faked progress would be worse than the old orb. Second risk: today's 3,423 inline
  styles mean these components have to be rewritten, not re-skinned.
- **Suggested order.**
  1. Tokens, type and both themes.
  2. The top line and the instrument foot, including the stop.
  3. The decision queue with real verdicts and friction by tier: the largest product fix.
  4. The exchange and the composer.
  5. The mark and the run states.
  6. The Trust overview.
  7. Glance.
  8. The 2560 Today column.
  Container queries can replace the width steps per column once the layout is in.

## 8. Self-critique

1. **Home is still dense.** The promise is "very few things, each at the size its importance
   deserves", and Glance keeps it. Home at 1920 carries the whole transcript, an open decision
   plate, five more decisions and an eight-cell foot. The hierarchy holds in the squint test:
   statement, then status sentence and reply, then open plate. Still, it is a busy stage, closer
   to a well-set working page than to the automotive calm the direction names. At the 1280 desktop
   default the three things fit only because the plate folds its member table, and the
   transcript shrinks to about two turns above the live one.
2. **The mark is mostly proven on paper.** The shared moment shows one state on screen (working,
   with the bead). Listening, speaking, hybrid, unknown and stopped exist in `mark-states.svg` and
   in this text, not in an interactive frame. The whole idea also depends on the hub reporting real
   step progress, which today it may not; without it the mark degrades to a plainer "working".
   Smaller risks: tungsten sits close to the conventional warning amber, so "yours" and "attention"
   share a colour on purpose, and that could read as a warning palette. The Bahnschrift → Barlow
   swap has not been rendered, because Barlow is not installed here.
