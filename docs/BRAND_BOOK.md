# Nerva — Brand Book

> The main marketing brand reference. Positioning, naming, messaging, voice, and visual identity —
> all downstream of [MOONSHOT.md](../MOONSHOT.md) (the *why*) and consistent with
> [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) §3 (the launch brief).
> Generated: 2026-07-04 · Owner: Andrei · Status: **v0.11.0** (feature-complete + refactor done; productionizing toward 1.0)
>
> **Visual identity rewritten 2026-11-23.** The owner replaced the HUD v2 "sci-fi cockpit" identity
> (void black, signal cyan, Space Grotesk, letter-spaced mono micro-labels) with the **Ledger**
> design and asked that this book follow it. Sections 2, 6, 7 and 9 below reflect that decision;
> the design, the comparison of the seven candidate directions and the jury that chose between
> them are in [`docs/design/hud-next/`](design/hud-next/).

---

## 1. Brand Essence

**One sentence:**
> **A private AI that works while you sleep and is owned by the person it serves.**

**The category we create:** the **personal AI operating system** — not a chatbot, not a workflow
builder. A persistent, proactive, *governed* cortex that runs on your own hardware, learns your
life, finds its own work, and asks for a decision only when it genuinely needs one — then learns
to stop asking.

**The enemy:** renting your private life to a hyperscaler — and its mirror image, the ungoverned
"viral agent" (the OpenClaw cautionary tale: plaintext secrets, unaudited autonomy, the #1
infostealer target of 2026).

**The wedge:** nobody else ships the intersection — **local-first + proactive autonomy + living
memory + observability + governance** in one system. Competitors hold one axis at best; the brand
is the intersection.

---

## 2. Name & Naming System

| Asset | Name | Notes |
|---|---|---|
| Product | **Nerva** (published by **Digitaholic**) | The end-user product and primary identity ([NERVA_VISION.md](../NERVA_VISION.md) §2). Repo/engine codename stays `jarvis-hub` until the GitHub repo rename (owner task). |
| The agent roster | **the Cabinet** | 17 specialists across 4 tiers (Command / Business / Tech / Foundation). "Andrei's Cabinet" is the founder-instance flavor name, not the product name. |
| The UI | **Nerva** (the interface), drawn in the **Ledger** design | Home is **Today**: today's page. Since 2026-11-23 "HUD" and "cockpit" are retired from marketing copy; never "dashboard" either. It is a working book you keep and sign, not a chart you watch. The owner can switch the interface's look between installed themes (section 7.9); the brand is Ledger. |
| Companion product | **WorldView** | The 4D OSINT globe (separate stack); **Argus** is its governed bridge agent. |
| Individual agents | Jarvis, Friday, Pepper, Jerome · Athena, Stark, Veronica, Vision, Argus · Steve, Oracle, Ultron · Gecko, Hercules, Hephaestus, Frigga, Howard | Personalities are part of the brand; don't rename or flatten them. Frigga is the *proof* agent: strictly local, family data, zero network — lead with her in trust stories. |

✅ **Naming risk — RESOLVED (2026-07-19):** the product renamed to **Nerva** across every
user-facing surface (HUD, executable + `Documents/Nerva` data folder, landing, README, logo).
The orchestrator *agent* keeps its Jarvis persona (agent roster names are part of the brand,
per the table above); `jarvis-hub` remains the repo/engine codename until the GitHub repo
rename (owner task). Logo assets: `docs/brand/nerva-mark.svg` + `nerva-wordmark.svg`
(neural-N mark, void black `#030810` · signal blue `#00AEEF`).

---

## 3. Taglines

**Primary:**
> **The AI that works while you sleep.**

**Secondary (rotate by context):**
- *17 agents. One system. Your data stays home.*
- *Finally: an AI assistant that learns what to stop asking you.*
- *From chat to cortex — the operating system for your life.*
- *Owned by you. Governed by you. $0/month.*

**Descriptor line (repo, app stores, directories):**
> Local-first, governed personal AI OS — 17 specialist agents, proactive autonomy with an
> approval queue and tamper-evident audit log, running on your own GPU for $0/month.

---

## 4. Audiences

1. **Privacy-conscious power users / self-hosters** (primary at launch) — run LM Studio/Ollama,
   refuse cloud assistants. Speak to: ownership, $0 COGS, inspectability, one-command install.
2. **The post-OpenClaw disillusioned** — wanted the always-on agent, got burned (or scared) by
   ungoverned autonomy. Speak to: approval queue, reversible/irreversible split, Merkle audit log,
   signed skills, kill-switch.
3. **Families & "digital household" builders** — want AI on family data without leaking it.
   Speak to: Frigga (strict-local), LAN-only data, mic-mute trust indicator.
4. **(Phase 2) Regulated professionals & design partners** — can't send data out. Speak to:
   governance as a feature, audit trail, % -local metric, provable-trust CI.

---

## 5. Messaging Pillars (with proof points — updated 2026-07-04)

| Pillar | Claim | Proof |
|---|---|---|
| **Private by architecture** | Your life never leaves your machine by default | Local LM Studio/Ollama inference; every cloud hop is per-agent opt-in; Frigga/Ultron/Howard are hard-coded `LOCAL_ONLY_AGENTS`; data trains no one's model |
| **Governed autonomy** | It acts alone only where it's safe — and proves it | 4-tier risk policy (read-only → irreversible/money); approval inbox with one-tap Telegram decisions; tamper-evident Merkle audit log; signed skills, quarantine, kill-switch |
| **It compounds** | More useful every week you use it | Nightly reflection → bi-temporal knowledge graph; fused recall (vector ⊕ graph RRF); preference learning ("learns to stop asking"); sleep-time consolidation |
| **Production-grade** | Not a demo | **3,600+ automated Python tests** plus frontend Vitest, mobile Jest, and Playwright HUD/flow suites; 36× SQLite hot-path speedup; circuit breakers; CI + CodeQL; 363 HTTP routes; HUD/mobile approval queue and O26 quality gates merged |
| **Yours, economically** | $0/month, no meter running | Runs on your GPU (~4B-active MoE); cloud only for explicitly approved agents; free self-host = the business model's honesty check |

**North-star metric (internal, keeps marketing honest):** weekly autonomous actions *accepted* per
active user. Counter-metrics: interrupt rate ≤4/day, reject rate, %-local, p95 latency.

---

## 6. Voice & Tone

- **Calm competence, butler not hype-man.** Jarvis says "Done, sir" — the brand never shouts.
- **Specific over superlative.** "3,600+ tests, 36× speedup, ≤4 interrupts/day" beats "blazingly
  powerful". Every claim must trace to the repo or a dated research doc.
- **Honest about trade-offs.** We publish our gap lists (`BACKLOG.md`, `HUD_V2_REMAINING.md`).
  Saying "the HUD's deep controls are 3–5 PRs behind the backend, here's the punch-list" *is*
  the trust pitch.
- **Security without fear-mongering.** Reference OpenClaw as a verified cautionary tale (dated,
  sourced), never as FUD.
- **Bilingual reality:** product docs are RO/EN by context; **marketing surfaces are EN**, agent
  personalities keep their established voices (don't translate Frigga's warmth away).

**Words we use:** own, govern, local, cabinet, cortex, sign, the record, audit, compound, sir.
**Words we avoid:** revolutionary, magic, superhuman, "AI employee", "set and forget".

**The voice of the interface's own words (since 2026-11-23).** Plain, specific, sentence case.
It names the thing and its consequence, and it says *unknown* when it does not know.

| Before (HUD v2) | Now (Ledger) |
|---|---|
| ALL NOMINAL (a constant) beside a red pulsing dot | Working, with 4 local services down · since 08:14 · checked 10:50 |
| DECISION QUEUE 36 · [Dismiss] | 9 await your signature · [Sign · restart all 4] [Defer] [Reject group] |
| Needs approval · irreversible | Irreversible · To undo: none · typed: delete |
| % LOCAL 100% | Runs on this machine 100% · 41 of 41 runs today · by route |
| MIC ON (also shown when unknown) | Microphone On — or Microphone Unknown |
| Speak or type a command… · [TRANSMIT] | Message Jarvis… · [Send] |

---

## 7. Visual Identity — Ledger (since 2026-11-23)

The product is still the brand asset: screenshots of the interface and the governed-autonomy demo
are the hero visuals. What changed is the interface. The source of truth for values is the
design system in code, [`frontend/src/theme/`](../frontend/src/theme/) (`tokens.css`,
`themes/ledger.css`, `CONTRACT.md`); the designer's identity sheet is
[`docs/design/hud-next/ledger/README.md`](design/hud-next/ledger/README.md) §2.

### 7.1 The idea

Nerva keeps books. Everything it says, does and proposes is an entry in a sealed chain, and
nothing risky happens without the owner's signature. So the interface is the book: a typeset
working page of ruled registers where type and rules carry the structure and colour is ink on
paper, or its carbon. One colour, vermilion, is reserved for the owner's hand.

**Promise:** nothing happens off the books, and nothing risky happens without your signature.

### 7.2 Logo and the seal

The neural N (three strokes, four nodes) inside a ring, drawn in ink, beside the wordmark
**Nerva** set in the serif, bold, sentence case. The void-black tile and the signal blue are
retired. The same ring is the product's seal, in three states of authority, and nowhere else:

| Mark | Meaning |
|---|---|
| ring and N in vermilion outline | awaits your signature |
| solid vermilion disc, N knocked out | signed by you |
| solid ink disc, N knocked out | sealed in the record |

### 7.3 Palette

Authored in OKLCH, one token per role, two schemes. Neutrals share one hue family ("ledger
green", hue 140–165) at chroma ≤ 0.022. **Carbon** (dark) is the default: the copy you work from
all day, with no bright fill at rest, kind to an always-on OLED panel. **Paper** (light) is the
original: daylight, long reading, anything printed or exported. Paper is designed, not inverted.

| Role | Carbon (dark, default) | Paper (light) |
|---|---|---|
| The page | `oklch(0.176 0.008 165)` ≈ #0e1210 | `oklch(0.979 0.006 150)` ≈ #f5f9f6 |
| A sheet (where you write or sign) | `oklch(0.212 0.010 165)` ≈ #151a18 | `oklch(0.997 0.002 150)` ≈ #fdfefd |
| Ink (text) | `oklch(0.912 0.014 138)` ≈ #dde4db | `oklch(0.205 0.022 165)` ≈ #0d1a15 |
| Ink, secondary | `oklch(0.775 0.014 145)` ≈ #b0b8b0 | `oklch(0.375 0.020 165)` ≈ #37453e |
| Ink, meta | `oklch(0.660 0.014 150)` ≈ #8c958e | `oklch(0.485 0.016 165)` ≈ #57625d |
| Hairline rule | `oklch(0.268 0.010 165)` ≈ #222825 | `oklch(0.880 0.010 150)` ≈ #d3d9d4 |
| **The seal — vermilion** | `oklch(0.705 0.185 35)` ≈ #fd6c48 | `oklch(0.535 0.200 33)` ≈ #c72500 |

Every text pairing clears WCAG 2.2 AA (ink 14.6:1 on Carbon, 16.8:1 on Paper; the seal ≥ 4.7:1),
enforced by `frontend/src/test/theme-contrast.test.ts`.

### 7.4 Type

Three families, each with one job. The split is the identity. All are open-licence and
self-hosted (the product is local-first; no font is ever fetched from the network).

| Role | Face | Sizes |
|---|---|---|
| What Nerva writes for you to read, and what you sign: replies, verdicts, entries, the record | **Literata** (serif, optical sizes) | replies 17/27 · titles 22 · verdict 32 · the one figure on a page 44 |
| The instrument: labels, tables, controls, navigation, and your own typed words | **Barlow** (DIN-like sans) | UI 14/20 · labels 13/18 · meta 12/16 |
| Identifiers only: hashes, ids, addresses, model and capability names | **JetBrains Mono** | 12 |

Sentence case everywhere; no uppercase tracked labels. Figures are lining, tabular in columns.
Nothing below 12px; on large screens every reading size steps up one. Literata (variable, with
optical sizes) and Barlow (300–700) ship with the app, self-hosted under the SIL Open Font License
(`frontend/src/assets/fonts/`); Sitka and Bahnschrift remain only as the stacks' fallbacks.

### 7.5 Shape, rules, marks, motion

- **Rules, not boxes.** A hairline separates rows, a 2px rule opens a register, a single rule
  above and a double rule below make a total. Radius 0 on rules and sheets, 2px on controls, 4px
  on transient layers; only seals and state marks are round. A page has at most one bordered
  sheet, and it is where the owner signs or stops. No shadows on work surfaces; no translucency.
- **Marks.** State is a shape plus a word, never a hue alone: ● ok · ◐ attention · ■ problem ·
  dashed ○ unknown · clock ○ stale · ‖ held · ⊘ blocked · ▶ working · ✓ done. Risk is a three-bar
  glyph plus its name (read only, reversible, external, irreversible or money).
- **Motion.** Still by default: 120ms on hover and press, 180ms when a seal fills or a row opens,
  nothing else. No pulsing, no tickers, no spinners; reduced motion sets both to 0.

### 7.6 Art direction for marketing assets

The page itself, photographed honestly: Today in Carbon, or Paper for print. Real data as
content, demo data visibly badged. No mascots, no glows, no gradients, no stock photos, no
decorative networks or globes. One idea per asset, generous margins, the serif for the headline,
Barlow for everything around it, vermilion only where the asset shows the owner signing.

### 7.7 Three things this identity never does

1. It never uses vermilion for itself — not for the brand, errors, alerts or emphasis.
   Vermilion means the owner's hand.
2. It never draws a box where a rule will do, and never a card inside a card.
3. It never shows a reading it did not get: no default values, no 0 for unknown, no "all clear"
   when the feed did not answer, no decorative shield.

### 7.8 Retired with HUD v2

Void black `#04070E` and `#030810`, signal cyan `#2BB8F0` and `#00AEEF`, Space Grotesk as the
brand face, letter-spaced uppercase mono micro-labels, corner brackets, chamfers, glows and
scanlines survive only inside the interface's optional **Classic** themes (7.9), and only as a
skin: since 2026-11-24 every theme, Classic included, draws the same Ledger page (the masthead,
the running head, Home's day, conversation and docket). The HUD v2 shell is gone in every theme:
the top bar and its badges, the scrolling ticker and its "ALL NOMINAL", the mode rail, the
cockpit's neural mesh and cognition trace, and the spinning reactor beside the wordmark.

Surfaces not migrated at the time of writing (2026-11-24):

- outside the interface: the marketing landing page (`marketing/landing/`), the brand SVGs in
  `docs/brand/`, the legacy `/v1` pages and the imported `/os` interface;
- the mobile app, which follows each theme's dark palette but keeps its own structure, faces and
  shapes, and has no light scheme;
- inside the interface, drawn in the HUD v2 markup and restyled by the theme rather than redrawn
  in the Ledger language: Cinema (`m`: the neural mesh, the voice orb and the briefing wall, kept
  at the owner's request, with the reactor mark in its corner), the agent Dossier, the provenance,
  keyboard-shortcut and first-run dialogs, and the bodies of the Console panels shown as pages.

### 7.9 Themes the owner can choose

The interface ships with installable themes, switched in Settings → Personalisation, each with a
dark and a light scheme: **Ledger** (the default and the brand), **Presence**, **Briefing**,
**Workbench**, **Threshold**, **Console**, **Atlas**, and **Classic** (Obsidian, Graphite — the HUD
v2 look). A theme changes the look of the same structure; it is a personal preference, not a
second brand. Marketing material always shows Ledger.

---

## 8. Boilerplate Copy (paste-ready)

**One-liner (≤140 chars):**
> Local-first, governed personal AI OS: 17 agents, proactive autonomy with approval queue + audit
> log, on your own GPU. $0/month.

**25 words:**
> Nerva is a personal AI operating system: 17 specialist agents working proactively on your
> hardware, with governed autonomy, living memory, and zero cloud dependency.

**100 words:**
> Nerva is a local-first personal AI operating system. Seventeen specialist agents — from
> daily intel to family memory — run 24/7 on your own GPU, coordinated by Jarvis. The system finds
> its own work: it monitors your world, consolidates every conversation into a knowledge graph
> nightly, and delivers a prioritized brief each morning. Every autonomous action passes a
> reversible/irreversible approval queue and a tamper-evident audit log; every cloud hop is
> per-agent opt-in, and the family agent never touches the internet. 3,600+ tests, 363 HTTP routes,
> $0/month. The AI that works while you sleep — owned by you.

**Ready-to-use launch assets** built from this brand: [`docs/marketing/`](marketing/) —
`ANNOUNCEMENT.md` (release post), `TEASER_PACK.md` (social + video script), `DESIGN_BRIEF.md`
(creative brief for Claude Design / a designer, with exact specs).

---

## 9. GitHub Repo Metadata (apply in Settings → General)

| Field | Value |
|---|---|
| **Name** | `jarvis-hub` today (engine codename, existing links); the rename to `nerva` is an owner task — see `docs/OWNER_TASKS.md` |
| **Description** | `Local-first, governed personal AI OS — 17 specialist agents, proactive autonomy with approval queue & tamper-evident audit log, living memory (KG + fused recall), voice + 7 channels. Runs on your own GPU. $0/month.` |
| **Website** | `http://www.andrei649.ro` (swap for a product page at launch) |
| **Topics** | `ai`, `personal-assistant`, `multi-agent`, `local-first`, `self-hosted`, `privacy`, `llm`, `fastapi`, `lm-studio`, `ollama`, `autonomous-agents`, `knowledge-graph`, `voice-assistant`, `osint` |

**Social preview image:** the Today page in Carbon (Ledger), cropped to the docket and the
conversation, with the serif wordmark and the primary tagline; same asset doubles as the README
hero until the demo GIF lands. (Before 2026-11-23 this was the HUD v2 cockpit on void black.)

---

## 10. Launch Narrative (the story in 5 beats)

1. **2026 proved the demand** — the OpenClaw wave showed everyone wants an always-on agent.
2. **It also proved the failure mode** — ungoverned autonomy + cloud memory = the #1 infostealer
   target. The "knows-you device" graveyard (Humane, Dot, Rewind, Pi) was uniformly cloud-bound.
3. **The durable position is local + governed** — privacy promise *and* $0 COGS, in one move.
4. **Nerva is that position, shipped** — the H1-H22 core is complete and the H23/O26
   productionization layer is actively landing, with every principle (local-first, opt-in cloud,
   inspectable, budgeted interrupts)
   enforced in code, not in a values page.
5. **The ask:** self-host it (one `INSTALL.bat` / `install.sh`), watch it earn autonomy one
   approved action at a time.

---

*Keep this file in sync with [MOONSHOT.md](../MOONSHOT.md) (positioning) and
[GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) (metrics). Stale numbers here are a brand bug — proof points
carry dates for that reason.*
