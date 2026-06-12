# Competitive Brief — Jarvis Hub vs. the personal-AI field

> The honest, sourced competitive picture for marketing + sales + positioning. Distilled from the
> repo's own deep research ([`docs/research/2026-06-02-personal-ai-competitors.md`](../../docs/research/2026-06-02-personal-ai-competitors.md),
> [`docs/research/2026-06-04-privacy-first-gtm.md`](../../docs/research/2026-06-04-privacy-first-gtm.md))
> and `GTM_PLAN.md`. Use this to write comparisons, answer "how are you different from X?", and
> stay out of fights we lose.
> **Perishable:** the assistant market moves fast — re-verify dated claims quarterly before any
> public use. Last synced 2026-06-11.

---

## 1. The one-sentence position

**Jarvis Hub is the *governed* alternative to OpenClaw** — and the *local-first* alternative to
Bee / Alexa+ / Gemini. It owns an intersection no shipping product holds:
**local + multi-agent + persistent memory + governed autonomy + observability + family privacy.**

Say it as a sentence, not a feature list: *"The always-on AI agent everyone wanted in 2026 —
with the governance, audit, and privacy the viral one was missing."*

---

## 2. Category framing (get this right or every comparison is wrong)

Jarvis is **not** a developer framework. Do **not** benchmark it against LangChain, Flowise,
CrewAI, AutoGen, LangSmith — a person choosing a *personal AI* never shortlists those. The real
category is **personal / proactive / private AI assistants**, and the real shortlist is below.

> ⚠️ If you find an old comparison table pitting Jarvis vs. 8 dev frameworks (it exists in
> `GO_LIVE_PLAN.md` §3, flagged), **don't reuse it for buyer-facing copy.** Use this brief instead.

---

## 3. The field, ranked by relevance

### Tier 1 — the rivals that define the conversation

**OpenClaw** — *the direct rival and the cautionary tale.*
Same thesis as Jarvis: self-hosted, always-on, local-capable, acts on your behalf. Went viral in
2026 (~180k★; the ~377k figure is inflated). **Its fatal flaw is our design strength:** plaintext
secrets, no reversible/irreversible governance, an unmoderated skill marketplace ("ClawHub") — and
by Feb 2026 it became the **#1 infostealer target**, with in-the-wild malware (Vidar) harvesting
users' agent `SOUL.md`/`MEMORY.md` files. *This is our single most powerful contrast.*
- **How we win:** approval queue + tamper-evident audit log + encrypted secrets + signed/sandboxed
  skills + kill-switch + a family agent that never touches the internet. Enforced in code, proven by tests.
- **Where they're ahead:** raw virality, breadth of chat-app bridges, mindshare.
- **The line:** *"Jarvis Hub is OpenClaw with brakes, a seatbelt, and a flight recorder."*

**Amazon Bee** — *the closest combined contender, but cloud.*
A $50 wearable Amazon acquired (Jul 2025), becoming a "proactive second brain" that drafts email
and schedules. Combines proactivity + memory + recaps — **missing only local-first.**
- **How we win:** it's Amazon's cloud and Amazon's business model; your day goes to their servers.
  Ours runs on your GPU, $0/month, your data trains no one.
- **The threat to watch:** if Amazon ever ships *on-device* Bee, the local-first moat narrows to it
  alone. Monitor quarterly.

**Khoj** — *closest on personal memory, in the OSS camp.*
The most mature open-source "second brain": ingests PDF/Notion/org-mode, Obsidian/Emacs/desktop/
WhatsApp clients, Ollama support, scheduled automations. AGPL, ~35k★, YC W24.
- **How we win:** its memory is **vector RAG, not a knowledge graph**; automations are
  **user-scheduled, not self-originated**; no autonomy/approval/preference-learning loop. Our
  nightly KG consolidation + governed autonomy is genuinely ahead.
- **Where they're ahead, be honest:** ingestion breadth and client polish. (Cloud tier deprecating
  Apr 2026 — a proof point for our "don't bet on hosted-AI subs" stance, not a dunk.)

### Tier 2 — big-tech proactive assistants (all cloud-bound)

**Apple "personalized Siri"** (delayed to spring 2026, now Gemini-powered), **Google Gemini
Personal Intelligence** (shipped Jan 2026, cloud, very capable), **Amazon Alexa+** (US GA Feb 2026,
$19.99/mo or free for Prime). All combine proactivity + memory — **all cloud-bound.**
- **How we win, uniformly:** they require trusting a hyperscaler with your private context, by
  architecture. We don't. The pitch isn't "more capable than Google" — it's *"the capability that
  doesn't require giving Google your life."*
- **Don't fight on:** raw model horsepower, breadth of integrations, polish. We lose those. Fight on
  ownership, privacy-by-architecture, governance, and cost.

**Microsoft Recall** — local (on-device NPU) but security-contested (TotalRecall-class exploits),
hardware-locked to Copilot+ PCs, and passive (a screenshot timeline, not an actor). A useful foil:
*"local isn't enough — it has to be local AND governed."*

### Tier 3 — ideological kin & reference points (learn from, rarely fight)

**Leon AI** (MIT, the ideological twin — 2.0 adds an "agentic loop + proactive pulse"; pre-release),
**Omi** (MIT ~$70 wearable, persistent memory but cloud-default + passive capture, no preference
loop), **Pieces.app** (the gold standard for on-device memory + no-train guarantee — a reference,
not a rival), **Home Assistant Voice PE / Willow / Jan.ai / GPT4All** (local-voice & local-model
references we interoperate with, e.g. Wyoming protocol).

---

## 4. The comparison table (buyer-facing — safe to publish)

| | **Jarvis Hub** | OpenClaw | Amazon Bee | Khoj | Apple/Google/Alexa+ |
|---|:---:|:---:|:---:|:---:|:---:|
| Runs on your hardware (local-first) | ✅ | ◐ | ❌ | ✅ | ❌ |
| Proactive / acts for you | ✅ | ✅ | ✅ | ◐ | ✅ |
| Persistent personal memory | ✅ KG + nightly | ◐ vector | ✅ | ◐ vector | ✅ |
| **Governed autonomy** (approval queue) | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Tamper-evident audit log** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Strict-local family agent** | ✅ | ❌ | ❌ | ❌ | ❌ |
| Preference learning ("stops asking") | ✅ | ❌ | ◐ | ❌ | ◐ |
| Open / self-hostable | ✅ | ✅ | ❌ | ✅ | ❌ |
| Price | **$0/mo** | free | $50 dev | free/$ | $0–20/mo |

Legend: ✅ yes · ◐ partial/qualified · ❌ no. *The three bold rows are ours alone — lead with them.*

---

## 5. Objection handling (sales + comment-section ready)

| They say… | We say… |
|---|---|
| *"Isn't local AI just worse than GPT/Gemini?"* | Hybrid by design — local for the 99% of daily tasks at $0, with an explicit, auditable per-agent cloud escalation for the heavy 1%. You don't trade capability for privacy; you choose per task. |
| *"OpenClaw does this and it's free."* | And it's the #1 infostealer target of 2026 — plaintext secrets, no action governance. We're the same thesis with the security model it skipped: approval queue, encrypted secrets, audit log, signed skills. |
| *"Why not just use Alexa+/Gemini? It's easier."* | Easier because it's their cloud and their business. Your calendar, email, and family data live on someone else's servers and feed someone else's model. Ours runs on your machine, $0/month, trains no one. |
| *"Is a solo/open project safe to depend on?"* | It's open and inspectable — every action audited, every fact editable/deletable, self-hostable so you're never locked in. The security model is the product, not an afterthought. |
| *"Setup sounds hard."* | One-click `INSTALL.bat` / `install.sh`; it installs everything and runs the test suite to prove it. First screen guides you to load a model. |

---

## 6. Lines NOT to cross (honesty discipline — the brand depends on it)

- **Don't claim to out-capability Google/Apple's models.** We don't, and saying so invites a fight
  we lose. Win on ownership + governance + cost.
- **Don't claim "only X in the world."** The honest, defensible form: *"No **shipping consumer**
  product combines autonomy + persistent memory + observability + preference-learning in a
  **local-first** system."* (Bee is cloud; Omi is passive; OpenClaw is ungoverned.)
- **Don't dunk on OpenClaw's users** — they wanted the right thing. Reference the security crisis as
  a *dated, sourced* cautionary tale, never as FUD.
- **Don't publish a stat that isn't in `BACKLOG.md` / `DESIGN_BRIEF.md` §5.** Stale numbers on a
  comparison graphic are a brand bug.

---

## 7. Threats to monitor (re-check quarterly)

1. **Amazon Bee on-device** — the one move that narrows our moat to itself.
2. **Apple personalized Siri** ships (spring 2026, Gemini-powered) — capable, but cloud + closed.
3. **Google Personal Intelligence** — already shipped, very capable, cloud.
4. **OpenClaw fixing governance** — if it ever does, our wedge narrows; watch its trajectory.

> Sourcing & verification log for every dated claim above:
> [`docs/research/2026-06-02-personal-ai-competitors.md`](../../docs/research/2026-06-02-personal-ai-competitors.md) §Verification log.
