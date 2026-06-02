# Jarvis Hub — Project Valuation & Subscription Pricing

> Generated: 2026-06-02 · Stage: v0.9.1-beta (pre-1.0, pre-revenue) · Owner: Andrei
> North star: [MOONSHOT.md](../MOONSHOT.md) · Companion to [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) and [BACKLOG.md](../BACKLOG.md)
>
> **Disclaimer:** These are estimates for internal planning, not a formal appraisal or
> investment advice. Numbers are scenario ranges based on the codebase as it stands today
> (solo-built beta, no external users, no revenue). Currency: figures given in EUR with USD
> in parentheses (~1.08 FX).

---

## 1. What's Actually Built (the asset)

| Dimension | Measure |
|-----------|---------|
| Python source | ~35,200 LOC across 216 files |
| Frontend (vanilla React + CSS) | ~9,850 LOC |
| Tests | 909 passing, 81 test files (backend); frontend 0% |
| Agents | 15 active + 15 bench, 4 tiers |
| Channels | 7 (web, voice, Telegram, Discord, Slack, email, sandbox) |
| Plugins / integrations | 20 |
| Skills | 13 |
| Subsystems | Orchestrator, hybrid memory (vector ⊕ graph RRF), autonomy cortex, workflow DAG engine, observability/trace, security/guardrails, voice pipeline, MCP client |
| Maturity | Feature backlog H1–H7+H9 at ~100%; hardening (H7 propus) + personal memory (H8) pending for v1.0 |

This is a **substantial, coherent technical MVP** — well beyond a prototype. The differentiators
(local-first + 24/7 autonomy + fused memory + preference learning + observability in one system)
are genuinely uncommon. The gaps that cap value today are **commercial, not technical**: zero users,
no revenue, single-person/key-person risk, no CI/CD or license, frontend untested, single-user validation only.

---

## 2. Valuation — Four Lenses

Pre-revenue software has no single "price." Here are four defensible framings, from most
conservative (what it's worth as code today) to most optimistic (what it could raise as a startup).

### Lens A — Replacement / Cost-to-Rebuild (most objective)

What would it cost to rebuild this from scratch with a competent team?

- ~45K LOC of non-trivial code (orchestration, ML/RAG, async infra, 20 integrations, 909 tests).
- Realistic effort: **9–15 senior person-months** for a strong full-stack + ML engineer (AI-assisted).
- Loaded monthly cost: €6–10k (RO/EU senior) to $10–15k (US contractor).

**Replacement cost: €90k–180k (~$100k–200k).** This is the "engineering value already created."

### Lens B — Asset / Code Sale, As-Is (what a buyer pays today)

A buyer of the codebase (no team, no users, no revenue) discounts heavily for key-person risk,
unproven market fit, missing license/CI, and handover cost.

**As-is asset value: €20k–70k (~$22k–75k)** — typically 20–40% of replacement cost for
unproven, solo-built IP.

### Lens C — Current Fair Enterprise Value (DCF view)

With zero revenue and no users, a discounted-cash-flow / market-multiple valuation rounds to
**~€0 enterprise value today.** The only defensible "today" number is the IP value from Lens B.
This is the honest answer to "what is it worth right now as a business": the code is worth
something; the business is worth what the IP is worth.

### Lens D — Venture / Pre-Seed Potential (if pursued as a startup)

*This is potential, contingent on founder commitment, incorporation, first users, and a clean license.*

- Pre-revenue AI-agent startups with a strong technical MVP + committed founder raise pre-seed at
  **€1M–4M post-money** (EU; US/SV higher), driven by team and narrative, not current revenue.
- Realistic for a **solo technical founder** with this MVP and early traction (a few hundred
  self-host installs or a design-partner): **€1M–2.5M post-money** at pre-seed.
- Without a second founder/commercial co-founder and early users, the lower bound applies or
  the round doesn't happen.

### Summary

| Lens | Range | Reading |
|------|-------|---------|
| A — Replacement cost | **€90k–180k** | Engineering value created |
| B — Asset sale (as-is) | **€20k–70k** | What a buyer pays today |
| C — Current EV (DCF) | **~€0 + IP** | Honest "today as a business" |
| D — Pre-seed potential | **€1M–2.5M** | *If* turned into a funded startup |

**Bottom line:** as a *product today* it's worth its IP (~€30–70k). As a *foundation for a
venture*, the upside is 1–2 orders of magnitude higher — but that value is unlocked by traction,
not more code.

---

## 3. Monetization Model

The product is **local-first / self-hostable**, which shapes how to charge. The proven pattern for
this category (n8n, OpenWebUI, GitLab, Supabase) is **open-core**:

- **Free, self-hosted core** — drives adoption, community, trust ("your data stays home").
- **Paid hosted/managed tier** — convenience (no GPU, no setup) for those who won't self-host.
- **Paid commercial license + support** — for businesses self-hosting at scale.
- **Cloud-LLM credits** — pass-through + margin for users without a local GPU.

Revenue is **not** mainly per-token (most compute is local at $0); it's **subscription for hosting,
multi-user, support, and advanced/enterprise features.**

---

## 4. B2C — Consumer / Prosumer Plans

Target: privacy-conscious individuals, self-hosters, prosumers, families. Anchors: ChatGPT Plus /
Claude Pro at ~$20/mo; but Jarvis's edge is *ownership + autonomy*, not raw model quality.

| Plan | Price | Who | Includes |
|------|-------|-----|----------|
| **Community** (self-host) | **€0** | Tinkerers, privacy maximalists | Full open-core: all 15 agents, 7 channels, memory, autonomy, workflows. Bring your own GPU + API keys. Community support. |
| **Personal** | **€9 / mo** (€90/yr) | Prosumer who self-hosts but wants more | Mobile PWA + push, premium voice (XTTS/ElevenLabs bridge), priority updates, small monthly cloud-LLM credit pool, email support. |
| **Pro** | **€19 / mo** (€190/yr) | Power user, no local GPU | Managed/hosted instance (we run the GPU), larger cloud-LLM credits, all integrations, autonomy cortex + daily briefs, 1 workspace. |
| **Family** | **€29 / mo** (€290/yr) | Households | Up to 5 members, Frigga strict-local family memory, shared household views, per-member profiles, parental scope controls. |

**Notes**
- Free → paid conversion lever is **convenience (hosting) and mobile/voice polish**, not gating core agents.
- Cloud-LLM credits billed as pass-through + ~20% margin above the included pool.
- Annual = ~2 months free (standard SaaS discount) to improve cash flow and retention.

---

## 5. B2B — Team / Business / Enterprise Plans

Target: SMB teams, agencies, and privacy/compliance-sensitive orgs that want an on-prem agent
platform. Anchors: Dust.tt (~€29–40/user/mo), LangSmith (~$39/user/mo), CrewAI/n8n enterprise (custom).

| Plan | Price | Who | Includes |
|------|-------|-----|----------|
| **Team** | **€39 / user / mo** (min 3 seats) | Small teams, agencies | Shared workspace, visual workflow builder, multi-agent pipelines, trace explorer + observability, role basics, standard support. |
| **Business** | **€99 / user / mo** *or* €1,500/mo flat (≤25 seats) | Growing companies | On-prem / VPC deploy, SSO, audit log + guardrails (PII/injection), MCP server mode, cost analytics, write-back integrations, priority support + SLA (next-business-day). |
| **Enterprise** | **Custom** (from ~€30–80k/yr) | Regulated / large orgs | Self-hosted commercial license, dedicated support + SLA (4h), custom agents/SOUL tuning, eval/regression harness, data-residency guarantees, security review, onboarding/training, optional managed ops. |

**B2B value drivers (what justifies the premium over B2C)**
- **Data sovereignty / on-prem** — the core wedge; many orgs can't send data to OpenAI/Anthropic.
- **Observability + eval** — trace explorer, offline eval, cost-per-agent (H7.10/H9.x/H10.A).
- **Governance** — guardrails, audit (Merkle chain), action-level approval, RBAC/data-spaces.
- **Extensibility** — MCP server mode (agents-as-tools), webhooks, write-backs, custom workflows.

**Pricing mechanics**
- Per-seat for Team/Business; **flat-rate option** for small teams who dislike per-seat math.
- Enterprise priced on value (data sovereignty + support + SLA), not seats — annual contracts.
- Offer a **14-day Team trial** and a **design-partner discount** (50–70% off year 1) for the first
  3–5 reference customers to seed case studies.

---

## 6. Illustrative Revenue Scenarios (Year 1, post-1.0)

Rough, for sanity-checking — not forecasts.

| Scenario | B2C Pro/Family | B2B Team/Business | Approx. ARR |
|----------|----------------|-------------------|-------------|
| **Conservative** | 100 paid @ ~€15 avg | 3 teams (~15 seats) @ €39 | ~€18k + ~€7k = **~€25k** |
| **Base** | 500 paid @ ~€16 avg | 10 teams (~70 seats) @ ~€50 avg | ~€96k + ~€42k = **~€140k** |
| **Optimistic** | 2,000 paid @ ~€17 avg | 30 accounts (~250 seats) + 2 enterprise | ~€408k + ~€150k + ~€100k = **~€660k** |

Even the base case meaningfully changes Lens C/D: with ~€140k ARR and growth, a SaaS multiple
(4–8× ARR for early-stage) implies **€560k–1.1M** — i.e., traction is what converts the
"potential" valuation into a real one.

---

## 7. Recommendations / Next Steps to Unlock Value

The fastest path from "~€50k of IP" to "fundable/sellable asset" is **commercial proof, not features**:

1. **Ship v1.0 gate** — CI/CD, hermetic tests, LICENSE + CONTRIBUTING, docker-compose one-command
   self-host (H7.1/H7.2/H7.9). A clean OSS license is a prerequisite for *any* monetization.
2. **Pick the license deliberately** — open-core (e.g., permissive core + commercial features) vs
   AGPL + commercial dual-license. This decision gates the whole B2B model.
3. **Stand up hosted Pro** — the single biggest B2C conversion lever (removes the GPU/setup barrier).
4. **Land 3–5 design partners** for B2B Team/Business at a discount → case studies + reference ARR.
5. **Instrument cost/usage analytics** (H7.10) so B2B customers can see ROI and you can price on value.
6. **Track the metrics investors/buyers want** — installs, WAU, paid conversion, NRR, logo list.

---

## 8. Hosting Cost Simulation — 100 / 1,000 / 1,000,000 Users

> **Key framing:** Jarvis is **local-first**. A self-hosted (Community) user costs us **$0** —
> their GPU, their electricity. The costs below apply only to the **hosted/managed (Pro)** subset
> where *we* run the inference. This is a worst-case "100% hosted" model.

### 8.1 Assumptions (stated so they can be challenged)

| Assumption | Value | Rationale |
|------------|-------|-----------|
| Engaged hosted user demand | ~20 interactive queries/day × ~1,500 output tokens + 1 nightly reflection (~2k) ≈ **32k output tok/day** (~960k/mo) | Proactive system; autonomy probes are cheap (no LLM), reflection is 1 call/night |
| GPU model | ~26B MoE (4B active), batched on a 24–48GB GPU (L40S / 4090 / 5090-class) | Current stack (LM Studio dual-slot) |
| GPU throughput | **~50M output tok/day sustained** per GPU (conservative; batched vLLM-class can exceed this) | Leaves headroom for prefill + latency |
| Peak concurrency | ~2% of users in-flight at peak; **~25 concurrent streams/GPU** at good UX | Daytime peak sizing |
| GPU unit cost | Rented community **$0.80/hr (~$585/mo)** · reserved **$0.50/hr (~$365/mo)** · **owned + colocated amortized ~$95/mo** (HW over 3yr + power + colo) | Rent at small scale, own at hyperscale |
| Cloud-LLM fallback | ~10% of heavy queries → Claude/Gemini ≈ **$0.10/user/mo** (own deep-tier GPUs cut this at scale) | Athena / heavy-reasoning escalation (H7.5 tiering) |

### 8.2 GPU sizing (two independent methods agree)

| Scale | Tokens/day | By throughput (÷50M) | Peak concurrent (2%) | By concurrency (÷25) | **GPUs provisioned** (peak + redundancy) |
|-------|-----------|----------------------|----------------------|----------------------|------------------------------------------|
| 100 | 3.2M | 0.06 | 2 | 0.1 | **1** (heavily underutilized) |
| 1,000 | 32M | 0.64 | 20 | 0.8 | **2** |
| 1,000,000 | 32B | 640 | 20,000 | 800 | **~1,000** |

### 8.3 Monthly cost stack

| Component | 100 users | 1,000 users | 1,000,000 users |
|-----------|-----------|-------------|-----------------|
| GPU inference | $585 (1 rented) | $730 (2 reserved) | **$95k** (1,000 owned+colo) |
| App / orchestration / channels / autonomy | $40 | $100 | $30k |
| Databases (Postgres + Qdrant + Neo4j) | $60 | $350 | $50k |
| Object storage (logs, embeddings, checkpoints) | $1 | $30 | $6k |
| Bandwidth / egress | $15 | $50 | $15k |
| Cloud-LLM fallback (Claude/Gemini) | $10 | $100 | $30k–100k* |
| Monitoring / backups / SRE tooling | $15 | $120 | $20k |
| **Total infra / month** | **~$725** | **~$1,500** | **~$250k–320k** |
| **Cost per user / month** | **~$7.30** | **~$1.50** | **~$0.25–0.32** |

\* Swing factor: serving the heavy tier on your *own* larger GPUs (vs paying Claude/Gemini per token)
is the difference between ~$30k and ~$100k/mo at 1M scale.

**Why per-user cost collapses with scale:** at 100 users one GPU sits ~6% utilized (you pay for a
whole GPU to serve almost nobody). At 1,000 users the GPUs fill up. At 1M you **own** the hardware
(amortized ~$95/mo/GPU vs ~$365 rented), batch at high utilization, and fill nightly valleys with
reflection jobs — so marginal cost per user drops ~25× from the 100-user case.

### 8.4 Break-even fee and recommended price

| Scale | Infra cost/user | Break-even fee | At **€19 Pro** price | Gross margin |
|-------|-----------------|----------------|----------------------|--------------|
| 100 | ~$7.30 | **~$8/mo** | €19 (~$20) | ~60% |
| 1,000 | ~$1.50 | **~$2/mo** | €19 | ~92% |
| 1,000,000 | ~$0.30 | **~$0.40/mo** | €19 | ~98% |

- **Minimum sustainable hosted price ≈ $8–10/user/mo** (set by the 100-user / cold-start case,
  not steady state). The €9 **Personal** tier only works if those users **self-host the GPU** and
  we just supply hosting glue + cloud credits; fully-managed users need the **€19 Pro** price.
- Above ~1,000 hosted users, €19 Pro is **highly profitable on infra** (>90% gross margin) — which
  is exactly why the open-core + hosted model works: free self-host drives adoption at $0 to us,
  and the hosted minority funds the company at fat margins.

### 8.5 The caveat that dominates at scale: **people, not servers**

Infra is the *easy* cost. The real monthly burn at scale is **payroll + support + G&A**:

| Scale | Infra/mo | Realistic team / opex /mo | True cost to "run all that" /mo |
|-------|----------|---------------------------|---------------------------------|
| 100 | ~$0.7k | Founder(s), ~$0–15k | **~$1k–16k** |
| 1,000 | ~$1.5k | Small team (3–5), ~$40–70k | **~$42k–72k** |
| 1,000,000 | ~$0.3M | SRE + support + eng + G&A (50–150 staff), **~$0.7M–2M** | **~$1M–2.3M** |

At 1M users the **$250–320k of servers is dwarfed by ~$1–2M of humans.** A 1M-user hosted base at
€19 Pro (even at 5–10% paid conversion = 50k–100k payers) generates **~€1M–1.9M/mo revenue** — i.e.,
the model closes, but only because infra is cheap (local-first MoE) and self-host carries the free tier.

### 8.6 One-line answers

- **100 users:** ~**$725/mo** to run (~$7.30/user). Price floor ~$8 → charge €19 Pro.
- **1,000 users:** ~**$1,500/mo** (~$1.50/user). €19 Pro ≈ 92% margin.
- **1,000,000 users:** ~**$250k–320k/mo** infra (~$0.30/user), but ~**$1M–2M/mo** all-in with staff.
  €19 Pro fully funds it at modest paid conversion.

> All figures assume the *hosted* path. Push users to **self-host (Community, $0 to us)** and the
> infra line for that cohort disappears entirely — the strategic reason local-first is also a
> cost-of-goods advantage.

---

## 9. Blended Base — the Realistic Mix (80% self-host / 20% hosted)

The §8 numbers are worst-case (100% hosted). In reality a local-first product converts most users to
self-host. Modeling **80% Community (free, self-host) / 20% Pro (€19, hosted)**:

- **Community 80%** → **$0 infra, $0 revenue** (their GPU, their power).
- **Pro 20%** → bears all GPU cost, pays €19/mo.

**GPUs are sized only for the hosted 20%**, so the whole infra bill shrinks ~5× vs §8.

| Total users | Hosted (20%) | GPUs needed | **Blended infra/mo** | Revenue/mo (20%×€19) | Net (infra only) |
|-------------|--------------|-------------|----------------------|----------------------|------------------|
| 100 | 20 | 1 (min) | ~$725 | ~$410 | **−$315** (cold-start loss) |
| 1,000 | 200 | 2 | ~$1,150 | ~$4,100 | **+$2,950** (~72% margin) |
| 1,000,000 | 200,000 | ~200 owned | ~$76k | ~$4.1M | **+$4.0M** (~98% gross margin) |

| Metric | 100 | 1,000 | 1,000,000 |
|--------|-----|-------|-----------|
| Infra **per total user** | ~$7.25 | ~$1.15 | **~$0.08** |
| Revenue **per total user** | ~$4.10 | ~$4.10 | ~$4.10 |
| Gross margin | negative | ~72% | ~98% |

### 9.1 Reading the blend

- **Revenue/total-user is flat (~€3.80)** — it's just `20% × €19`. **Infra/total-user collapses**
  from $7.25 → $0.08 as the hosted cohort fills GPUs and you switch to owned hardware.
- **Cross-over is ~150–200 hosted users** (≈750–1,000 total). Below that, one underutilized GPU
  makes the hosted line lose money — fund the cold-start phase from B2B/savings, or use **serverless
  GPU** (per-second billing) until the cohort fills a dedicated GPU.
- **At 1M the infra bill is ~$76k/mo** — trivially covered by ~$4.1M/mo of Pro revenue. The binding
  constraint becomes **people (~$1–2M/mo)**, not servers (see §8.5).

### 9.2 A richer 3-tier funnel (adds Personal payers)

If some self-hosters pay **€9 Personal** (their GPU, we supply cloud-LLM credits + mobile/voice):
e.g. **72% Community / 8% Personal / 20% Pro** →

- Revenue/total-user rises to **~€4.52** (`8%×€9 + 20%×€19`).
- Added cost is only **~$0.12/total-user** of cloud credits (no GPU) — funded by the €9 fee.
- Net effect: **+€0.72/user revenue at ~98% margin** on the Personal cohort. B2B Team/Business
  (§5) stacks on top as additional high-margin revenue on the *same* hosted GPU fleet.

### 9.3 Bottom line

> The blended model is the real business: **free self-host drives adoption at $0 COGS, a ~20% hosted
> minority funds everything at 70–98% gross margin once past ~1k users.** The only money-losing zone
> is cold-start (<~750 users on a single underutilized GPU) — bridge it with serverless GPU and B2B
> design-partner revenue.

---

*See also: [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) (features + marketing brief),
[BACKLOG.md](../BACKLOG.md) (roadmap), [docs/ARCHITECTURE.md](ARCHITECTURE.md) (technical map).*
