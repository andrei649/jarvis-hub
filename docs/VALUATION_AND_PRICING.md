# Jarvis Hub — Project Valuation & Subscription Pricing

> Generated: 2026-06-02 · Stage: v0.9.1-beta (pre-1.0, pre-revenue) · Owner: Andrei
> Companion to [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) and [BACKLOG.md](../BACKLOG.md)
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

*See also: [GO_LIVE_PLAN.md](../GO_LIVE_PLAN.md) (features + marketing brief),
[BACKLOG.md](../BACKLOG.md) (roadmap), [docs/ARCHITECTURE.md](ARCHITECTURE.md) (technical map).*
