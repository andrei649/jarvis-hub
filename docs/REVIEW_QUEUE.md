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
