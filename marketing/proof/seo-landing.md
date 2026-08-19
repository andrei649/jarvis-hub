# SEO landing content — Jarvis Hub

> **Purpose:** search-optimized copy and metadata for the public landing surface
> ([`marketing/landing/index.html`](../landing/index.html)). This is the *content spec* — the
> owner/site owns final layout and voice. Copy spine: [`docs/marketing/TEASER_PACK.md`](../../docs/marketing/TEASER_PACK.md);
> voice/tokens: [`docs/BRAND_BOOK.md`](../../docs/BRAND_BOOK.md); positioning:
> [`marketing/competitive-brief/COMPETITIVE_BRIEF.md`](../competitive-brief/COMPETITIVE_BRIEF.md).
> **Honesty discipline applies** — no claim beyond what ships or is core-built; owner/host-gated
> features are described as such. **Perishable** — re-verify quarterly. Last synced 2026-07-11.

---

## Target keywords (intent-ranked)

| Priority | Keyword / phrase | Search intent | Why we can rank honestly |
|---|---|---|---|
| P1 | local-first personal AI assistant | evaluators wanting privacy | true core — runs on your hardware |
| P1 | self-hosted AI assistant | homelab / privacy buyers | one-click `install.sh` / `INSTALL.bat`, self-hostable |
| P1 | private AI assistant no cloud | privacy-first buyers | `LOCAL_ONLY_AGENTS`, on-device VLM |
| P2 | governed AI agent / AI with approval queue | safety-conscious | Action Kernel — irreversible actions held for approval |
| P2 | OpenClaw alternative | rival's users post-security-crisis | governance is our design strength |
| P2 | getjarvis alternative local | namesake searchers | same UX thesis, local-first + governed |
| P3 | AI second brain knowledge graph | memory-focused | KG + nightly consolidation, not just vector RAG |
| P3 | multi-agent personal assistant | power users | 18-agent cabinet |

Avoid bidding/optimizing for "better than GPT/Gemini" — a fight the brief says we lose. Rank on
ownership, privacy-by-architecture, governance, and $0 cost.

---

## Page metadata

- **Title tag** (≤60 chars): `Jarvis Hub — Local-First, Governed Personal AI`
- **Meta description** (≤155 chars): `The always-on personal AI that runs on your hardware — governed
  autonomy, an audit log, and a knowledge-graph memory. $0/mo, your data trains no one.`
- **Canonical H1:** `The personal AI that lives on your machine, not someone's cloud.`
- **Subhead:** `Proactive and multi-agent — with the governance, audit log, and privacy the viral
  always-on assistants skipped.`
- **Open Graph / Twitter:** reuse title + description; image is the owner-captured HUD hero (M4,
  real data or clearly badged demo mode — see [`marketing/landing/demo-shot-list.md`](../landing/demo-shot-list.md)).

---

## Section outline (H2s → proof)

1. **What it is** — always-on, local-first, multi-agent personal AI you self-host.
2. **Why local-first** — data never leaves device/LAN; $0/mo; trains no one.
3. **Governed, not just capable** — approval queue + tamper-evident audit log + strict-local family agent.
   *(These three are ours alone — brief §4.)*
4. **Remembers like a brain** — knowledge graph + nightly consolidation + preference learning that
   stops re-asking.
5. **The last mile, closing** — floating-bar command service, one-hotkey screen reflex, and SaaS
   connectors: **cores built** (offline, tested); OS host overlay, screen-capture, and OAuth are the
   owner-gated wiring. *(Describe honestly — do not show as live.)*
6. **How it compares** — link to [`competitor-comparison.md`](competitor-comparison.md).
7. **Get started** — one-click install; first screen guides you to load a local model.

---

## FAQ (schema-ready — grounded in the brief's objection handling)

**Q: Is my data sent to the cloud?**
No. Jarvis Hub runs on your hardware; local-only agents never make network calls, and the family
agent never touches the internet. Cloud escalation for heavy tasks is explicit, per-agent, and audited.

**Q: How is it different from getjarvis.eu / OpenClaw?**
Same always-on thesis, opposite architecture. getjarvis.eu is cloud SaaS that holds your data and the
model keys; OpenClaw ships without action governance. Jarvis Hub is local-first and governed — approval
queue, encrypted secrets, audit log — with the brain running on your machine.

**Q: Is local AI worse than GPT or Gemini?**
It's hybrid: local for the 99% of daily tasks at $0, with an explicit, auditable cloud escalation for
the heavy 1%. You choose per task instead of trading capability for privacy.

**Q: What does it cost?**
$0/month to run — it uses your hardware. Optional cloud escalation uses your own API keys if you enable it.

**Q: Can I self-host it?**
Yes — one-click `install.sh` / `INSTALL.bat`; it's open and inspectable, so you're never locked in.

---

## Honesty guardrails for whoever ships the page

- Every capability shown as "live" must be shipped, not owner-gated. Floating bar / screen reflex /
  connectors = "core built, host wiring pending," never "available now."
- No proof-point number that isn't in `BACKLOG.md` / `DESIGN_BRIEF.md` §5.
- The hero image uses real HUD data or clearly badged demo mode — never a fabricated screenshot.
- Keep the "no *shipping consumer* product, *local-first*" superlative form; don't upgrade it to
  "only one in the world."
