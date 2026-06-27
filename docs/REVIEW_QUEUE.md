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
