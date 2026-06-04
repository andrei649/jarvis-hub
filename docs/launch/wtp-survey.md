# WTP survey + design-partner interview guide — Jarvis Hub

> Purpose: close the two evidence gaps the GTM research flagged (no public data exists for either):
> **(1)** the "privacy-concerned → willing to self-host on my own GPU" conversion, and
> **(2)** willingness-to-pay for a hosted Pro tier (esp. among regulated professionals).
> Keep the survey ≤2 minutes. Run it in r/LocalLLaMA + r/selfhosted (with mod permission) and/or a
> Google Form linked from the launch posts. Target n≥100 for the survey, 5–10 interviews.

---

## A. Survey (8 questions, ~2 min)

1. **Which best describes you?** (single)
   - Developer · Homelab/self-hoster · Privacy-conscious non-developer · Regulated professional (legal/medical/finance) · Other

2. **Do you currently run local LLMs?** (single)
   - Daily · Sometimes · Tried it · No, but want to · No

3. **If you use a cloud AI assistant (ChatGPT/Gemini/Copilot), what stops you from going fully local?** (multi)
   - Setup friction · Hardware/GPU cost · "Local isn't good enough" · Maintenance burden · Nothing — I'm already local · I don't want to go local

4. **How much do you trust an AI agent to take actions on your behalf *unattended*?** (1–5)
   - 1 = never · 5 = fully, for reversible actions

5. **Which would make you trust an agent to act unattended?** (multi)
   - Approval queue for irreversible actions · Tamper-evident audit log · Runs fully local · Open source · Kill-switch · Observability of every action · None would

6. **For a local-first personal AI you self-host for free, what would you pay monthly for a hosted "Pro" tier (managed sync + remote access + backups)?** (single)
   - $0 (self-host only) · $1–5 · $6–10 · $11–20 · $21+

7. **What would actually make Pro worth paying for?** (multi)
   - Cross-device sync · Remote access (no port-forwarding) · Backups · Hosted inference credits · Priority support · Premium/early agents · Nothing

8. **(Optional) Leave an email if you'd be a design partner / early tester.** (free text)

---

## B. Design-partner interview guide (30 min, 5–10 people incl. 2–3 regulated pros)

**Warm-up**
- Walk me through how you use AI today — which tools, for what, on what hardware?
- What do you deliberately *not* put into a cloud AI? Why?

**Pain & triggers**
- Last time you wished an assistant could just *do* something for you — what was it, and what stopped you trusting it?
- Has a privacy/security concern (or incident) ever changed a tool you use?

**Governance (the wedge)**
- If an agent could act unattended but every irreversible step waited for your one-tap approval and everything was logged — does that change what you'd let it do? Where's the line?
- What would you need to *see* to trust it (audit log? local-only proof? open source?)?

**Regulated-pro track (if applicable)**
- What are your hard compliance constraints (HIPAA/GDPR/EU AI Act/bar rules)?
- Would a local, auditable, on-device assistant change whether you can use AI at work? What proof/cert would procurement need?

**Pricing**
- Self-host is free. What would make a paid hosted tier a no-brainer vs. a nuisance? What's "too expensive"?
- (Van Westendorp, optional) At what monthly price is Pro: too cheap to trust / a bargain / getting expensive / too expensive?

**Close**
- If this existed and worked today, what's the one use-case you'd point it at first?
- Who else should I talk to?

---

## C. What to do with the answers
- **Q3/Q5 → messaging:** confirm whether friction or "good enough" is the bigger blocker, and which governance proof-points to lead with.
- **Q6/Q7 + interviews → pricing v1:** validate (or move) the ~$10/mo Hosted-Pro hypothesis and the feature gate.
- **Q4 → the autonomy default:** how much to let agents do out-of-the-box vs. behind approval.
- **Regulated-pro interviews → the high-WTP expansion** (persona "Counselor Carla") and any compliance roadmap.
