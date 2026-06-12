# Jarvis Hub — Marketing Design Brief

> A self-contained creative brief for producing launch visuals (with Claude Design, Canva, Figma, a
> video tool, or a human designer). Everything needed to make on-brand assets is here — copy, exact
> specs, palette, do/don't. Source of truth for brand: `docs/BRAND_BOOK.md`. Source for copy:
> `ANNOUNCEMENT.md` + `TEASER_PACK.md` (same folder).

---

## 0. The brief in one line

Make assets that feel like **a calm, premium, dark cockpit you command** — not a hype-y SaaS landing
page. The product itself is the hero; real on-screen data is the texture. Restraint signals trust.

---

## 1. Brand constants (use these exactly)

**Palette**
| Role | Hex | Use |
|------|-----|-----|
| Void (background) | `#04070E` | Dominant. Almost-black with a blue undertone. |
| Ink (text) | `#EEF1F5` | Primary text on void. |
| Signal cyan (accent) | `#2BB8F0` | The one accent. Headlines highlight, active states, the wordmark. Light variant `#8FE0FF`. |
| Status green | `#41F59B` | "verified / on-device / success" only. |
| Status amber | `#FFB23F` | "demo / caution" only. |
| Alert red | `#FF5A52` | "halt / danger" only — sparingly. |
| Violet | `#A78BFA` | Secondary accent (the "cloud" sliver, alt data series). |

**Type**
- **Display / UI:** Space Grotesk (600/500 for headlines, 400 body).
- **Data / labels / code / micro-caps:** JetBrains Mono. Letter-spaced (`.12–.18em`), often UPPERCASE, small.
- Numbers: tabular figures.

**Logo:** wordmark `JARVIS HUB` in Space Grotesk, signal-cyan on void, with an optional mono sub-line
(e.g. `PERSONAL · AI · OS`). No icon mark exists yet — wordmark is canonical.

**Texture (optional, subtle):** faint dot-grid or a single thin scanline. Never busy. Glows are
thin and tight, never neon-soaked.

---

## 2. Voice rules for any copy on an asset

- Calm, specific, declarative. Butler, not hype-man.
- Numbers over adjectives ("2,150+ tests, $0/month" beats "powerful").
- Never: "revolutionary", "magic", "superhuman", "AI employee", "set and forget".
- Always-true: every claim must trace to the repo (see the proof list in §5).

---

## 3. Assets to produce (priority order)

### A. Social preview / OG image — `1200 × 630`  ★ make first
- Background: void `#04070E`, faint dot-grid.
- Center-left: wordmark `JARVIS HUB` (cyan) + tagline in ink: **"The AI that works while you sleep."**
- Right third: a cropped, slightly-angled screenshot of the real HUD cockpit (the agent network brain).
- Bottom mono strip (ink-3, small): `LOCAL-FIRST · 17 AGENTS · GOVERNED AUTONOMY · $0/MONTH`.
- This doubles as the GitHub repo social preview and the README hero until a demo GIF exists.

### B. The "three pillars" card — `1080 × 1080` (square, for social)
Three stacked rows, each = mono label + one line:
- `PRIVATE BY ARCHITECTURE` — Local inference. Every cloud hop opt-in. Your data trains no one's model.
- `PROACTIVE, NOT REACTIVE` — Works 24/7. Escalates only what matters. Learns to stop asking.
- `GOVERNED, PROVABLY` — Approval queue + tamper-evident audit log. Enforced in code, proven by tests.
Accent the lead words in cyan. Lots of void space. Wordmark small, bottom.

### C. One-pager / sell sheet — `A4 portrait` (PDF)
Single page, top-to-bottom:
1. Wordmark + tagline (hero band).
2. One-paragraph "what it is" (lift the TL;DR from `ANNOUNCEMENT.md`).
3. The three pillars (as B).
4. A 6-cell "proof" strip (from §5 below) — big mono numbers.
5. The agent roster as a quiet 4-tier grid of names (Command / Business / Tech / Foundation).
6. Footer: `Self-host: INSTALL.bat / install.sh · github.com/andrei649/jarvis-hub · $0/month`.

### D. Teaser GIF / 60s video — storyboard is in `TEASER_PACK.md` §3
Screen-record the real HUD. The shot list is in `TEASER_PACK.md` §6. Captions in JetBrains Mono,
typed-on, cyan highlights. Calm synth bed, no voiceover needed.

### E. Carousel (5 cards, `1080 × 1350` portrait) — for the launch-day thread
One card per `TEASER_PACK.md` §2 post. Same template as B; one idea per card; final card = the CTA.

---

## 4. Layout do / don't

**Do:** generous void margins · one idea per asset · real product screenshots · thin cyan rules ·
mono micro-labels for structure · left-aligned, calm hierarchy.

**Don't:** gradients-for-the-sake-of-it · neon glow soup · stock photos of people at laptops ·
emoji-heavy headlines · more than one accent color competing · fabricated/stat UI mockups
(use the real HUD; demo mode is clearly badged — that honesty is the brand).

---

## 5. Approved proof points (verified 2026-06-10 — safe to put on an asset)

Use these exact, conservative framings:
- **17 specialist agents** (4 tiers) + 17 promotable bench agents.
- **2,150+ automated tests** (Python core) passing in CI, plus frontend + OSINT-stack suites.
- **~250 API endpoints**; a real-time cockpit HUD; **7 channels** (web, voice, Telegram, Discord, Slack, email, sandbox).
- **$0 / month** — local inference for ~99% of tasks; cloud is per-agent opt-in.
- **Tamper-evident audit log** (hash-chained, one-call integrity verify) · reversible/irreversible
  **approval queue** · signed skills · kill-switch.
- **Strict-local agents** (family, security, digital twin) — code-enforced to never reach the cloud.
- Runs on a **consumer GPU** via LM Studio / Ollama.

> If a number isn't on this list, don't put it on an asset without checking `BACKLOG.md` (the source
> of truth) first. Stale stats on a launch graphic are a brand bug.

---

## 6. The 12-word story (if you can only say one thing)

> A private AI that works while you sleep — owned by the person it serves.

---

## 7. Handing this to a tool

- **Claude Design / "make me a launch graphic":** paste §1 (palette+type), §3-A (the asset spec),
  and the hero copy from §3-A. That's a complete prompt.
- **A coworker:** this file + `BRAND_BOOK.md` + the screenshots in the launch shot list (`TEASER_PACK.md` §6).
- **A video tool:** `TEASER_PACK.md` §3 (script) + §6 (shots) + §1 here (palette/type).
