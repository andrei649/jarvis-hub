# Nerva — the next interface · design brief

Date: 2026-11-23 · Base commit: `77d6db88` · Branch: `claude/hud-redesign`

## 1. The job

The owner looked at the current interface and said: *"I feel the need for a new design — Nerva
has fallen behind."* He then added that the existing brand book is **not** a constraint: if the
design is new, the old identity is outdated and the brand book will be rewritten to follow.

So this is not a re-skin. Propose the next face of the product: its information architecture, its
interaction model for the things that matter, and a visual identity strong enough to anchor a new
brand book.

**Free to change:** palette, typefaces, the "sci-fi cockpit" art direction, the logo's rendering,
layout, navigation, component vocabulary, the words on the chrome, the name of the interface
("HUD", "cockpit").

**Not asked to change:** the product name **Nerva**; the agents' names; what the product *is* and
the rules it lives by (sections 2 and 5).

## 2. What Nerva is

A local-first personal AI operating system. One orchestrator (Jarvis) and 17 specialist agents run
on the owner's own workstation and GPU, with local models. It works proactively — it watches,
prepares, drafts — and anything risky waits for the owner's decision. Every action is written to a
tamper-evident audit chain. Cloud is opt-in per agent; some agents are local-only by code.

One person uses it: the owner, at a desk, in a maximized browser tab on a 31-inch 4K monitor at
150% scale — a viewport of about **2560×1353 CSS px at 1.5× pixel ratio**, measured on his
machine — all day, next to other tools. (The monitor may be an OLED panel: an interface that is
on all day should not park bright static elements in one place.) It is always on and visited in short sessions; the
product budgets itself to at most four urgent interruptions a day. The same interface also runs
in a desktop shell (a main window that opens at **1280×820**, plus a small 420×620 always-on-top
chat window) and may sit idle on a second screen. English and Romanian.

Replies come from a local model and take **4 to 60+ seconds**. "Working" is therefore not a
flicker: it is a state the owner looks at for a long time, and it deserves real design.

What the product believes, in its own documents: *calm competence — a butler, not a hype-man*;
*specific over superlative*; *honest about what it knows and does not know*; *restraint signals
trust*. The first design brief set the bar as "a Bloomberg Terminal as Apple would have designed
it." You may keep, sharpen or replace that framing — but the product is an instrument for someone
who delegates real authority to software, not a toy and not a chat app.

## 3. The owner's jobs, in order

1. **Talk** to the orchestrator and read what comes back.
2. **Decide** — approve, edit, reject or defer what the agents want to do.
3. **Check** — is everything healthy, what happened while I was away, what is running now.
4. **Find** — reach any of ~150 tools and settings without knowing where they live.

## 4. What is wrong today (measured on the running product)

Screenshots of the current interface are provided next to this brief. Facts:

| | |
|---|---|
| Text | On every screen 68–86% of text is below 11px; the smallest is 7.5px (the navigation labels). 126 of 240 font sizes in the stylesheet are under 11px, plus 702 more set inline. Nearly everything is uppercase, letter-spaced monospace. |
| Space | At 1920×1080 a decorative agent graph takes **30%** of the screen; the conversation gets **8.7%** (about one and a half messages) and the text field **1.6%**. The composer is a single-line input wrapped in four always-visible rows of options. |
| Decisions | The decision queue on the main screen **cannot decide anything**: its only button, "Dismiss", hides the card locally and it returns 30 seconds later. Real decisions live in a different overlay, 137 links away, which shows only the first ten. 36 identical-looking cards; duplicates are not grouped. |
| Health | There is no verdict. "ALL NOMINAL" is a hard-coded string next to a permanently red pulsing dot, while a marquee scrolls real warnings. Unknown values render as healthy defaults ("MIC ON", "0%"). |
| Agents | All 18 are listed twice. Every status dot is grey, because the screen expects states the hub never sends. |
| Navigation | 16 modes on a rail (five of them empty on a normal install), a hidden "Console" with 137 panels and no search, and three loose buttons floating over content. The command palette cannot find 137 of ~155 destinations. |
| Look | Cyan on navy, glow, corner brackets, chamfers, scanlines on by default, a spinning logo, a 40px glowing clock as the brightest thing on every page. The visual layer was drawn once, in June, and never revisited while the product tripled in size. |
| Honesty | The product's own rule is "show only what the hub returned; unknown is unknown". The main screen breaks it in 18 places. |

## 5. Truths the design must tell (these are product behaviour, not style)

- **Unknown is not OK.** Every status has at least: ok, attention, problem, unknown, stale. Never
  draw a default as a reading. Show when a value was last checked.
- **Demo data is labelled.** Each section says whether it is live, a demo sample, or empty.
- **Where it ran.** The product can say, per reply and overall, whether work stayed on this
  machine. No mainstream assistant shows this; it is Nerva's open lane. It must be driven by real
  routing data — a decorative shield would be worse than nothing. Be exact about the basis: today
  the hub knows which *route* a run used (local or cloud), not a verified measurement, so the
  figure reads "by route", "derived from the local-only switch" or "unknown" — and the design
  should leave room for a stronger "verified" later.
- **Trust signals never hide.** Egress (sealed or hybrid), the on-this-machine share, the
  microphone, the loaded model and whether the data on screen is live stay visible at every
  width. They may be compact; they may not disappear.
- **Risk has four tiers** (read-only, reversible, external, irreversible-or-money) and friction
  follows the tier: nothing → one click with undo → review then confirm → typed confirmation.
- **No keyboard shortcut approves or rejects.** Deliberate safety rule. Navigation and search are
  keyboard-first; verdicts are not.
- **A control never pretends.** If the home screen offers Approve, it is the real approval.
- **Emergency stop is one click** and reachable from the home screen.
- **Agents are tools with roles, not employees with faces.** No mascots, no avatars with eyes.
  (Research: framing AI as a named employee measurably weakens human review. The names stay; they
  are role labels.)

## 6. Information architecture you can rely on

The code's own structure supports **nine areas**, and all 137 existing panels fit under them:
Home · Work · Agents · Memory · Trust · Build · Connect · Observe · Settings (`content.json`
lists what each holds). The "Console" stops being a place: its panels become second-level pages.
Search-and-command finds every area, panel, agent and action. Approvals get **one** home (they
surface in four places today). You may regroup or rename if your concept needs it, but say why.

## 7. What reads as dated, and as current, in late 2026

From a research pass over primary sources (platform guidelines, design-system docs, product
changelogs through November 2026):

**Dated:** saturated navy with a cyan or neon accent · glow on text and borders · chamfers, corner
brackets, decorative frames · uppercase tracked monospace as the general label style · a scrolling
ticker · permanently pulsing indicators · a large decorative graph or orb as the hero · frosted
glass across the content area · purple-to-blue gradients · grids of stat cards each with a coloured
icon · cards inside cards · an agent roster as the centre of the screen · a separate overview
dashboard as the home page · dark only.

**Current:** near-neutral surfaces (dark around OKLCH L 0.14–0.18 with almost no chroma, or a
designed light) from **one token set for both themes** · colour computed in OKLCH and spent only on
meaning · exactly one accent · status colour always paired with a word or icon · one UI sans at
13–14px, 12px secondary, nothing under ~11px · sentence case · monospace only for identifiers,
hashes, timestamps, code · tabular numerals · structure from spacing, hairlines at low contrast ·
a short concentric radius scale · opaque work surfaces, translucency only on transient layers ·
navigation dimmer than content · stillness by default, one short transition when state changes ·
a work list sorted by *what needs the human* · one conversation in the centre · approvals as named,
scoped cards · presence as a small state-bearing mark beside a plain status sentence · a triage
home ("needs you now / happened while you were away / can wait") · the one decision that matters
made unmistakable.

**The trap on the other side:** calm neutral minimalism is itself now a template. A dark slate
page with a faint accent, a dot grid and one monospace word is what every AI design tool produces
on request. A direction that could be mistaken for any other 2026 SaaS product has failed as
identity. Distinctiveness has to come from typography, one considered colour decision, the quality
of the working views, and a point of view about what this product *is* — not from ornament.

## 8. Hard constraints

- **Local-first.** No network requests. Fonts are self-hosted, open-licence.
- **GPU budget.** The same GPU runs the model (VRAM sits at 96%). No large blurred areas, no
  continuous animation, no WebGL hero.
- **Opaque surfaces for content.** Today's translucent panels over gradients make contrast
  unmeasurable (about 700 "could not determine" results in the accessibility run).
- **Accessibility.** WCAG 2.2 AA contrast in every theme; visible focus; nothing conveyed by colour
  alone; `prefers-reduced-motion` honoured; nothing moves unless the user asked.
- **Both themes, one token set.** Dark and light are both designed. Say which is the default and
  why.
- **Widths.** Designed at 1920×1080; proven at 2560×1353 (the owner's real screen, where the
  extra room must be used, not stretched into); must hold at 1440×900 and 1280×800. 1280 is not
  an edge case: it is the desktop app's default window, so the home screen has to be genuinely good
  there. Say in the README what happens at 420×620 (the floating chat window) and on a phone,
  even if you do not draw them.
- **Runs in** Chromium and in WebView2 / WKWebView / WebKitGTK. Safe to use: `oklch()`,
  `color-mix()`, `light-dark()`, container queries, `:has()`, nesting, subgrid, `text-wrap:
  balance`. Avoid depending on anything Chromium-only.
- **Existing codebase.** React + plain CSS with custom properties; one 94 KB stylesheet with 29
  flat tokens; 3,423 inline style attributes. A second, cleaner token system already exists in the
  same repo for the Workspace app (light-first, 8px grid, radii 6/10/14, 50 `--ws-*` tokens). Your
  token sheet should be something both could converge on.

## 9. The moment to draw

`content.json` is one shared moment: Monday 10:51, the owner mid-conversation, a reply streaming in
Romanian, 18 raw approval requests that group into 9 actions (3 irreversible-or-money, 1 external,
2 reversible), four local services down but nothing blocked, three agents working, three waiting on
the owner, a meeting in nine minutes. Use it verbatim. It deliberately contains the hard cases:
duplicates to group, a money decision, an unknown value, an unavailable agent, mixed languages.

## 10. Deliverables (see `CONTRACT.md` for files, rules and gates)

- `cockpit.html` — the home screen for this moment, dark and light.
- `secondary.html` — the Trust area, in the same language, showing second-level navigation.
- `tokens.css` — the token sheet.
- `README.md` with these sections:
  1. **The idea** in three sentences, and the one-line promise of this direction.
  2. **Identity sheet** — a proposed name for the interface if you rename it; logo treatment;
     palette with roles and values (both themes); typefaces with roles, sizes and the production
     face if you used a stand-in; shape, elevation and motion rules; the voice of the words on the
     chrome with five before → after examples; three things this identity never does. This section
     must be complete enough to become section 7 of a new brand book.
  3. **Layout and navigation** — an ASCII diagram of the home screen; how the nine areas and their
     panels are reached; what collapses at 1440, 1280, 420×620 and phone.
  4. **How each job is served** — talk, decide, check, find — with the specific mechanism.
  5. **States** you designed: unknown, stale, empty, demo, error, working, waiting.
  6. **What you removed** from the current screen, and where its information went.
  7. **Building it** — which parts are tokens only, which need new CSS, which need new markup;
     the riskiest part; a suggested order.
  8. **Self-critique** — the two weakest things in your own design.

## 11. Bar

A direction is judged on: does the owner get faster and surer at the four jobs; does it look like
late 2026 and like nothing else; could it anchor a brand; is it legible and accessible by
measurement; can it be built on this codebase. Passing the gates in `CONTRACT.md` is the floor.

Draw real states with real content at real sizes. No lorem ipsum, no placeholder boxes, no "chart
goes here".
