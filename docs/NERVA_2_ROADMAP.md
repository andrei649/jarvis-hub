# Nerva 1.x → 2.0 — the roadmap for the rest of the backlog

> **Decided:** 2026-09-06 (CTO, ratified by the owner merging the PR that carries it) ·
> **Base:** `main` `c16d84e9` (v1.0.0 tagged 2026-09-02) · **Owner:** Andrei ·
> **Inputs (immutable, dated):** the 2026-09-06 backlog recount (349 rows after dedup: 110
> AI-executable, 101 owner-gated, 69 duplicates, 28 decided, 33 unclear, 6 perpetual, 2 rescoped),
> five code maps (operator, autonomy/24×7, Nerva 2.0 program, onboarding, tooling), the HUD
> builder map, and the online research pass on Hermes Agent and the 2026 field
> (`docs/research/2026-09-06-hermes-and-field-gap-matrix.md`).
>
> **How to use this doc.** `MOONSHOT.md` says why we exist and what never moves; `NERVA_VISION.md`
> says what the machine must be able to do; `BACKLOG.md` remains the priority truth per row. This
> file is the *sequence*: which rows close in which release, what "done" means for each release,
> and the protocol that keeps an unattended developer on that sequence
> (`docs/prompts/BACKLOG_DRIVER.md`). When this file and BACKLOG disagree on a row's status,
> BACKLOG wins and this file is stale — fix it in the same PR.

---

## 1. The thesis in one paragraph

Hermes Agent wins today on *hands* — a computer-use driver on three operating systems, eleven
browser tools, seven terminal backends, 27 messaging gateways, 240k stars — and explicitly declined
to build what Nerva already has: a tamper-evident action audit (their issue #487, closed "not
planned"), a spend cap, a kill switch, an interrupt budget, house risk tiering and an Action Kernel
with earned autonomy. Every 2026 competitor sells "an AI employee that works while you sleep" and
none can *prove* it: their success claims are exit codes, their approvals are "skip", their
budgets live in the cloud. The bet for 1.x → 2.0 is therefore not to rebuild Hermes but to give
Nerva's governance real hands and a real 24×7 loop whose every claim is evidence-backed by
construction — and to collapse the first ten minutes to one pasted line, one phone pairing and one
receipted autonomous action. Local-first, opt-in cloud, kernel-mediated, ≤4 interrupts a day, money
and locks never above the approval queue: those are the constraints *and* the moat.

## 2. What the field says (verified 2026-09-05, sources in the research pass)

| Capability | Hermes / best in field | Nerva at v1.0.0 | Verdict |
|---|---|---|---|
| Desktop control Win / macOS / Linux | cua-driver (UIA / AX / AT-SPI, pid-scoped input), Cowork background windows, Windows agent workspace | Windows-only pywinauto seam, no launchers wired, no macOS/Linux driver | behind |
| Browser automation | 11 tools, a11y snapshots, CDP passthrough, isolated profiles | governed Playwright seam that cannot navigate (SEC-B4 transport) | behind |
| Terminal targets | local / docker / ssh / modal / daytona | docker only; local and ssh refuse honestly | behind |
| Visual grounding | SoM overlay + pixel fallback; Qwen3-VL / UI-TARS / Holo open weights | screen grounding module unbound from any driver | behind |
| Skill self-creation | skill_manage patch loop, /learn | governed acquisition loop, quarantine, signing | behind on iteration, ahead on safety |
| Memory | MEMORY.md snapshot + 8 provider plugins | bi-temporal KG + RRF + episodes + digital twin | ahead |
| Scheduling / cron | continuity, monitor-mode skips the LLM, incidents | queue + watchers + night window; no continuity, no goal object | behind |
| Subagents | list / steer / stop, schema-validated outputs, per-delegation cost | in-memory spawns, unbudgeted in total | behind |
| Context compression | two-tier, protected head/tail, per-model thresholds | compressor exists, no policy | behind |
| Approval / safety | smart approvals (LLM-reviewed), YOLO mode | kernel GRANT/QUEUE/DENY, contracts, taint escalation, hard floors | ahead |
| Audit | none tamper-evident (declined) | Merkle chain + verify_chain | ahead |
| House / physical | HA as four tools | house model with per-device risk tiers, cameras read-only | ahead |
| Install / onboarding | one-line install, wizard, doctor, importers | four install paths, three first-run mechanisms, none ends in an accepted action | behind |
| Ecosystem | 88k+ indexed skills, 50+ MCP vendors | 78 pinned Hermes skills, signed marketplace | behind |

**Do not copy:** global approval bypasses ("YOLO", "skip confirmations"), a reviewer LLM as the
sole gate, fail-open judges, unbounded defaults, private-API input paths (SkyLight SPIs, raw
uinput), foreground control that hijacks the owner's mouse, credentials in model context,
continuous screen capture as the product, unofficial WhatsApp, star velocity as a north-star.

## 3. Milestones — the version is the plan

Versions continue from 1.0.0. A milestone is **done** when its exit gate is met, never when its
rows are ticked. Owner-gated rows keep their packet in `docs/OWNER_TASKS.md` and never block a
milestone on their own; they block the *proof* the next milestone needs.

| Version | Theme | Exit gate | Status |
|---|---|---|---|
| **1.1.0** | **Hands, company, activation** — the one-PR delivery (§4) | full backend + frontend + mobile suites green; every new privileged kind in `action_auth.json`; every driver refuses honestly off-box; company mode default-off with a hermetic seven-night simulation green; `install_smoke` passes from the new bootstrap; BACKLOG synced | 🔨 this PR |
| 1.2.0 | **Proven hands** — owner-hardware validation of the Windows/macOS/Linux drivers, browser transport and local terminal (🔨 → ✅ only from owner-live `nerva.evidence.v1` receipts); isolated operator session (dedicated browser profile, second Windows session); presence-gated *watch mode* with take-over; `credential.fill` kernel kind over the OS keychain; consent ledger completed (OS input persistence, MCP servers, HA devices); AUD-6 httpOnly tokens | 20-task operator benchmark scored on the owner box under kernel ON with zero ungoverned actions; every driver row ✅ with a receipt | ⬜ |
| 1.3.0 | **Night Shift E5.1** — company mode under `JARVIS_TASK_MEDIATION=enforce` (B7 evidence for #906); scheduled continuity live; HA WebSocket observer and physical-context-gated autonomy; MCP server exposure of the governed operator; record-then-replay v0 for recurring chores; T-0.21 pack catalog; browser wake word (H5.16); config dry-run (H10.28) | seven real nights of owner dogfood with `company.enabled` on: every "done" in the morning brief carries a receipt, zero unmediated privileged tasks, interrupt budget never exceeded | ⬜ |
| 1.4.0 | **Fast adoption** — hosted one-line installer on the owner's domain; Telegram pairing default in the design-partner posture; package presence from the generated Homebrew/winget/GHCR manifests (signing is owner-gated); the public demo instance (H23.30 R3); T-0.49 approval-gated timeline; activation and D7 measured with ≥3 design partners; proof-of-action receipts as the share loop | activation_30m and D7 (≥1 accepted action) computed locally for ≥3 design partners from opt-in aggregate export; GAP-0 closed | ⬜ |
| 1.5.0 | **Continuity and cognition** — E4.0 Howard preference model (`nerva.preference.v1`), identity manifest acceptance (#1008), E12.1 belief/metacognition fixtures, E7.0 scenario contract, Continuity Core suite nightly, H18.24/H18.25 mobile renderers (device), mobile parity ≤20 ⬜ | Continuity suite runs nightly on the E9.0 harness with a published held-out score; identity changes only through versioned proposals | ⬜ |
| 1.6.0 | **Reach and ecosystem** — artifact store wave 2 (H12.26), node mesh transport and media/desktop node actuators, skills hub scanner and trust tiers, digest skills (H12.23), media generation backend (H12.24), `agents/vision` real implementation, external IdP for MCP (H16.1), WorldView H19 🔨 proofs as owner infra allows | every new surface carries a reality case; external skills load only signed or quarantined | ⬜ |
| 2.0.0-rc | **Hardening and proof** — AUD-13 turn-pipeline de-dup, AUD-15 HUD v1 retirement + strict TypeScript, E11.1 drills emitting receipts, 72h soak PASS on the owner runner, `release_gate.py` receipt-driven, A1 ⭐B0 demo recorded | `scripts/release_gate.py` passes from receipts, not ticks; soak PASS; zero false DENYs over the dogfood weeks | ⬜ |
| **2.0.0** | **Program acceptance** | the owner marks E1–E12 accepted or explicitly deferred in `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json` with owner-live receipts; B7 enforce with verified evidence; manifest live-sync true | ⬜ |

Order inside a milestone follows `docs/prompts/BACKLOG_DRIVER.md` §1: red `main` first, then the
milestone's rows (PARTIAL before MISSING), then 1.0.1 defects, then DRA/SEC residuals, then debt.

## 4. The 1.1.0 delivery (this PR) — by theme

Each line is one file-disjoint slice built by one builder, checked by an independent adversarial
reviewer, with one fix round. Backlog ids in brackets are the rows the slice closes; hardware-
dependent behaviour lands as 🔨. Anything that did not make it is listed honestly in §5.

**Hands — a governed computer operator on three operating systems (P3 / S1–S3)**
- `op-host-probe` — per-OS capability probe (dependencies, TCC/portal permissions, display
  server) with an honest-refusal vocabulary and a Console panel.
- `op-driver-factory` — cross-platform capture/input layer (lazy `mss`/Pillow, `pynput`) and an
  OS-dispatching driver factory replacing the hard-coded Windows construction.
- `op-macos-driver` 🔨 — pyobjc accessibility tree, `AXPress`/`AXSetValue`, TCC preflight.
- `op-linux-driver` 🔨 — AT-SPI2 tree; X11 input via `xdotool` argv; Wayland via the XDG
  RemoteDesktop portal (`python-libei`), the compositor's consent dialog being the human gate.
- `op-windows-backend` 🔨 — `uiautomation` second UIA backend, elevated-window refusal,
  DPI-aware capture, coordinate actions with provenance.
- `op-desktop-core` — batch steps with stop-on-first-failure and post-action snapshots, OS
  actions (volume, brightness, lock), the DRA-43 validator reconciliation [DRA-43].
- `op-permission-ledger` — per-app / per-site grants {once, session, always, never} with a default
  deny list, a `permission.grant` kernel kind and a Permissions panel (the consent-ledger bet v0).
- `op-visual-grounding` — `LocalVLMLocator` gated to a proven-local VLM, pinned open-weight
  grounder presets and coordinate conventions, the visual route registered last [DRA-06 residual].
- `op-terminal-local` — governed local-host transport under the targets policy plane with a
  `terminal.exec` kernel kind and a static hardline denylist evaluated before any autonomy level.
- `op-file-tools` — governed file read/list/write/delete inside declared roots with snapshot-based
  rollback, reachable from the model loop [H20.R1 residual].
- `op-browser-transport` — the IP-pinned browser transport that lets the governed browser navigate
  at all, redirect re-validation, accessibility-snapshot-first observation, isolated profiles [SEC-B4].
- `op-browser-governed` — `browser.step` kernel kind, batch steps, `browser_run` as a model-loop
  tool and route, Operator panel wiring.
- `op-benchmark` — the 20-task browser/computer benchmark (hermetic + live twins) that NERVA_VISION
  S1 requires, with a persisted pass rate.
- `llm-tool-turns`, `runtime-breakers` — tool turns on Ollama and OpenAI-compatible backends
  [H13.2]; stuck-pattern and idle-timeout breakers with per-step token accounting.

**Company — the verified-outcome 24×7 loop (E5.0 candidate, delivered not program-accepted)**
- `co-goal-contract` — goal contract (outcome / verification / constraints / boundaries /
  stop_when) with deterministic gates.
- `co-work-run-ledger` — `nerva.work-run.v1`: goals, opportunities, work runs, progress ledger.
- `co-planner` — deterministic role assignment across the 18 specialists, tier ≤1 by construction.
- `co-judge` — fail-closed judge with a `work.gate` kernel kind; `co-verifier` — receipts per child
  task, noop/degraded/refused never verified.
- `co-supervisor` — the tick: stop checks first, reconcile, progress ledger, idempotent enqueue
  through `govern_enqueue`, checkpoints; `co-durable-hitl` — pending decisions survive restarts.
- `co-scheduled-continuity` — continuity, monitor-mode that skips the LLM when nothing changed,
  pinned model, missed-run policy; `co-context-compaction` — two-tier compaction policy;
  `co-subagent-steer` — steerable, budgeted subagents with typed outputs.
- `co-report-brief`, `co-company-routes`, `co-company-room-hud` — the verified-only daily report
  in the morning brief, `/api/company/*`, the Company Room panel; `n2-e5-slice-doc`.

**Activation — the first ten minutes (S8, GAP-0)**
- `install-bootstrap-doctor` — one stdlib bootstrap behind thin installers, `nerva doctor`, the
  full-pytest-on-install removed [phone-surface-LAN-path].
- `model-setup` — hardware tiers (NVIDIA / AMD / Apple Silicon), model recommendation, governed
  Ollama pull (`model.pull` kernel kind).
- `first-action-activation` — wizard step 6: one zero-key read-only proposal accepted from the
  phone; truth-derived wizard steps; a goals gallery.
- `ad-activation-metrics` — activation ≤30 min, D1/D7/D30, time-to-first-accepted-action on the
  north-star; `ad-day-report-receipts` — the redacted day report and proof-of-action receipt.
- `telegram-pair-60s`, `posture-wave2`, `seed-overlay`, `public-profile-overlay` [H23.30],
  `release-channels` (Homebrew/winget/GHCR manifest generators), `ad-hermes-import` (import from
  Hermes / OpenClaw / Claude Code) [BUG-13].

**Nerva 2.0 program — contracts that had no code**
- `gov-cognitive-ledger` (B4 / E1.3), `n2-evidence-receipt` (E11.0), `nerva2-e2e3-contracts`
  (E2.1 epistemic status, E3.2 recall admission), `nerva2-continuity-suite` (#731 suite on the E9.0
  harness), `identity-manifest-e4-1` (#1008), `nerva2-program-control` (B2 manifest reconciled to
  post-#981 truth, non-blocking checker, one Tier A integration pass), `proof-track-reviews` (the six
  pending independent attestations recorded as PASS/HOLD, never assumed).

**Security, memory and debt residuals**
- `autonomy-routes-honesty` [DRA-59], `taint-boundary` [TASK-3, H20.1], `egress-ssrf-honesty`
  [DRA-47, DRA-23], `cost-accuracy` [DRA-24 ×3, H10.24], `memory-hygiene-leg6` [DRA-27, SEC-B5,
  CDX-7], `mem-data-spaces` [H10.26], `subagent-shape-gate` [V3], `live-rails-behind-flags`
  [T-0.66, H10.30, H12.21, H12.22, H12.25], `llm-routing-upgrades` [H20.2, H13.4],
  `mcp-transports` [DRA-25, H10.5], `market-quotes` [T-0.39, DRA-21], `quickbar-route` [T-0.64],
  `fault-injection` [T-0.63], `ops-daemons-and-backup` [H34.2, H12.15, H12.7], `house-hestia-wled`
  [LVP-hestia-wiring, H30.8], `debt-xs-batch`, `debt-aud18-perf` [AUD-18 partial],
  `hud-inline-fixes`, `hud-voice-cockpit` [T-0.28], `mobile-capture` [T-0.26],
  `e2e-pwa-and-footage` [E2E-no-pwa-spec, T-0.52], `ci-advisory-lanes` [DRA-40], `worldview-xs`
  [AUD-4, H19.3.1], `ledger-hygiene` [DRA-55, DRA-39 doc, DRA-28], and the ambient-scale timing
  gate made load-tolerant (the nightly flake of 2026-09-04).

## 5. Deferred on purpose (with the milestone that owns them)

| Row | Why not in 1.1.0 | Milestone |
|---|---|---|
| AUD-13 turn-pipeline de-dup, AUD-15 HUD v1 retirement | architectural; the 2026-08-28 handoff says never in a single session | 2.0.0-rc |
| AUD-6 httpOnly HUD tokens | changes the auth surface; needs its own R3 review | 1.2.0 |
| credential.fill, consent ledger completion, isolated operator session, watch mode | need OS keychain and session designs and the owner box to prove | 1.2.0 |
| T-0.21 pack catalog, H5.16 browser wake word, H10.28 config dry-run, H12.23 digest skills | value below the 1.1.0 line | 1.3.0 / 1.6.0 |
| T-0.49 approval-gated timeline | under-specified; write the spec first | 1.4.0 |
| H18.24 / H18.25 native renderers | device-gated (no mic pipeline, no graphics dependency) | 1.5.0 |
| H12.24 media generation backend, H12.26 artifact store wave 2, LVP node mesh transport, LVP-vision-argus-code, H16.1 external IdP | reach work behind a real consumer | 1.6.0 |
| A11Y-incomplete-reporting-limits, E2E-settle-readiness-signal | e2e lane quality; needs per-mode readiness attributes across shared HUD files | 1.2.0 |

## 6. The owner lane (only you can do these)

Complete packets live in `docs/OWNER_TASKS.md`. In roadmap order: run the drivers on the Windows
box, a Mac and a Wayland Linux session and record the receipts (1.2.0); mark the six PR checks
required and drop the stale names (A4); the real Dependabot count (A3); the 72h soak on a
self-hosted runner and the ⭐B0 demo video (A1/A6); Telegram BotFather token, Google/Spotify OAuth,
Home Assistant and Frigate on the LAN (LVP); code-signing certificates and the hosted installer
domain (1.4.0); E1.2b inputs 1–2; #906 provision or re-scope (B7 acceptance).

## 7. The Hermes bar (NERVA_VISION §8) after 1.1.0

| # | Criterion | 1.1.0 state | Proof still owed |
|---|---|---|---|
| S1 | Execution breadth, kernel ON | 20-task pack hermetic-green; live twins 🔨 | owner-box run (1.2.0) |
| S2 | Skill acquisition | loop delivered (O32); iteration loop and hub scanner deferred | 1.3.0 / 1.6.0 |
| S3 | Multi-target execution | local + docker governed with audit; ssh deferred | 1.2.0 |
| S4 | Context endurance | compaction policy with per-model thresholds | eval lane ≥95% (1.3.0) |
| S5 | Governance | all new kinds kernel-mediated, snapshot zero-pending | continuous |
| S6 | Local-first proof | network monitor `clean=True` posture unchanged | continuous |
| S7 | Personal-world moat | house / media / acquisition VERIFIED states unchanged | owner hardware |
| S8 | Time to first governed action | measured by `activation` on the north-star | ≥3 partners (1.4.0) |

## 8. Bets nobody in the field ships (and why Nerva can)

1. **Proof-of-action receipts** — every accepted autonomous action becomes a redacted,
   Merkle-anchored receipt the owner can verify and share; the chain head mirrored to the phone.
2. **One consent ledger for the whole machine** — apps, sites, OS input persistence, HA devices and
   MCP servers as one earned-and-revocable permission ledger with presence gating.
3. **Chores that graduate to autopilot** — governed record-then-replay: supervised runs become
   deterministic zero-token scripts replayed only in the night window under the original scope.
4. **The verified-outcome company** — goals carry contracts, gates and a fail-closed judge; the
   morning brief reports only verified outcomes.
5. **Physical-context-gated autonomy** — house sensors and cameras become inputs to the kernel's
   risk policy for digital actions.

## 9. Metrics that decide progress (MOONSHOT §6 unchanged)

North-star: weekly accepted autonomous actions per active user. Counter-metrics: interrupt rate,
reject rate, %-local, p95 non-LLM latency. Added by 1.1.0 (`docs/METRICS.md`): activation ≤30 min,
D1/D7/D30 retention on accepted actions, time-to-first-accepted-action, operator benchmark pass
rate, verified-vs-unverified outcomes per day, and the mediation counters (refused unmediated).
Capability growth that makes Nerva noisier or less local is failure, not progress.

## 10. Anti-drift protocol

- The unattended developer runs `docs/prompts/BACKLOG_DRIVER.md`; a human run says "Max".
- Builder ≠ reviewer ≠ integrator for R2/R3 work; program acceptance is the owner's.
- A milestone closes on its exit gate, recorded here and in `docs/HISTORY.md`, never on ticks.
- Re-recount before trusting any row (`docs/BACKLOG_ZERO_LEDGER.md` recount rule).
- This file is re-dated whenever a milestone row changes; superseded wording stays as history.
