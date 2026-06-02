# Competitor & Product-Gap Research — Jarvis's *Actual* Category: Personal / Proactive / Private AI

> Date: 2026-06-02 · Method: deep-research (5 parallel web-search agents, adversarial verification of load-bearing claims)
> Companion to — and **deliberately disjoint from** — [2026-06-02-competitor-research-h10.md](2026-06-02-competitor-research-h10.md),
> which benchmarked Jarvis against 8 **developer frameworks** (Flowise, Langflow, CrewAI, AutoGen, SuperAGI, OpenWebUI, LangSmith, Dust).
> Output: ORIZONT 12 in [BACKLOG.md](../../BACKLOG.md) + a correction to the differentiation claim in [GO_LIVE_PLAN.md](../../GO_LIVE_PLAN.md).

---

## TL;DR — the one thing that matters

**The prior competitive analysis benchmarked the wrong category.** Jarvis's [moonshot](../../MOONSHOT.md) is *"a personal AI operating system that knows you, works while you sleep, and never sends your life to someone else's cloud."* That is the **personal / proactive / private AI assistant** category — not workflow builders. That category had **never** been analyzed. This document does it.

Three findings reshape the strategy:

1. **A direct rival now exists that the prior research missed entirely: [OpenClaw](https://github.com/openclaw/openclaw).** Born Nov 2025 (as "Clawdbot," by Peter Steinberger), it went viral (~180k stars by late Jan 2026) as a *self-hosted, always-on, local-capable* personal AI that bridges 20+ chat apps to agents that act on your machine. It is the same thesis as Jarvis. **Its fatal flaw is precisely Jarvis's design strength:** it stores secrets in plaintext, has no reversible/irreversible action governance, and ships an unmoderated skill marketplace — and is now the #1 target of infostealer malware harvesting agent `SOUL.md`/`MEMORY.md` files. *Jarvis is the governed, secure alternative to OpenClaw.* This is both a positioning wedge and a hardening mandate.

2. **The "knows-you device" market is a graveyard — which validates local-first + software-first.** Humane AI Pin (dead, HP bought assets $116M, Feb 2025), New Computer's Dot (shut down Oct 2025), Rewind/Limitless (acquired by Meta, pendant killed Dec 2025), Inflection's Pi (pivoted to B2B). Every casualty was **cloud-dependent**. The survivors that matter are **open-source + self-hostable** (OpenClaw, Khoj, Leon, Omi).

3. **The differentiation claim is still defensible but now narrowed and load-bearing.** Amazon's Bee (acquired Jul 2025) combines proactivity + memory but is **cloud**. Apple, Google, and Amazon all shipped proactive personal-memory features in 2025–2026 — all **cloud-bound** except Microsoft Recall, which is local but security-contested and hardware-locked. "No competitor combines autonomy + memory + observability + preference-learning in a *local-first* system" survives — but must be stated honestly (see §B).

---

## A. COMPETITION — the real category, ranked by relevance to the moonshot

### Positioning table

| Product | Local-first? | Proactive / autonomous? | Persistent personal memory | Privacy model | OSS? | Price | Status |
|---|---|---|---|---|---|---|---|
| **OpenClaw** | ◐ local-capable (Ollama); cloud optional | ✅ always-on orchestrator across 20+ chat apps | ◐ `SOUL.md` + Mem0/Qdrant (vector, not KG) | self-host; **plaintext secrets (broken)** | ✅ custom lic. | free | viral, ~180k★, **security crisis** |
| **Khoj** | ✅ self-host + Ollama | ◐ *user-scheduled* automations only | ◐ vector RAG over docs (not KG, no nightly consolidation) | self-host local; cloud no-train | ✅ AGPL-3.0 | free / $30 mo cloud | active, 34.8k★, YC W24 |
| **Amazon Bee** | ❌ cloud | ✅ drafting email / scheduling on your behalf | ✅ daily recaps/insights | cloud; "delete after processing" | ❌ | $50 device (Amazon-owned) | **acquired by Amazon Jul 2025** |
| **Leon AI** | ✅ self-host + local LLM (2.0) | ◐ 2.0 adds "agentic loop + proactive pulse" (pre-release) | ◐ "layered memory" (design) | self-host, privacy-first | ✅ MIT | free | active daily, 17.3k★ |
| **Omi (ex-Friend)** | ◐ cloud default, local LLM optional | ◐ summaries/notifications, not an actor | ✅ searchable memories, "brain map" | cloud or local; SOC2/HIPAA claims | ✅ MIT | ~$70 device | active, 12.7k★ |
| **Saner.ai** | ❌ cloud | ✅ proactive email/task/calendar triage | ✅ KG + semantic search | cloud | ❌ | free / $8 / $16 mo | active (markets as *"Your Jarvis"*) |
| **Pieces.app** | ✅ on-device "nanomodels" | ◐ surfaces context, feeds tools via MCP | ✅ 9-month passive workflow capture | **local by default; never trains; SOC2 II** | ❌ (SDKs open) | free / $14 mo | active, enterprise-ready |
| **Apple Intelligence / "personalized Siri"** | ◐ on-device + Private Cloud Compute | ◐ announced (on-screen awareness, in-app actions) — **not shipped** | ◐ "personal context" index — **not shipped** | on-device + PCC; **now Gemini-powered** | ❌ | free w/ device | **delayed to spring 2026** |
| **Microsoft Recall** | ✅ on-device (NPU), encrypted | ◐ passive screenshot timeline | ✅ visual timeline of everything on screen | local but **contested** (TotalRecall exploits) | ❌ | free on Copilot+ PC | GA ~Apr 2025, hardware-locked |
| **Google Gemini "Personal Intelligence"** | ❌ cloud (Nano on-device for some) | ✅ proactive over Gmail/Photos/YouTube/Search | ✅ "Memory" recalls past chats + account data | cloud / Google-account | ❌ | free / $19.99 mo | shipped ~Jan 14 2026 |
| **Amazon Alexa+** | ❌ cloud | ✅ agentic actions (order, book, schedule) | ✅ "remember that Laura is vegetarian" | cloud (AWS) | ❌ | $19.99 mo / **free for Prime** | US GA Feb 4 2026 |
| **Local-voice refs** (Home Assistant Voice PE, Willow, Jan.ai, GPT4All) | ✅ fully local | ❌ reactive | ❌ none/limited (RAG-over-docs at best) | strong local | ✅ | free / $59 HW | reference points, not direct rivals |

Legend: ✅ yes · ◐ partial/qualified · ❌ no.

### The competitors that matter most

**1. OpenClaw — the direct rival (and the cautionary tale).**
Same thesis as Jarvis: self-hosted, always-on, local-capable, persistent memory, acts on your behalf. Where it differs is governance: it can run arbitrary shell commands, stores API keys/OAuth tokens in plaintext Markdown/JSON, and ships a community skill marketplace ("ClawHub") with malicious entries. By Feb 2026, security firms (Cisco, Bitsight, Intel 471, Malwarebytes, VirusTotal, BleepingComputer) documented the **first in-the-wild infostealer (Vidar) harvesting OpenClaw `SOUL.md`/`MEMORY.md`** — "the transition from stealing browser credentials to harvesting the souls of personal AI agents." **Jarvis's reversible/irreversible approval queue, guardrails, PII scanner, and sandbox are the answer to exactly this.** Counter-position; do not copy.

**2. Khoj — closest on personal memory + automations.** The most mature *document* second-brain in the open-source camp: ingests PDF/Markdown/Notion/org-mode, clients for Obsidian/Emacs/desktop/WhatsApp, Ollama support, scheduled "automations." But its memory is **vector RAG, not a knowledge graph**, automations are **user-scheduled, not self-originated**, and it has no autonomy/approval/preference-learning loop. Jarvis's KG + nightly consolidation + autonomy is genuinely ahead here; Khoj's ingestion breadth and client polish are ahead of Jarvis.

**3. Amazon Bee — the closest *combined* contender (but cloud).** A $50 wearable Amazon acquired (Jul 2025) and is turning into a "proactive second brain" that drafts emails and schedules meetings. It combines proactivity + memory + recaps — missing only **local-first**. **The single threat to watch:** if Amazon ever ships on-device Bee processing, the local-first moat narrows to it alone.

**4. Leon AI — the ideological twin.** MIT-licensed, committing daily, 2.0 explicitly adds an "agentic loop, layered memory, self-model, and a *bounded proactive pulse*" — almost a paraphrase of Jarvis's autonomy queue. Pre-release and unproven, but validates the thesis and is more permissively licensed.

**5. Omi — closest local-first wearable.** MIT, ~$70, persistent memory, partial proactivity — but cloud-by-default and a passive capture device, not an autonomous actor, with no documented preference-learning loop.

**Reference points (not direct rivals) Jarvis should learn from:** **Pieces.app** (on-device nanomodels, no-train guarantee, multi-surface passive capture — the gold standard for local-first memory), **Home Assistant Voice PE** ($59 local voice hardware + the Wyoming protocol), **Willow** (satellite-mics → home-GPU inference-server topology), **Jan.ai** (one-click local-model UX + MCP in a GUI), **GPT4All** (frictionless folder→RAG), **Tana** (user-queryable structured KG).

---

## B. RESEARCH GAPS — where our analysis is blind or stale

1. **Wrong category benchmarked.** [GO_LIVE_PLAN §3](../../GO_LIVE_PLAN.md) and the H10 doc compare Jarvis to 8 *developer frameworks*. None is in Jarvis's category. A buyer choosing a *personal AI* never shortlists Jarvis against LangSmith — they shortlist it against Khoj, OpenClaw, Apple/Google/Amazon assistants. **All marketing comparisons should be re-anchored to this report's category.**

2. **OpenClaw was missed.** The single most relevant competitor of 2026 — same thesis, viral, self-hosted — does not appear anywhere in the repo. It launched Nov 2025; the H10 doc (this same date) omits it. Blind spot now closed.

3. **The differentiation claim is overstated as written.** Current claim: *"No competitor combines autonomy + memory + observability + preference learning in a single local-first system."* **Honest version:** *"No **shipping consumer** product combines autonomy, persistent memory, observability, and preference-learning in a **local-first** system. The closest combined product, Amazon's Bee, is cloud-based; the closest local-first option, open-source Omi, is a passive capture tool with no preference-learning loop; the viral local-capable rival, OpenClaw, has no action-governance or observability and a broken security model."* The wedge is the **intersection + governance + observability**, not any single axis.

4. **"Platform parity vs OpenJarvis" (ORIZONT 11) is too narrow.** It treats one ancestor as the yardstick. The real parity gaps are vs **Khoj** (ingestion/clients), **Jan** (local-model UX), **Home Assistant** (voice hardware + Wyoming), **Pieces** (multi-surface capture).

5. **Preference-learning is an *under-claimed* strength.** No competitor *documents* an explicit feedback/learning loop ("stops asking after N approvals"). This is genuinely rare and should be foregrounded — but it is currently asserted, not benchmarked/measured. Tie it to the north-star metric.

6. **Fast-moving threats to monitor (re-check quarterly):** Amazon **Bee** (on-device?), Apple **personalized Siri** (ships spring 2026, Gemini-powered), Google **Personal Intelligence** (cloud, very capable), and **OpenClaw**'s trajectory (does it ever fix governance?).

---

## C. PRODUCT IMPROVEMENTS — prioritized, source-tied, principle-checked

Each idea is tied to a real category competitor and checked against the [non-negotiable principles](../../MOONSHOT.md#5-non-negotiable-principles-the-guardrails). Full backlog items in [BACKLOG.md → ORIZONT 12](../../BACKLOG.md).

| # | Improvement | Borrowed from | Principle check | P |
|---|---|---|---|---|
| 1 | **Security hardening as the headline feature** — encrypt secrets at rest (no plaintext `SOUL`/memory), signed/sandboxed skills, surface the reversible/irreversible approval queue as the anti-OpenClaw story | OpenClaw's failures | ✅ all (esp. production-grade) | **P0** |
| 2 | **One-step "drop a folder → private doc chat" onboarding** | GPT4All LocalDocs, Khoj | ✅ local-first, inspectable | **P1** |
| 3 | **User-queryable / editable knowledge-graph UX** (the KG as a first-class, forgettable surface = H8.2) | Tana supertags | ✅ inspectable & forgettable | **P1** |
| 4 | **Wyoming protocol support** — interoperate with cheap Voice PE satellites & the HA local-voice ecosystem | Home Assistant, Rhasspy | ✅ local-first | **P1** |
| 5 | **Behavior preview / dry-run for autonomy** — show what an action *would* do before approving the pattern (also closes the observability gap) | Dust config preview | ✅ proactive-not-noisy, inspectable | **P2** |
| 6 | **Incremental (not only nightly) KG updates** — surface new memory same-session | Mem, Tana | ✅ proactive | **P2** |
| 7 | **Opt-in multi-surface passive capture** (browser/clipboard/files → KG), local-only | Pieces nanomodels, Omi | ⚠️ **must be opt-in + inspectable** | **P2** |
| 8 | **Satellite-mics → home-GPU inference-server split** | Willow / WIS | ✅ local-first | **P2** |
| 9 | **Polished local-model management UX** (browse/download/switch in HUD) | Jan.ai | ✅ local-first | **P2** |
| 10 | **Hardware/clear mute + strict-local indicator** in HUD & voice | Voice PE physical mute | ✅ inspectable, opt-in | **P2** |
| 11 | **Broaden escalation channels** beyond Telegram (WhatsApp/Signal/Slack/Discord) — *governed*, unlike OpenClaw | OpenClaw multi-channel | ✅ proactive (keep governance) | **P2** |
| 12 | **Curated, signed skill marketplace** (the moderated anti-ClawHub) | OpenClaw ClawHub (done safely) | ⚠️ must be moderated/signed | **P3** |
| 13 | **Opt-in E2E-encrypted cross-device sync** (home GPU ↔ phone) | Reflect / Limitless confidential cloud | ⚠️ must be E2E + opt-in | **P3** |
| 14 | **Ship a small purpose-tuned agentic model** (router/tool tasks) | Jan-nano | ✅ local-first, $0 COGS (overlaps H11.3) | **P3** |

### Flagged as violating non-negotiables — do NOT build

- **OpenClaw-style ungoverned shell + plaintext secrets + unmoderated marketplace** — violates *production-grade* and privacy. Counter-position, never copy.
- **Cloud-default passive capture** (Bee/Limitless model) — violates *local-first*. Capture only locally + opt-in (#7).
- **Training a hosted model on user data** (Personal.ai's cloud PLM) — violates *your data trains no one*. Local-only fine-tuning is fine; never upload (#14).

---

## Verification log (independently re-checked, not just agent-reported)

Both the personal-memory and big-tech research legs hit HTTP 403 on WebFetch for primary domains, so the most load-bearing/surprising claims were re-verified by direct search:

- ✅ **Meta acquired Limitless (ex-Rewind) on 2025-12-05**; pendant sales halted, screen/audio capture disabled 2025-12-19, EU/UK cut off. — TechCrunch, Neowin, WinBuzzer
- ✅ **Apple–Google deal (~$1B/yr) to power a Gemini-based Siri**, announced 2026-01-12; personalized Siri slipped to iOS 26.4 (spring 2026). — CNBC, AppleInsider
- ✅ **Amazon Alexa+ US GA 2026-02-04, $19.99/mo or free for Prime.** — CNBC, MacRumors, aboutamazon.com
- ✅ **OpenClaw is real, viral (~180k★, the 376k figure is inflated/contested), and the documented #1 infostealer target**, harvesting `SOUL.md`/`MEMORY.md`. — Cisco, Bitsight, Intel 471, Malwarebytes, VirusTotal, BleepingComputer
- ✅ **Humane Pin dead (HP, $116M, Feb 2025); Dot shut down Oct 2025; Pi pivoted to B2B** (graveyard thesis). — TechCrunch, Fortune

### Lower-confidence / monitor
- Khoj exact tier pricing (secondary sources; pricing page 403'd).
- Mem 2.0 "agentic execution" (review sites, not a primary changelog).
- Bee/Omi/Friend/Martin **preference-learning loops** — none documents one; scrutinize before claiming superiority.
- GitHub star/release figures for Jan/GPT4All/Ollama (rate-limited; approximate). Willow figures were API-verified.

---

## Sources (primary + reputable 2025–2026 reporting)

**Open-source rivals:** github.com/openclaw/openclaw · github.com/khoj-ai/khoj + docs.khoj.dev · github.com/leon-ai/leon + blog.getleon.ai · github.com/BasedHardware/omi · github.com/openinterpreter/open-interpreter + /01 · github.com/menloresearch/jan + jan.ai · github.com/nomic-ai/gpt4all
**OpenClaw security:** blogs.cisco.com/ai · bitsight.com/blog · intel471.com/blog · malwarebytes.com/blog · blog.virustotal.com · bleepingcomputer.com
**Personal memory:** limitless.ai + techcrunch.com/2025/12/05 · personal.ai · get.mem.ai · saner.ai · pieces.app + docs.pieces.app · reflect.app · techcrunch.com (Tana $25M)
**Big tech:** security.apple.com/blog/private-cloud-compute · cnbc.com/2026/01/12 (Apple-Gemini) · learn.microsoft.com (Copilot Memory) + theregister.com (Recall) · blog.google (Gemini Personal Intelligence) · aboutamazon.com + cnbc.com/2026/02/04 (Alexa+)
**Local voice/home:** home-assistant.io/voice-pe · github.com/HeyWillow/willow · github.com/rhasspy/rhasspy3 · ollama.com
**Graveyard:** techcrunch.com/2025/02/18 (Humane/HP) · techcrunch.com/2025/09/05 (Dot) · techcrunch.com/2025/07/22 (Amazon/Bee)
**Category framing:** blog.langchain.com/introducing-ambient-agents/

---

*Method note: 5 parallel research agents (one per angle: open-source AI, personal-memory AI, big-tech proactive, local voice/home, emerging always-on agents + claim verification), then independent re-verification of the load-bearing claims above. Treat fast-moving items (Bee, Siri, OpenClaw) as perishable — re-check quarterly.*
