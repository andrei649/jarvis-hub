# Threat Model — Jarvis Hub

> What Jarvis defends, against whom, and the concrete mechanism for each threat. This is
> a living document grounded in the actual code (every mitigation links to the seam that
> implements it). Pair with [`SECURITY.md`](../SECURITY.md) (disclosure policy) and
> [`docs/PRIVACY.md`](PRIVACY.md) (data handling). Last reviewed: 2026-06.

## 1. System & trust boundaries

Jarvis Hub is **local-first and single-user**: it runs on the owner's machine, binds to
**loopback by default**, and treats the cloud as **opt-in per agent/plugin**. The trust
boundaries, from most to least trusted:

```
  owner (localhost) ─► Jarvis hub process ─► [ kernel mediation ] ─► local model server
                                              │                       (LM Studio / Ollama)
                                              ├─► local stores (memory.db, KG, transcripts, analytics)
                                              ├─► LAN devices (Pi, homebridge, WhatsApp bridge)   [LAN-scoped]
                                              └─► cloud (LLM APIs, channels, OSINT)               [opt-in, allowlisted]
```

- **Inside the boundary (trusted):** the owner over loopback; the orchestrator + cabinet agents; local stores under the gitignored data root.
- **Mediated (semi-trusted):** plugins, MCP tools, channels — each runs under a declared network/data policy enforced at a choke point.
- **Outside (untrusted):** the public network; **untrusted external data** ingested by OSINT/WorldView and RSS/web fetches; any non-loopback caller.

## 2. Assets

| Asset | Why it matters |
| --- | --- |
| Personal memory / knowledge graph / transcripts | The most sensitive data; the whole product is built on it. |
| Credentials & secrets (API keys, channel tokens) | Compromise = impersonation + data exfiltration. |
| The host machine | Code execution (skills/sandbox/desktop control) could pivot to the OS. |
| Action authority | Autonomy can send messages, move money, post — misuse is high-impact. |
| The audit log | Tamper would erase the record of what happened. |

## 3. Threats & mitigations (mechanism, not aspiration)

| # | Threat | Mitigation (seam) |
| --- | --- | --- |
| T1 | **Data exfiltration** — a plugin/agent sends personal data off-box | Per-plugin **egress policy** (`plugin_gate.py` `NetworkAccess` NONE/LAN/RESTRICTED/FULL) enforced at the single client choke point (`http_client.py:_enforce_egress`, strict by default); **egress monitor** records every attempt and proves LOCAL_ONLY plugins make zero external calls (`observability/egress_monitor.py`, `GET /api/admin/network/calls`); SSRF-safe fetch (`plugins/websearch.py`). |
| T2 | **Unauthorized privileged action** — autonomy acts without approval | The **action kernel** (`kernel.authorize`) is an additional **deny** layer, not the only one — with the kernel off, the payment contract, the approval queue and the audit log all still run, so a fresh install is governed and enabling the flag *unlocks* autonomy rather than adding safety: kill-switch + capability + policy → `grant/deny/queue`; irreversible actions are queued for approval; the **action-auth matrix** (`test_action_auth_matrix.py`) fails CI if a privileged action bypasses the kernel. |
| T3 | **Runaway / unbounded consumption** (OWASP LLM) | The kernel **scheduler** (`kernel/budget.py`): per-task token/wall-time/recursion-depth ledger + a loop-wide **circuit breaker** that halts a runaway at the front door. Interrupt budget (≤4 proactive pushes/day) + per-plugin breakers. |
| T4 | **Secret theft at rest** | Credentials are **Fernet-encrypted** in `settings.db` (`settings_db.SECRET_KEYS`); backups encrypt to `.tar.gz.enc`; the **secret broker** gates injection on approval and **redacts** values from logs (`security/secret_broker.py`). |
| T5 | **Audit tampering** | The audit chain is **HMAC-SHA256** with an off-box key (`JARVIS_AUDIT_KEY`); a forged/edited row fails verification, including a **full-table downgrade** to unkeyed sha256, which verified until AUDIT-1 (`security/audit.py`, `test_audit_hardening.py`). **Without** a key the chain is integrity-only, not tamper-evident — anyone with file access can recompute it — and `GET /api/security/audit/verify` reports `tamper_evident` separately from `valid` so the two are not confused. |
| T6 | **Injection** — prompt / indirect / data-store | `GuardrailsEngine` REDACT/BLOCK; **Cypher** label/rel/key allowlist at the KG write chokepoint (`memory/graph.py`); **WKT** bounds-checking on untrusted OSINT coordinates (`wkt_guard`); cross-channel taint flag (partial — see §5). |
| T7 | **Sandbox escape** — untrusted skill/code | Containerized execution with **no network + read-only FS**, proven by a dedicated, un-skippable CI lane (`test_sandbox_isolation.py`, `RUN_SANDBOX_ISOLATION=1`). |
| T8 | **Network exposure** — a non-loopback bind leaks the API | Loopback default; `serve.assert_safe_bind()` **fails closed** on a non-loopback bind without a token; CSP + `X-Content-Type-Options`/`X-Frame-Options` headers (`_security_headers`); WorldView backend **fails closed** on `0.0.0.0` + empty secret. |
| T9 | **Credential/authZ abuse** — stolen token replays | Managed **token store** (hashed-at-rest, TTL, rotation revokes prior + the bootstrap env token); admin/user route-guard matrix (`test_route_auth_matrix.py`). |
| T10 | **Path traversal** — `session_id`/file inputs escape the data root | Anchored validation (`^[A-Za-z0-9_-]+$`) at the persistence boundary (`test_session_traversal.py`). |
| T11 | **Supply-chain** — tampered dependency or CI action | Hash-pinned lockfiles (`--require-hashes`); SHA-pinned GitHub Actions; blocking SAST (bandit/semgrep) + secret-scan (gitleaks) + dependency-CVE (pip-audit) gates (`AUD-10`). |

## 4. Continuous verification (defense that can't silently rot)

Mitigations are pinned by **snapshot matrices** that fail CI on regression, the discipline
that drove `PENDING_GUARD` to empty in SEC-3:

- **Route auth** (`route_auth.json`) — every HTTP mutator is guarded.
- **Action auth** (`action_auth.json`) — every privileged action flows through the kernel.
- **Capability readiness** (`capability_readiness.json`) — no capability claims `VERIFIED` without a green reality-harness; no user-facing capability is left a stub.
- **Reality harness** (`reality_harness.py`) — proves rails against the real protocol, not mocks.

## 5. Residual risks & out of scope (honest)

- **Single-user model.** No per-user isolation/RLS today (a 1.0 decision — `docs/SINGLE_USER_NOTE.md` / H23.23). Multi-tenant is **out of scope** for 0.x.
- **Kernel default-off, with a fail-closed MCP exception.** The action kernel (`JARVIS_ACTION_KERNEL`) remains opt-in for legacy action families; all privileged-action kinds are kernel-mediated (zero `PENDING_KERNEL` remain) once enabled. MCP mutating route tools are stricter: disabled/unavailable kernel, `DENY`, and `QUEUE` all refuse before the adapter, so only an explicit `GRANT` can write. A capability token is mandatory for admin.\*/kg.write; the already-authenticated operator route mints its own short-lived token when absent.
- **Taint-tracking is a flag, not full data-flow analysis** (H23.6).
- **Physical/host compromise** (a rooted machine, a malicious OS) is out of scope — Jarvis trusts the host it runs on.
- **The cloud providers you opt into** (LLM APIs, channels) handle data under *their* policies once you enable them — see [`docs/PRIVACY.md`](PRIVACY.md).

## 6. Reporting

Vulnerabilities: see [`SECURITY.md`](../SECURITY.md) for the disclosure policy and supported-version window.
