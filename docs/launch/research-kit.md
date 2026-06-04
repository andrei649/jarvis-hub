# Research kit — deploy-ready (run the primary research)

> Turns the survey/interview *design* (`docs/launch/wtp-survey.md`) into copy-paste-ready
> artifacts so you can launch the primary research **today**. Goal: close the two gaps the GTM
> research couldn't — the **"privacy-concerned → willing to self-host"** conversion, and **hosted-Pro
> willingness-to-pay** (esp. regulated pros). Targets: **n ≥ 100** survey responses, **5–10** interviews.

---

## A. Build the survey (Google Form, ~10 min)

Settings: **anonymous**, "collect email" **off**, "limit to 1 response" off, show progress bar.
Title: *"Local/private AI — a 2-minute survey for self-hosters."*
Intro: *"Building a local-first, governed personal AI. 8 quick questions; results shared back with this community."*

| # | Question | Type |
|---|---|---|
| 1 | Which best describes you? | Multiple choice (Developer / Homelab-self-hoster / Privacy-conscious non-dev / Regulated professional / Other) |
| 2 | Do you currently run local LLMs? | Multiple choice (Daily / Sometimes / Tried it / Want to / No) |
| 3 | What stops you going fully local? | Checkboxes (Setup friction / Hardware cost / "Not good enough" / Maintenance / Already local / Don't want to) |
| 4 | Trust an agent to act **unattended**? | Linear scale 1–5 |
| 5 | What would make you trust it? | Checkboxes (Approval queue / Audit log / Fully local / Open source / Kill-switch / Observability / None) |
| 6 | Monthly $ for a hosted "Pro" (sync + remote + backups)? | Multiple choice ($0 / $1–5 / $6–10 / $11–20 / $21+) |
| 7 | What makes Pro worth paying for? | Checkboxes (Sync / Remote access / Backups / Hosted inference / Support / Premium agents / Nothing) |
| 8 | Design partner? Drop an email (optional). | Short answer |

(Full rationale for each in `wtp-survey.md`.)

## B. Reddit survey post (copy-paste — **get mod permission first**)

> **r/LocalLLaMA** and **r/selfhosted** both restrict surveys/self-promo. DM the mods first, or post in the weekly/"what are you working on" thread.

**Title:** `[Survey] 2 min: how much autonomy + privacy do you actually want from a local AI? (results shared back)`

**Body:**
> I'm building a local-first, governed personal AI (runs on your own GPU; every autonomous action goes through an approval queue + audit log) and I want to design it around what this community actually wants, not my assumptions.
>
> 8 questions, ~2 minutes, anonymous: **<FORM_URL>**
>
> Especially curious: where local falls short for you today, and what (if anything) would make you trust an agent to act unattended. I'll post the aggregated results back here in ~2 weeks.

## C. Design-partner outreach (5–10, incl. 2–3 regulated pros)

**Where:** replies to your Show HN / Reddit launch threads; X; targeted DMs; your network for the regulated pros (lawyer/clinician/financial advisor).

**Short DM / reply template:**
> Thanks for the thoughtful comment — exactly the kind of perspective I want to build around. I'm taking on a handful of design partners (free, early access, direct line to me) to shape a local-first governed AI. 30-min call to hear how you'd use it? No pitch.

**Email template (regulated pro):**
> Subject: local, auditable AI — 30 min to pressure-test it with you?
> Hi <name> — I'm building a personal AI that runs entirely on your own hardware (nothing leaves the device by default) with an approval queue + tamper-evident audit log, aimed at people with real confidentiality constraints. Before I build the compliance story, I'd love 30 minutes to understand yours — what would procurement/your bar/regulator need to see? Free early access if it's useful. — <you>

Interview script: `wtp-survey.md` §B.

## D. Track it (a 6-column sheet is enough)

`source | persona (Q1) | runs-local (Q2) | trust (Q4) | WTP band (Q6) | top "worth-it" (Q7)` — plus a tab of interview notes keyed to the §B sections. Read against `wtp-survey.md` §C ("what to do with the answers").

## E. 2-week run plan
- **Day 1:** build the Form (§A); DM r/LocalLLaMA + r/selfhosted mods for survey permission.
- **Day 2–3:** post the survey (§B) where allowed; seed it in your Show HN / launch threads.
- **Day 2–10:** recruit interviews from thread replies + your network (§C); run 5–10 calls.
- **Day 12–14:** aggregate (§D), decide pricing v1 + the autonomy default + which governance proof-points to lead with, and **post results back** to the communities (goodwill + a second touch).

---
*Decisions this unblocks: the ~$10/mo Hosted-Pro hypothesis (Q6/Q7), the out-of-the-box autonomy default (Q4), and the lead governance proof-point (Q5) — see `docs/GTM_PLAN.md`.*
