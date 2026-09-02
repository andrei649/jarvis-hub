# Jarvis Hub — Moonshot

> The north-star document. Everything else (roadmap, architecture, pricing) serves this.
> Generated: 2026-06-02 · **Rewritten: 2026-07-11** (the AI-OS expansion — see
> [NERVA_VISION.md](NERVA_VISION.md) + the decision log) · Stage: **v0.11.0** (feature-complete +
> refactor done; building toward the expanded 1.0 — see §4 + [version roadmap](BACKLOG.md#version-roadmap)) · Owner: Andrei
>
> **How to use this doc:** read §1–§4 to know *where we're going*, §7 to know *how we stay on
> track*. When a decision feels off-mission, check it against §5 (principles) and §1 (the bet).
> The detailed *capability* vision (six pillars, target architecture, the Hermes superiority bar)
> lives in [NERVA_VISION.md](NERVA_VISION.md). The operational docs linked in §8 are *downstream* of this one.

---

## 1. The Moonshot

> **Nerva is a local-first Personal Intelligence Operating System that can perceive, understand,
> communicate, operate digital and physical systems, verify outcomes, and continuously expand its
> own capabilities under explicit human governance — owned by the person it serves, not the vendor.**

*(**Nerva** is the product brand, published by Digitaholic; the in-product rename was executed
2026-07-19 — `jarvis-hub` stays the repo/engine codename until the GitHub repo rename, an owner
task — [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md). Brand architecture —
Cortex · Atlas · Synapse · Vision · Ultron: [NERVA_VISION.md](NERVA_VISION.md) §2.)*

Not a chatbot. Not a workflow builder. A **persistent, proactive, private cortex** that runs on
your own hardware, builds a growing understanding of your life, finds its own work, and asks for a
decision only when it genuinely needs one — then learns to stop asking. And increasingly the
**operator** of your digital and physical world — screen, house, media, cameras — through one
governed kernel. The fundamental loop is not question→answer; it is:

```
Observe → Understand → Decide → Act → Verify → Learn
```

The 10-year bet: **the default interface to your digital life is a multi-agent system you own**,
the way the OS — not the mainframe — became the default for personal computing. Jarvis Hub aims to
be that OS, starting as Andrei's "cabinet" and generalizing to anyone who refuses to rent their
private life to a hyperscaler.

---

## 2. Why Now

- **Local inference crossed the usefulness threshold** — a ~4B-active MoE on a single consumer GPU
  is good enough for 99% of daily tasks at **$0 marginal cost** (see [VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) §8).
- **Privacy is becoming a buying criterion**, not a footnote — regulated orgs and privacy-conscious
  individuals can't or won't send their data to someone else's model.
- **Agent orchestration is fragmenting** into reactive chatbots vs rigid workflow builders. No
  *shipping consumer product* combines *autonomy + memory + observability + preference learning* in
  one **local-first** system: the closest combined product (Amazon's Bee) is cloud; the closest
  local-first one (open-source Omi) is passive capture, not an autonomous actor (verified 2026-06-02 —
  [docs/research/2026-06-02-personal-ai-competitors.md](docs/research/2026-06-02-personal-ai-competitors.md)).
- **The cautionary tale validates the bet.** The viral 2026 rival **OpenClaw** relaxed exactly the
  constraints this project holds non-negotiable (production-grade security, governed autonomy) — and
  within ~8 weeks became the #1 infostealer target, with malware harvesting users' agent-memory files.
  The "knows-you device" graveyard (Humane, Dot, Rewind/Limitless, Pi) was uniformly cloud-dependent.
  **Local-first + governed is the durable position, not the slow one** — this *confirms* thesis #3 below.
- **The execution plane is now a commodity.** Hermes-class open agents (MIT) prove that browser
  automation, terminal execution and skill self-improvement are *adoptable*, not a moat — Jarvis
  already ports those mechanisms under governance (ORIZONT 20). The moat is what they lack:
  governed authority + the personal-world model (verified 2026-07-11 —
  [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md)).

---

## 3. The Thesis (what has to be true)

1. **Local-first is a durable moat, not a constraint** — it's simultaneously the privacy promise
   *and* the cost-of-goods advantage (free self-host = $0 COGS; a hosted minority funds the company
   at 70–98% gross margin — [VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) §9).
2. **Proactivity compounds** — a system that works 24/7 and consolidates memory nightly gets more
   useful the longer you use it, creating switching cost no reactive tool can match.
3. **Trust is earned by inspectability** — every fact editable, every action audited, every cloud
   hop opt-in. The strict-local agent (Frigga) is the proof, not the marketing.
4. **Capabilities compound under governance** — a machine-readable capability registry with
   verification and *earned* autonomy makes every new integration multiply the others; ungoverned
   capability growth (the OpenClaw / unrestricted-self-modification path) is the failure mode,
   not the fast path ([NERVA_VISION.md](NERVA_VISION.md) §6–§7).

If any of these stops being true, revisit the moonshot — don't quietly drift from it.

---

## 4. Trajectory — From Cabinet to Platform

Mapped to the existing Horizon plan and [version roadmap](BACKLOG.md#version-roadmap). Each phase has
a clear "done" gate; we do not skip gates.

| Phase | Horizon → Version | The leap | Gate (done when…) |
|-------|-------------------|----------|-------------------|
| **0 — Foundation** ✅ | H1–H9 → v0.9.x-beta | 16 agents, memory, autonomy, workflows, observability all work | Live; foundation green |
| **1 — Feature-complete** ✅ | H10 + H11 + H12 + H13–H17 + H18–H22 + WorldView O19 → **v0.10.0** | From "works for Andrei" to a feature-rich, local-first AI OS — *every feature horizon shipped* | All feature backlog delivered; north-star instrumented. **But: single-user, unproven, not yet productionized.** |
| **2a — Proven core** 🎯 (in flight) | **H23** + O24–O26 → **v0.12 … v0.20** | From "code-complete" to a product a stranger can install, trust, upgrade — **the proof track** | H23 spine done · ⭐B0 manual run · 72h soak · 1–3 design partners ≥2 weeks with real north-star data. *Formerly the whole 1.0 gate; now the trust half of it.* |
| **2b — The AI OS** 🎯 | **O27–O33 → v0.21 … v0.27** | From governed assistant to a system that perceives, operates and grows: capability registry, computer/browser operators, media director, house brain, cameras, capability acquisition, ambient intelligence | Per-horizon gates in [BACKLOG.md](BACKLOG.md); each of the six pillars reaches its **v1 bar** ([NERVA_VISION.md](NERVA_VISION.md) §10); parked modules unfreeze per phase |
| **→ 1.0** | **2a AND 2b complete** | "Owned & proven" becomes "**the governed Personal AI OS — owned & proven**" | Both gates met + owner legal/brand done + manual-test/audit pass → tag |
| **3 — Sellable / ecosystem** | Hosted Pro + multi-user + moderated marketplace → post-1.0 (v1.x → v2.0) | Hosted tier, first revenue; others build *on* Jarvis; households/teams not just Andrei | Paid conversion measured; multi-user + signed marketplace + 3rd-party A2A/widget adoption |

> Phase boundaries are **release gates**, not suggestions. We are at **v0.11.0**. The version
> number *is* the roadmap: **1.0 is a real destination**, not the current state. **Decision
> (owner, 2026-07-11):** the 1.0 gate *expanded* — the full AI-OS capability vision (the former
> "v3.0 ambition", including the Hermes-integration/superiority goal) was pulled **into** 1.0,
> and the owner accepts this moves the tag out by roughly a year. The proof track (2a) is not
> displaced: B0, the soak and design partners remain the critical path and run in parallel.
> Manual testing/audit is the *post-tag proof of the tagged build*, not a gate item (owner directive 2026-08-28: the tag is the A5 license flip then the tag; the §0 run proves the build — ordering confirmed 2026-09-01). Rationale
> + provenance: [decision log](docs/HISTORY.md) ·
> [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md).

> **The substrate program — ORIZONT 24 "AI-OS" (decided 2026-06-23):** productionization isn't
> only a checklist of fixes; it's earning the word *operating*. The bridge from feature-complete (v0.10) to
> a **provable** 1.0 is one **Action Kernel** (every agent action mediated, budgeted, revocable) + a
> **Verification Fabric** (each capability proven against reality before it may claim "done"), with the four
> live capability packs deepened on top. The Capability Registry (ORIZONT 27) **extends** O24's V2
> registry — one system, not two. Full program, tracks (K/V/P) and gates:
> [BACKLOG.md → ORIZONT 24](BACKLOG.md).

---

## 5. Non-Negotiable Principles (the guardrails)

These override convenience, deadlines, and clever ideas. A change that violates one of these is
wrong even if it ships faster.

1. **Local-first by default** — core functionality never *requires* the cloud. `frigga`, `ultron`,
   `howard` are `LOCAL_ONLY_AGENTS` and stay that way ([ARCHITECTURE.md](docs/ARCHITECTURE.md) §7).
2. **Opt-in for every cloud hop** — no agent leaves the machine without an explicit, auditable toggle.
3. **Inspectable & forgettable** — the user can see, edit, and delete any fact about themselves (H8.2).
4. **Proactive, not noisy** — autonomy escalates reversible work silently; interrupts are budgeted
   (≤4 urgent push/day). We optimize for *fewer, better* decisions, not more notifications.
5. **Production-grade, not demo-grade** — every feature ships with tests; the hot path stays off the
   event loop; failures degrade gracefully (recall never hard-fails).
6. **Your data trains no one's model** — anonymization and local processing are defaults, not upsells.
7. **Capability growth is governed** — Jarvis may acquire new skills and integrations only through
   the sandbox → verification → approval → registry path ([NERVA_VISION.md](NERVA_VISION.md) §6, ORIZONT 32);
   unrestricted self-modification is out, permanently. A capability's autonomy is *earned* per the
   graduated-autonomy ladder (NERVA_VISION §7), never assumed — and money/locks/security actions
   never rise above the approval queue.

---

## 6. North-Star Metric & Health Signals

- **North-star:** **weekly autonomous actions accepted per active user** — it captures the whole
  thesis at once (the system is *used*, it's *proactive*, and the user *trusts* its judgment).
- **Counter-metrics (guardrails against gaming the north-star):**
  - interrupt rate (push/day) — must stay within budget; rising = we got noisy.
  - reject rate of proposed actions — rising = trust/quality eroding.
  - % tasks served locally vs cloud — falling = drifting off local-first.
  - p95 per-turn latency (non-LLM) — must stay flat as we add features.
- **Commercial signals (Phase 2+):** self-host installs, hosted paid conversion, NRR, gross margin
  (model in [VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) §6, §9).
- **Now instrumented:** the north-star + all four counter-metrics are computed in one place
  (`agents/core/observability/north_star.py`) and exposed read-only at `GET /api/metrics/north-star`.
  Field definitions and the single-user (n=1) honesty caveat: [docs/METRICS.md](docs/METRICS.md).
- **Capability health (supporting signal, not a replacement):** count of registry capabilities at
  **VERIFIED** (the O24 V2 ladder) — the AI-OS program's progress meter. It must rise *without*
  the counter-metrics above degrading; capability growth that makes Jarvis noisier or less local
  is failure, not progress.

---

## 7. Keeping On Track — Operating Rhythm & Governance

The moonshot is only real if day-to-day work bends toward it. This section is the contract between
*vision* (this doc) and *execution* (the operational docs).

### 7.1 Cadence

| Rhythm | Activity | Source of truth |
|--------|----------|-----------------|
| **Per task / PR** | Pick the next item by priority; follow conventions; ship with tests; update docs touched | [BACKLOG.md](BACKLOG.md), [AGENTS.md](AGENTS.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **Per release gate** | Verify the phase gate in §4 is met before tagging a version | [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md) launch checklist |
| **Periodic review** | "What's next / priorities / backlog?" → re-rank against the moonshot; archive done work | [BACKLOG.md](BACKLOG.md) → [docs/HISTORY.md](docs/HISTORY.md) |
| **Drift check** | When a decision feels off-mission, test it against §1 (the bet), §3 (thesis), §5 (principles) | this doc |

### 7.2 Which doc answers which question

| When you're deciding… | Read… |
|-----------------------|-------|
| *Where are we going / is this on-mission?* | **MOONSHOT.md** (this file) — §1, §3, §5 |
| *What is the full AI-OS capability vision / where is pillar X?* | [NERVA_VISION.md](NERVA_VISION.md) — pillars, architecture, registry, the Hermes bar |
| *What should I work on next?* | [BACKLOG.md](BACKLOG.md) — priorities, story points, horizons |
| *Are we ready to ship v1.0?* | [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md) — launch checklist |
| *Where does this code live / how do I change it?* | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module index, recipes |
| *How should I build it (conventions, workflow)?* | [AGENTS.md](AGENTS.md) — assistant + contributor rules |
| *What's the high-level architecture / stack?* | [NERVA.md](NERVA.md) |
| *What did we already deliver?* | [docs/HISTORY.md](docs/HISTORY.md) |
| *What's the current snapshot?* | [STATUS.md](STATUS.md) |
| *What's it worth / how do we price & fund it?* | [docs/VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) |
| *Where are the gaps to 1.0?* | [docs/gap-analysis-1.0.md](docs/gap-analysis-1.0.md) (proof track) + [NERVA_VISION.md](NERVA_VISION.md) §4 (capability gaps) |

### 7.3 Definition of "on track"

A change is on track when **all** hold:
- [ ] It advances the current phase gate in §4 (or fixes something that blocks it).
- [ ] It respects every principle in §5 (especially local-first + opt-in cloud).
- [ ] It ships with tests and updates any doc it makes stale ([AGENTS.md](AGENTS.md) convention).
- [ ] It does not regress a counter-metric in §6 (latency, interrupt rate, % local).
- [ ] The relevant operational doc (§7.2) is updated so the next contributor isn't surprised.

### 7.4 Decision log

Significant strategic decisions (license choice, hosted-vs-self-host, pricing changes, dropping a
principle) are recorded in [docs/HISTORY.md](docs/HISTORY.md) with date + rationale, so the moonshot
has an audit trail and future contributors understand *why*, not just *what*.

---

## 8. Doc Map (the canon)

| File | Role relative to the moonshot |
|------|-------------------------------|
| **MOONSHOT.md** | North star — *why we exist, where we're going, how we stay on track* |
| [NERVA_VISION.md](NERVA_VISION.md) | The product & capability vision — *the Nerva brand architecture (Cortex/Atlas/Synapse/Vision/Ultron), six pillars, target architecture, capability registry, graduated autonomy, the Hermes superiority bar* |
| [BACKLOG.md](BACKLOG.md) | The plan — *what's next, prioritized* |
| [GO_LIVE_PLAN.md](GO_LIVE_PLAN.md) | The launch — *features, marketing, road to 1.0* |
| [docs/VALUATION_AND_PRICING.md](docs/VALUATION_AND_PRICING.md) | The business — *value, pricing, unit economics* |
| [NERVA.md](NERVA.md) | The architecture overview |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The navigable map — *where code lives, how to change it* |
| [AGENTS.md](AGENTS.md) | The conventions — *how we build* |
| [docs/HISTORY.md](docs/HISTORY.md) | The record — *what we delivered + decision log* |
| [STATUS.md](STATUS.md) | The snapshot — *where we are right now* |
| [docs/gap-analysis-1.0.md](docs/gap-analysis-1.0.md) | The gaps — *what stands between us and 1.0* |
| [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md) | The human gate — *what only the owner can do* |
| [docs/AI_CONTEXT.md](docs/AI_CONTEXT.md) | The loading map — *how an assistant ingests this repo* |
| [docs/REVIEW_YEAR_ONE.md](docs/REVIEW_YEAR_ONE.md) | The review — *candid year-one retrospective: status, learnings, gaps, next 90 days* |
| [docs/METRICS.md](docs/METRICS.md) | The meters — *§6 north-star + counter-metric definitions and the n=1 honesty caveat* |

---

*If you only remember one sentence: **a private AI operating system that works while you sleep,
runs your world under your authority, and is owned by the person it serves.** Everything in this
repo is in service of making that real and keeping it true.*
