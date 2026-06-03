# Frontier Research — New Horizons for a Local-First Personal AI OS (2025–2026)

> Date: 2026-06-03 · Method: 5 parallel frontier-research agents + independent verification of load-bearing claims
> Scope: forward-looking — where the *field* is going, not a competitor survey. Companions:
> [2026-06-02-personal-ai-competitors.md](2026-06-02-personal-ai-competitors.md) (the category) ·
> [2026-06-02-competitor-research-h10.md](2026-06-02-competitor-research-h10.md) (dev frameworks).
> Output: **PROPUS ORIZONT 13–17** in [BACKLOG.md](../../BACKLOG.md) — 5 candidate horizons, ~20 items.

---

## TL;DR — five new horizons, two flagship themes

The product is past its feature backlog (H1–H9 shipped; H10–H12 queued). The question this research answers is *what comes after parity* — where a local-first, proactive, private AI OS should aim next. Five frontiers each map to a candidate horizon, all checked against the [non-negotiables](../../MOONSHOT.md#5-non-negotiable-principles-the-guardrails):

| Horizon | Frontier | Why now | Phase | Top priority item |
|---|---|---|---|---|
| **H13 — Local Capability Ceiling** | local models & inference | Apache-2.0 reasoning MoEs + local VLMs make new capabilities free on the home GPU | 2 | strict-local VLM tier (P1) |
| **H14 — Living Memory** | temporal & self-maintaining memory | bi-temporal KGs + self-editing memory move past static nightly RAG | 1–2 | bi-temporal KG edges (P1) |
| **H15 — Governed Computer-Use** | operate-the-machine | an open framework crossed the human baseline on OSWorld (Dec 2025) | 2–3 | local browser-use behind approval queue (P2) |
| **H16 — Agentic-Web Citizen** | interop & the agentic web | MCP + A2A settled as the two layers; agentic payments arrived | 3 | MCP server mode (P1; = H10.5) |
| **H17 — Provable Trust** | safety for always-on agents | by-design injection defenses + runnable evals exist; OpenClaw proved the anti-thesis | 1–2 | dual-LLM quarantine + AgentDojo CI (P1) |

**Two cross-cutting flagship themes the whole sweep keeps returning to:**

1. **"Sleep-time compute" — the moonshot tagline, now a research result.** Surfaced *independently* in the local-models **and** memory legs: a Letta/Berkeley paper (arXiv:2504.13171, Apr 2025) formalizes using idle time to pre-compute over context — **~5× less test-time compute, ~2.5× lower cost/query, up to +13–18% accuracy.** Jarvis already pioneers this (nightly reflection); the frontier is to generalize it from *summarize-the-day* into *pre-reason-for-tomorrow* on the idle GPU. This is the single most on-mission idea here — *"works while you sleep"* is literally the north star.

2. **Governance is now a measurable property, and OpenClaw proved why it matters.** The injection problem is accepted as unsolvable at the model layer; the field moved to **by-design containment** (CaMeL, Plan-Then-Execute, Dual-LLM quarantine) plus **runnable evals** (AgentDojo, AgentHarm, OWASP Agentic Top 10). Meanwhile OpenClaw became the **first AI agent targeted by infostealers** (Feb 13, 2026). Jarvis can convert "we're the governed alternative" from a *claim* into a *green CI badge* — the strongest possible wedge.

---

## H13 — Local Capability Ceiling (local models & inference)

**What's emerging (all 2025, all shipping):**
- **Open-weight reasoning MoEs that fit the home GPU:** **gpt-oss-20b** (Apache-2.0, 21B/3.6B-active, MXFP4, runs in 16 GB) and **Qwen3-30B-A3B** (Apache-2.0, hybrid *thinking/non-thinking* per request). Both are near-drop-in upgrades/peers to Jarvis's current ~26B/4B-active default; Qwen3's mode toggle could **collapse the fast/deep tiers into one model**.
- **Local VLMs crossed into usable screen/document understanding:** **Qwen3-VL** (Oct 2025; OCR 32 langs, UI grounding, computer-use, 256K ctx) — the 4B/8B runs on a single consumer GPU. This is the **biggest single new capability**: a strict-local vision tier (screenshots, PDFs, receipts) feeding the Howard ingestion pipeline, no cloud hop.
- **Free inference wins:** **speculative decoding** (2–3× throughput, *identical* output; native in vLLM/llama.cpp) and **constrained/structured decoding** (XGrammar/GBNF — guarantees schema-valid tool-args, kills validate-retry loops). For a multi-agent tool-calling system these are high-leverage at $0.
- **On-device fine-tuning is practical:** **Unsloth** QLoRA + **GRPO/DPO** fine-tunes 7–8B in ≤8 GB — the engine for preference learning *on-device* (the literal embodiment of "your-data-trains-no-one").

**Candidate horizon items:** strict-local VLM tier (P1) · GBNF/XGrammar default for tool-calling (P1) · speculative decoding (P2) · default-model refresh to a hybrid-reasoning MoE (P2). All ✅ local-first. *Flag:* verify the exact GGUF build + KV-cache budget before committing the VLM to the 24 GB card.

---

## H14 — Living Memory (temporal & self-maintaining memory)

Jarvis today is ~2024-era "static nightly KG + hybrid RAG." The frontier moved to **temporal, self-editing, decay-aware** memory — and most of it is Apache-2.0 and runs on the Neo4j + Ollama Jarvis already has.

- **Bi-temporal knowledge graphs — Graphiti/Zep (arXiv:2501.13956).** Every edge carries *valid-time* **and** *ingestion-time*; contradictions **invalidate** (end-date) rather than delete; updates are incremental, no batch recompute. Lets memory answer *"what did Andrei prefer as of March?"* and supersede stale facts without losing history. **The single most direct upgrade to the nightly KG** — and it runs on the existing Neo4j.
- **Self-editing consolidation — Letta (ex-MemGPT) + Mem0.** Reframe nightly reflection as a dedicated **sleep-time consolidation agent** emitting explicit **ADD/UPDATE/DELETE/NOOP** ops over de-duplicated, inspectable memory blocks — incremental and self-pruning instead of accreting near-duplicates.
- **Rigorous forgetting.** ACT-R **decay** in recall ranking (recency × frequency × relevance) + **dependency-aware deletion** to fix the documented "recontamination" failure (deleted facts reappearing from summaries). This turns *"inspectable & forgettable"* from a promise into a defensible feature.
- **Measure it.** LoCoMo/LongMemEval exist but their public scores are **vendor-disputed** → the honest move is a **Jarvis-specific memory-eval harness** over its own corpus (extraction, multi-session, temporal, knowledge-update, abstention).

**Candidate horizon items:** bi-temporal KG edges (P1) · memory-eval harness (P1, do early) · sleep-time consolidation agent w/ explicit ops (P2) · decay + dependency-aware forgetting (P2). All ✅ local-first, inspectable, forgettable. *Watch, don't adopt:* Titans/Nested-Learning (parametric test-time memory) — conflicts with "inspectable & forgettable" (weights aren't user-editable).

---

## H15 — Governed Computer-Use (operate-the-machine)

**The capability arrived in 2025:** an **open framework, Agent S3 (Apache-2.0), crossed the OSWorld human baseline (72.6% vs 72.36%) in Dec 2025** — and a **locally-hostable grounding model exists (ByteDance UI-TARS-1.5-7B, Apache-2.0)**. The lowest-risk entry is **browser-use** (MIT, 50k★), which drives any local LLM and slots into Jarvis's existing MCP + approval queue.

**But honesty about maturity:** best mainstream computer-use is still ~1-in-6 task failure (Claude Opus 4.8 ~83% OSWorld; the open SOTA leans on a cloud planner). The field consensus (OWASP Agentic Top 10, Microsoft/NVIDIA guidance, Anthropic's own docs) is exactly Jarvis's posture: **sandbox + egress allowlist + clean-OS isolation + human approval for irreversible actions.** Computer use in 2026 is *good enough to assist behind approval gates, not to run unattended* — which **validates the approval-queue-first design.**

**Candidate horizon items (the *governed* inverse of OpenClaw's ungoverned shell):** local browser-use behind the approval queue + sandbox + egress allowlist (P2, start here) · local screen-understanding module via UI-TARS (P2) · PiP isolated-virtual-desktop operator with no ambient credentials (P3) · **secret broker** that injects creds at action time, never plaintext in agent context (P2). *Flags:* OmniParser's icon detector is **AGPL** — prefer Apache-2.0 UI-TARS; cloud Claude computer-use is **opt-in only**; raw "OS mode" without the sandbox+queue is the OpenClaw failure mode — forbidden.

---

## H16 — Agentic-Web Citizen (interoperability & the agentic web)

The standards settled in 2025 into **two complementary layers**: **MCP** (agent→tools; the 2025-11-25 spec added async Tasks, OAuth 2.1 Resource-Server semantics, RFC 8707 audience-scoping, CIMD) and **A2A** (agent→agent; donated to the **Linux Foundation June 2025**, IBM's ACP merged in). **Agentic payments** arrived too — **Google AP2** (Sept 2025, signed Intent/Cart/Payment **Mandates**), Coinbase **x402**, OpenAI+Stripe **ACP** — converging on a *mandate / cap / approval* model that maps perfectly onto Jarvis's approval queue.

**Candidate horizon items:** **MCP server mode** — expose Jarvis agents as *governed* tools, LAN-only by default (P1; this is the already-queued **H10.5**, upgraded to the 2025-11 spec) · **A2A endpoint** with a signed Agent Card, opt-in + peer allowlist, inbound tasks routed through approval (P3) · **opt-in agentic payments** via a rail-agnostic mandate/cap/approval abstraction with **hard caps** and a local non-repudiable audit (P3) · **ambient inbound triggers** (webhooks/cron → escalation inbox; extends **H10.8**) (P2). *Flags:* A2A and payments are **network surfaces** — opt-in, disabled by default, governance mandatory; don't commit to a single payment rail (all beta) — adopt the *abstraction*, not the rail.

---

## H17 — Provable Trust (safety for always-on agents) — *the measurable anti-OpenClaw moat*

The most on-mission of the five for Jarvis's trust thesis. The field's consensus: **prompt injection is unsolvable at the model layer** (Simon Willison's **"lethal trifecta,"** June 2025 — private data + untrusted content + exfil channel; an email/calendar agent has all three by default). The answer is **by-design containment** + **measurement**:

- **By-design defenses:** **CaMeL** (DeepMind, arXiv:2503.18813 — plan-as-code + capabilities + data-flow tracking; drives many AgentDojo attacks to ~0) and the **"Design Patterns for Securing LLM Agents"** menu (arXiv:2506.08837 — **Plan-Then-Execute, Dual-LLM quarantine**, etc.): *once an agent ingests untrusted input, it must be structurally unable to take consequential actions.* Cheap first layer: **spotlighting/datamarking** (Microsoft).
- **Runnable evals:** **AgentDojo** (97 tasks/629 security cases; used by US+UK AISI) and **AgentHarm**, self-assessed against the **OWASP Top 10 for Agentic Applications** (Dec 9, 2025). Put these in CI → a **green "trust scorecard"** is a concrete differentiator OpenClaw can't match.
- **Governance done right:** capability gating + an **out-of-band kill-switch the agent cannot escalate** ("kill switches don't work if the agent writes the policy"); align to EU AI Act Art. 14 + the NIST Agentic Profile.
- **Verifiable audit:** extend Jarvis's Merkle chain with **external transparency-log anchoring** (Apple PCC-style) + per-action signed identity + **intent attribution** ("this send-email was driven by user goal X, not by untrusted email content Y").
- **TEEs** (NVIDIA H100/H200 confidential computing; Apple PCC as the north star) — only relevant *if* a future opt-in hosted tier is built; lets it honor "your-data-trains-no-one" *verifiably*.

**Candidate horizon items:** dual-LLM / Plan-Then-Execute quarantine for tool/web/email content (P1) · AgentDojo + AgentHarm CI gate + OWASP self-assessment (P1) · capability gating + out-of-band kill-switch (P2) · externally-anchored, intent-attributed audit (P2). All ✅ governed/inspectable/local. **The proven anti-thesis:** OpenClaw — first infostealer theft of `.openclaw` secrets Feb 13 2026, RCE CVE, ~30–42k exposed instances (93% unauthenticated), 386 malicious ClawHub skills.

---

## Verification log (independently re-checked; agents hit 403s on primary sources)

- ✅ **Agent S3 crossed the OSWorld human baseline (72.6% vs 72.36%), Dec 16 2025, open-source (~10.4k★)** — Simular; first AI to exceed it. *Caveat: headline run uses a strong cloud planner; fully-local scores lower.*
- ✅ **A2A donated to the Linux Foundation (June 23–25 2025)**; founding members AWS/Cisco/Google/Microsoft/Salesforce/SAP/ServiceNow — Google Developers Blog, Linux Foundation, SiliconANGLE.
- ✅ **Google AP2 announced Sept 16 2025**, 60+ partners (Mastercard/PayPal/Amex…), cryptographically-signed mandates — TechCrunch, Google Cloud blog.
- ✅ **OpenClaw first infostealer theft Feb 13 2026** (Vidar, `.openclaw` config) — BleepingComputer, Intel 471 (corroborates the H12 wedge).

### Flagged — adopt the *direction*, not the unverified specifics
- **Forward-dated fabrications in the search index** ("Qwen3.5/3.6/3.7," "Gemma 4," impossible arXiv IDs) were caught and **excluded**; only primary-sourced, shipping-in-2025 items are load-bearing.
- **Benchmark numbers** (CaMeL 67%, AgentDojo, LoCoMo/LongMemEval, sleep-time multipliers) are author/vendor-reported and partly behind 403s — confirm against primary PDFs before quoting externally; LoCoMo scores are actively disputed (→ build our own harness, H14).
- **Research-only (track, don't build yet):** Titans/Nested-Learning, test-time-training, agentic-unlearning, intent-attribution (AttriGuard), most 2026-dated arXiv IDs.
- **Fully-local computer-use** underperforms cloud-planner SOTA; **agent identity** is pre-standard (delegation-chain splicing is unsolved); **payment rails** are all beta.

---

## Sources (primary + reputable 2025–2026)

**Local models/inference:** github.com/openai/gpt-oss · qwenlm.github.io/blog/qwen3 · github.com/qwenlm/qwen3-vl · arxiv.org/abs/2504.13171 (sleep-time) · unsloth.ai · blog.vllm.ai (structured/spec decoding)
**Computer-use:** github.com/simular-ai/Agent-S · github.com/bytedance/UI-TARS · github.com/browser-use/browser-use · github.com/microsoft/OmniParser · arxiv.org/abs/2504.14603 (UFO²) · docs.anthropic.com (computer use)
**Memory:** github.com/getzep/graphiti + arxiv.org/abs/2501.13956 · letta.com (sleep-time agents) · arxiv.org/abs/2504.19413 (Mem0) · arxiv.org/abs/2410.10813 (LongMemEval) · arxiv.org/abs/2402.17753 (LoCoMo)
**Interop/agentic web:** modelcontextprotocol.io/specification/2025-11-25 · linuxfoundation.org (A2A) · cloud.google.com (AP2) · github.com/agentic-commerce-protocol · langchain.com (ambient agents)
**Trust/safety:** simonwillison.net/2025/Jun/16/the-lethal-trifecta · arxiv.org/abs/2503.18813 (CaMeL) · arxiv.org/abs/2506.08837 (design patterns) · github.com/ethz-spylab/agentdojo · genai.owasp.org (Agentic Top 10) · security.apple.com/blog/private-cloud-compute

---

*Method: 5 parallel frontier agents (local models · computer-use · memory/continual-learning · interop/agentic-web · trust/safety) + independent verification of the load-bearing claims. Frontier moves fast — re-check the perishable items (models, payment rails, 2026 arXiv) quarterly.*
