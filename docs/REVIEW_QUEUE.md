# Review Queue — manual-testing + product-review checklist

> The running log of everything shipped during the autonomous run that needs your eyes.
> Walk this top-to-bottom during the full manual-test / product-review pass. The codebase
> is green and merged at every step; this is about the things automated checks **can't**
> prove.

## How each item is verified

- **Automated, every PR (gates the merge):** `pytest` (full suite), `ruff`, the
  route/action/capability **auth-matrices**, OpenAPI/route parity, SAST (bandit/semgrep) +
  secret-scan (gitleaks), hash-pinned deps.
- **Scratch simulation (where possible):** I also boot the app and hit real endpoints — and
  load HUD pages headless in a real browser (Chromium/Playwright) — in a throwaway scratch
  dir (never committed) to catch obvious runtime bugs. Noted per item.
- **⚠️ NEEDS YOU:** real LLM / real channel / live HUD pixels / GPU / owner secrets — the
  things only a human + real hardware can confirm.

## Owner-only — I cannot do these (also in `docs/OWNER_TASKS.md`)

- GPU runs — 0.18 Howard fine-tune / speculative decoding.
- Publishing — PyPI / Docker / GPG-signing (your secrets).
- Recruiting design partners; GitHub settings (branch protection, CodeQL enablement).

## Conventions

- **Risky/new behavior ships behind a default-off flag** (e.g. `JARVIS_ACTION_KERNEL`) so it
  changes nothing at runtime until you enable it during testing.

---

## Items (newest first)

### Metrics — P1 proposal-funnel diagnostic on the north-star
- **What:** `compute_north_star` now also returns a **`proposal_funnel`** block — a *cohort*
  over the proposals **created** in the window: `proposed → surfaced` (a decision card reached
  the inbox / `pushed`) `→ accepted` (`done`) / `rejected` / `pending`, plus `surface_rate` and
  `accept_rate`. It localizes *where* a low north-star comes from (too few proposed? proposed
  but never surfaced? surfaced but rejected?). Auto-exposed read-only via
  `GET /api/metrics/north-star` — no new endpoint, no new storage, pure function over the
  existing autonomy `TaskQueue`. First of the three P1 proof-gaps (the pack that moves the
  north-star). Docs in `docs/METRICS.md`.
- **Verified (automated):** `tests/test_north_star.py` (+3) — a 4-proposal cohort
  (2 accepted / 1 rejected / 1 pending, 2 surfaced; `accept_rate`=2/3, `surface_rate`=0.5) with a
  30-day-old proposal proving the created-in-window cohort excludes it; plus empty-honest and
  None-queue cases. **Full suite 2,999 passed**, `ruff` + `bandit` clean. Backend-only — no HUD
  build artifact touched.
- **⚠️ Needs you:** nothing owner-only here — it's pure aggregate metrics over existing rows. If
  you want to eyeball it, `curl localhost:<port>/api/metrics/north-star | jq .proposal_funnel`
  after some real autonomy activity and sanity-check the drop-off story against what you saw.

### HUD — Onboarding panel (H23.20 UI)
- **What:** a Console *Observe* panel that drives the first-run wizard: it reads
  `GET /api/onboarding/wizard` and renders the ordered steps (intro → model → say-hello →
  autonomy-budget) with **done/pending** state + progress + the **cold-start hint** (shown when
  no model backend is reachable), and a per-step **done** button records the funnel event
  (`POST /api/onboarding/funnel`) so completion **persists across reloads**. Closes the UI half
  of H23.20 (backend already shipped).
- **Verified (automated):** `frontend/src/test/onboarding-panel.test.tsx` (+2, fetch-mocked) —
  steps render with completed-marking + the mark-done control, and the cold-start hint surfaces.
  Full frontend **vitest 62 passed**; `tsc --noEmit` clean; backend HUD-v2 parity green;
  `agents/web/v2` rebuilt + committed.
- **⚠️ Needs you (live pixels — CDX-9):** on a fresh install, open Console *Observe* and confirm
  the onboarding steps + cold-start hint render and that marking a step done sticks across reload.

### HUD — Feedback / NPS panel (H23.21 UI)
- **What:** a Console *Observe* panel that surfaces the design-partner feedback loop: it reads
  the **NPS summary** (`GET /api/feedback/summary`, admin — promoters/detractors + per-kind counts
  + recent comments) and carries a **submit form** (score 0–10 + comment → `POST /api/feedback`).
  Closes the UI half of H23.21 (the backend feedback store + endpoints already shipped).
- **Verified (automated):** `frontend/src/test/feedback-panel.test.tsx` (+2, fetch-mocked) — the
  NPS/promoters/detractors + a recent item render and the submit control is present; clean
  empty-state. Full frontend **vitest 60 passed**; `tsc --noEmit` clean; backend HUD-v2 parity
  green; `agents/web/v2` rebuilt + committed (the `hud-v2-build` guard).
- **⚠️ Needs you (live pixels — CDX-9):** open Console *Observe* in a real browser, submit an NPS
  score, and confirm it appears in the summary. (Recruiting the actual design partners is your call.)

### K3 (recursion-depth cap) — sub-agent delegation can't tower up unbounded
- **What:** `SubAgentManager` already capped how *wide* an agent forks (concurrency); this caps
  how *deep* — a sub-agent that spawns a sub-agent that spawns a sub-agent now hits a
  **recursion-depth cap** (OWASP unbounded-consumption). Depth is inferred from the recorded
  parent-chain, so no runner change is needed. Default **8** (a real guard out of the box;
  configurable via the `autonomy.max_subagent_depth` setting; `None`/≤0 = unbounded).
- **Verified (automated):** `tests/test_subagent_depth.py` (+4) — a deep chain is rejected at the
  cap with a clean `recursion_depth_cap` reason, flat (top-level) spawns never hit it, `None` is
  unbounded, and the `≤0 → unbounded` normalization + default-8 hold. Existing subagent tests still
  green. Full suite **2,996 passed**; ruff + bandit clean.
- **⚠️ Needs you:** nothing urgent — the default 8 is deep enough for any real delegation. If you
  build deeply-nested agent workflows, raise `autonomy.max_subagent_depth`.

### K3 (per-task wall-time budget) — a task can't run forever
- **What:** the autonomy worker's `TaskExecutor` now supports a per-task **wall-time budget**
  (`JARVIS_TASK_MAX_SECONDS`). A task whose handler overruns is **cancelled** at the dispatch
  point and returns a clean `{"status":"failed","reason":"wall_time_budget_exceeded"}` — an
  OWASP unbounded-consumption guard. **Default-off** (unset / ≤0 = unbounded → byte-identical).
- **Verified (automated):** `tests/test_executor_budget.py` (+5) — unbounded default runs
  normally, a within-budget task completes, an **overrunning task is cancelled** (its handler
  body provably does *not* finish) and returns the clean failed result, non-dict results still
  wrap, and the env parsing handles blank/zero/garbage. Full suite **2,992 passed**; ruff + bandit clean.
- **⚠️ Needs you:** if you enable `JARVIS_TASK_MAX_SECONDS`, pick a value above your **legitimate**
  longest task (deep-research / long autonomy runs can be minutes) — too low will cancel real work.
  The token + recursion-depth budget dimensions are still pending (they need handler-level hooks).

### HUD — Track-K safety panels (H23.3 + this session's backends)
- **What:** the Console *Trust* section now surfaces the kernel safety controls so an operator
  doesn't need `curl`. The **kill-switch one-tap** (HALT-ALL / disengage) was already there;
  this adds **`KernelMetricsPanel`** (`GET /api/metrics/kernel` — grant/queue/deny tallies + the
  recent denials with reasons; a default-off hint when the meter is empty) and **`LoopBreakerPanel`**
  (`GET /api/security/loop-breaker` — tripped/closed + threshold/window, with a **reset** button shown
  only when tripped). Frontend-only — all three endpoints already shipped this session.
- **Verified (automated):** `frontend/src/test/kernel-safety-panels.test.tsx` (+4, fetch-mocked) —
  verdict tallies + a denial render, the empty-meter hint, reset-only-when-tripped, no-reset-when-healthy.
  Full frontend vitest **58 passed**; `tsc --noEmit` clean; backend HUD-v2 parity guard still green.
- **⚠️ Needs you (live pixels — CDX-9):** open the Console *Trust* section in a real browser and
  confirm the three panels render and the buttons work — with `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch and watch the deny tally tick up on the kernel panel; trip the loop breaker (or its test
  hook) and confirm **reset** closes it. This is the operator cockpit for everything Track-K — worth a
  real look.

### Gate-K observability — `GET /api/metrics/kernel`
- **What:** now that every privileged action crosses `kernel.authorize`, there's a single
  place to see what the kernel is doing. An in-process meter tallies **grant/deny/queue per
  action kind** + a deny-rate + the **recent denials with reasons** (so a halt / runaway /
  over-budget is visible), served at `GET /api/metrics/kernel` (open, like the north-star /
  capabilities meters). In-memory only (resets on restart; the IntentLog audit chain is the
  durable record). **No runtime behavior change** — it only tallies what already happens, and
  stays empty until `JARVIS_ACTION_KERNEL` is on (brokers/routes don't call `authorize` when off).
- **Verified (automated):** `tests/test_kernel_metrics.py` (+5) — meter unit (record/snapshot/
  reset, bounded denials ring, unknown-verdict ignored), the kernel tallies grant/queue/deny
  through a real `authorize` (incl. a halted-kill-switch deny captured with its reason), and the
  endpoint returns the snapshot. Full suite **2,987 passed**; ruff + bandit clean; route/auth/
  OpenAPI parity snapshots reseeded (+1 open route).
- **⚠️ Needs you:** nothing — pure observability. During manual testing with the kernel flag on,
  `GET /api/metrics/kernel` is the quickest way to confirm the kill-switch/loop-breaker/budget
  denials are firing as expected (and a HUD panel for it is a natural future add).

### K3 (loop-breaker slice) — loop circuit breaker bound to the agent-action path
- **What:** the kernel's loop-wide circuit breaker (`LoopDetector`, an OWASP
  unbounded-consumption guard) is now wired in. The orchestrator owns one shared
  `self.loop_detector`, and the autonomy coordinator binds it into the **broker-mediated**
  kernel — so with `JARVIS_ACTION_KERNEL=1`, a runaway agent that re-requests the **same**
  governed action (call/social/writeback/node/payment) past the threshold (default 10 in
  60s) is **denied** at the kernel front door. **Default-off.**
- **The key design call:** it is bound **only** to the broker path, **not** routes/egress/
  MCP/KG. The breaker keys on `action.kind`, and those paths legitimately repeat one kind
  (many egress calls, many KG writes), so a fleet-wide binding would **false-trip** on
  normal traffic. `make_action_kernel(orch)` (used by routes/egress) omits the detector;
  only the autonomy coordinator passes it.
- **Verified (automated):** `tests/test_kernel_loop_breaker_wave.py` (+5): trips on a
  runaway · counts **per-signature, not total** · the route/egress kernel never carries it
  (20 identical `kg.write` never trip) · a None detector is inert · a **real `CallBroker`
  end-to-end** refuses the runaway. Full suite **2,978 passed**; ruff + bandit clean.
- **⚠️ Needs you:** the breaker threshold is **10 identical governed actions in 60s** — a
  conservative default. During testing with the kernel flag on, confirm your **legitimate**
  workloads (e.g. a pipeline dispatching many `node.dispatch` subtasks) don't hit it; if
  they do, that threshold should become configurable (a tracked follow-up). The breaker
  stays open until reset — the API for that now exists: `GET /api/security/loop-breaker`
  (status) + `POST /api/security/loop-breaker/reset` (admin; **not** kernel-mediated, so a
  tripped breaker can't block its own reset). A HUD button for it is still a future add.

### V3 — cross-agent interface-contract drift gate
- **What:** a new CI gate (`tests/test_interface_contract_drift.py`) snapshots the **shared
  schemas that cross agent boundaries** — the kernel `Action`/`Decision`/`Capability`/`Budget`
  dataclasses (the contract every Gate-K-mediated action is built as), the `Verdict`/`Mediation`
  enums, and the A2A pydantic wire bodies — and fails CI if any field is added/removed/renamed/
  retyped or an enum value changes. Pure test/guard addition; **no runtime behavior change**.
- **Verified (automated):** the 3 guard tests pass; full suite **2,973 passed**; `ruff` + `bandit`
  clean. I also confirmed it actually bites (a field rename would fail with a precise message and
  the `--update` regenerate hint).
- **⚠️ Needs you:** nothing — it's a fleet-coordination safety net. (Remaining V3 tail: extending
  the readiness matrix to components/skills needs a booted fixture; subagent return-dict shapes
  are ad-hoc dicts that aren't statically introspectable.)

### K1 (wave-3, kg.write slice) — externally-driven KG writes route through the Action Kernel — **Gate-K COMPLETE** 🎉
- **What:** the 6 externally-driven `/api/kg/*` mutating HTTP handlers (entity upsert/delete,
  relation add/delete, fact add, ingest) now pass `kernel.authorize` (default-off). With
  `JARVIS_ACTION_KERNEL=1`, a halted kill-switch → **403**. This is the **last** Track-K
  slice: **every one of the 11 privileged action kinds is now KERNEL-mediated** — a halt
  uniformly denies payments, plugin egress, MCP writes, gated Tool-RPC, admin escalations,
  and external KG writes.
- **The boundary is the whole point** (workflow-verified, 8 agents, no blockers): only the
  *external* HTTP handlers are gated. The **internal, high-frequency** ingestion path
  (`IncrementalKGUpdater.ingest` from `orchestrator._record_interactions`, `seed_graph`,
  reflection) writes graph methods **directly** and is **never** gated — so **a halt does
  NOT freeze per-turn memory**. A dedicated test pins this: while halted, external
  `/api/kg/ingest` returns 403 *and* internal `kg_updater.ingest` / `graph.add_entity` still
  write. `memory.remember` (vector write), `/consolidate` (plan-only), `/decay/forget`
  (ACT-R op) are not KG writes → intentionally out of scope.
- **Verified (automated + scratch):** `tests/test_kg_kernel_wave.py` (+9) over real
  `InMemoryGraph`+`BiTemporalKG`+`IncrementalKGUpdater`+`KillSwitch`+`AutonomyPolicy`+real
  `make_action_kernel`: default-off byte-identical · clean→200 · halt→403 on all 6 handlers
  · **boundary proof** · disengage recovers · presented-bad-token→403 · deny-precedes-lookup
  (403 not 404) · keys-only payload (no PII values). The action-auth matrix proves `kg.write`
  routes through the kernel when on / not when off. Full suite green (2,970 passed).
- **⚠️ Needs you:** with `JARVIS_ACTION_KERNEL=1`, engage the kill-switch and confirm an
  `/api/kg/*` write (e.g. `POST /api/kg/entities`) returns 403 **while normal conversation
  still builds memory** (the internal KG keeps updating per turn — this is the critical
  boundary; please verify a real chat still remembers facts during a halt). Then disengage
  and confirm external KG writes resume. Note no-token requests are still allowed by design
  (wave-4b/K2 makes capability tokens mandatory).

### K1 (wave-4a) — admin kill-switch + capability-issue route through the Action Kernel (B1 structural)
- **What:** the two admin escalation routes — engaging the kill-switch and minting a
  capability token — now pass `kernel.authorize` **in addition to** today's `admin_guard`.
  With `JARVIS_ACTION_KERNEL=1`: a halted kill-switch (or a *presented* capability token
  that lacks the named capability) → **403**; the clean path (unknown admin kind → policy
  QUEUE) is treated as **allow-through** so there's no approval-UX regression. **Default-off.**
- **Designed + adversarially verified by a workflow** (8 agents) that caught two real
  blockers before any code:
  - **Bootstrap lock-out:** if disengage were mediated, a halt would deny its own release
    and the operator could never recover. **Fix shipped:** *disengage bypasses the kernel*
    (stays `admin_guard`-only) — recovery always works. A test pins exactly this
    (halt → engage/issue 403, but disengage 200 → released → mint works again).
  - **Honest scope:** the `Capability` is K1-tolerant, so a *no-token* admin request still
    falls through (QUEUE→allow). So this is the **structural** half of B1 (route through the
    kernel + cross-check a *presented* token + kill-switch gate); making a token **mandatory**
    is **wave-4b/K2**. The PR/BACKLOG say so explicitly — I did **not** overclaim "closes B1".
- **Verified (automated + scratch):** `tests/test_admin_kernel_wave.py` drives the **real
  handlers** over a real `KillSwitch`+`CapabilityBroker`+`AutonomyPolicy`+real
  `make_action_kernel`: default-off byte-identical · clean→200 · halt→403 + disengage
  recovers · presented-bad-token→403 · each handler emits its own kind. The action-auth
  matrix proves both admin kinds route through the kernel when on / not when off. Full
  suite green (2,961 passed; the last kernel xfail scaffold is now a real pass).
- **⚠️ Needs you:** with `JARVIS_ACTION_KERNEL=1`, (1) confirm engaging the kill-switch and
  minting a capability still work normally (200) on a clean system; (2) engage a halt, then
  confirm a *second* engage and a capability-mint return 403 **but disengage still works**
  (this is the safety-critical recovery path — please exercise it for real); (3) note that a
  no-token admin request is still allowed today by design — wave-4b will make tokens mandatory.

### K1 (wave-3, Tool-RPC slice) — gated Tool-RPC calls route through the Action Kernel
- **What:** a *gated* (external/mutating) Tool-RPC call — the path a sandboxed agent
  script uses to reach a mutating tool — now passes the **kernel** before it can even
  enqueue its approval task. With `JARVIS_ACTION_KERNEL=1`, a **halted kill-switch
  blocks gated Tool-RPC calls** (plus over-budget / runaway-loop denials), returning
  `kernel_denied`. Read-only inline tools are untouched (they run with no side effects).
  **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests (flag-off skips the kernel even when
  bound, DENY blocks before the enqueue + audited, GRANT still enqueues, **read-only
  tools never consult the kernel**, args *keys* only in the payload — no values) **plus
  a real-primitives integration**: the production `kernel.authorize` over a real
  `AutonomyPolicy` + real `KillSwitch` — engage → not enqueued, release → enqueued. The
  action-auth matrix proves `tool.rpc` routes through the kernel when on / not when off.
  Full suite green (2,953 passed).
- **⚠️ Needs you:** Tool-RPC gated tools are an internal sandbox surface (no gated tool
  is registered by default beyond the `echo`/`time` read-only built-ins). When you wire
  a real gated tool, enable the kernel flag, engage the kill-switch, and confirm the
  gated call returns `kernel_denied` rather than enqueuing.

### K1 (wave-3, MCP slice) — MCP mutating tools route through the Action Kernel
- **What:** the MCP write surface (`MutatingRouteTool` — today just
  `route_memory_remember`, double-kill-switched off by default) now also passes the
  **kernel** after the existing per-identity gate. With `JARVIS_ACTION_KERNEL=1`, a
  **halted kill-switch blocks MCP writes** (plus over-budget / runaway-loop denials):
  identity proves *who*, the kernel decides *whether the write may run now*. A denial
  raises `MutatingKernelError`, is audited `refused-kernel`, and the write never runs.
  **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests (flag-off skips the kernel even when
  bound, no-kernel writes, DENY blocks + audits + no write, GRANT writes, **identity
  failure precedes the kernel**, builder threads the kernel) **plus a real-primitives
  integration**: the production `kernel.authorize` over a real `AutonomyPolicy` + real
  `KillSwitch` — engage → write blocked, release → write runs. The action-auth matrix
  now proves `mcp.mutating` really routes through the kernel when on / not when off.
  Full suite green (2,947 passed).
- **⚠️ Needs you:** this surface is reachable only with BOTH `JARVIS_MCP_ROUTE_TOOLS`
  and `JARVIS_MCP_MUTATING_TOOLS` on (default off). During testing, with those + the
  kernel flag on, drive `route_memory_remember` over MCP, engage the kill-switch, and
  confirm the write is refused (`blocked by kernel`) with a `refused-kernel` audit row.

### K1 (wave-2) — plugin egress routes through the Action Kernel
- **What:** policy-passing plugin egress (an HTTP call the plugin's manifest already
  allows) now also passes the **kernel**. With `JARVIS_ACTION_KERNEL=1`, a **halted
  kill-switch blocks all outbound plugin calls** (plus over-budget / runaway-loop
  denials) — the manifest decides *where* a plugin may reach, the kernel can veto *that
  it reaches at all right now*. `http_client` stays fully decoupled: the orchestrator
  injects a plain `(plugin, method, url, host) → reason|None` hook bound to
  `kernel.authorize`. A buggy hook **fails open** (the manifest policy already ran), so
  the experimental gate can never brick egress. **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests for the hook contract (deny blocks,
  allow passes, no-hook no-op, exception fails-open, **manifest block precedes the
  kernel**) + the production hook (default-off, deny-when-on, none-kernel-allows) **plus
  a real-primitives integration**: the production `kernel.authorize` over a real
  `AutonomyPolicy` + real `KillSwitch` — engage → egress raises `PluginEgressError`,
  release → egress allowed. The action-auth matrix now proves `plugin.egress` really
  routes through the kernel when on / not when off. Full suite green (2,938 passed); the
  old B3 xfail scaffold is now a real passing regression.
- **⚠️ Needs you:** during manual testing, set `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch from the HUD/API, and confirm a plugin that makes outbound calls (e.g. a
  weather/news plugin) is blocked while halted, then released. Also confirm the
  network-monitor panel records the blocked attempt (reason mentions the kernel).

### K1 (payment micro-wave) — payments route through the Action Kernel
- **What:** an *admissible* `request_payment` (one the mandate's hard caps already
  accept) now passes through `kernel.authorize`. A kernel **DENY** — kill-switch
  engaged, over-budget, or a runaway loop — refuses the payment **before** it can
  become `pending`; GRANT/QUEUE fall through to the existing always-approval flow.
  The kernel can only *add* a hard deny; it can't relax the rule that every payment
  needs explicit owner approval. The binding (`kernel/binding.py`) is now shared with
  the wave-1 brokers, so there's one definition of what the kernel front door is bound
  to. **Default-off** behind `JARVIS_ACTION_KERNEL` — zero behavior change until enabled.
- **Verified (automated + scratch):** unit tests (deny-before-pending, flag-off skips
  the kernel even when bound, inadmissible never reaches it, GRANT/QUEUE stay pending)
  **plus a real-primitives integration test**: the production `kernel.authorize` bound
  over a real `AutonomyPolicy` + real `KillSwitch` — halting the switch denies a
  payment (nothing becomes pending), releasing it lets the admissible payment proceed.
  Full suite green (2,928 passed).
- **⚠️ Needs you:** during manual testing, set `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch, and confirm a `request_payment` is refused (`kernel_denied`) and shows a
  `deny_payment` row in the payments audit; then release and confirm it goes to pending.

### H23.17 (slice) — i18n completeness gate
- **What:** `frontend/src/test/i18n-completeness.test.ts` fails CI if any locale (en/ro)
  is missing a key the reference has, has an extra key, or has a blank string. Runs in the
  existing CI vitest job.
- **Verified (automated):** ran the full frontend vitest suite locally — 54 tests pass
  including the 5 new i18n checks; en/ro are complete today.
- **⚠️ Needs you:** nothing. Remaining H23.17 slices (Playwright E2E, a11y, soak,
  browser/mobile matrix) are pending — E2E is feasible to build + simulate here.

### K2 — least-privilege capability set per agent (issuance)
- **What:** `kernel/capabilities.py` derives each agent's capability set from its declared
  config (plugins/channel/policy), and the orchestrator issues a scoped `CapabilityBroker`
  token per agent at boot (`orch.agent_capabilities`). Strict-local agents (frigga/ultron/
  howard) never get a cloud capability. **Inert** — nothing checks per-agent tokens yet
  (the per-action enforcement waves do), so zero behavior change.
- **Verified (automated + scratch):** unit tests (derivation least-privilege, real-broker
  issuance) + a scratch run over the **real 17-agent roster** confirming every agent gets a
  least-privilege token and the three local-only agents have no cloud cap.
- **⚠️ Needs you:** nothing yet. The enforcement half (B1 — admin actions require a
  capability; folding WorldView HMAC tokens) is a deliberate later wave.

### H23.6 — minimal taint flag + kernel escalation (indirect-injection guard)
- **What:** `security/taint.py` marks content from untrusted sources (web/OSINT/RSS/inbound)
  as tainted; the action kernel **escalates a tainted action from GRANT → QUEUE** (approval),
  so injected content can't auto-execute. Default-off effect: only fires for actions
  explicitly carrying the taint flag (nothing marks them yet — see pending).
- **Verified (automated + scratch):** unit tests (classifier, mark/is_tainted, kernel
  escalation) + scratch run against the **real** `AutonomyPolicy` confirming clean→GRANT,
  tainted→QUEUE.
- **⚠️ Needs you:** nothing yet — but note the producer side (marking ingested web/OSINT
  content tainted) and full data-flow propagation are a deliberate **deferred** follow-up,
  so this guard is mechanism-only until those land.

### B3 — strict-egress downgrade is now durably audited
- **What:** the `JARVIS_STRICT_EGRESS=0` escape hatch (allows a blocked-by-default egress
  host) was a *silent* log line. Now a decoupled audit sink (`http_client.set_egress_audit_sink`,
  wired by the orchestrator to an `AuditLogger` adapter) records a durable `EGRESS_DOWNGRADE`
  security event. No-op in strict mode (the default) — so no behavior change unless you've
  set `JARVIS_STRICT_EGRESS=0`.
- **Verified (automated):** unit tests — downgrade audits, strict mode blocks (no audit),
  no-sink no-op, a throwing sink never breaks egress, http_client stays decoupled from the
  security types. **Scratch:** real `AuditLogger` — a downgrade lands a durable row and
  `verify_chain()` returns valid (HMAC chain intact).
- **⚠️ Needs you:** nothing specific — but during testing, set `JARVIS_STRICT_EGRESS=0`,
  trigger a cross-host plugin call, and confirm the event shows in `GET /api/admin/audit`.

### K4 — kill-switch + credential-quarantine syscalls
- **What:** `kernel/syscalls.py` — `halt()` / `release()` promote the existing `KillSwitch`
  to a kernel call, and `inject_guarded()` makes secret injection **quarantine-aware** (while
  halted, injection is forced blocked regardless of approval). Folds H23.3. Composes existing
  primitives; no behavior change until a caller uses it.
- **Verified (automated):** unit tests — halt→quarantine→release, injection blocked while
  halted even when approved, `kernel.authorize` denies new grants when halted, audit emitted.
- **⚠️ Needs you:** the **one-tap kill-switch HUD control** (frontend) is not built yet — this
  is the backend syscall only. (HUD comes in the productionization-tail phase.)
