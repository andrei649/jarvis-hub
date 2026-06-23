# ORIZONT 24 · Track K — Action Kernel (design)

> Spec for the "operating" in operating system: one mediated front door so **every** privileged agent
> action passes through `kernel.authorize(action, capability, budget) → grant | deny | queue`, with
> capabilities as process-permissions, budgets as the scheduler, and kill-switch/quarantine as a syscall.
> Owner: Andrei · Tracks K1–K4 · ~21 SP · Priority: P0–P1 · Phase B (after Phase-A AUD-\*).
> Direction: [BACKLOG.md → ORIZONT 24](../../../BACKLOG.md) · sibling spec: Track V (Verification Fabric).
> **Compose, don't replace:** the seeds below already exist and mostly work; the kernel *unifies the
> entry point*, it does not rip out the queue/brokers that already enforce.

## Today (what exists, grounded)

Authorization works, but it runs on **several parallel spines** with no single front door:

1. **A partial `authorize()` already exists** — `agents/core/security/capability.py:117` —
   `authorize(broker, kill, token_id, capability, scope) → {"allowed": bool, "reason": str}`: checks the
   `KillSwitch` (`:80`, persisted, scope-aware) then the `CapabilityBroker` (`:34`, `issue`/`check`/
   `revoke`, scoped + TTL'd, non-escalatable). Used by `node_mesh.py:120` and the WorldView MCP path.
   **This is the kernel's nucleus** — but only two callers use it.
2. **The autonomy `TaskQueue` is the de-facto choke point for most actions** —
   `agents/core/autonomy/queue.py:90` (`enqueue(risk_tier, autonomy_level, origin)` + a legal-transition
   state machine `PROPOSED→APPROVED/BLOCKED/REJECTED→DONE/FAILED`). `AutonomyWorker.submit()`
   (`worker.py:82`) runs `policy.decide(action)` (`autonomy/policy.py`: READ_ONLY→ACT, REVERSIBLE→ASK,
   IRREVERSIBLE→ASK+caps) then enqueues / blocks. Payment, call, writeback, social, node-dispatch and
   signal recommendations all land here.
3. **Plugin egress** — unified at `agents/core/http_client.py:148` (`PluginHTTPClient._enforce_egress`)
   against `plugin_gate.py:BUILTIN_PLUGINS` manifests (`NetworkAccess`, `allowed_domains`,
   `register_dynamic_domain`). Unified *client*, but each plugin declares its own manifest.
4. **HTTP route guards** — `agents/web.py:83` (`_admin_guard`/`_user_guard`/`_user_credential_ok`),
   generalized by `tests/test_route_auth_matrix.py` + `route_auth.json` (`INTENTIONALLY_OPEN` /
   `PENDING_GUARD` escape sets — SEC-3 drove `PENDING_GUARD` to empty).
5. **Secret quarantine** — `agents/core/security/secret_broker.py:65` `inject(ref, approved=True)`
   returns a placeholder unless approved; `redact()` scrubs values from logs. Already approval-gated.
6. **Budgets — partial** — `InterruptBudget` (`worker.py:43`, `per_day=4`, the MOONSHOT §5.4 guardrail),
   mission step/wall-clock budget (`missions.py:45`, `MAX_STEPS=20`/`MAX_SECONDS=3600`), task retry cap
   (`queue.py`, `MAX_ATTEMPTS=3`), payment caps (`payments.py:45`). **Missing (= H23.1):** per-task
   token/time budget, recursion-depth cap, and a global circuit breaker (per-plugin breakers exist; no
   loop-wide one).
7. **Audit** — an injected `audit=` callable is already threaded through PaymentBroker / SocialBroker /
   WriteBackBroker / CallBroker / NodeMesh.

**The three live bypass risks Agent-A verified** (the kernel must close these):
- **B1** admin routes (`/api/security/kill-switch`, `/api/security/capabilities/issue`) are HTTP-admin-
  guarded but **don't cross-check a capability token** — a leaked admin token is universal + unscoped.
- **B2** MCP mutating tools (`mcp/route_tools.py:568`) fail **open** if `identity_check=None` (today
  mitigated only by an auditor-required bind).
- **B3** `JARVIS_STRICT_EGRESS=0` downgrades egress violations to warnings with **no audit/alert**.

## Approach

One front door that **composes** the existing gates into a single decision, leaving the queue and
brokers as the execution substrate.

```
   any privileged action  ─►  kernel.authorize(Action, Capability, Budget) ─► Decision
   (tool call · plugin egress · write-back · payment · social · node dispatch · MCP route · KG write)
                                          │
        ┌───────────────┬────────────────┼─────────────────┬───────────────┐
        ▼               ▼                ▼                 ▼               ▼
   KillSwitch       Capability        Budget/Scheduler   Policy.decide   Audit (always)
   .is_halted     Broker.check      (K3: interrupt+      (risk_tier →    record(actor,
   (existing)     (existing,         token+time+loop)     act/ask/block)  action, why)
                  generalize K2)     extend existing
                                          │
                          ┌───────────────┴───────────────┐
                       GRANT                  QUEUE  ──► autonomy TaskQueue (existing)
                    (execute now)          (approval card, interrupt-budgeted)   │
                       DENY (reason) ◄──────────────────────────────────────────┘
```

### Design points

1. **Compose, don't replace.** `kernel.authorize` is the *entry*; it calls the existing
   `security/capability.authorize()` nucleus, `policy.decide()`, and the budget checks, then returns
   `Decision ∈ {grant, deny(reason), queue(card)}`. A `queue` decision uses today's `TaskQueue` +
   `AutonomyWorker` unchanged. No second approval system.
2. **Capabilities as process-permissions (K2).** Generalize `CapabilityBroker` (today: 2 callers) so
   **every** agent runs under a scoped, expiring, revocable capability set, least-privilege by default.
   Fold the WorldView HMAC tokens (`security/worldview_mcp.py:59`) in as one capability *kind* rather
   than a parallel scheme. Closes **B1** (admin actions require a capability, not just a network origin).
3. **The scheduler (K3, folds H23.1).** One `Budget` object carried on every action: unify
   `InterruptBudget` + mission step/time budgets + payment caps, and **add the three missing limits** —
   per-task token budget, wall-time, and recursion-depth — plus a loop-wide circuit breaker that trips
   the kill-switch on runaway. The interrupt budget stays the MOONSHOT §5.4 "≤4 push/day" guardrail,
   now enforced in exactly one place.
4. **Kill-switch + quarantine as a syscall (K4, folds H23.3).** Promote the existing `KillSwitch` +
   `SecretBroker` to first-class kernel calls with one-tap HUD control: halt → quarantine credentials
   (`secret_broker` already gates injection on approval) → resumable, fully audited. Closes **B3** by
   routing the strict-egress escape through the kernel so a downgrade is *audited and alertable*.
5. **The action-auth matrix gate.** Generalize `tests/test_route_auth_matrix.py` from "every HTTP
   mutator is guarded" to "every privileged **action** flows through `kernel.authorize`": a snapshot
   test (`_snapshots/action_auth.json`) with `INTENTIONALLY_DIRECT` / `PENDING_KERNEL` escape sets that
   **fails CI if any new privileged call bypasses the kernel** — and shrinks `PENDING_KERNEL` to empty
   the way SEC-3 emptied `PENDING_GUARD`. Closes **B2** (no fail-open path can exist un-snapshotted).

### Gating & safety

- `JARVIS_ACTION_KERNEL=1` to route through the kernel; **default off until the matrix is green**, so
  migration is incremental and reversible (mirrors the H22.9 / H22.5 kill-switch discipline).
- Every `authorize` emits an audit record (grant/deny/queue + reason) through the existing audit callable.
- Strict-local agents (`frigga`/`ultron`/`howard`) are unaffected — the kernel mediates *authorization*,
  never forces a cloud hop (MOONSHOT §5.1).

## Acceptance

1. A privileged action with a missing/expired/insufficient capability → `deny(reason)`, audited.
2. A reversible action under budget → `grant`; an IRREVERSIBLE one → `queue` (approval card, interrupt-
   budgeted) — same UX as today, one code path.
3. Engaging the kill-switch halts new grants **and** quarantines credentials (injection blocked); release
   resumes; all four steps audited.
4. A runaway loop (recursion/token/time over budget) is halted by the scheduler and trips the breaker.
5. `tests/test_action_auth_matrix.py` **fails** when a new privileged call is added that bypasses
   `kernel.authorize` and isn't in an escape set.
6. Each of B1/B2/B3 has a regression test proving it's closed (admin action needs a capability; MCP
   mutating tool can't bind without an identity check; an egress downgrade is audited + alertable).

## Phasing / migration (no big-bang)

Land the `kernel.authorize` facade wrapping the existing nucleus, default-off. Route callers in waves —
**(1)** the TaskQueue-backed brokers (payment/call/writeback/social/node) that already share an
interface; **(2)** plugin egress; **(3)** the MCP route-tools + KG writes; **(4)** the admin security
routes (B1). Each wave moves entries out of `PENDING_KERNEL` in the action-auth snapshot, so progress is
CI-visible and a regression is impossible to merge silently. Track V's readiness registry marks a
capability VERIFIED only once it is *both* harness-green and kernel-mediated.
