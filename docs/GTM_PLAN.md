# GTM Plan — Jarvis Hub (privacy-first launch)

> **Status:** draft v1 · **Date:** 2026-06-04 · **Owner:** Andrei
> **Evidence base:** [`docs/research/2026-06-04-privacy-first-gtm.md`](research/2026-06-04-privacy-first-gtm.md) (5-angle cited research). This doc is the *action* layer — the report is the *why*.
> **Phase context:** this is the bridge from MOONSHOT Phase 1 (Complete & Trustworthy) → Phase 2 (Sellable). It does **not** change the product roadmap (`BACKLOG.md`); it sequences the launch.

## North-star positioning

> **"The governed OpenClaw."** A local-first, multi-agent personal AI that runs on your own hardware and **acts** for you — but every autonomous action passes through an approval queue and a tamper-evident audit log, with full observability, and a family agent that never touches the internet.

The market proved the demand (OpenClaw ~377k★ in 6 months) and proved the gap (the Feb-2026 OpenClaw infostealer; 65% of orgs hit by an AI-agent incident). Jarvis owns the intersection nobody else does: **local + multi-agent + persistent memory + governed autonomy + observability + family privacy.**

## ICP (sequence — do not try to serve all four at once)

| # | Persona | When | Why |
|---|---|---|---|
| 1 | **Homelab Hank** (self-hoster) + **Founder Felix** (privacy-dev) | **Launch** | Reachable (r/LocalLLaMA, HN, GitHub), willing, technical, amplifiers |
| 2 | **Privacy-first Priya** (non-CLI, packaged) | After 1-click install lands | Largest pool; needs zero-config |
| 3 | **Counselor Carla** (regulated pro) | After compliance/turnkey appliance | Highest willingness-to-pay; needs trust/compliance proof |

## Pricing v1 (decision)

- **Free / self-host: $0**, open-core — full app, bring-your-own model. *Never gate core local features.*
- **Hosted Pro: ~$10/mo** (~2 months off annual) — managed relay + **E2E cross-device sync** + remote access + backups + hosted inference credits. Sits in the proven privacy-convenience band ($5–13/mo) and deliberately **below** the $19–30 AI tier that churned.
- **Pro+ / Power: $18–20/mo** (later) — higher inference quotas / premium models / early access.
- **Support / Team / Commercial** (later) — $50–100/yr support or $6–19/seat (SSO, audit, commercial assurance).
- **⚠️ Hard rule from the evidence:** do **not** bet the model on hosted-AI subscriptions — Khoj Cloud (deprecating Apr 2026) and Rewind/Limitless (Meta, Dec 2025) both died there. Monetize **convenience + sync + support**, keep self-host first-class. Base case **3% free→paid**.

## Messaging to test

- **Proof-points to lead with (ranked):** (1) *runs on your GPU; nothing leaves by default; the family agent never touches the internet* (architectural, not a promise); (2) *open-source + every tool call in a tamper-evident audit log* (auditable trust); (3) *governed autonomy — approval queue + kill-switch* (the post-incident differentiator); (4) *$0/month, no data business*.
- **Endorse hybrid** explicitly (local default + optional cloud escalation) — kills the "is local good enough?" objection.
- **Lead with "it just works"** — friction is the #1 adoption killer; the one-command/one-click install is existential, not cosmetic.
- **Taglines to A/B** (specific vs emotional — the one trade-off the research couldn't resolve for our ICP):
  - B (spine): *"17 agents. One system. Your data stays home."*
  - A (hook, governance-qualified): *"17 agents working while you sleep — one system, every action logged, your data never leaves home."*

## Launch checklist (top 3 channels, fired together for GitHub star velocity)

**Pre-launch (T-4 to T-1 weeks)**
- [ ] README = landing page: **demo GIF above the fold**, one-command/one-click install, crisp what/why, screenshots.
- [ ] One-command install genuinely works on a clean machine (test on Win + Linux). *(INSTALL.bat / START.bat already exist — verify the cold-start path.)*
- [ ] "Secure by default" is real and demoable: no exposed gateway port, encrypted secrets, kill-switch (the OpenClaw-infostealer lesson) — and say so.
- [ ] Build HN/Reddit credibility (90/10 rule: ≥90% genuine participation). Read each subreddit's promo rules.
- [ ] Seed 2–3 technical YouTubers (NetworkChuck / Matthew Berman / Matt Williams tier) + newsletters (Ben's Bites, TLDR) with early access.
- [ ] Stand up a Discord (ready to open day one).
- [ ] Record a 60–90s demo: *"watch it do a real task — and watch me approve the one irreversible step."*

**Launch day (early in the week; founder free for ~4h)**
- [ ] **Show HN:** `Show HN: Jarvis Hub — a governed, local-first multi-agent assistant` → link the **GitHub repo**, not a marketing page. Work the comments live (agree-then-address, humble, lean OSS/privacy).
- [ ] **r/LocalLLaMA** post (value-first; what it does + why governed/local; GitHub link + `docker-compose` + hardware/stack). Answer every comment.
- [ ] **r/selfhosted** (+ r/homelab) post, tailored (not a cross-post).
- [ ] Watch GitHub star velocity; target ~200+/24h for the all-languages trending list.

**Post-launch (the flywheel)**
- [ ] Convert the spike → Discord members; open a public changelog; keep building in public.
- [ ] Encourage/seed YouTube tutorials (durable long-tail).
- [ ] Ship weekly; respond to every issue — durable winners "kept shipping in public."

## Metrics (the only 3 that matter at launch)

1. **GitHub star velocity** (stars/24–48h around launch) — leading adoption indicator.
2. **Activation rate** = % of installs that complete first-agent-run + connect a model — directly measures whether the friction risk is beaten.
3. **Free → Hosted-Pro conversion** (target 3%) — validates willingness-to-pay for convenience.

## Open questions → primary research (close the evidence gaps)

- [ ] Short survey in r/LocalLLaMA + r/selfhosted: WTP for a hosted Pro tier, and the "concerned → willing to self-host" conversion (no public data exists).
- [ ] 5–10 design-partner interviews, incl. **2–3 regulated professionals** (legal/medical/finance) to validate the high-WTP expansion + compliance asks.
- [ ] Decide the open-core license boundary (what's free vs Pro/commercial) before launch — see AnythingLLM/Khoj (AGPL) and Open WebUI (BSD + branding clause) as references.

## Risks to watch (from §7 of the research)

frontier "good enough?" doubt · setup friction · the hosted-AI-subscription trap · enterprise OSS-share decline (different buyer) · **the local agent's own security** (don't become the next OpenClaw-infostealer headline) · solo-dev sustainability · Big Tech absorbing the category (move on the governance + family-privacy + open-source wedge they structurally won't).

---
*Re-confirm fast-moving figures before any public/marketing use — see the research report's "Confidence, gaps & what to re-verify."*
