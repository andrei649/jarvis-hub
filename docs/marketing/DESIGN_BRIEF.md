# Nerva — Marketing Design Brief

> A self-contained creative brief for producing launch visuals (with Claude Design, Canva, Figma, a
> video tool, or a human designer). Everything needed to make on-brand assets is here — copy, exact
> specs, palette, do/don't. Source of truth for brand: `docs/BRAND_BOOK.md`. Source for copy:
> `ANNOUNCEMENT.md` + `TEASER_PACK.md` (same folder).

---

## 0. The brief in one line

Make assets that feel like **a calm, exact working book that belongs to its owner** — not a hype-y
SaaS landing page and no longer a sci-fi cockpit. The product itself is the hero; real on-screen
data is the content. Restraint signals trust.

> **Identity changed 2026-11-23.** The owner retired the HUD v2 cockpit identity (void black,
> signal cyan, Space Grotesk, mono micro-caps, glows) for the **Ledger** design. The constants
> below follow [`docs/BRAND_BOOK.md`](../BRAND_BOOK.md) §7, which is the source of truth.

---

## 1. Brand constants (use these exactly)

**Palette** — Carbon (dark) is the default; Paper (light) for print and daylight.
| Role | Carbon | Paper | Use |
|------|-----|-----|-----|
| The page | `#0e1210` | `#f5f9f6` | Dominant ground. Near-black with a faint green cast / ledger paper. |
| A sheet | `#151a18` | `#fdfefd` | The one raised surface: where the owner writes or signs. |
| Ink | `#dde4db` | `#0d1a15` | Text. Never pure white or pure black. |
| Ink, secondary | `#b0b8b0` | `#37453e` | Secondary text, captions. |
| Hairline | `#222825` | `#d3d9d4` | Rules between rows. Structure is drawn with rules, not boxes. |
| **Seal — vermilion** | `#fd6c48` | `#c72500` | The one colour. **Only** where the owner's signature is asked for, given or recorded. Never for emphasis, errors or the brand itself. |

**Type**
- **What Nerva writes, headlines, verdicts:** Literata (serif). Titles 600–700; reading 400.
- **The instrument, captions, labels, buttons:** Barlow (sans). Sentence case. No letter-spaced capitals.
- **Identifiers only (hashes, ids, model names):** JetBrains Mono, small.
- Numbers: lining, tabular in columns.

**Logo:** the neural N inside a ring, in ink, beside the wordmark `Nerva` in Literata bold,
sentence case. The ring is also the seal: vermilion outline = awaits a signature, solid vermilion
= signed, solid ink = sealed in the record. No void tile, no cyan.

**Texture:** none. No dot grids, scanlines, glows or gradients. A 2px ink rule opening a block and
a double rule under a total are the only ornaments, and both carry meaning.

---

## 2. Voice rules for any copy on an asset

- Calm, specific, declarative. Butler, not hype-man.
- Numbers over adjectives ("3,600+ tests, $0/month" beats "powerful").
- Never: "revolutionary", "magic", "superhuman", "AI employee", "set and forget".
- Always-true: every claim must trace to the repo (see the proof list in §5).

---

## 3. Assets to produce (priority order)

### A. Social preview / OG image — `1200 × 630`  ★ make first
- Background: Carbon `#0e1210`, no texture.
- Center-left: the ring-N mark and wordmark `Nerva` (Literata, ink) + tagline in ink: **"The AI that works while you sleep."**
- Right third: a straight (not angled) crop of the real Today page: the docket with one entry awaiting signature (the only vermilion on the asset) and the conversation beside it.
- Bottom line in Barlow, ink secondary, sentence case: `Local-first · 17 agents · Governed autonomy · $0 a month`.
- This doubles as the GitHub repo social preview and the README hero until a demo GIF exists.

### B. The "three pillars" card — `1080 × 1080` (square, for social)
Three registers, each opened by a 2px ink rule: a Barlow label + one Literata line:
- `Private by architecture` — Local inference. Every cloud hop opt-in. Your data trains no one's model.
- `Proactive, not reactive` — Works 24/7. Escalates only what matters. Learns to stop asking.
- `Governed, provably` — Every action sealed in the record; nothing risky without your signature.
Lots of page around them. Wordmark small, bottom. No accent colour unless the card shows a signature.

### C. One-pager / sell sheet — `A4 portrait` (PDF)
Single page, top-to-bottom:
1. Wordmark + tagline (hero band).
2. One-paragraph "what it is" (lift the TL;DR from `ANNOUNCEMENT.md`).
3. The three pillars (as B).
4. A 6-cell "proof" strip (from §5 below) — large Literata figures, Barlow captions, a double rule under the row.
5. The agent roster as a quiet 4-tier grid of names (Command / Business / Tech / Foundation).
6. Footer: `Self-host: INSTALL.bat / install.sh · github.com/andrei649/jarvis-hub · $0/month`.

### D. Teaser GIF / 60s video — storyboard is in `TEASER_PACK.md` §3
Screen-record the real interface (Ledger, Carbon). The shot list is in `TEASER_PACK.md` §6 (its
shots of the old cockpit, the network brain and the ticker need re-shooting on Today). Captions in
Barlow, sentence case, appearing whole rather than typed on; vermilion only on the moment the owner
signs. Calm synth bed, no voiceover needed.

### E. Carousel (5 cards, `1080 × 1350` portrait) — for the launch-day thread
One card per `TEASER_PACK.md` §2 post. Same template as B; one idea per card; final card = the CTA.

---

## 4. Layout do / don't

**Do:** generous margins · one idea per asset · real product screenshots · ink rules for
structure (a 2px rule opens a block, a double rule closes a total) · sentence-case Barlow labels ·
the serif for anything Nerva "says" · left-aligned, calm hierarchy.

**Don't:** vermilion for emphasis or decoration · cyan, glows, scanlines, dot grids, gradients ·
uppercase letter-spaced labels · boxes inside boxes · stock photos of people at laptops ·
emoji-heavy headlines · fabricated/stat UI mockups (use the real interface; demo mode is clearly
badged — that honesty is the brand).

---

## 5. Approved proof points (verified 2026-07-04 — safe to put on an asset)

Use these exact, conservative framings:
- **17 specialist agents** (4 tiers) + 17 promotable bench agents.
- **3,600+ automated Python tests** tracked in `STATUS.md`, plus frontend Vitest, mobile Jest, and Playwright HUD/flow suites.
- **363 HTTP routes**; a real-time cockpit HUD; **7 channels** (web, voice, Telegram, Discord, Slack, email, sandbox).
- **$0 / month** — local-first inference on owner hardware; cloud is per-agent opt-in.
- **Tamper-evident audit log** (hash-chained, one-call integrity verify) · reversible/irreversible
  **approval queue** · signed skills · kill-switch.
- **Strict-local agents** (family, security, digital twin) — code-enforced to never reach the cloud.
- Runs on a **consumer GPU** via LM Studio / Ollama.

> Since 2026-09-07 a ✅ in `BACKLOG.md` means *delivered*, not *proven* — so a capability claim also
> needs a check against [`../OWNER_TASKS.md`](../OWNER_TASKS.md) → "Production-verification
> checklist", which lists what has never run against real hardware, a real credential or a real
> network.
>
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
