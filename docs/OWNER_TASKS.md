# Owner tasks — things only Andrei can do

> The **feature** backlog is delivered — that's **v0.10.0**. The road to 1.0 is the productionization
> layer (**H23** in [BACKLOG.md](../BACKLOG.md#version-roadmap)) plus real design-partner users; this file is
> the **owner lane** running alongside it — the human-gated bits (real hardware, GitHub settings, legal,
> decisions) that only Andrei can do. Ordered queue. Created 2026-06-10 · check items off as you go.
> *2026-07-14: the 1.0 **tag** additionally requires both the AI-OS implementation program
> ([NERVA_VISION.md](../NERVA_VISION.md), ORIZONT 27–33) and its real-host v1 proof. BACKLOG A8
> names that owner-only hardware gate explicitly; hermetic reality packs do not clear it.*
> *Superseded 2026-08-28 (owner: "gates removed"; confirmed 2026-09-01; frozen 2026-09-02): the tag is
> two owner commands — the A5 licence flip, then `git tag v1.0.0` on `main` — the capability program is a
> 1.x roadmap, and A8 was cleared by the owner on 2026-08-28 (see the A9 item below).*

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
  - (3) ✅ decided 2026-09-01 (owner): sampling rule + source window —
    `consecutive-distinct-eligible-tasks` over `2026-08-01T00:00:00.000Z..2026-08-31T23:59:59.000Z`,
    `role=user` turns of the persisted conversation transcripts in timestamp order; predeclared
    exclusions (non-task turns, duplicates of an already-selected task, turns the label-set loader
    cannot hold verbatim — excluded, not normalised). Rule text verbatim in
    [`docs/nerva2/CORTEX_E1_2.md`](nerva2/CORTEX_E1_2.md) § Owner decisions for E1.2b (2026-09-01).
  - (4) ✅ decided 2026-09-01 (owner): retention policy **`owner-local-e1-2-v1`** for all five
    artifact classes (owner's own OS account on the owner box only, one git-ignored local directory
    excluded from backups, kept until the owner deletes them, secure deletion of every copy;
    raw-prompt artifacts and digests never copied/quoted/published — aggregate counts and
    privacy-minimised report text may be shared). Terms in `CORTEX_E1_2.md` § Owner decisions.
  - (5) ✅ permitted 2026-09-01 (owner): exactly **one** owner-local measured run (one warm-up +
    five retained runs via the documented Python API, current router, pinned `main` commit,
    results persisted to the owner-local E9 store under `owner-local-e1-2-v1`) — conditional on
    inputs 1–4 being present in the label file and the policy's filesystem controls being in place.
    Evaluation-only: its report earns no E1, B2, program or release decision by itself.
  - Still yours: input 1 (the ≥20-task dataset) and input 2 (acceptable routes/categories per
    case) are written together at the desk; this box stays open until the run has actually executed.
- [x] **A9 — tag v1.0.0** — ✅ done 2026-09-02: `v1.0.0` tagged, GitHub Release published (`release.yml` run 2 green). (in this order, after the A5 relicense PR merges; `main` is feature-frozen
  for 1.0 since 2026-09-02 — [decision doc](decisions/2026-09-02-cto-ci-posture-and-1.0-freeze.md)):
  (1) fold `CHANGELOG.md` `[Unreleased]` into `[1.0.0]` and set its date (the #981 de-gate entry
  has accumulated above the cut section); (2) check the `release.yml` `workflow_dispatch` `dry_run`
  triggered 2026-09-02 by the coordinator — the workflow has never run on GitHub before; (3)
  `git tag v1.0.0 && git push origin v1.0.0` on `main`. Findings from the post-tag §0 run are 1.0.1.
- [ ] **Run the manual-test runbook on the RTX box** — [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md),
  full pass incl. §0 sign-off and the ⭐B0 governed-autonomy demo. *Ordering decided 2026-09-01
  (owner, confirming the 2026-08-28 "gates removed" directive in BACKLOG.md): the v1.0.0 tag is
  two owner commands — the A5 licence flip, then the tag on `main` — and this runbook is
  **post-tag proof**, not a tag precondition; the §0 run record is still owed*
  ([GO_LIVE_PLAN](../GO_LIVE_PLAN.md) §launch checklist).
- [ ] **Dispatch the 72h soak — needs a self-hosted runner, which only you can register.**
  *Why this is yours and not an agent slice:* `soak.yml`'s real lane is `workflow_dispatch` with
  `runner` pointed at a **self-hosted label**, because a GitHub-hosted runner is capped at ~6h of
  wall clock. Registering that runner is repo-settings + your hardware; nothing an agent can do.
  *Current state, measured 2026-09-04:* the workflow has **one run in its entire history** — the
  weekly canary, 2026-08-30, `schedule`, a 90-minute window, PASS
  ([run 33295821935](https://github.com/andrei649/jarvis-hub/actions/runs/33295821935)). The
  workflow landed 2026-08-28, so that is the one Sunday it has had. **The 72h window has never
  run.**
  *What it costs you:* register a self-hosted runner on the box, then Actions → Soak → Run
  workflow with `duration: 72h`, `interval: 5m`, `runner: <your label>`. The job is unattended —
  `scripts/soak_report.py --fail-on-verdict` grades it (PASS 0 · FAIL 1 · INCONCLUSIVE 3) and
  publishes the report plus evidence to the run summary. No read-through, no sign-off.
  *What it unblocks:* the **Burn-In** half of the `0.90–1.0 gates` row in
  [`BACKLOG.md`](../BACKLOG.md) (the A2 *gate* was removed by your 2026-08-28 directive, but the
  window itself has still never been executed), and criterion (c) of the Action-Kernel
  default-rail decision
  ([2026-09-01](decisions/2026-09-01-action-kernel-default-rail.md)) — one 72h PASS soak with
  both `JARVIS_ACTION_KERNEL` and `JARVIS_UNIFIED_ACTION_API` on.
- [ ] **HUD v2 runtime verification** — `python serve.py`, open `/`, click every mode + every
  Console (▦) panel against the live backend ([`docs/design/HUD_V2_REMAINING.md`](design/HUD_V2_REMAINING.md) §0).
  The mock-fallback design hides wrong-but-not-failing wiring; the 2026-06-10 depth pass (PR #181)
  shipped ~16 new control surfaces that have only been verified offline (tsc + mocked tests).
- [x] **A8 — AI-OS v1 owner-host proof** — ✅ **cleared by the owner 2026-08-28** (the owner-host
  proof run on real hardware came back with good feedback; A8-iv closed independently on `main` in
  #946 + #972) — **no longer a blocking release gate**. Original ask, kept for the record: run
  [`docs/MANUAL_TESTING.md`](MANUAL_TESTING.md) §N on the isolated RTX/Windows host and real
  household integrations, separate from code-complete H28–H33 and their hermetic reality packs, proving:
  installed Chromium + Windows UIA through the governed browser/desktop path; live Home Assistant
  state projected into the device/room/occupant/presence graph plus a safe governed actuation; a
  consented Frigate event flowing through house/memory/ambient without raw-frame egress;
  presence-aware Media Director delivery on at least two non-chat output surfaces/device classes;
  and one approved acquisition-to-reuse loop. Record build SHA plus redacted task/audit/device
  evidence in the §0 run record (never secrets, household identifiers, or raw camera frames).
- [x] **Dependabot: 54 vulnerabilities on main** — ✅ fixed 2026-06-10 (agent wave): HUD
  frontend 5→0 (vite 7/vitest 4), worldview 13→2 (fastify 5, next 16.2.9 + react 19,
  vitest 4, tsx), mcp 2→0; all suites green (HUD 19, WV frontend 101, backend 218).
  - [ ] **Remaining, needs you (re-measured offline 2026-09-02; the 2026-07-07 re-audit and its
    #634 fixes — frontend `undici`, worldview/mcp `hono` ×5 + `esbuild` — are history):**
    `npm audit --omit=dev` today: **frontend 0** · root `package-lock` (HUD-test tree) **5 (2 high)**
    · **worldview 3 high** · **worldview/mcp 5 (2 high)** · **mobile 21–22 (10–11 high)**; Python
    `requirements.lock` clean (`pip-audit`). The worldview, worldview/mcp and root trees are all
    `fixAvailable` and are being fixed by the 2026-09-02 dependency audit wave (engineering, not
    you). Still yours: (a) **mobile/** — the Expo SDK chain. The gate was *tested* 2026-07-07: a
    non-forced `npm audit fix` bump broke `tsc` in the audio path (`expo-audio`
    AudioPlayer.addListener), so it truly needs the SDK upgrade + real-device validation;
    (b) **read GitHub's own Dependabot count** — the figures above are offline measurements, the
    alert count on the default branch has not been read since the 2026-08-28 UI snapshot (35 / 22
    high in the handoff): Security tab, or
    `gh api repos/andrei649/jarvis-hub/dependabot/alerts?state=open`; (c) dismiss the stale alerts
    in the GitHub UI once the audit wave merges.
- [x] **Relicense MIT → Apache-2.0** — ✅ done 2026-09-02 (#1012). — decided 2026-06-04, deferred to pre-1.0
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

- [ ] **Let Actions open PRs — one checkbox, and it un-reds a weekly workflow** (found 2026-09-04
  while triaging red scheduled lanes). **Settings → Actions → General → Workflow permissions →
  tick "Allow GitHub Actions to create and approve pull requests."** If the account sits under an
  org, the org-level toggle has to allow it first.
  **What is broken.** `Third-Party Auto-Update` (`.github/workflows/thirdparty-autoupdate.yml`,
  Thursdays 07:00 UTC) does all of its real work correctly — `discover` finds the drifted sources,
  each `update` job re-vendors, bumps the pin, passes `check_thirdparty_drift.py --consistency`,
  and force-pushes its per-source branch to origin. It then dies on the last step, when
  `peter-evans/create-pull-request` calls the REST API with the workflow token:
  `GitHub Actions is not permitted to create or approve pull requests.` The
  `permissions: pull-requests: write` already in the YAML is necessary but **not** sufficient —
  that repo/org toggle overrides it for `GITHUB_TOKEN`. Nothing in the repo is at fault and there
  is no code fix; this is why it is here and not in the backlog.
  **Scale.** 8 of 11 runs have failed this way (2026-07-02 → 2026-09-03, latest
  [33751779652](https://github.com/andrei649/jarvis-hub/actions/runs/33751779652)); the 3 "green"
  runs are ones where nothing had drifted, so the `update` job was skipped entirely. The lane has
  therefore never once delivered its output.
  **Note the side effect:** the update branches *are* on origin already — the work exists, only the
  PR is missing. After you tick the box the next scheduled run opens them.
  **If you would rather not flip the global toggle:** a fine-grained PAT with contents +
  pull-requests write on this repo, stored as a secret and passed to the action as `token:`, does
  the same job with a narrower blast radius. That one is a code change and I can do it — say which
  you prefer.

- [x] **De-gate merges (decided 2026-08-29 — remove the branch-protection gates)** — ✅ the repo
  half shipped in #981 (merged 2026-08-30 09:09 UTC); that merge going through indicates the
  required checks no longer block. *If you merged it via admin bypass rather than clearing the
  settings, the sub-items below still apply to every future PR.* **Reversible:**
  [`docs/restore/`](restore/README.md) keeps every removed gate as an independent patch —
  restore one gate or all of them, with the exact check names to re-add here. Original task:
  - [ ] Remove **all required status checks** — the names to drop: `test (windows-latest)`,
        `nerva-movement`, `boundary`, `review (correctness)` / `review (boundary)` /
        `review (tests)`, `Secret scan (gitleaks)`, `SAST (semgrep)`, `SAST (bandit — blocking gate)`,
        `Dependency audit (pip-audit)`, `in-sync`, `parked-modules`, `validate`, `Analyze (python)` /
        `CodeQL`, `sandbox-isolation`, `signal-layer-smoke (…)`, `frontend`, `hud-v2-build`,
        `openapi-types`, `e2e`, `server-boot`, `analyze`, `drift` — *except the four below, which
        came back on 2026-09-02.*
  - [ ] **Mark the four re-gated PR checks required (CTO D1, 2026-09-02 —
        [decision doc](decisions/2026-09-02-cto-ci-posture-and-1.0-freeze.md)):**
        `test (ubuntu-latest)` (ruff + pytest + the tracked-test-count drift step), `hud-v2-build`
        (committed-bundle staleness), the security-scans lanes (`Secret scan (gitleaks)`,
        `SAST (semgrep)`, `Dependency audit (pip-audit)`, `SAST (bandit — blocking gate)`) and the
        lockfile-drift lane (`in-sync`). Until you list them they are advisory only — and
        `pr-auto-merge.yml` merges any non-draft PR GitHub reports CLEAN, hourly, with no review.
  - [ ] Turn off **Require review from Code Owners** and any required-approvals count
        (CODEOWNERS was deleted).
  - [ ] Delete the **CodeQL merge-protection ruleset** if one exists (code-scanning merge rule).
  - [ ] Keep **Allow auto-merge** on — `pr-auto-merge.yml` still sweeps hourly and squash-merges
        any non-draft PR GitHub reports as clean.
  > If a PR is stuck at "Expected — Waiting for status to be reported", that is this task not yet
  > done: see [`MAINTENANCE_RUNBOOK.md`](MAINTENANCE_RUNBOOK.md) §10.
- [ ] **Repo description + topics + social preview** — paste-ready strings in
  [`docs/BRAND_BOOK.md`](BRAND_BOOK.md) §9 (current description is just "Personal AI").
- ✅ **Code scanning** — resolved 2026-08-31, nothing left here. The repo is public, code scanning is
  enabled and SARIF upload succeeds (run 33384718270: *"Analysis upload status is complete."*), so the
  old code-scanning-unavailable failure is gone and the workflow no longer swallows analysis
  errors. Settled posture: **CodeQL = advisory, push-to-main + weekly, not required, fails
  loudly on analysis/upload errors.** The one remaining owner action is already tracked above —
  drop `Analyze (python)` / `CodeQL` from required status checks and delete the code-scanning
  merge-protection ruleset.
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
- [x] **(optional) Wire a bare "Max" on the GitHub side** — ✅ decided 2026-09-01 (owner): **no
  bare-`Max` trigger**; `@claude Max` via `claude.yml` stays the only comment trigger, no second
  workflow or label trigger gets added. Background: the workflow half landed in
  #976: [`.github/workflows/claude.yml`](../.github/workflows/claude.yml) runs Claude Code on any
  **`@claude`** comment in an issue, PR, or review, authenticated by the `CLAUDE_CODE_OAUTH_TOKEN`
  repo secret (subscription auth — no `ANTHROPIC_API_KEY`, no GitHub App install needed). That run
  checks the repo out, so it reads `CLAUDE.md` and `.claude/skills/max/`: **`@claude Max`** is the
  intended no-session trigger path. A *bare* `Max` comment still does nothing — the action's
  `trigger_phrase` defaults to `@claude` and accepts a single phrase, so bare-`Max` would need a
  second workflow with `trigger_phrase: Max` (or `label_trigger`) — declined, not worth the extra
  surface for five characters.
- [ ] **Post the first real `@claude` comment** (verifies `claude.yml` + `CLAUDE_CODE_OAUTH_TOKEN`)
  — unverified until first use: comment triggers are read from the default branch, so #976's CI
  could not exercise the workflow. The first real `@claude` comment is also the first test of
  whether `CLAUDE_CODE_OAUTH_TOKEN` is set correctly.

## 🟡 GPU-host work (the last 2 backlog items + Howard)

- [ ] **H12.14** — small fine-tuned agentic model (SFT/GRPO) — runbook [`docs/GPU_RUNBOOK.md`](GPU_RUNBOOK.md).
- [ ] **H13.3** — speculative decoding (draft Qwen3-4B → target 32B); config-only, output-identical.
- [ ] **TASK-1** — Howard's first real run: needs *your* data export (conversations → `memory_logs/learning/*.jsonl`),
  then the dedicated backend + ingestion run.
- [ ] **LM Studio end-to-end** — validate `lms server start/load/unload` against the real binary
  on the 5090 box (current coverage is mock-only), incl. the new HUD Admin → LM STUDIO panel.
- [ ] **GAP-4 / DRA-45 — the Hermes head-to-head (~1 day)** — protocol, tasks and pass/fail bars are
  written and frozen: [`docs/HERMES_HEAD_TO_HEAD.md`](HERMES_HEAD_TO_HEAD.md) (status: **NOT RUN**).
  Blocked on the Hermes licence/CVE/SBOM review in the Parking lot below — that decision must clear
  before Hermes is pulled or installed. Feeds S1/S2; publish the table **including the losses**.
- [ ] **Live-mic validation** — HUD voice loop + barge-in tuning need a real microphone
  (PR #162/#164 caveat), incl. Wyoming satellite if you set one up.
- [ ] **Wall-screen room validation (briefing wall)** — the `brain` cinema stage was built from
  reference video and verified only in a headless browser. On the real wall screen, check:
  (a) legibility of the hairline chrome and region chips at your actual viewing distance;
  (b) mic placement — HOLD TO TALK captures usable audio from where you stand, not just at the desk;
  (c) echo/feedback when the reply plays through the TV or soundbar while the mic is open;
  (d) **the privacy call — DECIDED 2026-09-01 (owner):** never visible with other people present.
  The spoken-line transcript stays HIDDEN by default on every screen
  (`TRANSCRIPT_DEFAULT_VISIBLE=false` in `frontend/src/wall.tsx`); the existing per-screen
  one-click toggle is an owner-alone-in-the-room convenience only; no per-room allowlist or
  config gets built.
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
- [ ] **`house.presence_enabled`** (or env `JARVIS_HOUSE_PRESENCE=1`) — GAP-9: the
  production presence writer, feeding Home Assistant `person.*`/`device_tracker.*`
  + room motion sensors into the strict-local presence inference on every
  `/api/house/state` read. Room presence is only claimed when identity AND
  same-room motion corroborate (the model's anti-overclaim floor); the route's
  `presence_status` field reports off/live/degraded separately from the array.
  Needs `house.enabled` + `house.ha_enabled` first.
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
  - [x] **History caveat (your call):** the personal details remain visible in old git
    commits (the repo was public throughout). A full scrub needs a history rewrite
    (BFG/filter-repo + force-push) — disruptive, and forks/caches may retain copies anyway.
    ✅ decided 2026-09-01: **accept** — no history rewrite, no BFG/filter-repo, no force-push;
    already-public, HEAD-equivalent facts are gated by `NERVA_PUBLIC_PROFILE`.

## 🟣 Production-verification checklist — what has never run for real

> **This is where the unproven/proven line is drawn.** On 2026-09-07 the owner decided that
> verification happens in production, and [`BACKLOG.md`](../BACKLOG.md)'s 64 🔨 rows became ✅
> **delivered**. That flip changed the ledger's marker, not the facts: everything below has still
> never executed against real hardware, a real credential or a real network, and CI cannot tell you
> otherwise — a container proves nothing about a keycode table, a code-signing certificate or a
> vendor's rate limiter.
>
> So this list is the honest counterweight to a file that now reads all-green. Each packet says what
> only you can do, the exact commands, and which rows it covers. Every flag named is default-off — see
> [`FLAGS.md`](FLAGS.md) for what each one costs — so nothing here is running until you turn it on.
>
> **What it covers, stated rather than implied.** P1–P10 came out of the 2026-09-06 wave and name
> about 18 rows between them. That left roughly forty flipped rows with no entry at all — including
> every one of the 33 WorldView `H19.x` rows, the WLED bridge and the container quickstart — so the
> first version of this section claimed a completeness it did not have. P11–P14 close that gap:
> **P11** WorldView (live feeds + the rescoped scale gates), **P12** the WLED strip, **P13** the
> docker quickstart, **P14** the Nerva 2.0 rows that need a *reviewer attestation* rather than
> hardware. **P15**–**P20** (2026-09-07) are the first packets from the Hermes absorption: the
> tool loop on each cloud provider and on Ollama, built from documented contracts and never sent
> to a real one; the Telegram group gate, never exercised in a real group; the `nerva`
> command plus the chat slash commands, never pointed at a running hub; the owner's
> scheduled jobs, never fired on a wall clock; the model's hands (`file_search`,
> `session_search`, the loop breakers), never driven by a model choosing to use them; and the
> Telegram renderer, never shown to the real API.
> If you flip a row to ✅ and its proof still depends on something only you can run, it
> belongs here — that rule is written into
> [`docs/prompts/BACKLOG_DRIVER.md`](prompts/BACKLOG_DRIVER.md) so an unattended session applies it.
>
> **Read the risk asymmetrically.** Most of these fail loudly and cheaply the first time you use
> them: a wrong credential is a 401, an unreachable strip is `wled_unreachable`, a missing binary is
> a named refusal. Two do not, and they are worth doing before the first real use rather than
> during it:
>
> - **P9 (keycode tables).** The macOS and Linux desktop drivers send OS-level input from tables
>   derived from documentation, not from an observed keypress. The chord allowlist that refuses
>   `ctrl+alt+delete` and `cmd+alt+escape` is keyed on the *canonical* form of those chords — if a
>   platform's table maps a key differently than the docs say, a refusal can miss and the wrong
>   chord gets pressed on your machine. That is a fail-silent path, and it is the one item here
>   where "find out in production" means finding out by having it happen to you.
> - **P10 (published packages).** A Homebrew cask, a winget manifest and a public GHCR image are
>   things other people install. A mistake there is not yours to discover privately.
>
> Everything else on this list is genuinely fine to learn in production.

- [ ] **P1 — Local terminal on your box** *(unblocks `OP-TERM-1`, `OP-TERM-3`)*
      Only you have a host worth running commands on; CI has a container that proves nothing about
      process groups, PATH resolution under a scrubbed env, or the Windows Proactor loop.
      ```bash
      export JARVIS_TERMINAL_TARGETS=1 JARVIS_ACTION_KERNEL=1 JARVIS_TERMINAL_LOCAL_HOST=1
      export JARVIS_TERMINAL_LOCAL_ROOTS="$HOME/work"      # optional; default is <data root>/workspace
      # restart the hub, then from the HUD approve one terminal_run task for target `local-host`:
      #   argv: git status
      ```
      **Confirm three things:** (a) the command ran and its output came back; (b) an audit entry
      exists in `data_path('environments','target-audit.jsonl')`; (c) `rm -rf /` is refused
      `hardline_denied` **with no audit entry and no spawn**. If you are on Windows, also run one
      path-quoted command (e.g. `cmd /c dir "C:\Program Files"`) — `parse_argv` is posix-shlex with a
      backslash tweak and unusual Windows quoting is the one thing the hermetic suite cannot settle.
      *Blocked on:* the kernel registration + coordinator binding (integrator I1) landing first —
      until then the backend refuses `kernel_unavailable` / `approval_check_unbound` even with the
      flags on. That is honest, not a bug.

- [ ] **P2 — Pinned browser transport against a real Chromium** *(unblocks the live half of `SEC-B4`)*
      The resolver-rule semantics and `aria_snapshot(boxes=True)` are pinned from documentation, not
      from a running browser.
      ```bash
      pip install playwright && python -m playwright install chromium
      export JARVIS_PLAYWRIGHT_HOST=1
      # run one governed navigate to an allowlisted public host
      ```
      **Confirm three things:** (a) the launch args contain
      `--host-resolver-rules=MAP <host> <ip>, MAP * ~NOTFOUND`; (b) a redirect to an off-list host
      lands in `driver.blocked_requests` with a named reason; (c) `observe_snapshot()` returns
      elements with `rect` populated on Playwright ≥ 1.60 (`boxes=True`) or `rect=None` on older
      runtimes — either is correct, we just need to know which. *No longer blocked:* the
      `GovernedBrowser.run_step` navigate edit landed, so with `JARVIS_PLAYWRIGHT_HOST=1` an
      allowlisted navigation now reaches the driver instead of refusing
      `browser transport not configured`.

- [ ] **P3 — Visual grounding with a real grounder** *(unblocks `OP-VISUAL`)*
      Each preset's coordinate convention comes from published model notes. Only a real screenshot
      round-trip proves it, and a wrong preset mis-clicks.
      ```bash
      export JARVIS_VLM_BACKEND=lmstudio JARVIS_VLM_MODEL=<served name>
      export JARVIS_VLM_PRESET=<matching preset>
      export JARVIS_DESKTOP_HOST=1 JARVIS_DESKTOP_ISOLATED=1     # isolated desktop box only
      # POST a `locate` step for a control that is MISSING from the a11y tree
      ```
      Do it **twice** — once with a `relative_1000` preset (`qwen3-vl-8b`) and once with an
      `absolute_resized` one (`ui-tars-1.5-7b`) — and report whether the returned `(x, y)` landed on
      the control. If a server re-resizes internally (UI-TARS `smart_resize` to multiples of 28), the
      offset shows up here and the fix is a per-model resize rule in the preset table.

- [ ] **P4 — One real model pull on the RTX box** *(unblocks `MS-2`; the second half unblocks `MS-1`)*
      ```bash
      export JARVIS_MODEL_PULL=1 JARVIS_UNIFIED_ACTION_API=1 JARVIS_ACTION_KERNEL=1
      # GET /api/onboarding/model-plan   → confirm the card and the 24gb+ rung
      # POST /api/onboarding/model-pull  → approve, then: ollama list
      ```
      **Confirm:** (a) the plan reports the right rung; (b) the Ollama tag for that rung actually
      resolves in the Ollama library — `gemma-4-31b-a4b` is the spec's name and was **not** verified
      against a live registry; if it differs, that is a one-line `TIERS` edit; (c) the pull lands and
      `ollama list` shows it. Installing the Ollama runtime itself stays your step — the code only
      detects a loopback Ollama and otherwise reports `ollama_unreachable` with the URL.
      *Optional, same lane —* on any Apple Silicon or ROCm machine:
      ```bash
      python -c "from agents.core import hardware; print(hardware.detect_gpu(force=True))"
      ```
      Confirm `kind=apple` / `kind=amd` with a plausible `vram_total_mb`, then `MS-1` flips to ✅.

- [ ] **P5 — Arm the live rails, one at a time** *(unblocks `T-0.66`, `H10.30`, `H12.21`, `H12.22`, `H12.25`)*
      Every one of these is a *real* external write, post or phone call — after your approval. Store
      the credentials first; the brokers refuse `credential_not_configured` rather than sending an
      unauthenticated request.
      **In the SecretBroker:** `<target>_token` for linear / asana / trello / todoist / clickup /
      gsheets / m365 (Trello additionally `trello_api_key`); `notion_api_key`, `github_token`,
      `google_oauth_token` (H10.30); `x_api_token` (social); `twilio_auth_token` **or**
      `telnyx_api_key` (calls).
      **For calls, also:**
      ```bash
      export JARVIS_CALL_CONFIG='{"twilio": {"account_sid": "AC…", "from": "+1…"}}'   # or telnyx connection_id/from
      export JARVIS_CALL_LIVE=1
      ```
      Otherwise the broker refuses `call_config_missing:<keys>` before spending an interrupt-budget
      slot. **Decide per rail** whether to set `JARVIS_WRITEBACK_LIVE` / `JARVIS_SOCIAL_LIVE` /
      `JARVIS_CALL_LIVE`; all three default off and every send still requires an approved ask-tier
      task. *Note:* until the integrator registers `create_task` / `task.create` in the executor,
      approved transcript tasks fall through to the LLM fallback instead of creating the item.

- [ ] **P6 — MCP: connect Claude Desktop / Cursor, and (separately) let the hub call out**
      *(unblocks the live half of `H10.5`; makes `DRA-25`'s transport reachable from the admin UI)*
      **Client → Nerva** (no cloud hop, stdio only):
      ```jsonc
      // Claude Desktop config
      {"mcpServers": {"nerva": {"command": "python",
                                "args": ["<repo>/scripts/nerva_mcp_stdio.py"],
                                "env": {"JARVIS_USER_TOKEN": "…"}}}}
      ```
      Prerequisite on the hub: `mcp.server_enabled=true`. The token goes in the client's `env`
      block, **never** in argv. The bridge widens no hub gate. It has been tested against a fake hub
      route, not a live process — your run is the proof, and the Windows console fallback in
      `open_stdio_streams` is untested on Windows.
      **Nerva → a remote MCP server** (this *is* an outbound cloud hop — opt in deliberately):
      ```bash
      export JARVIS_MCP_HTTP_CLIENT=1
      # then configure {"transport": "streamable-http", "url": "https://…/mcp"}
      ```
      Waits on the integrator's `routers/mcp.py` admin-API edit; until then configure it through
      `MCPManager.load_from_config`. Bearer headers are in memory only — re-supply them after a
      restart.

- [ ] **P7 — The hosted install one-liner needs a domain (and a public repo)**
      *(unblocks `install-one-step-native`'s hosted path)*
      `docs/INSTALL.md` and `README.md` currently document
      `curl -fsSL https://raw.githubusercontent.com/andrei649/jarvis-hub/main/install.sh | bash`.
      That URL only works once the GitHub repo is **public**. The nicer end state is a hosted
      install domain — `install.nerva.<tld>` → the raw `install.sh` — which is DNS plus a redirect,
      both yours. Until one of the two is true, the one-liner is documentation, not a path.
      *Also unproven, and only you have the hardware:* `install.sh` / `INSTALL.bat` / `START.bat` /
      `install.ps1` were syntax-checked and their Python was tested hermetically, but never executed
      end-to-end on real Linux / macOS / Windows. Run each once on a clean box.
      *And a small follow-up nobody owns yet:* `UPDATE.bat` still installs from the loose
      `requirements-beta.txt` and runs the full pytest suite; replacing its steps 3–4 with
      `!PY! scripts\\bootstrap.py --skip-smoke` reuses the venv and installs from the hash lock.

- [ ] **P9 — The operator's keyboard, on each machine you own** *(unblocks the live half of
      `OP-DESKTOP-KEYS` and `op-windows-backend`)*
      `key`, `scroll` and `focus` are pinned against documentation and a fake adapter. The chord
      allowlist and every refusal are settled by the hermetic suite; what it cannot settle is
      whether a chord *arrives* — the keycode tables, `{VK_LWIN down}`, AT-SPI's
      `generateKeyboardEvent` and CGEvent flags are all things a machine has to confirm.
      ```bash
      export JARVIS_DESKTOP_HOST=1 JARVIS_DESKTOP_ISOLATED=1 JARVIS_ACTION_KERNEL=1
      export JARVIS_UNIFIED_ACTION_API=1
      # restart the hub, open a scratch text editor, and approve these desktop_step tasks:
      #   {"action": "focus",  "args": {"name": "<the text area's accessible name>"}}
      #   {"action": "key",    "args": {"chord": "ctrl+a"}}       # cmd+a on macOS
      #   {"action": "scroll", "args": {"name": "<a scrollable list>", "direction": "down"}}
      ```
      **Confirm four things:** (a) the chord actually took effect in the editor — not that the call
      returned `ok`, which it will even if nothing arrived; (b) **no modifier is left held** —
      immediately type a letter afterwards and check it is lowercase and unmodified, because a stuck
      modifier is the failure mode that outlives the step and quietly corrupts everything the owner
      types next; (c) `{"chord": "cmd+q"}` (or `alt+f4`) comes back `chord_refused_by_policy` and
      your app is **still open**; (d) `{"direction": "down", "notches": 500}` comes back
      `scroll_notches_out_of_range` and nothing scrolled. Do this on **each** OS you have — the
      three keycode tables are independent, and a wrong entry sends a different key than the card
      named, which is the one failure worse than sending none.
      *Report back:* which OS, and for (a) exactly which chords arrived. If a chord silently does
      nothing, that is a mapping bug worth a row, not something to work around.

- [ ] **P10 — Publish the two package-manager channels** *(unblocks the live half of
      `REL-CHANNELS`)*
      The cask and the winget manifests are generated on every tagged release, from the
      checksums that release actually produced, and attached to it (`dist/packaging/*`). What
      only you can do is create the two places they get published to — both are free, and both
      turn "clone the repo" into one command.
      **Homebrew:** create a public repo named **`homebrew-nerva`** under your account. That name
      is what makes `brew tap andrei649/nerva` work; any other name will not. Then, per release,
      copy `nerva.rb` from the release assets into `Casks/nerva.rb` and push.
      ```bash
      brew tap andrei649/nerva && brew install --cask nerva
      ```
      **winget:** fork `microsoft/winget-pkgs`, copy the three
      `Nerva.Nerva.*.yaml` files into
      `manifests/n/Nerva/Nerva/<version>/`, and open a PR. First submission is reviewed by a
      human and takes a few days; later ones are usually automatic.
      **Confirm three things:** (a) `brew install --cask nerva` on a Mac you have not installed
      on before ends at a working `./install.sh`; (b) the sha256 in the cask matches the release
      asset — if it does not, **stop and report it**, because that means the generator and the
      build disagree and every user would hit a corrupt-download error; (c) a **prerelease** tag
      (`v1.1.1-rc1`) does **not** move the `stable` cask or the `:stable` image tag.
      *Also needs:* GHCR publishing is on by default for the repo's own `GITHUB_TOKEN`, but the
      package is **private** until you make it public once, in the repo's Packages settings.
      Until then `docker pull ghcr.io/andrei649/nerva:stable` fails for everyone but you — which
      is the single most likely reason a "it works for me" install report is wrong.

- [ ] **P8 — The 72h soak, and the two chaos rows a simulation cannot close**
      *(unblocks the remaining half of `T-0.63`)*
      The failure-injection harness shipped and is green in CI; it **does not replace the soak**.
      Dispatch `soak.yml` (`workflow_dispatch`, self-hosted `runner` label — see the soak item near
      the top of this file, unchanged) and record the verdict.
      *Optional, same box:* a manual pass of **CHA-013 / CHA-014** — a real volume fill and a real
      data-root rename — upgrades those two manual-test rows beyond ⚠️. `disk_full` is simulated by
      the harness and honest about it: it does not intercept `os.open`/`os.write`/`tempfile`, file
      objects or sqlite connections opened before the fault.

- [ ] **P11 — WorldView against real feeds and real infrastructure**
      *(covers the 33 `H19.1.1`–`H19.5.7` rows, the largest block the 2026-09-07 marker change
      flipped, and the one this checklist previously did not mention at all)*
      Every WorldView row is code-complete and offline-tested; none has ingested a real feed or
      been run at the scale its acceptance criteria name. Two separable halves:
      **(a) live sources** — each needs a credential only you can create: OpenSky (OAuth2 client
      id/secret) for ADS-B, AISStream key for AIS, a Space-Track login for TLE, FAA-NOTAM auth for
      the airspace layer. With those set, run the `worldview/` docker-compose so the ingest hop and
      the local Kafka leg execute for real, and confirm the globe renders live points rather than
      the fixture corpus.
      **(b) scale** — WS1/WS5's numbers (KEDA at 50k msg/s, 10k concurrent WebSocket clients, a
      multi-AZ DR game-day, 1M-point tiles) need cloud infrastructure and a budget. The owner
      rescoped these on 2026-09-01 as *opportunistic, off the Nerva 1.x critical path*; that
      rescope stands, and this packet exists so the rows stop being silently uncovered.
      **What is at risk if neither runs:** nothing in production — WorldView is a separate product
      behind its own compose file and is not reachable from the hub's default surface. This is the
      one block on the list where "verify in production" costs nothing, because there is no
      production to break yet.

- [ ] **P12 — The light strip** *(covers `H30.8`)*
      `WLEDBridge` has never addressed a real WLED controller — every test drives a fake transport.
      Set `JARVIS_WLED_URL` to the strip's LAN address, restart the hub, and change the assistant
      state (speak to it) so one `house.control` action crosses the kernel. Confirm three things:
      the strip follows the orb's colour; unplugging it yields `wled_unreachable` rather than a
      guess; and an unchanged scene sends nothing (the no-op path). Then pull the URL back out if
      you do not want it armed.
      *This packet exists because the preamble above uses `wled_unreachable` as its example of a
      failure that is loud and cheap — which was true of the code and false of the coverage: the
      row had no packet at all until now.*

- [ ] **P13 — The container quickstart, actually run once** *(covers `docker-quickstart-loopback`)*
      `docker-compose.quickstart.yml` has never been brought up. `docker compose -f
      docker-compose.quickstart.yml up`, then open the HUD on the published loopback port and send
      one message. It either works in one command or it does not; there is no partial credit, and
      it is the first thing a new user runs.

- [ ] **P14 — Program acceptance (a reviewer, not hardware)** *(covers `B2`, `B4`/`nerva.ledger.v1`,
      `E1.3`, `E2.1`+`E3.2`, `E4.1`/#1008, the Continuity Core suite)*
      **These are on this list for a different reason than everything above** — they need no
      credential and no device. They are *delivered, not program-accepted*: the Nerva 2.0 manifest
      cannot be self-accepted, so each needs an attestation from a reviewer who is not the builder
      (the pattern used for the four attestations in
      [`docs/nerva2/attestations/`](nerva2/attestations/)). Nothing about production use closes
      them; only a review does. They are listed here so the count of ✅ rows with an outstanding
      obligation is honest, not to imply you must run something.

- [ ] **P15 — Tools on a cloud model, once per provider** *(covers `HA-0.1`, the first wave of the
      Hermes absorption)*
      Until 2026-09-07 an agent routed to Claude, Gemini, OpenRouter or local Ollama had no tools at
      all; the four backends now translate the tool loop into each provider's dialect, but every
      translation was built from the provider's documented contract and exercised only against fakes —
      no request in `tests/test_cloud_tool_turns.py` ever left the container. Set
      `llm.tool_loop_enabled` to true, keep at least one governed tool registered (the default
      `echo`/file tools suffice), then for **each** provider you hold a key for, ask an agent that
      routes there (`athena` is cloud-only; `/model <id>` hot-swaps OpenRouter; a `LOCAL_ONLY_AGENTS`
      member on an Ollama-only box covers Ollama) to *use a tool* — "list the files in the workspace
      root" is enough. Confirm three things per provider: `tool_requested` → `tool_result` events
      appear in the audit chain for that turn; the model's second turn *sees* the result (it quotes
      it, not guesses); and a malformed call, if you can provoke one, ends as `bad_tool_arguments`
      rather than an exception in the log. Two provider-specific checks: on Gemini a thinking model
      must complete a two-step tool exchange without a 400 about a missing thought signature (the
      signature is remembered per call id and echoed — this is the part most likely to drift with
      their API); on Claude, parallel tool calls must come back as one user turn of `tool_result`
      blocks (the API rejects them split). If a provider 400s on the request shape, the failing field
      is the finding — file it against `agents/core/llm/tool_dialects.py`, do not disable the loop.

- [ ] **P16 — The bot in a real group** *(covers `HA-0.4`)*
      Every group-gating decision was exercised against a fake Telegram transport; no real
      supergroup has ever carried a message through it. Add the bot to a group you control with
      privacy mode **off** (so it sees unaddressed messages at all), leave the env defaults
      (`TELEGRAM_GROUP_REQUIRE_MENTION=1`, `TELEGRAM_GROUP_OBSERVE=0`), and check five things:
      a plain message from an allowed member gets **no** reply; `@<bot> status` gets one, and the
      transcript shows `status`, not the mention; a reply to one of the bot's own messages gets
      one; `/status@<bot>` works; and with `TELEGRAM_ALLOWED_CHAT_IDS` set to a *different* chat
      id, even an @mention in this group is ignored. Then set `TELEGRAM_GROUP_OBSERVE=1`, restart,
      send three unaddressed messages and one @mention: the three appear in the session
      transcript as user turns with no bot reply, the mention is answered, and the gateway's
      rate counter for `telegram` moved by one, not four. If the bot answers an unaddressed
      message, check the hub log for the getMe warning first — without its own username it
      cannot recognise a mention, and the fail-closed path is to drop, never to answer.

- [ ] **P17 — The `nerva` command against a running hub, and a slash command on a live channel**
      *(covers `HA-1A`, `HA-1B`)*
      Every online verb was exercised against a recording fake; no request has reached a real
      hub. With the hub up on the box: `python scripts/nerva.py status` (no token) must print
      version, backend and channels; `python scripts/nerva.py approvals list` without
      `JARVIS_ADMIN_TOKEN` must exit 4 and name the token, and with it must list the same items the
      HUD's Decision Inbox shows; `estop engage` then `estop status` then `estop resume` must
      round-trip and the HUD's e-stop chip must follow; `config set llm.skills_in_prompt off`
      must show in /admin within 30 s without a restart; `kernel explain payment --payload
      '{"amount": 120}'` must say QUEUE. Then, on Telegram from the owner account: `/status`
      answers, `/pause` engages the e-stop (the HUD chip turns red), `/resume` lifts it, and from
      a non-owner account `/pause` is refused in words and the e-stop does not move. If a verb
      400s or 422s, the request shape is the finding — file it against `agents/cli/nerva.py`.

- [ ] **P18 — A job that fires on the wall clock** *(covers `HA-2a`)*
      Every firing in the tests is forced (`run` now) against a fake scheduler and a fake
      Telegram; no job has fired at its own time on a running hub. With the hub up and
      `autonomy.owner_chat_id` set: `nerva jobs create --blueprint reminder --param
      "message=this is the job" --when "every 5 minutes"` (the floor), then wait — within six
      minutes the message must arrive on Telegram, `nerva jobs runs <id>` must show an `ok` run
      with "delivered to telegram", and `nerva jobs list` must say the scheduler is alive.
      Then `nerva estop engage`: the next firing must be recorded as `skipped` ("emergency stop
      engaged") and nothing must arrive; `nerva estop resume` and the one after must arrive
      again. Then arm `--blueprint ask_agent --param "prompt=say the time and one word"
      --param agent=friday --when "every 5 minutes"`: the second run's reply should reference
      the first (the notepad is in the prompt). Finally break delivery on purpose (`nerva config
      set autonomy.owner_chat_id ""`, restart): after three firings the job must show
      `paused_reason` starting with "3 consecutive failures", `problems.jsonl` must carry one
      `E_JOB_PAUSED` line, not three, and `nerva jobs resume <id>` must put it back. Delete the
      test jobs afterwards. If a weekday job fires on the wrong day, that is the cron→APScheduler
      day-of-week translation — file it against `jobs.cron_kwargs`.

- [ ] **P19 — The model's hands on a live loop** *(covers `HA-3a`)*
      `file_search`, `session_search` and the two loop breakers are proven against fakes and
      scripted backends, never against a model choosing to call them. With the tool loop on
      (`llm.tool_loop_enabled`), `JARVIS_FILE_TOOLS=1` and a workspace under `JARVIS_FILE_ROOTS`
      holding a few real documents: first drop a `.env` into the workspace containing a phrase
      you know is in exactly one other file, then ask in chat "which file mentions <that
      phrase>". The tool feed must show one `file_search` call, the answer must name that file
      and line, and the `.env` must not appear anywhere. Then "what did I tell you about <a
      thing from an older conversation>": one `session_search` call, and the reply must quote
      the earlier turn's words. Then ask for something the workspace does not contain and
      watch the feed on a local model: the third identical search must come back
      `repeated_call` with the notice, and if the model keeps going the turn must end with
      "kept repeating the same tool call", not with the 8-turn safety limit. If the model never
      picks the tools at all, that is a prompt-catalogue finding (`HA-0.2`), not a tool one.
      Windows: the search skips symlinks and secret names by the same rules but only Linux ran
      the tests — confirm once on a real workspace there. Last, the profile (`HA-3b`): from a
      Telegram account that is *not* on the owner allowlist, ask the same "which file mentions
      …" question — the tool feed must show a `tool_profile` event with `inbound / guest` and
      `file_search` among the withheld names, and the reply must not contain the file's words;
      the same question from the owner's Telegram account must search.

- [ ] **P20 — A long, badly formatted reply on a real Telegram** *(covers `HA-4a`)*
      The renderer and the chunker are proven against Telegram's documented HTML subset and a
      fake client, never against the real API. From the owner's account ask for something long
      and formatted — "write me a 6,000-character guide with headings, a code block and a
      table" — and for something deliberately broken — "reply with exactly: 3 * 4 = 12 and
      **unclosed". The first must arrive as two or more messages in order, headings bold, the
      code block monospaced, nothing cut mid-code; the second must arrive with the literal
      asterisks and nothing missing. If a message shows raw `<b>` tags, Telegram rejected the
      HTML and the plain-text fallback did not fire — file it against
      `TelegramChannel._send_chunk`; if a message is missing, the chunker dropped it — file it
      against `channels/render.py`.

## Parking lot (decisions, no rush)

- [ ] **Is the web HUD a phone surface? — one decision, and it unblocks a nightly that has never
  been green.** Packet refreshed 2026-09-04 against `main` @ `bf48cf2`; the question itself is the
  2026-07-29 call recorded in `BACKLOG.md` → *"The phone surface"*. Nothing about it is engineering-
  blocked — it needs your answer, not more code.
  **Where it stands.** `HUD E2E` runs nightly. It has failed **every scheduled run — 63 of 63**.
  22 cases fail: 12 `mobile-chrome`, 10 `webkit`. The 12 are **4 specs × 3 soak repeats**
  (`E2E_SOAK_ITERATIONS: 3` → `repeatEach`): `a11y.spec.ts:33` plus `hud.spec.ts:87/:123/:153`.
  Only those 12 are yours to decide; the webkit 10 are
  a `page.route` harness defect and are being fixed as ordinary engineering.
  **What was already wrong in the old packet, corrected here.** It said the buttons "intercept
  pointer events", which reads as an overlay bug. There is no overlay: at the Pixel 5 viewport
  `elementFromPoint()` at the button's centre returns the button, and `force`/`dispatchEvent` clicks
  both succeed. The HUD simply lays out wider than the viewport, mobile Chromium shrink-to-fits, and
  Playwright then hit-tests at the wrong coordinates. Numbers, dated so they cannot go stale
  silently: **915px inside 393px, scale 0.43 @ `bf48cf2`**; after the laptop-width topbar fix
  landed on this branch, **640px inside 393px, scale ≈ 0.61**. Narrower, still mismatched, and
  the failing `mobile-chrome` cases still fail with the identical symptom — so there is no
  small fix hiding here — the old packet's instinct was right, its reason was not.
  **The two options, unchanged:**
  - **(A) The phone story is the `mobile/` React Native app.** Then the web HUD is a desktop
    surface, `mobile-chrome` comes out of the Playwright matrix, and the nightly can be green.
    Cost: ~1 slice. Consequence: the HUD is documented as desktop-only and the LAN-access note
    below still needs writing.
  - **(B) The web HUD should also work on a phone.** The earlier estimate here — "a genuine
    responsive slice with design decisions in it (R2)" — **looks too pessimistic, and you should
    know that before choosing.** An A/B test found **four CSS declarations** that turn every
    test in `hud.spec.ts` green under `mobile-chrome` — all six, i.e. the three that fail plus the
    three that already pass — and I verified the load-bearing half myself: with them the layout
    viewport becomes 393px = the visual viewport (scale 1, no shrink-to-fit) and the transmit click
    lands instead of being intercepted.
    ```css
    .main[data-ia="rail"]{grid-template-columns:60px minmax(0,1fr)}
    .badges{flex-wrap:wrap}
    .badge{min-width:0}
    .workzone{overflow-y:auto;grid-auto-rows:minmax(0,auto)}
    ```
    **Read that honestly, though: "the specs pass" is not "the phone experience is designed."**
    Those four declarations stop the cockpit being broken by overflow; whether a stacked desktop
    cockpit is actually *good* on a 393px screen is still a design judgement, and it is yours. What
    has changed is the price of finding out — closer to one small slice than to a redesign.
    Note also that the fourth declaration is the same lever as the separate **≤1100px chat-off-screen
    desktop bug** recorded in `BACKLOG.md`, so option B and that fix may well be one piece of work.
  **Either way, one thing is owed regardless:** the supported LAN path is documented nowhere. A
  `docs/` grep for LAN/remote-access guidance returns nothing, while `serve.py:66` +
  `boot_guards.py:25` + `web.py:192` make reaching the HUD from another device a deliberate,
  token-gated setup. That note should be written whichever way you decide.
  **Not blocking you:** the ≥760px half of the same overflow bug was a plain desktop defect (at
  800/900/1000px the cockpit scrolled sideways) and is already fixed and pinned by
  `frontend/e2e/layout.spec.ts`. That fix stops deliberately at 760px so it does not pre-empt this
  decision.

- [x] **Pick the payment rail — or ratify that there is none** — ✅ ratified 2026-09-01 (owner):
  **no real payment rail for 1.0.** `PaymentBroker.settle()` keeps auditing *"settled (no real
  rail)"*, no money moves, and no AP2/ACP/x402 adapter, `PaymentRail` protocol or `NullRail` gets
  written. **Reopen condition:** a concrete consumer of agent-initiated spending exists *and* you
  are ready to answer (1)–(3) below — open a merchant account, supply credentials, accept the
  liability and name a production mandate ceiling. (Moves real money, so only you can
  decide.) Mirrors the (now ratified, 2026-09-01) line in `BACKLOG.md` → *Genuinely unbuilt — needs real code*
  and the DRA-20 row.
  **What is already built, and is deliberately rail-agnostic:** `PaymentBroker`
  (`agents/core/payments.py`) enforces mandate + per-payment cap + total cap + payee allowlist +
  currency + expiry; every payment is created `pending` with **no auto-approve at any amount**; the
  caps are re-checked at approve *and* again at settle; create/approve/reject/settle are all
  hash-chain-audited. `settle()` (`agents/core/payments.py`) increments the mandate's spend, marks
  the payment settled and audits the reason *"settled (no real rail)"* — no money moves. Admin
  surface: `/api/payments/*` in `agents/core/routers/payments.py`.
  **What only you can supply, in order:**
  1. **Choose the rail** — Google AP2 vs Stripe ACP vs x402 (the three the backlog row names).
  2. **Open the merchant/account and provide credentials** for it.
  3. **Accept the liability** of an agent initiating real transfers, and name the mandate ceiling
     that is acceptable in production.
  **Until (1)–(3) are answered:** no rail adapter, no `PaymentRail` protocol and no `NullRail`
  default gets written. A selector with zero real implementations is dead plumbing that makes the
  system look wired for money it cannot move; `settle()`'s docstring already documents the seam
  more honestly than a no-op object would.

- [ ] **🔴 Public web demo instance for digitaholic.ro — four calls, all yours** (spec:
  [`docs/decisions/2026-08-24-public-web-demo-digitaholic.md`](decisions/2026-08-24-public-web-demo-digitaholic.md),
  ✅ **spec APPROVED 2026-09-01** — v1 as written; risk tiers: roster-overlay slice R2, deploy
  slice R3; backlog: BACKLOG.md → *P0 — public web demo*, H23.30). A real Nerva
  instance in a digitaholic.ro page, free cloud model, auto-updated from `main`, one disposable
  install per visitor as the "save slot". The four calls (1–2 decided, 3–4 still open):
  1. [x] **Ratify H23.23 (A)** — ✅ ratified 2026-09-01 (owner): Nerva 1.0 is **single-user per
     install**; per-user isolation stays a post-1.0 horizon that opens only when a design partner
     needs multiple distinct people on one shared install
     ([decision doc](decisions/2026-07-11-single-user-1.0.md)). Still owed: the boundary notes in
     `SECURITY.md`, `docs/COMPATIBILITY.md`, `docs/THREAT_MODEL.md`, `docs/FAQ.md` in one doc-only
     PR. (A) is the recorded default the H23.30 spec assumes — v1.0.0 itself is not tagged yet.
  2. [x] **Turn on CDX-12 hardened for this box + fix its `JARVIS_PLUGIN_GRANTS`** — ✅ decided
     2026-09-01: hardened ON (`JARVIS_HARDENED=1`) + `JARVIS_AUDIT_KEY` off-box +
     `JARVIS_PLUGIN_GRANTS` empty + `NERVA_PUBLIC_PROFILE=1` on the public box, so none of the 12
     external-transmit plugins is reachable from it; **personal install unchanged.** Posture rule
     for other boxes: the CDX-12 item below.
  3. **Pick the free LLM provider/key** (OpenRouter / Groq / Gemini — verify current free-tier limits
     at implementation time, they move).
  4. **Pick the container host** (no GPU / heavy RAM needed: cloud LLM + in-memory stores).

  ✅ The `seed_graph()` blocker shipped — the personal graph seed self-gates on
  `NERVA_PUBLIC_PROFILE` (H23.30, #967; `agents/core/memory/seed_graph.py`,
  `tests/test_public_profile_seed_gate.py`). Set `NERVA_PUBLIC_PROFILE=1` on the public box and no
  personal fact is seeded.

  ✅ Its residual shipped too (DRA-07 / DRA-14): a *mistyped* flag used to resolve to the private
  default and seed the owner's family on a public box. `boot_guards.assert_parseable_posture_flags`
  now refuses to start when `NERVA_PUBLIC_PROFILE` is set to a spelling nothing recognizes, from
  both documented entry points (`agents/core/boot_guards.py`, `serve.py`,
  `tests/test_public_profile_boot_guard.py`). The parse convention itself (AUD-14) is unchanged.
  With that in, no code change remains — all of v1 is configuration plus calls 3–4 above.

- [ ] **Before any future Hermes adapter proposal:** decide whether the four productivity-skill
  subtrees carrying separate Anthropic terms are legally acceptable for the intended use, and
  require a fresh CVE, transitive-license, SBOM/provenance and platform review
  against the exact proposed artifact. E8.1c is static preflight evidence only; this is
  not a current release blocker and grants no permission to pull, install or execute
  Hermes. **This decision also gates GAP-4 / DRA-45** — the head-to-head protocol
  ([`HERMES_HEAD_TO_HEAD.md`](HERMES_HEAD_TO_HEAD.md)) cannot be run until it clears.
  - ✅ decided 2026-09-01 (owner): the four productivity-skill subtrees carrying separate
    Anthropic terms (`skills/productivity/docx`, `pdf`, `powerpoint`, `xlsx`) are **NOT accepted
    and out of scope** — removed from the shipped importer allowlist
    `agents/core/skills/hermes_pin_v1.json` (E8.1a pin tests adjusted) so the importer cannot fetch
    them. A **static-only** fresh review (OSV/CVE re-query, transitive-licence closure,
    SBOM/provenance, platform review) is commissioned against the exact pinned artifact
    (v2026.8.3 / 3c27eb6 / OCI `sha256:1678…2c9e`) with inspection-only access —
    **PASS/HOLD: pending.** Permission to pull-for-execution, install or execute Hermes stays
    **WITHHELD** until that PASS is recorded, so the head-to-head still cannot run.
  - E8.1c / #804 — decided 2026-09-01 (owner): stays **EXECUTING ADAPTER BLOCKED** — no container
    runtime, no registry egress beyond the single inspection-only digest pull above, and no
    isolation decision now. Pull-for-execution, runtime and egress may be re-requested only after
    (1) the fresh Hermes review above is recorded as PASS, (2) the B7/#918 retain-or-revert
    decision is recorded (done 2026-09-01: retained, default-off) **and** `JARVIS_TASK_MEDIATION=enforce`
    actually works for real task kinds, and (3) the fixture is proposed exactly as the preflight's
    isolation list (digest-bound image, non-root 10000:10000, read-only rootfs, disposable tmpfs
    `HERMES_HOME`, entrypoint override bypassing `/init` and stage2, deny-by-default egress,
    parent-owned cancellation).

- [x] **When does the Action Kernel become the default rail?** ✅ decided 2026-09-01 (owner) —
  criteria recorded in
  [`docs/decisions/2026-09-01-action-kernel-default-rail.md`](decisions/2026-09-01-action-kernel-default-rail.md):
  (a) four consecutive weeks of opt-in dogfood on the owner box with both flags set, (b) zero
  kernel-caused false DENYs / ungoverned actions in `GET /api/metrics/kernel` over that window,
  (c) one 72h PASS soak with both flags on; the A8 owner-host proof is **not** a precondition;
  the flip is one agent PR with the flags kept as kill-switches. Original framing: the always-on
  risk-tier policy is the load-bearing gate; the unifying kernel (`JARVIS_ACTION_KERNEL`) and the unified
  Action API (`JARVIS_UNIFIED_ACTION_API`) are code-complete but opt-in (H27.3/H27.7, docs-vs-code
  audit 2026-07-24). Decide the promotion criteria — e.g. N weeks of opt-in dogfood with zero
  kernel-caused blocks/false-DENYs, plus the H28+ operator surfaces exercising it — then flip the
  defaults in one deliberate PR.

- [ ] **The jarvis-hub → Nerva rename** — Nerva is now the product brand across the canonical docs
  ([NERVA_VISION.md](../NERVA_VISION.md) §2, decision 2026-07-12); the *deliberate* rename of the
  repository, packages, install scripts and public pages is owner-gated: pick the moment (likely
  alongside the license flip / pre-1.0 launch), reserve names (GitHub repo, domain, PyPI-style
  package ids), then have an agent prepare the mechanical rename PR.

- [x] **After the manual-test pass:** green-light **CLN-2/CLN-3** (the big `orchestrator.py` /
  `web.py` split) — deliberately sequenced post-1.0 (your call, 2026-06-10) so a refactor
  can't add regression risk before the human gate. ✅ superseded 2026-09-01 (owner): the split
  shipped as **v0.11.0 (#293/#296)** under route-parity guards — nothing left to green-light.

- [ ] Phase 2 design partners: who are the first 3–5 non-Andrei users? (MOONSHOT §4, Phase 2 gate)
- [x] Hosted-Pro appetite: build vs wait for pull (VALUATION_AND_PRICING §9). ✅ decided
  2026-09-01 (owner) — **wait for pull**: no hosted Pro tier before or at v1.0; re-open triggers:
  ≥3 design partners / WTP-survey respondents explicitly asking for managed hosting/sync, or
  ~750 active self-host installs (VALUATION §9.1 cross-over); when it does, prototype on serverless
  per-second GPU, never a dedicated fleet.

- [x] **CDX-12 hardened profile (a posture decision — do you want it, and when).** ✅ decided
  2026-09-01 (owner): `JARVIS_HARDENED=1` + off-box `JARVIS_AUDIT_KEY` is **required on the public
  demo box and any hosted/multi-tenant box** (first: the digitaholic demo — public-demo call 2
  above, decided for that box), is the **default on design-partner boxes** via the
  `design_partner` bootstrap (2026-07-07 sync decision 2), and stays **OFF on your personal
  install**. Reference: `JARVIS_HARDENED=1`
  is one switch that flips four toggles: guardrails→REDACT, **audit-HMAC required** (server won't start
  without `JARVIS_AUDIT_KEY`), strict egress forced (no `JARVIS_STRICT_EGRESS=0` downgrade), and mutating
  MCP route tools forced off — plus it enables CDX-11 plugin least-privilege. It's **OFF by default**;
  enabling is your call for a design-partner / multi-tenant box. To turn on: set `JARVIS_HARDENED=1` **and**
  `JARVIS_AUDIT_KEY=<off-box secret>`, then declare `JARVIS_PLUGIN_GRANTS` (next item). Confirm via
  `GET /api/security/posture` → `hardened`.

- [x] **(optional) Persist workflow run history (0.34).** Set `JARVIS_WORKFLOW_PERSIST=1` so the HUD's
  recent-workflow-runs overlay survives a restart (stored bounded under `data/workflows/runs.json`). Default
  unset = in-memory only. ✅ decided 2026-09-01: **stay unset (in-memory)**; revisit only when a
  workflow that must survive a restart actually exists — note the flag also enables the
  pending-queue drain.

- [x] **(optional) System profile (0.62).** Set `JARVIS_SYSTEM_PROFILE=gaming|ai|multimedia|admin` to switch
  the assistant's usage mode (default `balanced`). `gaming`/`multimedia` pause proactive agent heartbeats to
  free local resources; `balanced`/`ai`/`admin` keep them on. Confirm via `GET /api/system/profiles`.
  ✅ decided 2026-09-01: **`balanced` by default** (flag unset); `gaming`/`multimedia` are ad-hoc
  session switches you set yourself when you need the GPU, not a standing decision.

- [x] **(optional) Channel send rate limits (0.44).** To cap outbound broadcast volume on the external
  webhook channels (WhatsApp/Signal/Matrix/Teams/Google Chat), set `JARVIS_CHANNEL_SEND_RATE=<per-minute>`
  (global) and/or `JARVIS_CHANNEL_SEND_RATES="whatsapp:10,teams:30"` (per channel). Default unset =
  unlimited. The interactive reply path (telegram/web/voice) is intentionally NOT limited.
  ✅ decided 2026-09-01: **stay unlimited** (both vars unset, zero behaviour change) until a
  design-partner or hardened box exists; note a cap also gates chat replies on
  WhatsApp/Signal/Matrix/Teams/Google Chat.

- [ ] **CDX-11 plugin grants (only if/when you enable the hardened profile).** Turning on
  least-privilege (`JARVIS_PLUGIN_LEAST_PRIVILEGE=1`, or the `JARVIS_HARDENED` preset) stops
  honoring the `agents_served=["all"]` wildcard for the 12 external-transmit plugins (social_x,
  writeback_*, call_*, channel_*, telegram) — so each is **deny-by-default** until you declare
  which agent may use it. Set `JARVIS_PLUGIN_GRANTS="social_x:veronica,writeback_github:stark,…"`
  (comma list of `plugin_id:agent_id`). This is the deliberate **policy** decision the code does
  *not* guess for you; pick grants that match how you actually want each write surface used.
  Verify on `GET /plugins` (`least_privilege:true`, per-plugin `wildcard_restricted`/`grants`).
  *Public box: `JARVIS_PLUGIN_GRANTS` empty decided 2026-09-01 (public-demo call 2 above); the
  personal-install grant list stays OPEN until hardening there is decided.*

- [x] **BUG-2b.2 — build the drag-drop workflow canvas, or drop it from the backlog (BACKLOG.md
  line 2206).** ✅ decided 2026-09-01 (owner): **(b) dropped** — the JSON-paste WORKFLOW BUILDER
  panel is the v2 editing surface of record. Honesty note: the *legacy v1 HUD* does carry a
  `WorkflowCanvas` (`agents/web/static/workflows.js`), so the "no canvas anywhere" reading below
  holds only for `frontend/src` (v2); that v1 canvas retires together with the v1 HUD (AUD-15 /
  HUD_V2_REMAINING §8) and is ported only on demonstrated demand, as a fresh spec with its own id.
  Original packet: Recounted 2026-08-28: this row has always asked for *frontend tests* of a visual
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

- [x] **E731-CONTINUITY-IDENTITY — does Jarvis's own continuity identity get its own tracked issue?**
  ✅ decided 2026-09-01 (owner): **new issue #1008** — *"Continuity Core — Jarvis's own Identity
  Manifest (E4 identity-boundary lane, not Howard)"* under program #757, body lifted verbatim from
  #731 §1 plus acceptance criteria 1 and 10; **#762 stays scoped to Howard preference-prediction
  only**; no authority change — identity changes are versioned proposals through the existing
  approval queue, Ultron stays the sole privileged-action authority. Sibling placements recorded
  the same day: #731 criterion 5 (observed / inferred / simulated) is homed in E2 #760 observation
  provenance (an epistemic-status field on `nerva.observation.v1`; name left to the E2 slice);
  criterion 6 (Frigga family-domain isolation) is owned under RISKS.md PRIV-02 (E2 #760 primary);
  the evaluation suite runs on the E9.0 `nerva.benchmark.v1` harness as a separate
  `evaluation_only` package outside E9's serialized repair queue.
  Original packet (BACKLOG.md, "B3/Continuity Core mapping" section). `docs/nerva2/CONTINUITY_CORE_RECONCILIATION.md`
  found that #762/E4 only covers **Howard's** preference-prediction scope — nothing currently tracks
  Jarvis's own Identity Manifest (a versioned/signed identity-history contract with migration and
  rollback, the way #731 originally asked for it). The reconciliation doc explicitly declined to
  create that destination unilaterally, calling it "an owner-scoping decision... not a documentation
  call this pass should make." Recounted 2026-08-28: still true, no later commit filled the gap. Your
  call: open a new issue scoped to Jarvis's own continuity identity, fold it into #762's scope
  (broadening what that issue owns), or explicitly decide this isn't worth tracking separately from
  the existing SOUL/persona system. Whichever you pick, a one-line note back in `BACKLOG.md` closes
  the row.

- **HUD chrome is painted below AA contrast, and the a11y gate cannot see it (2026-09-04).**
  Two separate facts, both measured.

  *The defect.* `styles.css` colours text with `--ink-3` (**2.79:1** on `--void`, **2.83:1** on
  `--void-2`) and `--ink-4` (**1.56 / 1.59:1**) in places AA requires **4.5:1**. Already fixed
  where a scan could prove it: the `<Tag>` chip's default, two onboarding inline styles, and the
  command palette's `.pal-group` / `.pal-foot` / `kbd` — that last one was 1.59:1 on the keyboard
  hints telling you how to close the overlay. Still on `--ink-3` and **not** fixed: `.rail-btn`
  (16 in the DOM) and `.center-tab`, i.e. the primary navigation.

  *The measurement problem.* axe can only judge contrast when it can compute one backdrop colour,
  and this shell is gradients. On the live 1280×720 lane `a11y-modes.spec.ts` records **701
  `incomplete` `color-contrast` nodes against 0 violations** (899 / 954 / 1198 on its other three
  lanes); **630 of the 701** carry *"background color could not be determined due to a background
  gradient"*, the rest are non-text characters, images, short content and overlap. `.center-tab`
  sits in that bucket; the rail labels are not reported at all. So contrast across most of the HUD
  is not passing — it is **unknown**, and a green a11y lane must not be read as "contrast is fine".

  Your call, and the first option is the one that fixes the defect rather than the instrument:

  1. **Retune the palette so chrome text clears AA.** Raise `--ink-3` (and stop using `--ink-4`
     for text), or introduce a dedicated "dim but legible" token and move `.rail-btn` /
     `.center-tab` onto it. Costs de-emphasis contrast between active and inactive states; costs
     nothing in depth or layout. This is what the numbers point at, and it is a design decision
     about how muted "muted" may be — which is why it is yours and not taken here.
  2. **Give text-bearing surfaces an opaque backdrop** behind the gradient, so axe becomes
     authoritative. Costs some of the depth the shell is designed around — and note it converts
     ~700 unknowns into real violations, most of which option 1 would then have to fix anyway.
  3. **Accept the blindness and audit by hand** on a schedule, treating `incomplete` as a review
     queue rather than noise. The artifacts already exist: `e2e.yml` uploads `e2e/artifacts/`.
  4. **Assert on `incomplete` too**, which fails the lane today on all ~700 and forces 1 or 2.

  Nothing above is assumed from the fact that the lane is green, and no option has been taken.

