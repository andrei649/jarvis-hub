# Campaign Plan — Jarvis Hub v1.0 launch

> The executable launch playbook: audiences, message ladder, channel-by-channel plan, a T-minus
> timeline, and the metrics that decide success. Action layer for [`docs/GTM_PLAN.md`](../../docs/GTM_PLAN.md)
> (the strategy) and [`docs/research/2026-06-04-privacy-first-gtm.md`](../../docs/research/2026-06-04-privacy-first-gtm.md)
> (the evidence). Copy to drop in: [`../content/CONTENT_CALENDAR.md`](../content/CONTENT_CALENDAR.md).
> Draft v1 · 2026-06-11.

---

## 1. Campaign goal (one number)

**Beat the friction risk and earn star-velocity.** Primary success = **GitHub star velocity**
(~200+ stars / 24h around launch → all-languages trending) **plus an activation rate** (installs
that complete first-agent-run + connect a model) high enough to prove "it just works." Revenue is a
Phase-2 question — this launch sells *trust and adoption*, not subscriptions.

---

## 2. Audiences (sequenced — do NOT serve all at once)

| Wave | Persona | Where they are | The message that lands |
|------|---------|----------------|------------------------|
| **Launch** | **Homelab Hank** (self-hoster) + **Founder Felix** (privacy-dev) | r/LocalLLaMA, r/selfhosted, HN, GitHub, X | "Local-first, governed, $0/month, open. Acts for you — every action audited." |
| **+weeks** | **Privacy-first Priya** (non-CLI, wants packaged) | YouTube tutorials, newsletters, word of mouth | "It just works — one click, no terminal. Your data never leaves home." |
| **+months** | **Counselor Carla** (regulated pro) | LinkedIn, professional communities, direct | "Provable governance + audit trail for client-confidential work." |

Wave 1 is technical, reachable, and amplifies. Win them first; they carry waves 2–3.

---

## 3. Message ladder (one spine, three altitudes)

**Spine:** *The AI that works while you sleep — owned by the person it serves.*

1. **Hook (3s):** "Your AI shouldn't live in someone else's cloud."
2. **Proof (15s):** 17 agents, on your hardware, proactive, governed — approval queue + tamper-evident
   audit log, family agent never touches the internet, $0/month.
3. **Story (60s):** the BUG-14 catch — the family agent *could* have reached the cloud; we caught it
   pre-launch and made it impossible by construction, with a test. *That's what governed means here.*

**The four ranked proof-points** (from the GTM research — lead with #1):
1. Runs on your GPU; nothing leaves by default; the family agent never touches the internet *(architectural, not a promise)*.
2. Open-source + every tool call in a tamper-evident audit log *(auditable trust)*.
3. Governed autonomy — approval queue + kill-switch *(the post-OpenClaw-incident differentiator)*.
4. $0/month, no data business.

> **Always endorse hybrid explicitly** (local default + optional, auditable cloud escalation) — it
> kills the "is local good enough?" objection before it's raised.

---

## 4. Channel plan (Wave 1 — fired together for star velocity)

**Show HN** — the anchor.
- Title: `Show HN: Jarvis Hub — a governed, local-first multi-agent AI assistant`
- Link the **GitHub repo**, not a marketing page. Founder free ~4h to work comments live:
  agree-then-address, humble, lean OSS/privacy. Post early in the week.

**r/LocalLLaMA** — value-first, technical.
- Lead with what it does + the local/governed architecture; include GitHub + `docker-compose` +
  hardware/stack. Answer every comment. Respect the 90/10 self-promo rule.

**r/selfhosted (+ r/homelab)** — tailored, not a cross-post. Emphasize self-host, audit log, $0/mo.

**X / Mastodon** — the 5-post teaser arc (see content calendar), launch-day reveal post, then live
amplification of the HN/Reddit threads.

**Seeded (pre-launch):** 2–3 technical YouTubers (NetworkChuck / Matthew Berman / Matt Williams
tier) + newsletters (Ben's Bites, TLDR) with early access. Discord stood up, ready to open day one.

---

## 5. T-minus timeline

**T-4 to T-1 weeks — pre-launch (the make-or-break is friction + the demo)**
- [ ] README *is* the landing page: **demo GIF above the fold**, one-click install, crisp what/why, screenshots. (The first-run onboarding banner now guides new users — verify it on the cold-start.)
- [ ] One-command install genuinely works on a clean Win + Linux machine (cold-start path).
- [ ] "Secure by default" is real + demoable: no exposed gateway port, encrypted secrets, kill-switch — and say so.
- [ ] Record the 60–90s demo: *"watch it do a real task — and watch me approve the one irreversible step."* (Script in [`../../docs/marketing/TEASER_PACK.md`](../../docs/marketing/TEASER_PACK.md) §3.)
- [ ] Produce the OG/social image + three-pillars card (specs in [`../../docs/marketing/DESIGN_BRIEF.md`](../../docs/marketing/DESIGN_BRIEF.md)).
- [ ] Apply repo metadata (description + topics from BRAND_BOOK §9); enable code scanning (kills CodeQL noise).
- [ ] Seed YouTubers + newsletters; stand up Discord; schedule the teaser arc.

**Launch week — the teaser arc (5 posts, T-5 → T-1 days)**
- Post 1 premise → 2 proactivity → 3 governance → 4 memory → 5 the reveal. (Copy: content calendar.)

**Launch day (early week, founder free ~4h)**
- [ ] Fire Show HN + r/LocalLLaMA + r/selfhosted **together**; X reveal post; work every thread live.
- [ ] Watch star velocity; target ~200+/24h.

**Post-launch (the flywheel)**
- [ ] Convert the spike → Discord; open a public changelog; keep building in public.
- [ ] Seed/encourage YouTube tutorials (durable long-tail).
- [ ] Ship weekly; respond to every issue.

---

## 6. Metrics (the only three that matter at launch)

1. **GitHub star velocity** (stars / 24–48h) — leading adoption indicator.
2. **Activation rate** = % of installs that finish first-agent-run + connect a model — measures
   whether friction is beaten (the #1 adoption killer).
3. **Free → Hosted-Pro conversion** (Phase 2 target ~3%) — willingness-to-pay for convenience.

---

## 7. Risks & the pre-mortem

| Risk | Mitigation |
|------|------------|
| **Setup friction** kills activation | One-click install tested cold; first-run banner guides; demo GIF shows it working |
| **"Is local good enough?"** doubt | Endorse hybrid explicitly; lead with "$0 for 99%, audited cloud for the 1%" |
| **We become the OpenClaw headline** (our own security) | Secure-by-default is demoable + audited; lead with it, don't hide it |
| **Big Tech absorbs the category** | Compete on the wedge they structurally won't: governance + family-privacy + open-source ownership |
| **Hosted-AI-subscription trap** (Khoj/Rewind died there) | Monetize convenience + sync + support, never gate core local features |
| **Solo-dev sustainability doubt** | Build in public, weekly ship cadence, open changelog → credibility |

---

## 8. What this campaign deliberately does NOT do

- No paid ads at launch (wrong for this technical, skeptical audience — earned > paid).
- No enterprise/compliance push yet (that's Carla, Wave 3, post-appliance).
- No revenue messaging (this launch sells adoption + trust; Pro is Phase 2).
- No fighting Big Tech on model capability (a losing frame — see competitive brief §6).

---

*Re-confirm fast-moving competitor figures before any public use — see the competitive brief §7 and
the research report's verification log.*
