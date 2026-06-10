# Owner tasks — things only Andrei can do

> The agent-side backlog is code-complete at 194/196 (≈99% SP); what's left to reach v1.0 and
> launch is mostly **human-gated**: real hardware, GitHub settings, and decisions. This is your
> queue, ordered. Tracked mirror: GitHub issue "Owner tasks — the human gate to v1.0".
> Created 2026-06-10 · check items off here (or in the issue) as you go.

## 🔴 Blockers for the v1.0 tag

- [ ] **Run the manual-test runbook on the RTX box** — [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md),
  full pass incl. §0 sign-off and the ⭐B0 governed-autonomy demo. *This runbook IS the audit
  gate; no tag ships without it* ([GO_LIVE_PLAN](../GO_LIVE_PLAN.md) §launch checklist).
- [ ] **HUD v2 runtime verification** — `python serve.py`, open `/`, click every mode + every
  Console (▦) panel against the live backend ([`docs/design/HUD_V2_REMAINING.md`](design/HUD_V2_REMAINING.md) §0).
  The mock-fallback design hides wrong-but-not-failing wiring; the 2026-06-10 depth pass (PR #181)
  shipped ~16 new control surfaces that have only been verified offline (tsc + mocked tests).
- [ ] **Dependabot: 54 vulnerabilities on main (6 critical, 14 high)** —
  https://github.com/andrei649/jarvis-hub/security/dependabot. Likely mostly `worldview/` npm
  deps; triage criticals first. An agent can do the upgrade PRs once you confirm scope.
- [ ] **Relicense MIT → Apache-2.0 + `TRADEMARKS.md`** — decided 2026-06-04, deferred to pre-1.0
  ([`docs/LICENSE_DECISION.md`](LICENSE_DECISION.md)). 1 SP, but only you can sign off a license change.

## 🟠 GitHub settings (5 minutes, Settings → …)

- [ ] **Repo description + topics + social preview** — paste-ready strings in
  [`docs/BRAND_BOOK.md`](BRAND_BOOK.md) §9 (current description is just "Personal AI").
- [ ] **Enable code scanning** (Settings → Code security) or make the `Analyze (python)` CodeQL
  check non-required — it intermittently fails with "Code scanning is not enabled"
  ([`HUD_V2_REMAINING.md`](design/HUD_V2_REMAINING.md) §9).

## 🟡 GPU-host work (the last 2 backlog items + Howard)

- [ ] **H12.14** — small fine-tuned agentic model (SFT/GRPO) — runbook [`docs/GPU_RUNBOOK.md`](GPU_RUNBOOK.md).
- [ ] **H13.3** — speculative decoding (draft Qwen3-4B → target 32B); config-only, output-identical.
- [ ] **TASK-1** — Howard's first real run: needs *your* data export (conversations → `memory_logs/learning/*.jsonl`),
  then the dedicated backend + ingestion run.
- [ ] **LM Studio end-to-end** — validate `lms server start/load/unload` against the real binary
  on the 5090 box (current coverage is mock-only), incl. the new HUD Admin → LM STUDIO panel.
- [ ] **Live-mic validation** — HUD voice loop + barge-in tuning need a real microphone
  (PR #162/#164 caveat), incl. Wyoming satellite if you set one up.

## 🟢 Launch assets (when you're ready to show it)

- [ ] **Record the 30–60s demo GIF** for the README hero — one real task incl. an approved
  irreversible step (the `TODO(launch)` in README.md).
- [ ] **HUD screenshot on void-black** for the GitHub social preview (doubles as README hero
  until the GIF lands) — art direction in BRAND_BOOK §7.
- [ ] **Decide the "Jarvis" naming question** before anything commercial (Phase 2) —
  trademark-risk note in BRAND_BOOK §2.

## Parking lot (decisions, no rush)

- [ ] Phase 2 design partners: who are the first 3–5 non-Andrei users? (MOONSHOT §4, Phase 2 gate)
- [ ] Hosted-Pro appetite: build vs wait for pull (VALUATION_AND_PRICING §9).
