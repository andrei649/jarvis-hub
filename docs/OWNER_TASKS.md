# Owner tasks — things only Andrei can do

> The **feature** backlog is delivered — that's **v0.10.0**. The road to 1.0 is the productionization
> layer (**H23** in [BACKLOG.md](../BACKLOG.md#version-roadmap)) plus real design-partner users; this file is
> the **owner lane** running alongside it — the human-gated bits (real hardware, GitHub settings, legal,
> decisions) that only Andrei can do. Ordered queue. Created 2026-06-10 · check items off as you go.

## 🔴 Owner gates that block tagging a release (and ultimately 1.0)

- [ ] **Run the manual-test runbook on the RTX box** — [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md),
  full pass incl. §0 sign-off and the ⭐B0 governed-autonomy demo. *This runbook IS the audit
  gate; no tag ships without it* ([GO_LIVE_PLAN](../GO_LIVE_PLAN.md) §launch checklist).
- [ ] **HUD v2 runtime verification** — `python serve.py`, open `/`, click every mode + every
  Console (▦) panel against the live backend ([`docs/design/HUD_V2_REMAINING.md`](design/HUD_V2_REMAINING.md) §0).
  The mock-fallback design hides wrong-but-not-failing wiring; the 2026-06-10 depth pass (PR #181)
  shipped ~16 new control surfaces that have only been verified offline (tsc + mocked tests).
- [x] **Dependabot: 54 vulnerabilities on main** — ✅ fixed 2026-06-10 (agent wave): HUD
  frontend 5→0 (vite 7/vitest 4), worldview 13→2 (fastify 5, next 16.2.9 + react 19,
  vitest 4, tsx), mcp 2→0; all suites green (HUD 19, WV frontend 101, backend 218).
  - [ ] **Remaining, needs you:** the 2 worldview moderates are a postcss XSS *bundled inside
    next itself* — clears when Vercel ships next 16.3 stable (re-run `npm audit` then).
    **mobile/: 11 moderates** are the Expo SDK chain — needs an Expo SDK upgrade verified on a
    real device (can't be validated headlessly). Python deps: clean (`pip-audit`).
- [ ] **Relicense MIT → Apache-2.0 + `TRADEMARKS.md`** — decided 2026-06-04, deferred to pre-1.0
  ([`docs/LICENSE_DECISION.md`](LICENSE_DECISION.md)). 1 SP, but only you can sign off a license change.
- [ ] **(optional) Signed release artifacts** — the release pipeline (H23.13) builds tar/zip + SBOM +
  checksums automatically; to also emit GPG signatures, generate a signing key and add the repo
  secrets `GPG_PRIVATE_KEY` (+ `GPG_PASSPHRASE` if set). Steps in [`docs/RELEASE.md`](RELEASE.md).
  Optional too: publish a prebuilt Docker image to `ghcr.io` (compose already builds locally) — your
  call, needs registry perms.

## 🟠 GitHub settings (5 minutes, Settings → …)

- [ ] **Repo description + topics + social preview** — paste-ready strings in
  [`docs/BRAND_BOOK.md`](BRAND_BOOK.md) §9 (current description is just "Personal AI").
- [ ] **Enable code scanning** (Settings → Code security) or make the `Analyze (python)` CodeQL
  check non-required — it intermittently fails with "Code scanning is not enabled"
  ([`HUD_V2_REMAINING.md`](design/HUD_V2_REMAINING.md) §9).
- [ ] **Dismiss resolved scanning alerts** (Security → Secret/Code scanning) — the code-side fixes
  merged 2026-06-17 (#215, #216); these remaining ones are false positives / won't-fix:
  - Secret scanning **#1** (OpenAI key) → "Used in tests" — it's a synthetic guardrail fixture (#215).
  - CodeQL **#22 / #23 / #431** (path injection in `get_agent_soul`) → false positive: the agent-id
    regex `^[a-z0-9_-]{1,64}$` forbids separators, so traversal is impossible.
  - CodeQL **#299 / #298 / #247** ("variable defined multiple times") → false positive: those are
    fallback defaults that are actually read.
  - CodeQL **#432** (info exposure) → won't-fix: it's a docs code-snippet, not shipped.
- [ ] **Paste the remaining ~12 CodeQL alerts** to the agent — only 13 of the 25 selected came
  through and there's no MCP tool to list code-scanning alerts, so the rest need a manual paste to
  finish triage (6 real ones fixed in #216; the 7 above are FPs/won't-fix).

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
- [x] **SOUL.md templating** — ✅ approved + shipped 2026-06-10: repo souls/heartbeats are
  generic templates; personalized copies live in gitignored `agents/<id>/SOUL.local.md` /
  `HEARTBEAT.local.md` overlays that win at load time (`docs/ARCHITECTURE.md` §8).
  - [ ] **Your one-time action (deployed box, after pulling):**
    `python scripts/restore_personal_souls.py` then restart — restores your personalized
    souls from git history into the `*.local.md` overlays.
  - [ ] **History caveat (your call):** the personal details remain visible in old git
    commits (the repo was public throughout). A full scrub needs a history rewrite
    (BFG/filter-repo + force-push) — disruptive, and forks/caches may retain copies anyway.

## Parking lot (decisions, no rush)

- [ ] **After the manual-test pass:** green-light **CLN-2/CLN-3** (the big `orchestrator.py` /
  `web.py` split) — deliberately sequenced post-1.0 (your call, 2026-06-10) so a refactor
  can't add regression risk before the human gate.

- [ ] Phase 2 design partners: who are the first 3–5 non-Andrei users? (MOONSHOT §4, Phase 2 gate)
- [ ] Hosted-Pro appetite: build vs wait for pull (VALUATION_AND_PRICING §9).

- [ ] **CDX-12 hardened profile (a posture decision — do you want it, and when).** `JARVIS_HARDENED=1`
  is one switch that flips four toggles: guardrails→REDACT, **audit-HMAC required** (server won't start
  without `JARVIS_AUDIT_KEY`), strict egress forced (no `JARVIS_STRICT_EGRESS=0` downgrade), and mutating
  MCP route tools forced off — plus it enables CDX-11 plugin least-privilege. It's **OFF by default**;
  enabling is your call for a design-partner / multi-tenant box. To turn on: set `JARVIS_HARDENED=1` **and**
  `JARVIS_AUDIT_KEY=<off-box secret>`, then declare `JARVIS_PLUGIN_GRANTS` (next item). Confirm via
  `GET /api/security/posture` → `hardened`.

- [ ] **(optional) Channel send rate limits (0.44).** To cap outbound broadcast volume on the external
  webhook channels (WhatsApp/Signal/Matrix/Teams/Google Chat), set `JARVIS_CHANNEL_SEND_RATE=<per-minute>`
  (global) and/or `JARVIS_CHANNEL_SEND_RATES="whatsapp:10,teams:30"` (per channel). Default unset =
  unlimited. The interactive reply path (telegram/web/voice) is intentionally NOT limited.

- [ ] **CDX-11 plugin grants (only if/when you enable the hardened profile).** Turning on
  least-privilege (`JARVIS_PLUGIN_LEAST_PRIVILEGE=1`, or the `JARVIS_HARDENED` preset) stops
  honoring the `agents_served=["all"]` wildcard for the 12 external-transmit plugins (social_x,
  writeback_*, call_*, channel_*, telegram) — so each is **deny-by-default** until you declare
  which agent may use it. Set `JARVIS_PLUGIN_GRANTS="social_x:veronica,writeback_github:stark,…"`
  (comma list of `plugin_id:agent_id`). This is the deliberate **policy** decision the code does
  *not* guess for you; pick grants that match how you actually want each write surface used.
  Verify on `GET /plugins` (`least_privilege:true`, per-plugin `wildcard_restricted`/`grants`).
