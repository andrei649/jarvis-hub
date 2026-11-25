# Console — the dense instrument

Direction for the next Nerva interface. Files: `cockpit.html` (Home), `secondary.html` (Trust),
`glance.html` (extra frame: glance mode, for idle or a second screen), `tokens.css` (the token
sheet), `console.css` (frame and components every page shares). Default theme: **dark**.
Renders: `shots/` (`glance-1920-*.png` were shot with the kit's `shoot.mjs`; `shootset` covers
the two required pages).

> Continuation note. This direction was started by another designer and finished here. The idea,
> name, palette grammar and layout are theirs and were kept. What changed, and why, is listed at
> the end of section 1.

## 1. The idea

Nerva is an instrument for someone who has delegated real authority to software, so its face is an
instrument: one strict grid of tiled panes, real tables with aligned tabular numerals, and nothing
on screen that is not a reading. Its centrepiece is a truthful picture of the day: one lane per
active agent on a shared time axis, showing what each did, what it is doing, and — as an amber rail
that starts at the minute it asked — what it has been holding for the owner, with every decision
pinned by number to the moment that raised it. Colour is not branding: the screen is neutral
graphite or paper, **amber is lit only where something waits for the owner** and red only where
something is broken or stopped, so the colour on screen is itself the to-do list.

**Promise:** everything in view, nothing decorative — and if nothing is lit, nothing needs you.

What the finishing pass changed (kept: idea, name, identity, layout):

- **The now-lens.** The last six minutes of the time axis are magnified (a lighter band from 10:45
  to now, labelled in the legend). At one scale, work that began two minutes ago was a 7-pixel blob;
  in the lens it is a readable bar, so "what is running now" is drawn, not just written.
- **The decision sheet** now shows the moment that raised the decision (the owner's own words,
  quoted, beside Gecko's), its audit seal and request number; its verdict footer is pinned and stays
  visible at every width (it was cut off at 1440 and 1280). The confirmation field no longer shows
  "4200" as its placeholder, which read as already filled in.
- **The verdict** lost its amber wash: degraded-but-not-blocking is attention, not an alarm, and a
  lit band parked all day at the top of an OLED panel is exactly what the brief warns against.
- **Widths.** 1280 overflowed and clipped the verdict controls; 2560 stretched panes into dead
  space. Both now have their own layouts (section 3).
- **The working reply** shows who is working on it (Pepper, Stark, since 10:49) and how long it has
  run (asked 10:48 · 3 min).
- **Production face**: Barlow instead of Sofia Sans, because the identity rests on DIN 1451
  shapes and Barlow is the open face closest to them (section 2).

## 2. Identity sheet

### Name

**Nerva Console.** It replaces "HUD" and "cockpit". The old hidden "Console" drawer of 137 links
disappears — its panels become second-level pages of the nine areas — and the word is promoted
from a hiding place to the name of the instrument. In copy: "the Console", "Home", "Trust"; never
"HUD", "cockpit", "mission control".

### Logo

The neural N (`_kit/nerva-mark.svg`) redrawn as a single ink stroke with four nodes: no ring, no
tile, no glow, no rotation. The mark is also a presence signal: its top-right node takes the
**signal amber when something waits for the owner** and the **fault red when the agents are
stopped**; otherwise all four nodes are ink. It is drawn at 20 px beside the word "Nerva" set in
the UI face, semibold, at 16 px, tracked +0.02 em. Minimum size 16 px; clear space one node
diameter.

### Palette — roles and values

One token set; every colour is written once as `light-dark(<day>, <night>)` in OKLCH, so the theme
is only `color-scheme` on `<html>`. There is no green, no blue and no brand colour.

| Role | Token | Night (default) | Day |
|---|---|---|---|
| Frame, bars, wells where things happen now | `--nv-bg` | `oklch(0.150 0.004 75)` | `oklch(0.930 0.006 85)` |
| Panes | `--nv-surface` | `oklch(0.184 0.004 75)` | `oklch(0.975 0.004 85)` |
| Raised: decision sheet, inputs, owner turns | `--nv-surface-2` | `oklch(0.224 0.005 75)` | `oklch(1 0 0)` |
| Hover, pressed, keycaps | `--nv-surface-hover` | `oklch(0.258 0.006 75)` | `oklch(0.905 0.007 85)` |
| The magnified minutes of the axis | `--nv-lens` | `oklch(0.198 0.005 75)` | `oklch(0.966 0.006 85)` |
| Hairline | `--nv-border` | `oklch(0.272 0.005 75)` | `oklch(0.885 0.006 85)` |
| Control edge | `--nv-border-strong` | `oklch(0.360 0.006 75)` | `oklch(0.780 0.008 85)` |
| Text-field edge (3:1) | `--nv-input-border` | `oklch(0.540 0.008 75)` | `oklch(0.560 0.010 85)` |
| Ink: readings, body | `--nv-text` | `oklch(0.955 0.006 85)` | `oklch(0.205 0.010 80)` |
| Ink: secondary | `--nv-text-muted` | `oklch(0.810 0.006 85)` | `oklch(0.360 0.010 80)` |
| Ink: labels, units (4.5:1 everywhere) | `--nv-text-subtle` | `oklch(0.690 0.006 85)` | `oklch(0.455 0.010 80)` |
| Non-text marks: idle ticks, run cells | `--nv-mark` | `oklch(0.520 0.006 80)` | `oklch(0.600 0.008 80)` |
| **Signal** — waits for you: words | `--nv-signal-text` | `oklch(0.830 0.140 80)` | `oklch(0.480 0.115 62)` |
| Signal: rails, glyphs, sheet edge | `--nv-signal-line` | `oklch(0.830 0.140 80)` | `oklch(0.590 0.150 62)` |
| Signal: pins | `--nv-signal-fill` | `oklch(0.830 0.140 80)` | `oklch(0.810 0.150 74)` |
| Signal: wash behind ink | `--nv-signal-soft` | `oklch(0.245 0.038 78)` | `oklch(0.948 0.048 80)` |
| **Fault** — broken, failed, stopped: words | `--nv-fault-text` | `oklch(0.735 0.160 28)` | `oklch(0.500 0.190 28)` |
| Fault: glyphs, the stop edge | `--nv-fault-line` | `oklch(0.700 0.180 28)` | `oklch(0.560 0.210 28)` |
| Focus | `--nv-focus` | = ink | = ink |

Why dark is the default: the Console is on all day beside other tools on an OLED-capable panel;
a graphite ground keeps the large areas dim and lets the only colour on screen — amber — carry
meaning. The day theme is designed, not inverted: it is paper panes on a grey desk (the frame is
darker than the panes, the reverse of night), the signal shifts from yellow-amber to a burnt amber
that still makes 3:1 as a line on paper, and the type runs one weight step heavier because dark ink
on paper does not spread the way light ink on graphite does.

### Type

| Role | Face | Size / line | Weight night · day | Width |
|---|---|---|---|---|
| The one figure that matters (stake) | UI face | 36 px (44 on 2560) | 600 · 650 | 100% |
| Trust readings, locality figure | UI face | 26–44 px | 600 · 650 | 100% |
| Figures in table rows | UI face | 20 / 22 | 600 · 650 | 100% |
| Selected decision title | UI face | 16 / 22 | 600 · 650 | 100% |
| Conversation, decision titles | UI face | 14 / 21, measure ≤ 72 ch | 350 · 400 | 100% |
| Table cells, controls, navigation | UI face | 13 / 18 | 350 · 400 | 87.5% |
| Column heads, units, provenance | UI face | 12 / 16 | 350 · 400 | 87.5% |
| Keycaps and pin numerals only | UI face / mono | 11 | 700 | 100% |
| Identifiers, addresses, hashes, models, code | JetBrains Mono | 12–13 | 400 | — |

- **UI face:** a DIN 1451 engineering sans. Rendered here with **Bahnschrift** (installed, variable
  weight and width). **Production: Barlow + Barlow Semi Condensed** (SIL OFL, self-hosted, Latin
  Extended with Romanian ș ț). Barlow is static, so production snaps the half-step night weights
  to its instances (night 400 / 500 / 600, day 400 / 500 / 700) and keeps the night/day difference
  in ink lightness instead. Width 87.5% maps to the Semi Condensed files.
- **Mono:** JetBrains Mono (already vendored), only for things a person might copy: `127.0.0.1:1234`,
  `71bb…e2c4`, `gemma-4-31b`, `file_write`, `/refine`.
- Tabular numerals everywhere (`font-variant-numeric: tabular-nums` on `body`); numeric columns
  right-aligned. Sentence case everywhere; no uppercase labels, no tracked capitals.

### Shape, elevation, motion

- **Panes tile.** The screen is divided by 1 px hairlines into square panes; no gaps, no cards
  inside cards, no radius on panes.
- **Radius** only on things you press or type into: 2 px (pins, tags, keycaps), 4 px (buttons,
  fields), 6 px (the raised decision sheet, transient layers).
- **Elevation:** panes are flat and opaque. The decision sheet is the only raised surface on Home
  (one step lighter, 3 px signal edge). Shadow exists only for transient layers (palette, menus).
- **Lines carry meaning by weight:** the hold rail is 4 px for tier 3, 2 px for tier 2, 1 px for
  tier 1; tier tags go from hairline to inverted ink as risk rises. Risk is never a colour.
- **Motion:** nothing moves by itself. No ticker, no pulse, no spinner, no rotating mark. A state
  change is one 120–180 ms step (`--nv-dur-1/2`), zero under `prefers-reduced-motion`. The live
  reply advances by its text and its step ladder, not by animation.

### Voice on the chrome — before → after

| Before (today) | After (Console) |
|---|---|
| `ALL NOMINAL` beside a red pulsing dot | **Degraded** — Working, with 4 local services down · since 08:14 · checked 10:50 |
| `Needs approval · irreversible` on all 36 cards | Tier 3 asks for a typed confirmation. Type **4200** to approve the transfer. |
| `Dismiss` (hides the card for 30 seconds) | **Defer** — and it really defers; or **Reject**, with an optional reason |
| `MIC ● ON` (also shown when unknown) | Microphone **On** · and, when the hub does not say, Microphone *unknown* |
| `% LOCAL 100%` | Runs on this machine **100%** · 41 of 41 runs today · `by route` |
| `TRANSMIT` | Send |
| `SITUATION` marquee | While you were away: 4 done · 2 held or blocked · 1 problem |

Rules: say the number, the thing, and the time; name the agent as a role label; say "you", never
"the user"; say what a control does ("Approve transfer", "Stop reply"), never "OK" or "Confirm".

### Three things this identity never does

1. **It never colours something that is normal.** No green "OK", no coloured agent icons. Normal is
   ink; amber means *waits for you*; red means *broken, failed or stopped*. If amber appears for
   any other reason, the system has lied.
2. **It never moves on its own.** Nothing scrolls, pulses, spins or glows; the screen changes only
   when the state does.
3. **It never draws a default as a reading.** An unmeasured value is a hatched swatch and the word
   *unknown* — never 0, never "On", never "all clear" when the feed did not answer.

## 3. Layout and navigation

### Home at 1920 × 1080

```
┌─ bar 44 ─────────────────────────────────────────────────────────────────────────────────────────┐
│ N Nerva  Home  Work ■9  Agents  Memory  Trust  Build  Connect  Observe ◆4  Settings              │
│          [⌕ Search or run a command  Ctrl K]     Mode [Auto|Ask|Off]  ▮▮▮▯ 3 of 4  EN RO ◐ ▭ [■ Stop all agents] │
├─ status line 30 ─────────────────────────────────────────────────────────────────────────────────┤
│ ▲ Degraded  Working, with 4 local services down · since 08:14 · checked 10:50 │ [1] Restart waits for you │
│                    🔒 Egress Sealed │ ▭ Runs on this machine 100% · 41 of 41 [by route] │ Mic On │ Model … │ Data Live │
├─ conversation 568 ──────────┬─ Today ──────────────────────────────────────────────────────────────┤
│ 08:02 You    Morning…       │ 09:30 Standup │ 11:00 1:1 [in 9 min] │ 14:00 Raiffeisen [Important] │ 16:30 [6] │ 19:00 │
│ 08:02 Jarvis Good morning…  │ 8 active   06:00   07:00   08:00   09:00   10:00  10:45│Now 10:51  3 waiting · 3 working │
│   on this machine · gemma   │ Steve            ◆ services stopped ……[1]═══════════════│■ Waiting on you   4 restarts…  │
│ 08:05 You    draft the…     │ Gecko             ▭"sweep idle cash"…[2]═══════════════│■ Waiting on you   Sweep €4,200 │
│ 08:05 Stark  … ✓ ✕          │ Ultron   PII held □ □ SSRF blocked [4]────────────────│■ Waiting on you   Holding…     │
│ 08:07 You    sweep idle cash│ Jarvis       [3]══════════════════ routed ●  ▬▬▬▬│▬ Working          Answering you│
│ 08:07 Gecko  … [2] waits    │ Stark        ✕ file_write failed [5]──────────  ▬▬▬│▬ Working          Pulling…     │
│ 10:48 You    Ce proiecte…   │ Pepper    ● calendar synced [6]───────────────  ▬▬▬│▬ Working          Checking…    │
│ 10:51 Jarvis ▬ Gathering    │ Friday  ● brief · Vision ● indexed · Athena ---- · 9 idle                 (quiet rows)│
│   Classify Route Gather Syn │                                       └ lens: last 6 min, magnified       │
│   ▬ Pepper  deadlines 10:49 ├─ Decisions ─────────────────────────────────────┬─ sheet 528 ──────────┤
│   ▬ Stark   status    10:49 │ [3 Irreversible or money] typed; never in bulk  │ [2] [3 Money] Gecko  │
│   Trei proiecte au…▌        │ [1] Restart 4 local services   4 services 08:14 │ Sweep €4,200 …       │
│ ┌ To Jarvis · orchestrated ┐│     402 lmstudio 127.0.0.1:1234  Not blocking…  │ €4,200  Current → Ladder │
│ │ Message Jarvis…          ││ [2] Sweep €4,200 …   €4,200  08:07  Shown at right│ Context / Would run / Undo│
│ │ + Attach ⚙ Options 🎙 Voice ready      Mode Ask [Send]││ [3] Delete logs …  312 files 07:30   │ Raised 08:07: “sweep idle cash” │
│ └──────────────────────────┘│ [2 External] [4] LinkedIn draft   [Review the draft]│ Recorded 71bb…e2c4   │
│                             │ [1 Reversible] [5] Draft reply   [Approve] ⋯      │ 0 1 2 [3] ladder      │
│                             │                [6] Move sync     [Approve] ⋯      │ Type 4200 [____] [Approve transfer] │
├─ key line 26 ───────────────┴─────────────────────────────────────────────────┴─ Edit · Reject · Defer ┤
│ Ctrl K Search · 1–9 Areas · J K Move · Enter Open · / Message · Esc · ? Keys │ Verdicts never take a key │ p50 unknown · RAM · VRAM · GPU │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Reading order on Home is the owner's job order: **talk** (left, full height), **check** (Today:
what each agent did, is doing, is waiting on), **decide** (the table and the open sheet). Pins are
the glue: decision 2 is the same numbered amber square in the conversation, on Gecko's lane, in the
table, in the sheet, in the Trust audit chain and in Payments.

### The nine areas and their 137 panels

- The **bar** lists the nine areas (Home · Work · Agents · Memory · Trust · Build · Connect ·
  Observe · Settings), dimmer than content, with a count only where something is abnormal: Work ■9
  (amber: needs you), Observe ◆4 (red: services down). Keys `1`–`9` jump to them.
- Each area opens on an **Overview** with its **panel list** as second-level navigation down the
  left (Trust shows all 21: 18 named + "and 3 more"), with a filter field and live counts beside
  the panels that have something to say (Audit chain 921, Emergency stop Armed, Payments ■1 waits).
- **Search and command** (`Ctrl K`) indexes every area, all 137 panels, the 18 agents and the
  actions; it is the only "more" place. The old Console drawer, the 16-mode rail and the floating
  buttons are gone.
- **Approvals have one home:** the Decisions table. On Home it is the live pane; Work › Decisions
  is the same table at full height with the history. Everywhere else a decision appears only as its
  numbered pin, which links to the row.

### What collapses

| Width | What changes |
|---|---|
| **2560 × 1353 @1.5×** (owner's screen) | More columns and more words, never wider measures: conversation 680 px with the 72 ch cap; lanes 42 px with a 128 px lens; tier-3 rows gain a third line (would run · undo); the four services gain *not responding · since 08:14*; the sheet gains *Payments today* and the friction ladder gains its rules; status facts and key line show their long forms. The sheet sizes to its content instead of stretching. |
| **1920 × 1080** | As drawn. The page never scrolls; the conversation, the decision list and the sheet body scroll inside. |
| **1440 × 900** | Conversation 448 px with name and time stacked in one gutter; lanes 30 px, lens 80 px; agenda loses the weather; the restart group's four services fold into its row; the sheet's body scrolls under a fade while its verdict footer stays pinned; long tails of the status facts drop (never the facts). |
| **1280 × 800** (desktop window default) | Conversation 384 px; the agenda folds into the Today header (*Next 11:00 1:1 with Cosmina · in 9 min · 14:00 Raiffeisen · Important*); Athena and the idle row fold into the counts; the *Doing* column goes (the live reply already lists who is working on what); *Raised* folds into the timeline; search becomes its key; trust facts go compact (icon + value; *On this machine 100% by route* never drops). |
| **420 × 620** (always-on-top chat) | The conversation alone: transcript, live reply with its crew and elapsed time, composer with recipient and mode. A one-line strip on top keeps the trust signals as glyph + value (Sealed · 100% by route · Mic On · Live) and the pins as links ("[1][2][4] wait — open"); verdicts open in the main window. The emergency stop stays, one click. |
| **Phone** | One column, three tabs: Decisions (the sheet full-screen; typed confirmation works with the numeric keyboard), Conversation, Today (lanes turn into a list of agents with state, a short rail of the day, and the pins). The trust strip is pinned at the top. |

### Glance mode (`glance.html`)

The bar's glance button (or idle) turns the Console into something readable from across the room:
the five glance readings at 64 px (*10:51 · 9 need you · ▲ Degraded, 4 services down · 100% on
this machine, by route · 11:00 1:1 with Cosmina, in 9 min*), then the day picture with only the
lanes that wait on the owner or are working — pins, rails and run bars at three times the size, no
event labels — and the trust signals along the bottom. Ink is one step dimmer than on Home and
nothing is white-hot, because this is the screen most likely to sit unchanged for hours on an OLED
panel; in production the whole frame also shifts by a few pixels every few minutes. Amber is still
the only colour, so from across the room the question "does anything need me?" is answered by
whether there is amber on the screen.

## 4. How each job is served

**Talk.** A transcript, not bubbles: time · who · text in three aligned columns, body at 14 px
capped at 72 characters. Every reply carries its provenance under it (*on this machine ·
gemma-4-31b*). The reply that is still being written gets the most attention on the screen for as
long as it takes (4–60 s and more): an ink bar on its edge, its status line (*Gathering — asking
Pepper and Stark*), the step ladder (Classify ✓ Route ✓ **Gather** · Synthesize), the agents working
on it with what each is doing and since when, the text as it arrives with a caret, the elapsed time
(*asked 10:48 · 3 min*), and **Stop reply**. Per-reply actions show only on the last finished reply
(Copy, Save, Read aloud, Create task, More). The composer is a multi-line box that names the
recipient (*To Jarvis · orchestrated*, a menu) and the mode (*Ask*); attachments and options sit
behind two buttons; Send stays quiet until there is text. `/` focuses it.

**Decide.** One table, sorted by risk tier, each tier headed by its friction (*typed confirmation;
cannot be bulk-approved* · *review what will be sent, then confirm* · *one click, undo available*).
The 18 raw requests arrive grouped as 9 actions in 6 rows; the restart group shows its four
services with addresses and impact. Friction follows the tier in the row itself: tier 1 rows carry
a real **Approve** (undo available) and a menu; tier 2 offers **Review the draft**; tier 3 opens.
The open decision gets the sheet: the stake as the largest figure on the screen (**€4,200** ·
Current account → Savings ladder), context, what would run, undo, why it waits, the conversation
moment that raised it, and its audit seal. The verdict footer is pinned at every width: tier ladder,
*Type 4200 to approve the transfer*, a disabled **Approve transfer** until the amount matches,
**Edit then approve**, **Reject**, **Defer**, **Preview**. No key approves or rejects; the key line
says so.

**Check.** One verdict with its cause, its age and its fix (*▲ Degraded — Working, with 4 local
services down · since 08:14 · checked 10:50 · [1] Restart waits for you*), followed by the trust
signals that never hide (egress, on-this-machine share with its basis, microphone, model, data on
screen). Below, Today answers "what happened, what is running, what is waiting" in one picture: the
agenda, then one lane per active agent with marks for what it did (● done, □ held or blocked,
◆ problem, ✕ failed), amber rails for what it holds for you, ink bars for what it is running, and the
magnified last six minutes. The key line carries the machine's own readings (latency *unknown*, RAM,
VRAM 96%, GPU) and the Observe badge counts what is down.

**Find.** `Ctrl K` finds any area, panel, agent or action; `1`–`9` jump to areas; every area has a
filterable panel list; `J`/`K` move in any list, `Enter` opens, `Esc` goes back, `?` lists every
key. Navigation and search are keyboard-first; verdicts are deliberately not.

## 5. States

| State | How it looks | Where it is drawn |
|---|---|---|
| **Waiting** (on you) | Amber, and only here: the pin with the decision's number, a rail from the minute it was raised to now (weight = tier), *Waiting on you* in the lane, the logo's node lit, Work ■9 in the bar | Home lanes, table, sheet, conversation, agenda (pin 6 on 16:30), status line; Trust chain and Payments |
| **Working** | An ink bar in the lens from when it started; *Working* with a bar glyph; in the conversation the live reply with ladder, crew, caret and elapsed time | Home |
| **Error / problem** | Red, and only here: ◆ for a service down, ✕ for a failed call, with the sentence that says what it means (*Not blocking: the model is being served by Ollama instead.*) | Home lanes, restart group, conversation tool calls, Trust chain, Observe ◆4 |
| **Unknown** | A hatched swatch and the word, never a number: *Latency p50 unknown*; the locality basis has *Unknown* as a rung; an unanswered decision feed reads *Unknown — sign in as the owner to see what is waiting* | Key line on both pages; Trust basis ladder |
| **Stale** | The last reading kept, ink drops to muted, the source tag becomes an outlined square with its time (*Stale · 10:32*); verdicts always carry *checked hh:mm* | `.src.stale` in `console.css`; *checked 10:50* in the status line |
| **Empty** | Said in words: *Nothing is waiting for you.* With nothing waiting, no amber remains anywhere and the logo is all ink | `.src.empty`; copy in this README |
| **Demo** | A dashed tag with a hatched square, *Demo sample*, on each section that shows seed data — never one chip for a whole page | `.src.demo` in `console.css` |
| **Unavailable / idle** | Slash-circle *Unavailable* with the reason (*Cloud only — unavailable while egress is sealed*); idle agents fold into one row of names | Home lanes; Trust routing policy |

Every section labels its source (*● Live*) at its own header, so a page that mixes live rows and
seed rows says so where it happens.

## 6. What was removed, and where its information went

| Removed from today's screen | Where it went |
|---|---|
| The neural-network graph (30% of the screen) | Today's lanes: the same agents, but only the active ones, drawn as what they did and hold; the rest fold into a count |
| The roster column (18 agents, listed twice) | Lanes by exception; the full roster lives in Agents |
| The 40 px glowing clock | *Now 10:51* on the time axis, where time means something; the OS clock does the rest |
| The scrolling SITUATION marquee | *While you were away* counts in the Today header and the events on the lanes; nothing scrolls |
| `ALL NOMINAL` and the permanent red dot | The computed verdict with its cause, age and fix |
| Seven top-bar badges | Five trust facts in the status line (each with a word, a value and, for locality, its basis) |
| The 36-card queue that could only Dismiss | The grouped Decisions table with real verdicts and tier friction, and the sheet |
| The four-row composer with 14 controls and two help sentences | Recipient + mode line, the box, Attach and Options menus, Voice, Send |
| Eight always-visible buttons per reply | Four actions + More, on the last finished reply only |
| The 16-mode rail, the hidden Console with 137 links, three floating buttons | Nine areas in the bar, second-level panel lists, `Ctrl K` |
| The System panel (RAM/VRAM/GPU bars, `BACKEND unknown`) | The key line, with *unknown* drawn as unknown |
| Weather and Heartbeat panels | Weather: one cell at the end of the agenda (9° · Mist). Heartbeat: gone (it could never have content) |
| Scanlines, glow, chamfers, corner brackets, cyan on navy | Nothing |

## 7. Building it

**Tokens only.** Swap `--hud-*` for the `--nv-*` sheet: surfaces, lines, ink, signal, fault,
spacing (4 px base), radii (2/4/6), durations. The slot names deliberately mirror the Workspace
sheet (`--ws-bg`, `--ws-surface`, `--ws-text-muted`, `--ws-s1…`), so the two can converge on one
file: Workspace's light-first values become the `light-dark()` day half. Removing glow, scanlines,
uppercase and letter-spacing is mostly deleting rules.

**New CSS on existing markup.** Status line, key line, pane header, the `.tbl` table rules, pins,
tier tags, source and basis tags, the hatched unknown, the ladder, buttons. These are small,
self-contained classes in `console.css` and can replace the 3,423 inline style attributes area by
area.

**New markup (React components).**
1. `<StatusLine>` — verdict + fix + trust facts; one data source, one place.
2. `<DecisionTable>` and `<DecisionSheet>` — grouped rows from the hub's existing groups, counts,
   `approval_deadline_at`, preview and rollback; the sheet's typed confirmation reuses the existing
   `confirm.tsx` logic.
3. `<DayLanes>` — the timeline: events from the audit chain and "while you were away", holds from
   the decision queue, runs from agent state; positions are plain CSS (`--t` minutes, `--m` lens
   minutes).
4. `<Transcript>` + `<LiveReply>` + `<Composer>`.
5. `<PanelList>` for second-level navigation, fed by the same index as `Ctrl K`.

**Riskiest part: the lanes' truth.** The picture is only as honest as its data. Today the hub
reports agents as *ready* or *idle*; *working since* and *held since* need real timestamps per
agent and per request, and the audit chain must be joinable to agents and requests. Until those
fields exist, a lane must render what is known (events and holds, which exist) and say *unknown*
for the rest — never interpolate. Second risk: Barlow's tabular figures and Romanian comma-below
glyphs must be checked in the self-hosted subset before the switch.

**Suggested order.** (1) tokens + typeface + delete the decorative layer; (2) status line and key
line on every page (fixes most of the honesty defects at once); (3) Decisions table and sheet on
Home (makes the main screen able to decide); (4) transcript and composer; (5) area bar, panel
lists and `Ctrl K` over all 137 panels; (6) the lanes, once the hub sends state timestamps;
(7) day theme QA; (8) the 1280 and 420 layouts.

## 8. Self-critique

1. **The density has a learning curve, and the timeline asks the most of it.** Pins, rail weights,
   five event marks and a magnified last six minutes are a vocabulary; until it is learned, the
   lanes read as a busy chart, and the lens's change of scale could mislead a quick glance (the
   band and the *10:45* tick are its only warning). The legend helps at 1920 but disappears at
   1440 and below, exactly where the axis is most compressed. A first-run explanation, or dropping
   the lens below 1440, may be needed.
2. **The 2560 screen is used well but not transformed.** It gets more words and more columns, not
   a different instrument: the conversation still leaves empty space above the first message, the
   decision list ends with air below it, and the agenda strip stays a strip. A wider screen could
   have earned a genuinely new view — the day continued forward to 20:00 with meetings on the
   owner's own lane, or a standing *Work* column — and this direction did not design it.

Smaller, and honest: the Trust page was designed at 1920; at 2560 it renders correctly but its
bottom third is empty. In production the audit table would fill that room with more of the 921
entries, but the mockup has only eight to show, and I did not design a wider layout for the page. The "by route" basis is the strongest claim the hub can make today, so the most distinctive
figure on that page is also the one with the weakest evidence. And several states (stale, empty,
demo) exist as components and copy here but are not drawn on the screens, because the shared moment
is entirely live.
