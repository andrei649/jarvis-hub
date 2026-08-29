# Owner tasks — things only Andrei can do

> The **feature** backlog is delivered — that's **v0.10.0**. The road to 1.0 is the productionization
> layer (**H23** in [BACKLOG.md](../BACKLOG.md#version-roadmap)) plus real design-partner users; this file is
> the **owner lane** running alongside it — the human-gated bits (real hardware, GitHub settings, legal,
> decisions) that only Andrei can do. Ordered queue. Created 2026-06-10 · check items off as you go.
> *2026-07-14: the 1.0 **tag** additionally requires both the AI-OS implementation program
> ([NERVA_VISION.md](../NERVA_VISION.md), ORIZONT 27–33) and its real-host v1 proof. BACKLOG A8
> names that owner-only hardware gate explicitly; hermetic reality packs do not clear it.*

## 🔴 Owner gates that block tagging a release (and ultimately 1.0)

- [ ] **E1.2b — authorize representative owner-local route evidence** — provide an
  ignored-path dataset of at least 20 historical tasks; declare acceptable routes/categories;
  predeclare the sampling/exclusion rule; approve one named retention/access/deletion policy for
  the label file, E9 suite `vN.jsonl`, `runs.jsonl`, JSON report, and Markdown report; and give
  permission for the local run. `owner_attested=true` is a typed declaration, not proof of consent
  or label correctness; it does not clear this owner gate. E1.2a (PR #842) is
  merged onto `main`; the code is `contract_ready` but remains
  `owner_evidence_blocked` until these five inputs are present, with
  `real_task_outcome_quality=not_measured`.
- [ ] **Run the manual-test runbook on the RTX box** — [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md),
  full pass incl. §0 sign-off and the ⭐B0 governed-autonomy demo. *This runbook IS the audit
  gate; no tag ships without it* ([GO_LIVE_PLAN](../GO_LIVE_PLAN.md) §launch checklist).
- [ ] **HUD v2 runtime verification** — `python serve.py`, open `/`, click every mode + every
  Console (▦) panel against the live backend ([`docs/design/HUD_V2_REMAINING.md`](design/HUD_V2_REMAINING.md) §0).
  The mock-fallback design hides wrong-but-not-failing wiring; the 2026-06-10 depth pass (PR #181)
  shipped ~16 new control surfaces that have only been verified offline (tsc + mocked tests).
- [ ] **A8 — AI-OS v1 owner-host proof** — run [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md) §N
  on the isolated RTX/Windows host and real household integrations. This is a blocking release
  gate, separate from code-complete H28–H33 and their hermetic reality packs. It must prove:
  installed Chromium + Windows UIA through the governed browser/desktop path; live Home Assistant
  state projected into the device/room/occupant/presence graph plus a safe governed actuation; a
  consented Frigate event flowing through house/memory/ambient without raw-frame egress;
  presence-aware Media Director delivery on at least two non-chat output surfaces/device classes;
  and one approved acquisition-to-reuse loop. Record build SHA plus redacted task/audit/device
  evidence in the §0 run record (never secrets, household identifiers, or raw camera frames).
- [x] **Dependabot: 54 vulnerabilities on main** — ✅ fixed 2026-06-10 (agent wave): HUD
  frontend 5→0 (vite 7/vitest 4), worldview 13→2 (fastify 5, next 16.2.9 + react 19,
  vitest 4, tsx), mcp 2→0; all suites green (HUD 19, WV frontend 101, backend 218).
  - [ ] **Remaining, needs you (re-audited 2026-07-07, agent-side fixes shipped in #634):**
    the agent fixed the 2 fixable highs (frontend `undici` dev-chain; worldview/mcp `hono`
    ×5 advisories + `esbuild`) with suites green (176 vitest · 51 mcp tests). Still yours:
    (a) the 2 worldview moderates — postcss XSS *bundled inside next itself*, clears when
    Vercel ships next 16.3 stable (re-run `npm audit` then); (b) **mobile/: 11 moderates**
    — the Expo SDK chain. The gate was *tested* 2026-07-07: a non-forced `npm audit fix`
    bump broke `tsc` in the audio path (`expo-audio` AudioPlayer.addListener), so it truly
    needs the SDK upgrade + real-device validation; (c) dismiss the stale alerts in the
    GitHub UI once #634 merges. Python deps: clean (`pip-audit`, CI).
- [ ] **Relicense MIT → Apache-2.0** — decided 2026-06-04, deferred to pre-1.0
  ([`docs/LICENSE_DECISION.md`](LICENSE_DECISION.md)). **Fully prepared in #634 (2026-07-07):**
  `TRADEMARKS.md` is live, `CONTRIBUTING.md` carries the relicense grant (in place BEFORE any
  design-partner contribution lands), and the canonical Apache-2.0 text is staged at
  `docs/legal/LICENSE-APACHE-2.0-staged.txt`. The flip is now 3 commands, only you may run them:
  `git mv docs/legal/LICENSE-APACHE-2.0-staged.txt LICENSE` (replacing the MIT file) · update the
  README badge `license-MIT-green` → `license-Apache--2.0-blue` · commit as its own PR titled
  "relicense: MIT → Apache-2.0 (pre-1.0, per LICENSE_DECISION)".
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
- [ ] **(optional) Wire "Max" on the GitHub side** — the codename already auto-triggers the
  finishing protocol ([`MAX.md`](../MAX.md)) in any Claude Code session via
  `.claude/skills/max/`. To also make a bare **"Max"** issue/PR comment start a run with no
  session open, install the Claude GitHub App on the repo (or add a `claude.yml` workflow with
  an `ANTHROPIC_API_KEY` secret) — app install + secret are owner-only. Until then, the trigger
  path is: open any Claude session on the repo and say "Max".

## 🟡 GPU-host work (the last 2 backlog items + Howard)

- [ ] **H12.14** — small fine-tuned agentic model (SFT/GRPO) — runbook [`docs/GPU_RUNBOOK.md`](GPU_RUNBOOK.md).
- [ ] **H13.3** — speculative decoding (draft Qwen3-4B → target 32B); config-only, output-identical.
- [ ] **TASK-1** — Howard's first real run: needs *your* data export (conversations → `memory_logs/learning/*.jsonl`),
  then the dedicated backend + ingestion run.
- [ ] **LM Studio end-to-end** — validate `lms server start/load/unload` against the real binary
  on the 5090 box (current coverage is mock-only), incl. the new HUD Admin → LM STUDIO panel.
- [ ] **Live-mic validation** — HUD voice loop + barge-in tuning need a real microphone
  (PR #162/#164 caveat), incl. Wyoming satellite if you set one up.
- [ ] **Wall-screen room validation (briefing wall)** — the `brain` cinema stage was built from
  reference video and verified only in a headless browser. On the real wall screen, check:
  (a) legibility of the hairline chrome and region chips at your actual viewing distance;
  (b) mic placement — HOLD TO TALK captures usable audio from where you stand, not just at the desk;
  (c) echo/feedback when the reply plays through the TV or soundbar while the mic is open;
  (d) **the privacy call** — the spoken-line redaction now defaults to HIDDEN
  (`TRANSCRIPT_DEFAULT_VISIBLE` in `frontend/src/wall.tsx`); decide per room whether the opt-in
  should ever be turned on with other people present.
  Until this is done, the wall is *unproven in a room*, whatever CI says.

## 🟢 Optional: desk-presence daemon (H34.2 away-notify)

The engine side is code-complete and default-off: with nothing reporting, owner
presence stays `unknown` and nothing changes. Turning it on makes Nerva route
decision/approval cards to your phone (via the existing WhatsApp/Telegram
escalation channels) **only when you're away from the desk** — while you're at
the machine they stay calm in the HUD. It's still bounded by the same ≤4/day
interrupt budget. What's yours to wire is the tiny owner-side signal:

- [ ] **Run a host presence daemon** on your desktop that POSTs your state to the
  hub whenever it changes (and as a heartbeat inside the TTL, default 15 min):
  ```
  POST /api/presence/owner
  X-Admin-Token: <hud.admin_token>
  { "state": "away", "source": "win-idle", "idle_seconds": 320 }
  ```
  `state` accepts `present`/`away`/`idle`/`unknown` or the OS aliases
  `active`/`locked`/`inactive`/`unlocked`/`offline`. The simplest version is a
  Windows idle/lock watcher (session lock → `locked`, unlock → `active`, N min
  idle → `away`); the 0.64 Tauri host overlay can emit the same signal.
- [ ] **Pick the away channels** — set `autonomy.escalation_channels` (admin
  settings) to the channels that should ring when you're away (e.g.
  `["whatsapp","signal"]`). Leave it unset to use every configured channel.
  Telegram is auto-excluded from the away fan-out (it already gets the rich card).
- [ ] **(Optional) tune the staleness TTL** via `autonomy.presence_ttl` (seconds,
  default 900). If the daemon goes quiet longer than the TTL, presence reverts to
  "not away" so a crashed daemon can never keep escalating to your phone.

Verify from the Mission Control page (`/mission-control`): the **OWNER** chip in
the header shows `PRESENT` / `AWAY→ESC` / `IDLE` / `STALE`. Nothing here is
release-blocking — it's an owner-side convenience daemon plus one setting.

## 🟢 Optional: turn on Self-Improvement

Most of "Jarvis proactively finds bugs, watches for anomalies, and grows its own
capabilities" already exists and is already running by default (the resource/
service Observer, event Watchers, and the 15-min/hourly/daily log-bug scanner —
`system.observer_enabled`/`watchers_enabled`/`log_scan_enabled`, all default
`true`). What's left is default-off by deliberate governance choice (Product
Posture O26-P2.4, H32/H33 explicit owner opt-in), and needs *you* to flip it —
one call from the Console → Observe → **SELF-IMPROVEMENT** panel's "enable
bundle" button, or `POST /api/self-improvement/enable`:

- [ ] **`cognition.enabled` + `cognition.review_enabled`** — the H20 per-turn
  background-review distiller + nightly skill curator (strict-local, distills
  durable facts/corrections; proposed skill patches still need your approval).
- [ ] **`acquisition.enabled`** — H32 Capability Acquisition (gap → reuse-search →
  sandboxed research → strict-local codegen → hostile-sandbox verification →
  **your approval** → signed install). The acquisition research path is
  **SearXNG-only** (`SEARXNG_URL` in `.env`; a Tavily key is deliberately
  refused on this path — cloud research is forbidden for local codegen) plus a
  digest-pinned `JARVIS_ACQUISITION_SANDBOX_IMAGE` — without them the drive
  route refuses honestly (`_degraded {reason, needs}`) instead of sitting inert.
  Drive a captured gap end-to-end with `POST /api/acquisition/{request_id}/drive`
  (admin; A8-i — no Python shell needed anymore).
- [ ] **Presence-aware media (A8-ii)** — for `target:"presence:auto"` set
  `JARVIS_MEDIA_PRESENCE_ROOM=<your desk room>` in `.env` (plus the desk-presence
  daemon posting `POST /api/presence/owner` — H34.2 install above). Unset, the
  target refuses `presence_unknown`; it only ever fires on a fresh `present`
  signal, so a dead daemon can never trigger media at a guessed location.
- [ ] **`ambient.enabled`** — H33 Ambient Intelligence monitors over house/camera/
  digital signals (only meaningful once H30/H31 hardware is connected).
- [ ] **`autonomy.tech_scout_enabled`** — the new Proactive Technology Scout: a
  weekly, read-only websearch scan (same `SEARXNG_URL`/`TAVILY_API_KEY` backend
  as above) for new AI/tech developments worth knowing about. Findings are
  informational only (`RiskTier.READ_ONLY`, no executor) — they show up in the
  task list / morning brief, never auto-act. Tune the query list at
  `autonomy.tech_scout_queries` (admin settings) if the defaults aren't your interests.

None of this is release-blocking — it's config + credentials, not code. The
bundle endpoint only flips settings that already exist and are already
individually toggleable via `/api/admin/settings`; it changes nothing for
anyone who doesn't press the button.

## 🟢 Build the Windows executable (packaged install)

The packaging layer is code-complete and Linux-verified (built binary boots,
`/readyz` green, `Documents/Jarvis` scaffolded — `docs/PACKAGING.md`), but
PyInstaller does **not** cross-compile, so the shippable `jarvis.exe` must be
built on your Windows box:

- [ ] On the RTX/Windows machine, in the project venv:
  `pip install pyinstaller` → `python scripts\build_exe.py` (builds + boots `nerva.exe`
  against `/readyz` with an isolated temp data home).
- [ ] Install it: `powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1`
  (→ `%LOCALAPPDATA%\Programs\Nerva` + a "Nerva" Start Menu shortcut, no admin needed).
- [ ] First run: verify `Documents\Nerva` is created (README, `.env`, `memory/`,
  `skills/`, `souls/`), put your API keys in `Documents\Nerva\.env`, and if you
  use personalized souls copy your `*.local.md` overlays into
  `Documents\Nerva\souls\<agent>\`.

## 🟢 Launch assets (when you're ready to show it)

- [ ] **Record the 30–60s demo GIF** for the README hero — one real task incl. an approved
  irreversible step (the `TODO(launch)` in README.md).
- [ ] **HUD screenshot on void-black** for the GitHub social preview (doubles as README hero
  until the GIF lands) — art direction in BRAND_BOOK §7.
- [x] **Decide the "Jarvis" naming question** — ✅ decided + executed 2026-07-19: the product
  is **Nerva** on every user-facing surface (HUD, executable + `Documents/Nerva`, landing,
  README, logo — `docs/brand/nerva-mark.svg`); agent personas keep their names. BRAND_BOOK §2
  updated.
  - [ ] **Still yours — rename the GitHub repo** (Settings → General → Repository name):
    `jarvis-hub` → `nerva` (or `nerva-hub`). GitHub auto-redirects old clones/remotes. Then
    update the repo description + topics (paste-ready strings in BRAND_BOOK §9) and re-point
    any local remotes: `git remote set-url origin <new-url>`.
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

- [ ] **🔴 Public web demo instance for digitaholic.ro — four calls, all yours** (spec:
  [`docs/decisions/2026-08-24-public-web-demo-digitaholic.md`](decisions/2026-08-24-public-web-demo-digitaholic.md),
  DRAFT awaiting your review; backlog: BACKLOG.md → *P0 — public web demo*, H23.30). A real Nerva
  instance in a digitaholic.ro page, free cloud model, auto-updated from `main`, one disposable
  install per visitor as the "save slot". The four calls:
  1. **Ratify H23.23 (A)** — or note that this spec uses the install-per-user shape H23.23 already
     recommends, so it doesn't block on ratification either way.
  2. **Turn on CDX-12 hardened for this box + fix its `JARVIS_PLUGIN_GRANTS`** (the two items below —
     this is that decision, scoped to the public box: grant nothing that writes anywhere real).
  3. **Pick the free LLM provider/key** (OpenRouter / Groq / Gemini — verify current free-tier limits
     at implementation time, they move).
  4. **Pick the container host** (no GPU / heavy RAM needed: cloud LLM + in-memory stores).

  ⚠️ Whoever implements this must gate `seed_graph()` first — `agents/core/memory/manager.py:45`
  today seeds hardcoded personal facts (Andrei/Alexandra/Max/Raiffeisen/Cosmina de Sus/BMW E93) into
  any empty graph. That is the one blocking code change; the rest of v1 is configuration.

- [ ] **Before any future Hermes adapter proposal:** decide whether the four productivity-skill
  subtrees carrying separate Anthropic terms are legally acceptable for the intended use, and
  require a fresh CVE, transitive-license, SBOM/provenance and platform review
  against the exact proposed artifact. E8.1c is static preflight evidence only; this is
  not a current release blocker and grants no permission to pull, install or execute
  Hermes.

- [ ] **When does the Action Kernel become the default rail?** Today the always-on risk-tier
  policy is the load-bearing gate; the unifying kernel (`JARVIS_ACTION_KERNEL`) and the unified
  Action API (`JARVIS_UNIFIED_ACTION_API`) are code-complete but opt-in (H27.3/H27.7, docs-vs-code
  audit 2026-07-24). Decide the promotion criteria — e.g. N weeks of opt-in dogfood with zero
  kernel-caused blocks/false-DENYs, plus the H28+ operator surfaces exercising it — then flip the
  defaults in one deliberate PR.

- [ ] **The jarvis-hub → Nerva rename** — Nerva is now the product brand across the canonical docs
  ([NERVA_VISION.md](../NERVA_VISION.md) §2, decision 2026-07-12); the *deliberate* rename of the
  repository, packages, install scripts and public pages is owner-gated: pick the moment (likely
  alongside the license flip / pre-1.0 launch), reserve names (GitHub repo, domain, PyPI-style
  package ids), then have an agent prepare the mechanical rename PR.

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

- [ ] **(optional) Persist workflow run history (0.34).** Set `JARVIS_WORKFLOW_PERSIST=1` so the HUD's
  recent-workflow-runs overlay survives a restart (stored bounded under `data/workflows/runs.json`). Default
  unset = in-memory only.

- [ ] **(optional) System profile (0.62).** Set `JARVIS_SYSTEM_PROFILE=gaming|ai|multimedia|admin` to switch
  the assistant's usage mode (default `balanced`). `gaming`/`multimedia` pause proactive agent heartbeats to
  free local resources; `balanced`/`ai`/`admin` keep them on. Confirm via `GET /api/system/profiles`.

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

- [ ] **BUG-2b.2 — build the drag-drop workflow canvas, or drop it from the backlog (BACKLOG.md
  line 2206).** Recounted 2026-08-28: this row has always asked for *frontend tests* of a visual
  drag-drop SVG canvas (pointer events, node layout, edges), scoped to "ride with" H10.2 (Visual
  Workflow Trace Overlay) and H10.7 (AI-Assisted Workflow Builder). Both of those shipped **as
  backend-only features** — a trace-data endpoint and an LLM step-config generator — neither built
  a visual node-and-edge canvas. The actual HUD `WorkflowsPanel`
  (`frontend/src/gap.tsx:1104`) is a plain list-with-run/delete-buttons panel, and the AI Step
  Builder panel explicitly outputs JSON meant to be "paste[d] into the workflow builder" — there is
  no drag-drop canvas anywhere in the frontend to write pointer-event tests against (verified: no
  `WorkflowCanvas`/drag-handler component exists in `frontend/src`). So this isn't a missing-test
  gap, it's a missing-feature gap wearing a test-coverage row. Two honest paths, and only you can
  pick: **(a)** commission the visual canvas as new scope (a real frontend feature, sized well
  beyond "add tests" — treat it as a fresh spec, not a BUG-2b sub-item) and then BUG-2b.2 becomes
  real work again, or **(b)** explicitly drop BUG-2b.2 from the backlog since Jarvis has shipped
  without a visual node-graph editor for its whole life and the JSON-paste workflow works today.
  Either answer just needs to be *written down* in `BACKLOG.md` so the row stops silently reading
  as "ambiguous."

- [ ] **T-0.29 signed installers — needs your code-signing certificates (nothing an agent can do).**
  The PWA half of 0.29 shipped 2026-08-28 (the v2 HUD is now installable with an offline shell).
  The other half — *signed* desktop installers — is blocked on credentials only you can obtain:
  `desktop/src-tauri/tauri.conf.json` has a bare `bundle` block with no `signingIdentity`,
  `certificateThumbprint`, or notarization config, and no signing secrets exist in CI. To unblock:
  **(a)** an Apple **Developer ID Application** certificate + an app-specific password for
  notarization (macOS), and **(b)** a **Windows OV or EV code-signing certificate** (EV avoids
  SmartScreen warm-up; OV is cheaper but users see warnings until reputation builds). Both are paid,
  identity-verified purchases in your name — an unsigned installer is not a bug to fix in code, it
  is a missing legal identity. Once you have them, store them as repo secrets and an agent can wire
  the Tauri signing config + a release workflow in one bounded slice. Until then, the honest
  position is: we ship an unsigned bundle and say so.

- [ ] **E731-CONTINUITY-IDENTITY — does Jarvis's own continuity identity get its own tracked issue?**
  (BACKLOG.md, "B3/Continuity Core mapping" section). `docs/nerva2/CONTINUITY_CORE_RECONCILIATION.md`
  found that #762/E4 only covers **Howard's** preference-prediction scope — nothing currently tracks
  Jarvis's own Identity Manifest (a versioned/signed identity-history contract with migration and
  rollback, the way #731 originally asked for it). The reconciliation doc explicitly declined to
  create that destination unilaterally, calling it "an owner-scoping decision... not a documentation
  call this pass should make." Recounted 2026-08-28: still true, no later commit filled the gap. Your
  call: open a new issue scoped to Jarvis's own continuity identity, fold it into #762's scope
  (broadening what that issue owns), or explicitly decide this isn't worth tracking separately from
  the existing SOUL/persona system. Whichever you pick, a one-line note back in `BACKLOG.md` closes
  the row.
