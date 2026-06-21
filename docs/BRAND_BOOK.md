# Jarvis Hub — Brand Book

> The main marketing brand reference. Positioning, naming, messaging, voice, and visual identity —
> all downstream of [MOONSHOT.md](../MOONSHOT.md) (the *why*) and consistent with
> [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) §3 (the launch brief).
> Generated: 2026-06-10 · Owner: Andrei · Status: **v0.10.0** (feature-complete, productionizing toward 1.0)

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
| Product / repo | **Jarvis Hub** (`jarvis-hub`) | The platform. Always two words in prose, kebab-case in code. |
| The agent roster | **the Cabinet** | 17 specialists across 4 tiers (Command / Business / Tech / Foundation). "Andrei's Cabinet" is the founder-instance flavor name, not the product name. |
| The UI | **the HUD** (V2 "cockpit") | Never "dashboard" in marketing copy — it's a cockpit you command, not a chart you watch. |
| Companion product | **WorldView** | The 4D OSINT globe (separate stack); **Argus** is its governed bridge agent. |
| Individual agents | Jarvis, Friday, Pepper, Jerome · Athena, Stark, Veronica, Vision, Argus · Steve, Oracle, Ultron · Gecko, Hercules, Hephaestus, Frigga, Howard | Personalities are part of the brand; don't rename or flatten them. Frigga is the *proof* agent: strictly local, family data, zero network — lead with her in trust stories. |

⚠️ **Naming risk (pre-commercial):** "Jarvis" carries Marvel/Disney association. Fine for an
open-source personal project; **revisit before Phase 2 (Sellable)** — the planned relicense pass
(`docs/LICENSE_DECISION.md`, TRADEMARKS.md) is the natural checkpoint. Candidate fallback: keep
"Hub"/"Cabinet" equity, rename the orchestrator persona only.

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

## 5. Messaging Pillars (with proof points — updated 2026-06-10)

| Pillar | Claim | Proof |
|---|---|---|
| **Private by architecture** | Your life never leaves your machine by default | Local LM Studio/Ollama inference; every cloud hop is per-agent opt-in; Frigga/Ultron/Howard are hard-coded `LOCAL_ONLY_AGENTS`; data trains no one's model |
| **Governed autonomy** | It acts alone only where it's safe — and proves it | 4-tier risk policy (read-only → irreversible/money); approval inbox with one-tap Telegram decisions; tamper-evident Merkle audit log; signed skills, quarantine, kill-switch |
| **It compounds** | More useful every week you use it | Nightly reflection → bi-temporal knowledge graph; fused recall (vector ⊕ graph RRF); preference learning ("learns to stop asking"); sleep-time consolidation |
| **Production-grade** | Not a demo | **~2,400 backend tests + 184 frontend tests**; 36× SQLite hot-path speedup; circuit breakers; CI + CodeQL; ~299 API routes; **194/196 backlog items (≈99% SP) code-complete** |
| **Yours, economically** | $0/month, no meter running | Runs on your GPU (~4B-active MoE); cloud only for explicitly approved agents; free self-host = the business model's honesty check |

**North-star metric (internal, keeps marketing honest):** weekly autonomous actions *accepted* per
active user. Counter-metrics: interrupt rate ≤4/day, reject rate, %-local, p95 latency.

---

## 6. Voice & Tone

- **Calm competence, butler not hype-man.** Jarvis says "Done, sir" — the brand never shouts.
- **Specific over superlative.** "~2,400 tests, 36× speedup, ≤4 interrupts/day" beats "blazingly
  powerful". Every claim must trace to the repo or a dated research doc.
- **Honest about trade-offs.** We publish our gap lists (`BACKLOG.md`, `HUD_V2_REMAINING.md`).
  Saying "the HUD's deep controls are 3–5 PRs behind the backend, here's the punch-list" *is*
  the trust pitch.
- **Security without fear-mongering.** Reference OpenClaw as a verified cautionary tale (dated,
  sourced), never as FUD.
- **Bilingual reality:** product docs are RO/EN by context; **marketing surfaces are EN**, agent
  personalities keep their established voices (don't translate Frigga's warmth away).

**Words we use:** own, govern, local, cabinet, cortex, approve, audit, compound, sir.
**Words we avoid:** revolutionary, magic, superhuman, "AI employee", "set and forget".

---

## 7. Visual Identity (from the shipped HUD V2)

The product *is* the brand asset — screenshots and the 30–60s governed-autonomy demo GIF
(README TODO) are the hero visuals.

**Palette (HUD V2 tokens, `frontend/src/styles.css`):**

| Role | Token | Hex |
|---|---|---|
| Background ("void") | `--void` | `#04070E` |
| Text ("ink") | `--ink` | `#EEF1F5` |
| Primary accent — signal cyan | `--accent` | `#2BB8F0` (light `#8FE0FF`) |
| Status green | `--green` / accent variant | `#41F59B` |
| Status amber | `--amber` / accent variant | `#FFB23F` |
| Alert red | `--red` | `#FF5A52` |
| Violet (alt accent) | `--violet` | `#A78BFA` |

**Typography:** **Space Grotesk** (UI/display) + **JetBrains Mono** (data, timestamps, code).
Tabular numerals for metrics. Letter-spaced mono micro-labels are a signature element.

**Art direction:** dark cockpit, thin glowing strokes, real data as texture (network brain, globe,
timelines). No mascots, no gradients-for-gradients'-sake, no stock-photo humans. WorldView's globe
inherits the same void/cyan language.

**Logo:** currently the wordmark "JARVIS HUB" set in Space Grotesk with the mono sub-line (see HUD
top bar `brand-tx`). A dedicated mark is open work — until then, the wordmark + signal-cyan on void
is canonical.

---

## 8. Boilerplate Copy (paste-ready)

**One-liner (≤140 chars):**
> Local-first, governed personal AI OS: 17 agents, proactive autonomy with approval queue + audit
> log, on your own GPU. $0/month.

**25 words:**
> Jarvis Hub is a personal AI operating system: 17 specialist agents working proactively on your
> hardware, with governed autonomy, living memory, and zero cloud dependency.

**100 words:**
> Jarvis Hub is a local-first personal AI operating system. Seventeen specialist agents — from
> daily intel to family memory — run 24/7 on your own GPU, coordinated by Jarvis. The system finds
> its own work: it monitors your world, consolidates every conversation into a knowledge graph
> nightly, and delivers a prioritized brief each morning. Every autonomous action passes a
> reversible/irreversible approval queue and a tamper-evident audit log; every cloud hop is
> per-agent opt-in, and the family agent never touches the internet. ~2,400 tests, ~299 API routes,
> $0/month. The AI that works while you sleep — owned by you.

**Ready-to-use launch assets** built from this brand: [`docs/marketing/`](marketing/) —
`ANNOUNCEMENT.md` (release post), `TEASER_PACK.md` (social + video script), `DESIGN_BRIEF.md`
(creative brief for Claude Design / a designer, with exact specs).

---

## 9. GitHub Repo Metadata (apply in Settings → General)

| Field | Value |
|---|---|
| **Name** | `jarvis-hub` (keep — matches brand + existing links) |
| **Description** | `Local-first, governed personal AI OS — 17 specialist agents, proactive autonomy with approval queue & tamper-evident audit log, living memory (KG + fused recall), voice + 7 channels. Runs on your own GPU. $0/month.` |
| **Website** | `http://www.andrei649.ro` (swap for a product page at launch) |
| **Topics** | `ai`, `personal-assistant`, `multi-agent`, `local-first`, `self-hosted`, `privacy`, `llm`, `fastapi`, `lm-studio`, `ollama`, `autonomous-agents`, `knowledge-graph`, `voice-assistant`, `osint` |

**Social preview image:** HUD V2 cockpit screenshot on void-black with the wordmark + primary
tagline; same asset doubles as the README hero until the demo GIF lands.

---

## 10. Launch Narrative (the story in 5 beats)

1. **2026 proved the demand** — the OpenClaw wave showed everyone wants an always-on agent.
2. **It also proved the failure mode** — ungoverned autonomy + cloud memory = the #1 infostealer
   target. The "knows-you device" graveyard (Humane, Dot, Rewind, Pi) was uniformly cloud-bound.
3. **The durable position is local + governed** — privacy promise *and* $0 COGS, in one move.
4. **Jarvis Hub is that position, shipped** — 99% of a 1,119-SP backlog code-complete, audit gate
   in progress, every principle (local-first, opt-in cloud, inspectable, budgeted interrupts)
   enforced in code, not in a values page.
5. **The ask:** self-host it (one `INSTALL.bat` / `install.sh`), watch it earn autonomy one
   approved action at a time.

---

*Keep this file in sync with [MOONSHOT.md](../MOONSHOT.md) (positioning) and
[GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) (metrics). Stale numbers here are a brand bug — proof points
carry dates for that reason.*
