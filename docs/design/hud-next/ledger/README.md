# Ledger — a direction for the next Nerva interface

Files: `cockpit.html` (Today, the home page) · `secondary.html` (Trust › Overview) ·
`glance.html` (the extra frame: idle and second screen) · `tokens.css` · `ledger.css` (components
shared by every page) · `shots/` (renders; `glance-*` were shot with `shoot.mjs` because the set
tool only knows the two required pages; files starting with `_` are my detail probes).
Default theme: **Carbon** (dark). Paper (light) is `?theme=light`.

*Revision note.* This direction was started by another designer and finished by me. I kept its
idea, name, identity and layout. One rule changed: the first draft set a vermilion seal on every
recorded entry; that spent the owner's colour on the system's own bookkeeping. Now the chain's
seal on every entry is ink, and vermilion means only the owner's hand (asked for, given, or the
stop). The rest is refinement: the 2560 page fits in four registers, the docket shows all six
entries at 1440 and 1280, closed entries are set regular so the open decision is the only bold
type, the signature instruction stays visible while typing, and the working reply shows elapsed
time and where it runs.

## 1. The idea

Nerva's difference from every other assistant is that it keeps books: everything it says, does
and proposes is an entry in a sealed chain, and nothing risky happens without the owner's
signature. So the interface *is* the book: a typeset working page of ruled registers (the day, the
conversation, the docket of things awaiting signature) where type and rules carry the structure
and colour is ink on paper, or its carbon. One colour, vermilion, is reserved for the owner's
hand: it appears only where a signature is asked for, given or recorded, and the effort of
signing follows the risk tier.

**Promise:** nothing happens off the books, and nothing risky happens without your signature.

## 2. Identity sheet

**Name.** The interface is *the Ledger* (it replaces "HUD" and "cockpit"). Home is *Today*:
today's page. The nine areas keep their names. Decisions are *signed*, not "approved"; the queue
is *the docket*; the audit chain is *the record*.

**Logo.** The real neural N (three strokes, four nodes) inside a ring, drawn in ink at 28 px
beside the wordmark "Nerva" set in the serif, bold. The void-black tile and signal blue are
retired. The same ring is the product's seal, in three states of authority, and nowhere else:

| Mark | Meaning |
|---|---|
| ring and N in vermilion outline | awaits your signature |
| solid vermilion disc, N knocked out | signed by you |
| solid ink disc, N knocked out | sealed in the record (every entry) |

**Palette.** Authored in OKLCH, one token name per role, two themes. Neutrals share one hue
family (140–165, "ledger green") at chroma ≤ 0.022. Status never uses hue.

| Token | Role | Carbon (dark, default) | Paper (light) |
|---|---|---|---|
| `--paper` | the page | `oklch(0.176 0.008 165)` #0e1210 | `oklch(0.979 0.006 150)` #f5f9f6 |
| `--paper-2` | hover, quiet fills | `oklch(0.204 0.009 165)` #131816 | `oklch(0.958 0.008 150)` #edf3ee |
| `--paper-3` | pressed, meter track | `oklch(0.240 0.010 165)` #1b211e | `oklch(0.932 0.010 150)` #e4eae5 |
| `--sheet` | where you write or sign | `oklch(0.212 0.010 165)` #151a18 (raised) | `oklch(0.997 0.002 150)` #fdfefd (whiter) |
| `--ink` | text | `oklch(0.912 0.014 138)` #dde4db | `oklch(0.205 0.022 165)` #0d1a15 |
| `--ink-2` | secondary text, navigation | `oklch(0.775 0.014 145)` #b0b8b0 | `oklch(0.375 0.020 165)` #37453e |
| `--ink-3` | meta, labels, the past | `oklch(0.660 0.014 150)` #8c958e | `oklch(0.485 0.016 165)` #57625d |
| `--rule` | hairline between rows | `oklch(0.268 0.010 165)` #222825 | `oklch(0.880 0.010 150)` #d3d9d4 |
| `--rule-2` | under table heads | `oklch(0.340 0.012 165)` #323a36 | `oklch(0.770 0.012 155)` #afb7b1 |
| `--rule-field` | edge that marks a control | `oklch(0.540 0.014 160)` #68716c | `oklch(0.555 0.014 160)` #6c7670 |
| `--rule-ink` | the 2 px rule that opens a register | `oklch(0.640 0.014 150)` #868f88 (dimmed) | = `--ink` (printed) |
| `--seal` | the owner's hand | `oklch(0.705 0.185 35)` #fd6c48 | `oklch(0.535 0.200 33)` #c72500 |
| `--seal-wash` | hover on a seal control | `oklch(0.255 0.042 35)` #341b15 | `oklch(0.958 0.024 45)` #ffede4 |
| `--on-seal` | text on a solid seal | `oklch(0.160 0.012 165)` #090f0c | `oklch(0.992 0.004 150)` #fbfdfb |

Measured: ink 14.6:1 / 16.8:1, ink-2 ≥ 8.1:1, ink-3 ≥ 5.2:1, seal ≥ 4.7:1 on every ground;
control edges ≥ 3.3:1. axe reports 0 contrast failures on both pages in both themes.

Paper is not an inversion. On Paper the register rule is printed in full ink and the signing
sheet is whiter than the page; on Carbon the register rule is dimmed so it never glares on an
OLED panel, the signing sheet is a slightly raised ground, and nothing is pure white.

**Why Carbon is the default.** The owner keeps this open all day, maximised beside other tools,
possibly on OLED, and his newest taste (the imported OS view) is dark. Carbon puts no bright fill
at rest anywhere. Paper is the original the carbon is copied from: daylight, long reading, and
anything printed or exported, such as a Trust report. Both come from the same token names.

**Type.** Three families, each with one job. The split is the identity.

| Role | Face (rendered here) | Production (open licence, self-hosted) | Sizes |
|---|---|---|---|
| What Nerva writes for you to read, and what you sign: replies, verdicts, entries, consequences, the record | Sitka, optical sizes (Small / Text / Subheading / Display) | **Literata** (OFL, variable, optical sizes) | replies 17/27 · consequence 15/21 · closed entry 17/23 regular · open entry and register titles 22 bold · verdict 32 · one figure per page 44 |
| The instrument: labels, tables, controls, navigation, and your own typed words | Bahnschrift (DIN) | **Barlow** (OFL) | UI 14/20 · labels 13/18 · meta 12/16 · your words 15/23 semibold |
| Identifiers only: hashes, ids, addresses, model and capability names | JetBrains Mono | JetBrains Mono (already vendored) | 12 |

Sentence case everywhere; no uppercase tracked labels. Figures are lining everywhere and
tabular in columns. Nothing below 12 px. At the owner's 2560 screen every reading size steps up
one (replies 19/30, verdict 36, labels 14) because it is read from further away; measures stay.

**Shape, rules, elevation.** Rules, not boxes. A 1 px hairline separates rows; a 1 px stronger
rule sits under a table head; a 2 px rule opens a register; a single rule above and a double rule
below make a *total*, the accountant's convention, used for every summary line. Radius 0 on
rules, cells and sheets, 2 px on controls, 4 px on transient layers; only seals and state marks
are round. A page has at most one bordered sheet, and it is where the owner signs (the open
docket entry) or exercises authority (the emergency stop); the composer is the one other framed
surface, because it is where you write. No shadows on work surfaces; transient layers (the
command sheet, menus) use `--shadow-sheet`. Translucency: none.

**Marks.** State is a shape plus a word, never a hue: ● ok · ◐ attention · ■ problem ·
dashed ○ unknown · clock ○ stale · ‖ held · ⊘ blocked · ▶ working · ✓ done · ○ idle. Risk is a
three-bar glyph (▯▯▯ read only, ▮▯▯ reversible, ▮▮▯ external, ▮▮▮ irreversible or money) plus its
name. All are inline SVG strokes in one sprite; the Trust page carries the key.

**Motion.** Still by default. 120 ms on hover and press, 180 ms when a seal fills or a row
opens, nothing else. No pulsing, no tickers, no spinners: work in progress is a dotted rule on
the current step and an elapsed time. `prefers-reduced-motion` sets both durations to 0.

**Voice of the chrome.** Plain, specific, sentence case; it names the thing and its
consequence; it says *unknown* when it does not know.

| Before (today) | After (Ledger) |
|---|---|
| ALL NOMINAL (hard-coded) beside a red pulsing dot | Working, with 4 local services down · since 08:14 · checked 10:50 |
| DECISION QUEUE 36 · [Dismiss] | 9 await your signature · [Sign · restart all 4] [Defer] [Reject group] |
| Needs approval · irreversible | Irreversible · *To undo:* none · typed: delete |
| % LOCAL 100% | Runs on this machine 100% · 41 of 41 runs today · by route |
| MIC ON (shown when unknown) | Microphone On, or Microphone Unknown |
| Speak or type a command… · [TRANSMIT] | Message Jarvis… · [Send] |
| Merkle-verified · 921 entries | Chain intact: 921 sealed entries · verified 10:50 |

**Three things this identity never does.**
1. It never uses vermilion for itself: not for the brand, errors, alerts or emphasis. Vermilion
   means the owner's hand, and a problem is shown by a mark and a word.
2. It never draws a box where a rule will do, and never a card inside a card.
3. It never shows a reading it did not get: no default values, no 0 for unknown, no "all clear"
   when the feed did not answer, no decorative shield.

## 3. Layout and navigation

Today at 1920 × 1080 (three registers between a running head and a running foot):

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ (N) Nerva  Home  Work 9 need you  Agents  Memory  Trust  Build  Connect  Observe ■4  Settings│
│                               [⌕ Search or run a command   Ctrl K]  EN RO  ◐  Glance  [■ Stop]│ masthead
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Egress ● Sealed │ Runs on this machine ● 100% · 41 of 41 · by route │ Microphone On │ Model … │
│ Data on screen ● Live · checked 10:50 │ Audit chain ● Intact        Approval mode Auto [Ask] Off│ running head
├─────────────────────┬─────────────────────────────────────┬──────────────────────────────────┤
│━━━━━━━━━━━━━━━━━━━━━│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│
│ Monday, 23 November │ Conversation          with Jarvis … │ 9 await your signature    Live   │
│ ◐ Degraded · 10:50  │ 08:02 You    Morning Jarvis — …     │ Risk  Entry, and what happens…Hand│
│ Working, with       │ 08:02 Jarvis Good morning, Andrei…  │ ▮▮▮   Restart 4 local services   │
│ 4 local services    │       ▣ on this machine · gemma     │ Steve  402 lmstudio  409 qdrant  │
│ down                │ 08:05 You    draft the churn slide  │       If you sign / To undo / If │
│ ■ lmstudio …        │ 08:05 Stark  … file_write failed    │       you wait (written out)     │
│ ■ qdrant …          │ 08:07 Gecko  … ⊛ 1 action waits →   │      ┌ Sign here — type restart ┐│
│ ⊛ Restarting them   │ 10:48 You    Ce proiecte sunt …     │      │ × restart____ [⊛ Sign · 4]││
│   waits for you →   │ 10:51 Jarvis ✓Classify ✓Route ▶Gath │      └──────────────────────────┘│
│ Today               │       Gathering — asking Pepper …   │      Preview Edit Defer   Reject │
│  ▶ 11:00 1:1 …      │       Trei proiecte au termene … |  │ ▮▮▮ Money   Sweep €4,200 … [Open]│
│  ◆ 14:00 Raiffeisen │       ▣ running here · 3 min so far │ ▮▮▮ Irrev.  Delete logs …  [Open]│
│ While you were away │ ┌ To Jarvis · orchestrated  Mode Ask┐│ ▮▮▯ Ext.    Veronica's … [Review]│
│  ✓ 06:00 Friday …   │ │ Message Jarvis…                   ││ ▮▯▯ Rev.    Draft a reply  [⊛Sign]│
│  ‖ 07:48 Ultron …   │ │ + Attach  Voice ready  Options  Send││ ▮▯▯ Rev.    Move the sync  [⊛Sign]│
│ 7 entries ══════════│ └───────────────────────────────────┘│ 6 entries · 9 actions ═══════════│
├─────────────────────┴─────────────────────────────────────┴──────────────────────────────────┤
│ Agents 18 ▶3 working ⊛3 waiting on you ✓2 ○9 ⊘1 │ RAM 19% VRAM 96% GPU 3% Latency unknown │ running foot
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Areas and panels.** The nine areas sit in the masthead, always visible, with a count only where
something needs the owner (Work: *9 need you* in vermilion; Observe: *■ 4 services down*). Each
area opens on its own page with a *contents* column on the left: the area's second-level panels
in a few named groups, the current one marked with a rule, a count beside a panel only when the
hub supplied one, and *N more panels* behind a disclosure (`secondary.html` shows Trust's 21).
The old Console stops being a place. **Search and command (Ctrl K)** is one sheet that finds every
area, panel, agent and action by name; it can run navigation and read-only actions, never a
verdict. The running head (trust signals, approval mode, interrupts) and the running foot (agents
by exception, the machine) are the same on every page, like a book's running head.

**Widths.**
- **2560 × 1353, the owner's screen:** four registers. The fourth holds *Agents* by exception
  (working / waiting on you / finished / unavailable / idle as one line) and *The record*, the
  tail of the audit chain with its hashes. The day register gains *This machine*. Reading sizes
  step up one; columns are fixed widths and the conversation takes the remainder, with prose
  capped at 660 px, so nothing stretches. The transcript is bottom-anchored on the composer.
- **1920 × 1080:** three registers, as drawn above; the agents and the machine live in the foot.
- **1440 × 900:** the day folds into a band of three cells under the running head (the verdict,
  the next meeting, while you were away), each opening its full list. The docket keeps its open
  entry in full and turns every other entry into one ruled line: risk, title, hand. A one-click
  signature keeps what it would do on its line, because nothing is signed unseen.
- **1280 × 800, the desktop app's default window:** the same, tighter. Every trust signal stays
  (shortened labels), all six docket entries are visible, the open decision is fully signable,
  and the signature line puts its instruction beside the line instead of above it.
- **420 × 620 floating chat (not drawn):** the conversation register alone. The running head
  becomes one line of marks (egress, the on-this-machine share with its basis, microphone, model,
  live), never hidden. Above the composer a single line reads *⊛ 9 await your signature — open*;
  tier-1 entries can be signed there in one click with undo; tier 2 and 3 open the main window,
  because the consequence has to be read at full size. The stop stays in the window's title bar.
- **Phone (not drawn):** one column with three tabs, *Today* (verdict and docket), *Conversation*
  and *Trust*. The running head becomes a strip of marks under the title. Typed signatures work
  there too; nothing can be approved from a notification.

## 4. How each job is served

**Talk.** One conversation in the centre register, newest entry sitting on the composer. Your
words are set in the instrument face, Nerva's in the book face, so who said what is legible from
across the room. Every reply carries a footnote: where it ran (*on this machine · gemma-4-31b*,
by route) and what it called (*web_search done · ■ file_write failed*). A reply that raises an
action carries a ruled slip, *⊛ 1 action waits for your decision — On the docket*: it links,
it never decides. The composer says who receives the message (*To Jarvis · orchestrated*) and
the approval mode, and keeps attachments, voice (*runs locally*) and options behind three quiet
controls; `/` and `@` are hinted, not explained. Because replies take 4 to 60+ seconds, the
working reply is designed as a page you read: the four steps as ruled segments (done, current
dotted, to come), the status in italic (*Gathering — asking Pepper and Stark*), who was asked
and what each is doing, the text as it streams, where it is running, how long it has taken
(*asked 10:48 · 3 min so far*), and one control, *Stop this reply*. Nothing animates.

**Decide.** The docket is the one home of approvals; every other mention (the verdict's remedy,
the slip in the conversation, agents waiting on you, the record) links to it and none of them
decides. It shows the hub's grouping: 18 requests, 9 actions, 6 entries, ordered by risk. Each
entry is a ruled row with three columns: *Risk* (glyph, tier name, who raised it and when),
*Entry, and what happens if you sign*, and *Your hand*. The open entry writes the consequence out
in full (*If you sign · To undo · If you wait*), lists its members with ids and addresses, and
offers the real verbs: **Sign**, Preview (dry run), Edit then sign, Defer, Reject. Friction
follows the tier:
- tier 0, read only: no signature; it is recorded in the chain.
- tier 1, reversible: one click on *⊛ Sign*, with undo available afterwards.
- tier 2, external: *Review the draft*, then confirm what will be sent.
- tier 3, irreversible or money: a typed signature (*type restart*, or the amount for money) on a
  signature line in the page's one bordered sheet; never bulk-approved.

No keyboard shortcut signs or rejects, and the page says so beside the verbs; Enter in the
signature line does nothing. The signing button stays an outline until the typed word matches,
then fills with vermilion: a control never pretends to be ready.

**Check.** Top left, one verdict sentence with its state mark, *since* and *checked* times, then
its causes, each with its consequence (*Not blocking: the model is being served by Ollama
instead*), then the remedy as a link to the docket. The running head carries the trust signals
at every width: egress, the on-this-machine share with its basis, microphone, model, whether the
data on screen is live, and the audit chain. *While you were away* replaces the ticker: seven
ruled entries, exceptions in semibold, totalled under a double rule. Agents are shown by
exception, the machine's readings sit in the running foot, and the unknown latency says unknown.

**Find.** Nine areas, always in view; their counts appear only when something needs the owner.
*Search or run a command* (Ctrl K) finds every area, panel, agent and action. Inside an area the
contents column lists every second-level panel, so nothing is more than two clicks deep, and
search reaches the rest by name.

## 5. States

| State | How it looks |
|---|---|
| **Unknown** | A dashed ring and the word *Unknown*, with the reason when the hub gives one: *Latency p50 — Unknown, not measured yet*. Never a 0, never a default. If the decisions feed does not answer, the docket head reads *Unknown — sign in as the owner to see what is waiting* in place of the figure, and no *Nothing waits* line is drawn. |
| **Stale** | The clock ring, the value set in ink-3, and the age in words: *checked 09:12 · stale*. The section's source label changes to *Stale* so a stale section cannot pass for a live one. |
| **Empty** | Said in a sentence, then totalled: *Nothing is waiting for you.* over a double rule reading *0 entries*. The docket figure disappears rather than showing a vermilion 0. |
| **Demo** | Every section head carries its source: *● Live · checked 10:50*, or a dashed-ruled *Demo sample* label. Demo rows are never mixed into a live section without their own row label (the Trust key shows the mark). |
| **Error** | A failed tool call is a row in the reply's footnote (*■ file_write failed*) and an entry in the record (*file_write failed — nothing was changed*). If the hub is unreachable, the running head's values become unknown marks, *Data on screen* reads *Offline*, and the verdict says so with the time of the last good reading. |
| **Working** | The streaming reply described in §4: steps as ruled segments, the current one dotted; who was asked; elapsed time; where it runs; *Stop this reply*. Agents working show ▶ and what they are doing. |
| **Waiting** | Wherever the owner's hand is needed, the vermilion outline seal: the docket, the verdict's remedy, the conversation slip, *3 waiting on you* in the foot, *awaits your signature* in the record. |

## 6. What I removed, and where it went

| Removed from today's screen | Where its information went |
|---|---|
| The neural-network graph (30% of the screen) and the 18-agent roster listed twice | Agents by exception: the running foot at 1920, the fourth register at 2560; the full roster is the Agents area |
| The 40 px glowing clock | 10:51 in the day register's head; large only in glance |
| *ALL NOMINAL*, the red pulsing dot, the scrolling warning marquee | One verdict sentence with causes and times; the marquee became *While you were away*, which does not move |
| Seven stat badges (AGENTS, LLM, DATA, GATEWAY, % LOCAL, EGRESS, MIC) | The running head, with words, marks, basis and *checked* times; channels are in the foot at 2560 and in Observe |
| The decision queue that could only *Dismiss* (36 identical cards) | The docket: grouped, ordered by risk, really signable, friction by tier |
| 16 rail modes, the hidden Console with 137 panels, floating buttons (Automations, demo, AMBIENT, CONSOLE, WORLD) | Nine areas plus each area's contents column and Ctrl K; *demo* became per-section source labels; AMBIENT became *Glance*; Automations live in Build and Work › Scheduled jobs; World is Observe › world signals |
| Four rows of composer options and two help sentences | *To* and *Mode* on the composer head; Attach, Voice and Options; `/` and `@` hints |
| Eight always-visible buttons per reply | Copy, Save, Read aloud, Create task, More, on the newest reply and on hover elsewhere |
| COGNITION and ARTIFACTS tabs | Cognition is the working reply's steps, inline; artifacts are attachments and Memory |
| Cyan on navy, glow, chamfers, corner brackets, scanlines, the spinning logo | Ink, rules and one seal colour |

## 7. Building it

- **Tokens only** (`tokens.css`): both palettes, the type scale and the three families, spacing,
  radii, rule weights, motion, plus a convergence layer (`--color-bg`, `--color-text`,
  `--color-accent` …) that both the HUD's 29 flat tokens and the Workspace app's `--ws-*` tokens
  can be re-pointed at. Workspace's 6/10/14 radii map to 2/4/4 here; its 8 px grid is the same.
- **New CSS, existing markup:** the global type rules (sentence case, lining and tabular
  figures, nothing under 12 px), the running head and foot, the marks sprite, the register
  frame (heavy rule, title strut, totals), replacing the cyan theme wholesale.
- **New markup:** the docket and its signature line (a real component, wired to the hub's tier
  and grouping fields and to the existing approve, edit, reject, defer and preview endpoints);
  the working reply; per-section source labels; the contents column for each area; the record
  table; the dayband for narrow widths.
- **Riskiest part:** the docket. It retires today's approval overlay and the dismiss-only cards
  in one move, so it must reproduce every verdict the overlay can give, enforce *no keyboard
  verdicts* in code rather than only in copy, and read tier and grouping from the hub instead of
  re-deriving them. Second risk: the serif. Literata with optical sizes must be self-hosted and
  subset (Latin and Latin Extended for Romanian) to keep the first paint fast in WebView2 and
  WebKitGTK.
- **Order:** 1. tokens, fonts and global type · 2. masthead with the nine areas, running head and
  foot on every page · 3. the docket on Today, wired to real approvals, then retire the overlay ·
  4. conversation restyle and the working reply · 5. the day register from the health endpoint ·
  6. area contents columns and Ctrl K over all ~155 destinations · 7. Trust › Overview ·
  8. widths (2560, 1440, 1280, the 420 window) · 9. glance.

## 8. Self-critique

1. **The serif is a bet.** It gives the Ledger its voice and makes Nerva's words distinct from
   the owner's, but a serif in a dense live instrument risks reading as literary rather than
   operational, and the whole effect depends on a font the product does not yet ship. If
   Literata renders softer than Sitka in WebView2, the replies and docket titles lose the crisp
   printed quality these renders show. It needs a real-font prototype on the owner's monitor
   before it is committed.
2. **Status without hue asks the owner to learn shapes.** A problem and an OK differ by a filled
   square against a dot, in the same ink. Every mark is paired with a word, so it is accessible,
   but on a busy day a degraded service is found by reading rather than by colour, and that is
   slower than a red mark. On the home page the verdict sentence at the top left carries the
   weight; on dense second-level pages (Observe, with many services) this choice may need
   reinforcing with grouping and ordering, not colour. Smaller, honest gaps: the Trust page at
   2560 has unused height in the authority register because the content is short, and 1280 shows
   compact docket titles ellipsised.
