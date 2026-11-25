# Atlas — a direction for the next Nerva interface

Files: `cockpit.html` (Home), `secondary.html` (Trust), `glance.html` (extra frame: idle / second
screen), `tokens.css`, `atlas.css` (shared components), `shots/` (renders).
Default theme: **dark**. Light is designed, not inverted (see 2.3).

> **Continuation note.** A previous designer started this direction (idea, name, territory map,
> three-column layout). I kept all of that and changed four things on purpose: (1) the typeface,
> from Bahnschrift/Barlow to **Space Grotesk**, because six of the seven directions converged on
> the same DIN face and Atlas needs its own voice, and because Nerva already self-hosts Space
> Grotesk, so the change costs nothing to ship; (2) the map now shows agents **by exception**:
> idle agents fold into one quiet line per district instead of being drawn as places; (3) the
> owner's real screen (2560×1353) gets its own composition instead of a stretched 1920; (4) Today
> became a "day line" with a *you are here* stop.

---

## 1. The idea

Nerva runs on one machine for one person, and everything it promises is about *where*: where your
words went, which agent holds what, what is waiting at the door for your signature, and whether
that door is shut. So the interface is an atlas of that machine — one fixed territory (four
districts, a wall that is the egress boundary, two gates) drawn flat on the ground of the screen,
with the things you act on, the conversation and the decisions, floating over it as opaque sheets.
The map is small, static and exact: every mark carries state, every waiting decision carries a
number that reappears wherever it is mentioned, and the only line that ever crosses the map is the
route your current question is taking.

**Promise:** you can always see where your words went, and what is waiting at the gate.

## 2. Identity sheet

### 2.1 Name and mark
- **Interface name: Atlas.** It replaces "HUD" and "cockpit". The home screen is *Home*; its
  drawing is *the day map*. Every area owns a *plate* of the same territory asked a different
  question (Home: who is doing what, and where your words went; Trust: who may leave).
- **Logo:** the existing neural N, redrawn as a route: three strokes, four stations, the bottom-left
  station filled in the home emerald ("you are here"). No ring, no glow, no rotation, no tile.
  Ink-coloured on both themes; the emerald station is the only colour in it.

### 2.2 Palette (OKLCH, one token set, `light-dark()`)

| Role | Token | Dark | Light |
|---|---|---|---|
| Ground — the table, the map is drawn on it | `--ground` | 0.140 0.006 170 | 0.952 0.008 92 (warm paper) |
| Land — districts, flat, never shadowed | `--land` | 0.184 0.011 168 | 0.918 0.024 145 (sage) |
| Sheet — floating work surfaces | `--sheet` | 0.203 0.007 170 | 0.994 0.003 95 |
| Inset / pressed | `--sheet-2` / `--sheet-3` | 0.240 / 0.290 | 0.966 / 0.927 |
| Hairline / control edge / wall | `--line` / `--line-2` / `--wall` | 0.283 / 0.505 / 0.585 | 0.895 / 0.620 / 0.520 |
| Ink, three text steps + one glyph step | `--ink` … `--ink-4` | 0.955 / 0.835 / 0.720 / (0.530 glyphs only) | 0.205 / 0.345 / 0.450 / (0.610 glyphs only) |
| **Home emerald — you / here / on this machine** | `--home` | 0.805 0.150 162 | 0.470 0.120 162 |
| Needs you (amber; pins are filled amber) | `--attn` / `--attn-fill` | 0.845 0.135 82 | 0.505 0.115 66 / 0.825 0.150 84 |
| Irreversible, money, stop, failed (rationed red) | `--danger` | 0.750 0.150 24 | 0.500 0.180 27 |
| Beyond this machine: cloud, external (violet) | `--outside` | 0.785 0.115 300 | 0.465 0.160 300 |

Rules: **one accent**, and it has one meaning — emerald is *you / here / on this machine* (the
route of your words, the You gate, "you are here", locality facts, the primary action, focus).
It never means "ok". **Ok is quiet**: ink and a check. Every status colour is paired with a shape
and a word. Amber is only "waits for you"; violet is only "outside this machine".

### 2.3 The two themes
- **Dark, "night chart" (default).** Near-black with a faint green cast, the owner's newest taste
  (the imported OS view), and right for an all-day OLED panel: nothing bright is parked in one
  place, the brightest static marks are small (pins, the Send pill).
- **Light, "printed atlas".** Warm paper ground, sage land, white sheets, deep emerald. It reads
  like a printed plate in an atlas, not like the dark theme inverted.

### 2.4 Type
- **Space Grotesk** (SIL OFL, already self-hosted by Nerva, latin-ext: ă â î ș ț) for every word on
  screen, in sentence case. Its round, slightly idiosyncratic forms (the open *a*, the flagged *1*)
  belong with circles and pills; set properly it reads as a calm reading face, not the old tracked
  micro-label. **No stand-in: this is the production face.**
- **JetBrains Mono** (already vendored) only for identifiers: model names, addresses, hashes,
  request ids, file names, and the word you type to confirm.
- Scale: 12 meta · 13 secondary · 14 UI · 15 conversation · 17 sheet titles · 26 (30 on the owner's
  screen) verdict · 44 glance. Nothing under 12px anywhere. Weights are optically compensated:
  dark 370 / 480 / 590 / 680, light 400 / 500 / 610 / 700. Tabular numerals everywhere.

### 2.5 Shape, elevation, motion
- **Shape:** circles for places and states, pills for controls, places and pins, large-radius
  sheets. Radius scale 6 / 10 / 14 / 20 / 28 / pill, always concentric (child = parent − padding).
- **Elevation, four layers:** ground → land (flat) → sheet (opaque, hairline, one soft shadow) →
  overlay. **No blur, no translucency on content** (the GPU is running the model).
- **Motion:** none at rest. One 120–160 ms ease-out when a state changes; zero under
  `prefers-reduced-motion`. The working mark is a still arc, the streaming caret is still, nothing
  pulses, spins or scrolls by itself.

### 2.6 Voice on the chrome
Plain, specific, sentence case, the butler's register: say what happened, where, and what it waits
for. Five before → after:

| Today | Atlas |
|---|---|
| `ALL NOMINAL` (hard-coded, next to a red dot) | **Degraded** · since 08:14 · checked 10:50 — *Working, with 4 local services down* |
| `% LOCAL 100%` | 100% on this machine · 41 of 41 runs today · **by route** |
| `Needs approval · irreversible` on all 36 cards | Irreversible — type `restart` to approve. |
| `Dismiss` (hides the card for 30 s) | **Defer** — beside the real Approve / Reject |
| `TRANSMIT` / `NEURAL NETWORK · focus mode` | **Send** / *This machine · 17 agents* |

### 2.7 Three things Atlas never does
1. Never draws a default as a reading: unknown is a dashed ring and the word *unknown*, never 0,
   never "on", never "all clear".
2. Never spends the emerald on decoration or on "ok": if it is green, it is about you, here.
3. Never moves on its own: no pulse, no spin, no ticker, no glow, no glass.

## 3. Layout and navigation

### 3.1 Home at 1920×1080
```
(N Nerva)    (Home | Work 9 | Agents | Memory | Trust | Build | Connect | Observe 4 | Settings)   (Search Ctrl K) (EN RO | Dark | Glance)

+-- TALK (sheet) --------------+   Monday 23 November . 10:51        Live  +-- NEEDS YOU (sheet) --- Auto [Ask] Off -+
| (o) Jarvis  Prime Orchestr.  |   ! Degraded . since 08:14 . checked 10:50 | 3 irreversible/money . 1 ext . 2 rev   |
|     Gathering - asking ...   |   Working, with 4 local services down      | +-[1] Restart 4 local services ------+ |
|                              |   ... the restart waits for you in (1)     | | Irreversible . Steve . 08:14 x3     | |
|  thread, newest at bottom    |                                            | | lmstudio qdrant neo4j n8n + impact  | |
|  each reply: who, text,      |  +- This machine . 17 agents -+  Outside   | | Would do / Undo: None / Deadline    | |
|  provenance "on this machine |  You==(o)Jarvis 3 - - - (o)Stark 5 | 0% by route | [restart____] [Approve once for 4] | |
|  . model . by route"         |  |   :          | Vision       |            | | Reject . Edit . Defer . Preview     | |
|                              |  | (o)Pepper 6  | Veronica,    | [Egress    | +-------------------------------------+ |
|  Jarvis 10:51                |  | Friday       |  Argus . idle|  sealed]   | [2] Sweep EUR 4,200 ...    [Approve...]| 
|  +-working: steps . asking-+ |  |--------------+--------------|            | [3] Delete logs ...        [Approve...]| 
|  +-------- step 3 of 4 Stop+ |  | Steve 1      | Gecko 2      | (:) Athena | [4] LinkedIn draft ... [Review draft]  |
|  Trei proiecte au ...|      |  | Ultron 4     | 5 idle       | cloud only | [5] Draft a reply ...      [Approve]   |
| +-To Jarvis ---- Ask-------+ |  | Oracle !     |              |            | [6] Move the research sync [Approve]   |
| | Message Jarvis...        | |  +--------------------------------+          | Ask - side effects wait . Interrupts 3/4 |
| | + Attach  Options  Voice  Send|  key: 3 working . 3 waiting . 2 finished ..  +-----------------------------------------+
| +--------------------------+ |  While you were away (7)  |  Today: day line, "you are here"
+------------------------------+

( ! Degraded . Egress Sealed . 100% on this machine . 41 of 41 runs [by route] . Microphone On . gemma-4-31b . Data Live . ... )  ( Stop all agents )
```
The three sheets float; the plate between them is drawn on the ground, and your words leave the
conversation sheet, pass the **You** gate and reach Jarvis — the route is literally drawn from the
place you typed.

### 3.2 Areas and panels
- **Nine areas in one capsule**, dimmer than content, with live badges (Work 9 need you, Observe 4
  services down). Each area opens as an **index sheet** (its panels, grouped, with a filter) beside
  its **plate** (the area's drawing of the territory) and its working sheet — `secondary.html`
  shows Trust: 21 panels in four groups (Proof, Control, Money and keys, Posture and devices). I
  grouped them because 21 flat items are slow to scan; the names are unchanged.
- **Search and command (Ctrl K)** finds every area, panel, agent and action; the "Console" stops
  being a place.
- **Approvals have one home:** Work → Decisions. Home's *Needs you* is that same live queue, not a
  copy; chat replies and the map only *point* to it with the decision's number.
- Every place on the map links to its agent; every pin links to its decision.

### 3.3 What collapses
- **2560×1353 (the owner's screen):** more said, not bigger boxes. The map writes what each active
  place holds; decisions become a list beside a full docket (request ids, all four impacts, the
  12-request explanation) with the friction ladder under it; every trust fact is spelled out.
- **1920:** three columns; compact map (one line per place); open docket above the queue.
- **1440:** the map stacks into a column of districts and folds idle agents into counts; the route
  becomes a trunk down the left of the wall; *While you were away* folds to its counts; Today shows
  the next stop and the one that matters; badges shorten to numbers; less-used docket actions go
  under More.
- **1280 (desktop app default):** as 1440, plus the verdict keeps its sentence but drops the service
  list, the key hides, Today shows *you are here* and the next stop. The trust strip keeps all five
  required facts **with their labels**; the stop never folds.
- **420×620 floating chat (not drawn):** one column — presence mark and status sentence; the
  thread; the composer with *To* and the approval mode; above it one compact trust row (Sealed ·
  100% by route · mic · model · Live) and one line "9 need you" that opens the main window. No
  approvals in the mini window: they have one home.
- **Phone (not drawn):** a stack — verdict and trust row, *Needs you* cards (tier friction intact:
  typing still required for tier 3), the conversation; the map in its stacked, by-exception form.

### 3.4 Glance (extra frame, `glance.html`)
For an idle or second screen: the time, the presence sentence, four large values from the shared
moment (9 need you · Degraded · 100% on this machine, by route · 11:00 1:1 with Cosmina), and the
territory reduced to where the nine decisions sit, with the sealed gate. Large type is ink-2, not
white, so nothing bright stays parked on an OLED panel. `?state=stale` draws the hub-unreachable
state: one sentence ("The hub is not answering. Everything below is what it said at 10:50."), every
value marked *as of 10:50*, pins and the wall turned to quiet outlines, the presence mark removed —
nothing pretends to be live. Rendered in `shots/glance-1920-{dark,light,stale}.png`.

## 4. How each job is served
- **Talk.** One conversation in a sheet that gets the largest column. Multi-line composer that says
  who receives the message (*To Jarvis · orchestrated*) and the approval mode (*Ask*); attachments,
  options and voice behind three controls; `/` and `@` hints. Each reply names its agent by role,
  carries provenance (*on this machine · gemma-4-31b · by route*), folds tool calls into chips
  (failures in red), and shows four actions plus More on the latest reply only. **Working** (4–60 s)
  is a still status board, not a spinner: the four steps with the current one marked, who was asked
  and what each is doing, *step 3 of 4 · asked 10:48*, Stop, then the streaming text with a still
  caret and its route — while the map draws the same route (solid delivered, dashed asked).
- **Decide.** One queue, grouped by the hub (18 requests → 9 actions in 6 groups), each with a number
  that is the same on the map, in the chat, in the away list and on the calendar. Risk is an ordinal
  tier meter plus a word; friction follows it: tier 1 *Approve* is one real click with the undo
  stated; tier 2 is *Review the draft* (review, then confirm); tier 3 opens a docket that states
  what would run, that undo is *None*, the deadline, and asks you to **type** the word — the button
  stays disabled until you do, and it cannot be bulk-approved. The approval mode switch sits on the
  queue; the interrupt budget (3 of 4) in its footer. No keyboard shortcut approves or rejects.
- **Check.** One verdict with its state word, since-time and checked-time, and its causes in one
  sentence. The map answers "what is running, what waits for me, did anything leave": state by
  shape, decisions by number, the route, the wall with its sealed gate, and *Outside: 0%, by
  route*. *While you were away* is a still list (time, agent, result). *Today* is a day line with a
  *you are here* stop. The trust strip never hides.
- **Find.** Ctrl K for everything; the area capsule with live badges; each area's grouped index
  with a filter; every map mark and pin is a link.

## 5. States designed
- **Unknown** — dashed ring + the word: *Latency p50 unknown* (never 0). The decision queue's
  unknown state reads "Unknown — sign in as the owner to see what is waiting." under a dashed ring,
  never "all clear". If egress is unknown, the strip says *Egress unknown* and the wall on the map
  is drawn dashed.
- **Stale** — dotted ring + the last time: every section's state tag can read *Stale · checked
  10:50*; the verdict always shows *checked 10:50*; when the hub stops answering, everything keeps
  its last value, marked stale (shown in `glance.html`).
- **Empty** — hollow ring + a sentence: "Nothing is waiting for you." Empty and unknown never share
  a drawing.
- **Demo** — amber dashed square + *Demo sample*, per section, never one chip for a mixed page (the
  Trust page states which sections are live).
- **Error** — red diamond + the word: *file_write failed*; services *not responding* with their
  impact and fallback.
- **Working** — still arc with a centre dot; on the map the place is outlined in emerald when it is
  on your route; in the thread, the status board.
- **Waiting** — pause mark, amber pin with the decision's number, "waits for your decision".
- **Unavailable** — violet dashed ring, outside the wall (*Athena · cloud only — unavailable while
  egress is sealed*). **Finished** — check in a faint ring; **idle** — one quiet line per district.

## 6. What was removed, and where it went
| Removed from today's screen | Where its information went |
|---|---|
| 40px glowing clock | 13px in the plate's kicker; large only in glance mode |
| Decorative neural graph (30% of the screen) | The day map: same territory, but every mark carries state, a decision number, the route or the boundary |
| Roster column (18 agents, listed twice) | Map by exception; idle agents in one quiet line per district; the full roster lives in Agents |
| Scrolling ticker | *While you were away*, a still list |
| "ALL NOMINAL" + permanent red dot | The verdict with causes, since and checked times |
| Seven top badges | The trust strip (egress, locality with basis, mic, model, data) |
| Queue whose only button was "Dismiss" | The real queue: Approve / Edit then approve / Reject / Defer / Preview, tier friction |
| 16-mode rail, hidden Console, three loose buttons | Nine areas + Ctrl K + each area's index sheet |
| Composer's four rows of options and help text | Attach, Options, Voice; a `/ @` hint |
| Eight buttons on every reply | Copy, Save, Read aloud, Create task, More — on the latest reply |
| System meters, Heartbeat, weather panel | VRAM in the strip (RAM, GPU spelled out at 2560), the rest in Observe; weather in one line |
| Scanlines, glow, chamfers, uppercase tracked mono | Gone |

## 7. Building it
- **Tokens only:** the whole palette (both themes through `color-scheme` + `light-dark()`), radius,
  space, type scale and weights, elevation, motion. The current 29 flat tokens map onto these role
  names; the Workspace kit's `--ws-*` can alias them (its radii 6/10/14 are `--r-xs/sm/md`).
- **New CSS, existing markup:** capsules, sheets, buttons, pins, tier meter, state tags, the trust
  strip, the thread and reply chrome.
- **New markup:** the plate (verdict, map, key, away list, day line), the docket + queue (one
  component, accordion at 1920, master–detail at 2560), the composer header (*To* + mode), the
  area index sheet, the Trust policy map and basis ladder.
- **Riskiest part: the map.** It needs data the hub does not fully send yet — agent states beyond
  ready/idle, the live route of the current run, and the locality basis per run — and its route is
  drawn with fixed-row CSS arithmetic (one stylesheet, three drawings chosen by container queries).
  It must be fed by real routing data or not drawn: a guessed route would be the decorative shield
  the brief warns about. It degrades honestly: with only ready/idle, the map becomes districts with
  pins and no route.
- **Suggested order:** (1) tokens and both themes; (2) the trust strip and the verdict (the honesty
  fixes); (3) *Needs you* with real tiered approvals; (4) thread, composer, working state; (5) area
  index sheets and Ctrl K; (6) the map — stacked first (it is the simplest), then compact, then
  expanded — once the hub sends routes; (7) the Trust plate; (8) glance.

## 8. Self-critique
1. **The map leans on data and geometry that are not yet robust.** Today's hub only reports
   ready/idle and does not stream the current route, so the most distinctive part of Atlas is the
   part that depends most on backend work. Its route is drawn with fixed-row arithmetic that is
   exact for this moment's layout; an extra agent in a district or a much longer name needs the
   drawing rules re-checked. Until then, the map is a good roster-by-exception with numbers — useful,
   but not yet the "working picture" it promises.
2. **The amber pins are a powerful cross-reference, but loud.** At 1920 there are about 17 amber
   marks on screen for 6 decisions (map, queue, chat, away list, calendar). On a day with 30
   decisions this would become confetti; it needs a cap (pins for the first nine, "+n" after) that
   I have not drawn. Related: at 1280×800 the queue shows the open docket plus two decisions, so the
   owner must scroll the queue in the desktop app's default window.
