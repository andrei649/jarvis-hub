# Pre-Go-Live Sync — meeting summary (2026-07-07)

> **Purpose:** stakeholder sync before inviting the first design partners, assuming ⭐B0
> has just passed on the RTX box. Chaired by the Product Owner (AI, Fable 5); five
> stakeholder seats played by agents, each grounded in the repo (files cited inline).
> Decision-maker of record: **Andrei (owner)** — every DECISION below is a PO
> recommendation pending his ratification.

**Attendees:** Product Owner (chair) · Engineering Lead · Security & Trust Officer ·
Design-Partner Proxy ("Homelab Hank", RTX 3080, r/selfhosted) · GTM Lead · Ops & Support Lead

**Agenda:** go/no-go positions → conflicts → decisions → action items → cut list.

---

## 1. Positions (one line each)

| Seat | Position | Headline |
|------|----------|----------|
| Engineering | GO-with-conditions | Code is ready; **B0 is a demo, not endurance** — no soak, untested OS/Python matrix, blind-debug loop never exercised |
| Security | GO-with-conditions | **The posture B0 proves is not the posture a partner installs** — kernel/hardened/grants all default-OFF |
| Design Partner | WOULD INSTALL, **BUT** | ~50/50 odds of surviving hour one: README is owner-centric, no VRAM guidance, WorldView auto-starts opt-out, zero pixels of demo proof |
| GTM | GO-with-conditions | We built a *public-launch* kit; the partner phase needs private artifacts + a **no-public-surface freeze** or we burn the HN launch to recruit 3 people |
| Ops/Support | GO-with-conditions | The support **loop** is one-directional and untested: the bundle dies when the server does, and partner feedback is stored on *their* box |

**No seat said NO-GO.** Every condition is fixable in days, not weeks.

## 2. Conflicts the chair had to resolve

**C1 — Security vs. Design Partner: "require hardened posture" vs. "the first hour is already booby-trapped."**
Security demands `JARVIS_HARDENED=1` + off-box `JARVIS_AUDIT_KEY` + `JARVIS_ACTION_KERNEL=1` + explicit plugin grants on every partner box; the Partner says every additional setup step halves survival odds.
*Resolution:* the friction moves into **code, not onto the partner**. O26-P2.4 already shipped `product.posture=design_partner` — extend the partner install path so ONE bootstrap step sets the full hardened posture, generates the audit key, and walks plugin grants interactively, verified by `GET /api/security/posture → hardened`. Security's bar met, Partner's hour-one intact. B0 must be **re-run once under this posture** (the P2.4 acceptance criterion already says so).

**C2 — Design Partner vs. the repo's identity: "one person's everything-machine."**
The README's subtitle names the owner's machines; WorldView (a full OSINT stack) auto-starts opt-out; agents are visibly personal; three surfaces show three different test counts (README badge 2,800+ / run-section ~2,400 / landing 3,600+ — a *third* counter-drift site, found by the freshest pair of eyes).
*Resolution:* a **stranger-first README rewrite** + WorldView flipped to opt-IN and moved out of the default start path + a VRAM-tiered model table (8–12/16/24GB) + counters pointed at the synced STATUS value. This is packaging, not product — no code risk.

**C3 — Engineering's self-caught contradiction: the Python floor.**
`COMPATIBILITY.md` says 3.12+ hard floor; PR #634 added a 3.11 numpy marker and verified the full suite green on 3.11 — twice. A straddle helps no one.
*Resolution (PO recommendation):* **widen official support to 3.11** — the evidence already exists — by adding a 3.11 job to the CI matrix and updating COMPATIBILITY. Fallback if the owner prefers a strict floor: enforce ≥3.12 at boot with a clear error and revert the marker. Either is fine; the contradiction is not.

**C4 — GTM vs. the license timing.**
LICENSE_DECISION says flip at "just before v1.0"; GTM argues the flip must land **before the first external install** ("trivial now, contested after outside usage") — and Security's CLA-note prep (already merged) points the same way.
*Resolution:* re-anchor the flip to the **partner-invite milestone**, not the tag. Everything is staged (`docs/legal/`, TRADEMARKS.md, CONTRIBUTING grant); it remains a 3-command owner action.

## 3. Decisions (ratified / superseded 2026-09-01 — only decision 6 still pending owner wording)

> **Owner ratification 2026-09-01:** decisions **3, 4 and 7 ratified** as written; **2 ratified**
> minus the unbuilt snapshot-refusal clause (dropped until Gate-2 🚧5 ships; effective from the
> v1.0.0 tag); **1 superseded** by the A7 close-out (2026-08-28); **5 superseded** by the A7
> close-out plus the H23.30 public-demo approval (2026-09-01); **6 stays PENDING** the owner's own
> SLA wording (T-0.55 stays open). Per-decision annotations inline below.

1. ~~**Conditional GO.**~~ *Superseded 2026-09-01 — overtaken by the A7 close-out (2026-08-28:
   partners recruited and running on non-owner installs while Gate-2 🚧5/6/8/9 stay open).*
   Original text: No partner invite ships until the Gate-2 checklist (§4, items marked 🚧) is complete. Target: invite-ready within ~2 weeks of B0.
2. **Partner installs = signed release tag + hardened posture by default**, never `main`, never the demo posture. Owner soaks each tag ≥1 week on his box before recommending it; monthly upgrade cadence; ~~the update path takes an automatic pre-upgrade snapshot and refuses to migrate without one~~. *✅ Ratified 2026-09-01 minus the struck clause — dropped until Gate-2 🚧5 ships; effective from the v1.0.0 tag.*
3. **WorldView and the Signal Layer leave the default install/start path** (opt-in, companion-project section at the bottom of the README). The private-assistant promise stays unmuddied. *✅ Ratified 2026-09-01 as written.*
4. **The first-30-minutes path must end in one accepted, fully-local, zero-key autonomous action** (e.g. propose daily brief → approve in the queue → watch it land in the audit log). The north-star metric, demonstrated inside onboarding. The 0.19 Command Center is the natural surface for it. *✅ Ratified 2026-09-01 as written.*
5. ~~**No public surface until the partner gate**~~ *Superseded 2026-09-01 — by the A7 close-out (2026-08-28) plus the H23.30 public-demo approval (2026-09-01).* Original text: no Show HN, no teaser, no published landing page (strip the embedded capture-checklist section before it ever goes live), no r/LocalLLaMA thread. Recruitment = owner's personal 1:1 outreach (2 warm + 3–5 OpenClaw-burned self-hosters), screened for: 16–24GB-class GPU, already self-hosts, 30-day daily-driver commitment, weekly 30-min call, north-star metrics opt-in.
6. **Honest support contract:** 48h *first-response* (workdays, solo maintainer), fix **or** clear won't-fix/workaround — never promised fix timelines, never after-hours, never remote-access debugging. Onboarding includes one supervised backup+restore drill per partner. Kickoff email asks for version + support bundle + feedback export (closing Ops's "feedback cul-de-sac": the NPS store lives on the partner's box and must be exported to be seen). *⏳ PENDING 2026-09-01 — the owner's own SLA wording is still owed (T-0.55 stays open); not ratified yet.*
7. **Messaging stays inside the repo's own honesty rules:** the narrowed competitive claim ("no *shipping consumer* product combines…"), preference-learning not led with until measured, and the OpenClaw counter-position *shown* (B0 footage of an action visibly waiting for approval) rather than told. *✅ Ratified 2026-09-01 as written.*

## 4. Action items

| # | Action | Owner | When |
|---|--------|-------|------|
| 🚧1 | Partner bootstrap: one step → `design_partner` posture (hardened + audit key + interactive plugin grants), posture-verified; re-run B0 golden loop under it | AI session | before invites |
| 🚧2 | Offline support-bundle CLI (works with the server down: bundle JSON + install-smoke + sanitized log tail) + "how to file a bug" one-pager | AI session | before invites |
| 🚧3 | Stranger-first README rewrite + VRAM model table + WorldView opt-in flip + fix badge/landing counters + strip landing internals | AI session | before invites |
| 🚧4 | First-30-minutes local autonomous loop wired into onboarding/Command Center | AI session | before invites |
| 🚧5 | Pre-upgrade auto-snapshot in the update path (refuse to migrate without) | AI session | before invites |
| 🚧6 | Partner trust brief (compromised-box reality incl. the `*.key`/`.env` exposure, incident/notify channel, honest SLA) + fix stale SECURITY.md line | AI session draft → owner sign-off | before invites |
| 🚧7 | 72h soak (A2) + one clean-machine install on a partner-shaped box (Windows, Ollama-only, 3.11 & 3.12) with install-smoke exit-0 | **Owner** | before invites |
| 🚧8 | Cut 3–5 min unlisted partner walkthrough from the B0 recording (shots 2–4) + one-page partner brief | **Owner** (+AI draft) | before invites |
| 🚧9 | License flip (3 staged commands) + GitHub settings batch (SEC-4 required checks, CQ-2/3) + flip `JARVIS_EVAL_CI_SMALL_MODEL=1` | **Owner** | before invites |
| 10 | ~~Python floor decision (recommend: add 3.11 to CI + update COMPATIBILITY)~~ ✅ **decided 2026-09-01: keep the 3.12 floor** — no CI-matrix change, the 3.11 numpy marker stays as a courtesy and COMPATIBILITY.md says 3.11 is unsupported/untested | **Owner** ratified, AI executes the doc fix | closed |
| 11 | First 3–5 outreach touches under the owner's personal identity, using the screening bar | **Owner** | at gate |
| 12 | Support-loop dry run: owner plays remote partner once (bundle → diagnose → fix) | Owner + AI | before invites |

## 5. The cut list (unanimous "do NOT" for this phase)

- **No new inward-facing horizons** — B7 / Hermes 3/5/6 stay parked (zero consumers; `ToolRPCSandboxRuntime` has zero callers); scope-gravity is the named top risk and it is currently *materializing*.
- **No multi-user, no RLS, no 0.20 Vault** — one partner = one box = one user, stated in the trust brief.
- **No public launch playbook** — the HN/star-velocity mechanic is single-use; DMs recruit 3 people better.
- **No promised fix timelines, no pager, no remote-access support** — it contradicts both bus-factor-1 honesty and the privacy promise.
- **No trademark rename debate now** — Phase-2 work; keep partner materials cheap and name-light.

## 6. Verdict

**CONDITIONAL GO.** The room is unanimous that the product is real and the wedge
(governed autonomy, visibly) is genuinely differentiated — and equally unanimous that
*today's default install does not deliver the product B0 demonstrates*. The gap is not
capability; it is packaging, posture, and the support loop. Roughly two focused weeks:
~6 AI-executable items and ~5 owner items, then invites go out.

*The sentence the chair kept hearing, from every seat: the demo proves the thesis —
now make the install prove the demo.*
