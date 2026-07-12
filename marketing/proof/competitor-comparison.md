# Jarvis Hub vs. the field — buyer-facing comparison

> **Purpose:** a public, publishable comparison for the landing page, sales replies, and
> "how are you different from X?" questions. Grounded in the repo's own research —
> [`docs/research/2026-06-25-getjarvis-competitive-gap.md`](../../docs/research/2026-06-25-getjarvis-competitive-gap.md),
> [`docs/research/2026-06-02-personal-ai-competitors.md`](../../docs/research/2026-06-02-personal-ai-competitors.md) —
> and the positioning in [`marketing/competitive-brief/COMPETITIVE_BRIEF.md`](../competitive-brief/COMPETITIVE_BRIEF.md).
> **Honesty discipline applies** (brief §6): no stat that isn't in `BACKLOG.md`; owner/host-gated
> capabilities are marked, never implied as live; we win on ownership + governance + cost, not on
> out-capability-ing Google/Apple.
> **Perishable** — the assistant market moves fast; re-verify dated claims quarterly before public use.
> Last synced 2026-07-11.

---

## The one-sentence position

**Jarvis Hub is the *local-first, governed* alternative to the always-on personal AI** — the brain
(privacy, governance, agentic depth, persistent memory) that the polished cloud front-ends skip.

Honest, defensible superlative: *"No **shipping consumer** product combines governed autonomy +
persistent memory + observability + preference-learning in a **local-first** system."* (Bee is cloud;
Omi is passive; OpenClaw is ungoverned; getjarvis.eu is cloud SaaS.)

---

## Head-to-head: getjarvis.eu ("Jarvis AI") — the namesake

Same name, **different kind of product**. getjarvis.eu wins the *last mile* (signature floating-bar UX,
distribution, SaaS-connector breadth, freemium funnel). We win the *brain* (privacy, governance,
multi-agent depth, local LLM/VLM). None of their advantages require us to rebuild our core — they are
packaging and go-to-market, most of it already seeded and now partly built.

| | **getjarvis.eu** | **Jarvis Hub** |
|---|---|---|
| Shape | Monetized consumer **cloud SaaS** + thin native overlay | **Self-hosted, local-first agentic OS** (single-user) |
| Where your data lives | Uploaded to their EU cloud (GDPR, AES-256-GCM, no-train **claimed**) | On your device/LAN — never leaves (`LOCAL_ONLY_AGENTS`, on-device VLM) |
| Floating bar + global hotkey | ✅ shipped, signature UX | ◐ **command-service core built** (`quickbar.py`, offline); OS host overlay owner-gated |
| One-hotkey screen reflex | ✅ shipped end-to-end | ◐ **capture→VLM→answer core built** (`screen_reflex.py`); screen-grab + hotkey owner-gated |
| SaaS connectors | ✅ 30+ OAuth, live | ◐ **request-builders built** for Linear/Asana/Trello/Todoist/ClickUp/Sheets/M365 (`writeback_connectors.py`); owner OAuth setup gated |
| Governed autonomy (approval queue) | ❌ | ✅ Action Kernel — irreversible actions held for approval |
| Tamper-evident audit log | ❌ | ✅ |
| Strict-local family agent | ❌ | ✅ never touches the internet |
| Persistent memory | ✅ preferences/context | ✅ **knowledge graph + nightly consolidation** (not just vector RAG) |
| Model routing | Cloud only (they hold the keys) | **Local-first hybrid** — local for the 99%, explicit auditable per-agent cloud escalation for the heavy 1% |
| Price | Free (15 req/wk) · Pro ~$16/mo · Unlimited ~$32/mo | **$0/mo** — runs on your hardware |

Legend: ✅ shipped/live · ◐ partial or core-built-but-host-gated · ❌ absent.

**The honest line:** *"They productized the front door; we built the brain — and we're closing the
last mile without giving up local-first."* The floating-bar, screen-reflex, connector, and
desktop-control **cores now exist in the codebase** (offline, tested); what remains is the owner-gated
host wiring (OS overlay, screen-capture permission, OAuth setup), not new invention.

---

## The wider field

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

The three **bold** rows are ours alone — lead with them. (Table mirrors `COMPETITIVE_BRIEF.md` §4.)

---

## Objection handling (comment-section ready)

- **"Isn't local AI just worse than GPT/Gemini?"** — Hybrid by design: local for the 99% of daily
  tasks at $0, with an explicit, auditable per-agent cloud escalation for the heavy 1%. You choose
  per task; you don't trade capability for privacy.
- **"getjarvis.eu / OpenClaw already does this."** — getjarvis is their cloud, holding your data and
  the model keys; OpenClaw is the #1 infostealer target of 2026 (plaintext secrets, no action
  governance). We're the same thesis with the security model they skipped — approval queue, encrypted
  secrets, audit log, signed skills — and the brain runs on *your* machine.
- **"Why not just use Alexa+/Gemini? It's easier."** — Easier because it's their cloud and their
  business model. Your calendar, email, and family data feed someone else's model. Ours trains no one.
- **"Is a solo/open project safe to depend on?"** — It's open and inspectable: every action audited,
  every fact editable/deletable, self-hostable so you're never locked in.

---

## Lines NOT to cross (from the brief §6 — the brand depends on it)

1. Don't claim to out-capability Google/Apple's models. Win on ownership + governance + cost.
2. Don't claim "only X in the world" — use the defensible "no *shipping consumer* product, *local-first*" form.
3. Don't imply owner/host-gated capabilities are live. The floating bar, screen reflex, and connectors
   have **cores built, host wiring pending** — say exactly that.
4. Don't publish a stat that isn't in `BACKLOG.md`. Stale numbers on a comparison graphic are a brand bug.
5. Reference OpenClaw's security crisis as a *dated, sourced* cautionary tale, never as FUD, and never
   dunk on its users — they wanted the right thing.
