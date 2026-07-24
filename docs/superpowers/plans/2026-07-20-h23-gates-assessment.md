# H23 Release Gates Assessment (2026-07-20)

**Goal:** Identify the true critical path to the 1.0.0 release by mapping the Lane A gates to their actual blockers.

## Lane A Gates Status & Blockers

| Gate | Description | Status | Blocker / Owner Action Needed |
|------|-------------|--------|-------------------------------|
| **A1** | ⭐B0 governed-autonomy demo + manual testing pass | ⬜ Pending | **Owner execution** of `docs/MANUAL_TESTING.md` on the RTX box. |
| **A2** | 72h soak (0.63) + record AUD-0 / H23.23 | ⬜ Pending | Depends on A1. Requires 3 days of unattended stability. |
| **A3** | Dependabot re-triage (vulns) | 🟢 Partial | **Owner action:** Resolve WorldView/Mobile expo alerts & dismiss stale UI alerts. |
| **A4** | GitHub settings batch (SEC-4, CQ-2, metadata) | ⬜ Pending | **Owner action** in GitHub repository settings. |
| **A5** | License flip MIT → Apache-2.0 | 🟢 Prep Done | **Owner action:** Execute the 3 commands to flip the license just before v1.0. |
| **A6** | Demo video (60s) + publish landing | 🟡 Partial | **Owner action:** Record M4 video. Landing page code is already done. |
| **A7** | Recruit 1–3 design partners (≥2 weeks usage) | ⬜ Pending | **Owner action:** Recruitment & onboarding. Requires 2 weeks of real-world usage. |
| **A8** | AI-OS v1 owner-host proof (real hardware) | ⬜ Pending | **Owner execution:** Validate Playwright, Home Assistant, Frigate, and Media Director on physical hardware/network. |
| **A9** | Tag 1.0.0 | ⬜ Blocked | Blocked by all of the above. |

## AI-OS Pillar Readiness (The "Code" half of 1.0)
All six AI-OS pillars required for 1.0 are **code-complete** and hermetically verified:
1. **Operator (H28):** Hermetic complete. (Blocked by A8 real UIA/Playwright)
2. **Media Director (H29):** Hermetic complete. (Blocked by A8 device delivery)
3. **House Brain (H30):** Hermetic complete. (Blocked by A8 Home Assistant state)
4. **Camera Intelligence (H31):** Hermetic complete. (Blocked by A8 Frigate NVR)
5. **Capability Acquisition (H32):** Hermetic complete.
6. **Ambient Intelligence (H33):** Hermetic complete.

## Critical Path Analysis & Recommendation

The codebase is ready. **Zero code features are blocking 1.0.** The critical path is entirely constrained by owner/human validation and real-world execution.

**The True Critical Path:**
`A8 (Hardware Proof) & A1 (Manual Test)` ➔ `A2 (72h Soak)` ➔ `A7 (Design Partners for 2 weeks)` ➔ `A9 (Tag 1.0.0)`

**Recommendation for the Owner:**
1. **Stop writing product code.** The AI-OS pillars are hermetically proven. Further code changes introduce risk without advancing the 1.0 tag.
2. **Focus immediately on A1 and A8.** These are the manual validation steps on the host machine. Doing this unblocks the 72-hour soak (A2).
3. **Parallelize A7 (Partners) and A6 (Video).** While the 72h soak runs, execute the marketing/recruitment steps.

**Timeline Estimate:** Assuming A1 and A8 take 3-5 days of effort, the absolute minimum time to 1.0 is **~3 weeks** (bound strictly by the 2-week requirement of A7).