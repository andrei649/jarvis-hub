# Security Route-Policy Audit — Verified Assessment (2026-06-17)

> Status: **assessment only — no routes changed.** This reconciles the external
> GPT audit (`jarvishubfullaudit20260617.md`) against the live code and a runtime
> route enumeration, and proposes a route-policy table for a later remediation
> pass. Owner decides scope before any guard is added.
>
> **Remediation update (2026-06-19):** the proposed pass has since landed — see
> `BACKLOG.md` SEC-1…SEC-5. The original verdicts below are kept as the historical
> as-assessed record; each affected row and the remediation order now carry a
> **current-status** note. Net: the P0 (F-01) and the P1s (F-02, F-03) are fixed
> and CI-enforced; F-10 is **superseded 2026-08-29 (de-gate)** — see its row below — and the
> remaining items are deferred (SEC-5b, F-11).

## Method

Unlike the source audit (which used conservative AST extraction), the open-route
list here comes from **runtime introspection of `app.routes`** — each route's
resolved `dependant` chain checked for `_user_guard` / `_admin_guard`. This is
ground truth for what actually gates each endpoint.

Enumerated on `main` @ commit after #214:

| Guard | Count |
|---|---:|
| Total routes | 300 |
| `admin` | 89 |
| `user` | 87 |
| **OPEN (no guard)** | **124** |
| **OPEN *and* mutating (POST/PUT/DELETE/PATCH)** | **43** |

The guard model itself is sound: `_user_guard`/`_admin_guard` require a token when
one is set, else allow **localhost only** and fail closed behind an untrusted
proxy (HF-7). The issue is exclusively routes that attach **no guard at all** —
they bypass that model entirely. Routers are mounted in `agents/web.py:1337-1396`;
only the cognition router gets a mount-level guard, so every other route depends
on its own per-route `Depends(...)`.

**Deployment caveat:** on a localhost-only bind (the current default usage) these
are footguns, not live exploits. They become real unauthorized-control surfaces
on LAN / Pi / reverse-proxy / public-tunnel exposure.

## Finding-by-finding verdict

| ID | Audit claim | Verified verdict |
|---|---|---|
| **F-01** | Webhook management unguarded (P0) | **CONFIRMED.** `agents/core/routers/webhooks.py` `GET/POST/DELETE /api/webhooks` have no `Depends`; `web.py:1372` mounts the router with no guard. `POST /api/webhooks` mints a token; `POST /api/webhooks/{id}` runs `orch.handle_input(..., agent_override=…)`. Real reachability→agent-exec path off localhost. **Since FIXED (SEC-1):** management routes now require `admin_guard`; the trigger keeps its token/HMAC; off-localhost management → 403, covered by a guard-contract test. |
| **F-02** | Several open mutating routes (P1) | **CONFIRMED + refined:** 43 open mutating routes at runtime (table below). Some audit entries are actually self-authenticating (see "keep open"). **Since FIXED (SEC-3):** all 43 classified — 12 → admin, 23 → user, 6 self-authenticating in `INTENTIONALLY_OPEN`; the matrix test's `PENDING_GUARD` set is now empty. |
| **F-03** | No full route/auth matrix test (P1) | **CONFIRMED.** `tests/conftest.py` autouse-overrides `_user_guard` for most tests; `tests/test_route_guard_contracts.py` covers only selected routes. A green suite can hide a newly-unguarded route. **Since FIXED (SEC-2):** `tests/test_route_auth_matrix.py` introspects `app.routes` against `tests/_snapshots/route_auth.json` and fails CI on guard drift or any new/unclassified open mutator. |
| **F-04** | Local repro broken (stale venv / no node_modules) | **Environment-specific, not a repo bug.** The auditor's Windows `.venv`/`node_modules`; CI builds clean. Worth a `bootstrap`/`doctor` script (nice-to-have), not a code defect. |
| **F-05** | Dependency advisories partial; npm not in Dependabot | **Plausible, needs owner's Dependabot view.** `.github/dependabot.yml` covers pip + actions only; 5 npm lockfiles exist. Adding npm ecosystems is cheap and worthwhile. **Partially done (SEC-4):** npm ecosystems added to `.github/dependabot.yml`; the rest needs the owner's Dependabot view. |
| **F-06** | WorldView secure-mode vs Jarvis bridge auth mismatch | **FIXED.** Bridge now sends `Authorization: Bearer` when `WORLDVIEW_API_TOKEN` is set (off by default → unchanged local behavior). Contract + tests updated. |
| **F-07** | PluginGate not a hard egress boundary | **FIXED.** Anchored host/sub-domain matching (kills the `api.openai.com.evil` substring bypass) + per-request manifest enforcement in `PluginHTTPClient` (`NONE` blocks; `LAN` local-only; `RESTRICTED` allowlist). **SEC-5: now strict by default** — `for_plugin` names reconciled to manifest ids and allowlists completed (Gemini, Google OAuth, RO news), so undeclared egress is blocked; `JARVIS_STRICT_EGRESS=0` is the escape hatch. Still-unmanifested networked plugins (websearch/balance/analytics/n8n + dynamic families) tracked as SEC-5b. |
| **F-08** | Runtime state under repo (`memory_logs/`) | **Confirmed (by design).** Git-ignored, but colocated with source. `JARVIS_HOME` default would be cleaner. P2. **Since FIXED (SEC-4):** `JARVIS_HOME` runtime-state relocation landed. |
| **F-09** | Stale route/test counters in docs | **Confirmed, cosmetic.** Runtime is 300 routes / 296 in the parity snapshot; docs say ~253. Fix counters or auto-generate. **Since FIXED (SEC-4):** counters refreshed. |
| **F-10** | CI broad but some gates advisory/push-only | **Confirmed.** ruff `--exit-zero`, codeql `continue-on-error`, Windows smoke push-only. Acceptable pre-1.0; make the route-matrix test required once it exists. **Superseded 2026-08-29 (de-gate):** the owner decided to remove the merge gates rather than promote them (#981, `824ff18`). No workflow blocks a PR any more; the route-auth-matrix and HUD-parity tests run inside the single advisory `test (ubuntu-latest)` lane on PRs (`ci.yml`) plus the post-merge push-to-main lanes. Re-gating is a reversible owner action — the workflow half is a patch in [`docs/restore/`](restore/README.md), the branch-protection half is in [`docs/OWNER_TASKS.md`](OWNER_TASKS.md) → "De-gate merges". |
| **F-11** | Large hubs (`web.py` ~2.4k, `orchestrator.py` ~1.5k) | **Confirmed** — already tracked as CLN-2/CLN-3 (owner decision: after the 1.0 gate). |
| **F-12** | Mixed scale/storage policy | **Confirmed (acceptable for personal use).** `InMemoryVectorStore` uncapped + linear scan; bitemporal facts JSON append. P2. |

Net: the security thesis is **correct and the P0 is real**. The reproducibility/
dependency findings are environmental or owner-side, not repo defects.

## Proposed route-policy table (the 43 open mutators)

### Keep OPEN — genuinely self-authenticating / public-by-design (verified)
| Route | Why it's safe open |
|---|---|
| `POST /api/webhooks/{hook_id}` (trigger) | per-webhook token or HMAC over body, verified constant-time |
| `POST /api/a2a/task` | peer HMAC signature; **off by default**; fails closed on unknown peer |
| `POST /api/mcp/server/rpc` | **disabled by default** (`mcp.server_enabled`); optional OAuth bearer |
| `POST /api/oauth/callback` | provider redirect; `verify_state` (expiring) gates it |
| `POST /api/widget/{token}/message` | widget token in path (confirm token is verified) |
| `POST /api/channels/pairing/request` | inbound pairing; lands in approval, mints nothing |

### Recommend ADMIN — config / destructive / credential / operational
| Route | Reason |
|---|---|
| `POST /api/webhooks`, `DELETE /api/webhooks/{hook_id}` | **F-01** — token minting + management |
| `PUT /plugins/{plugin_id}/toggle` | persistent config |
| `POST /heartbeat/{agent_id}/start\|stop\|run` | operational agent scheduling |
| `POST /api/traces/clear` | destructive |
| `POST /api/oauth/refresh` | credential operation (no state, unlike callback) |
| `POST /api/oracle/sync`, `POST /api/oracle/conflicts/resolve` | operational sync |
| `POST /api/security/audit/action` | audit-chain write (governance) |
| `POST /api/workflows`, `PUT\|DELETE /api/workflows/{pipeline_id}` | persisted-config CRUD |

### Recommend USER — personal data / owner-triggered execution
| Route | Reason |
|---|---|
| `POST /api/kg/entities`, `DELETE /api/kg/entities/{name}`, `POST /api/kg/facts`, `POST /api/kg/ingest`, `POST /api/kg/relations`, `DELETE /api/kg/relations` | personal knowledge graph |
| `POST /api/local-docs/index` | indexes personal folders into memory |
| `POST /api/workflows/run`, `POST /api/workflows/hierarchical` | agent execution |
| `POST /api/arena/run`, `POST /api/arena/vote` | runs candidate model calls (cost) |
| `POST /api/reflection/run` | triggers reflection (cost) |
| `POST /api/review/flag`, `POST /api/review/{item_id}/vote`, `POST /api/review/{item_id}/dataset` | review queue |
| `POST /api/agent-templates/instantiate` | creates an agent instance |
| `POST /api/memory/eval/run`, `POST /api/eval/datasets/run` | eval runs |
| `POST /api/autonomy/preview` | previews an autonomy decision |

### Borderline — stateless utilities (USER or keep open, low risk)
`POST /api/llm/grammar` · `POST /api/schedule/parse` · `POST /api/security/scan-injection` · `POST /api/security/spotlight` — no persistence; classify USER for consistency or leave open.

### Sensitive OPEN reads to also classify (not in the 43; data exposure)
`GET /api/webhooks` (lists masked tokens) · `GET /api/kg/*` (personal graph) · `GET /api/traces`, `GET /api/traces/{id}` · `GET /api/security/audit/*` · `GET /memory/stats`. Decide user vs admin per row.

## Recommended remediation order (status as of 2026-06-19 — completed)

This ordering was followed; all but the owner-side GitHub setting is done.

1. ✅ **F-01 (SEC-1)** — `GET/POST/DELETE /api/webhooks` now guarded with `admin_guard`; the trigger keeps its token/HMAC. Guard-contract test added. *(P0)*
2. ✅ **F-03 (SEC-2)** — runtime route-auth **matrix test** (`tests/test_route_auth_matrix.py`) + checked-in policy snapshot (`tests/_snapshots/route_auth.json`); CI fails on any unclassified/unguarded mutator. *(P1)*
3. ✅ **F-02 (SEC-3)** — policy applied to all remaining open mutators (12 admin / 23 user) and sensitive reads; `PENDING_GUARD` empty. Localhost dev unaffected (localhost passes guards token-free). *(P1)*
4. **Env/posture (SEC-4, owner-side):** npm Dependabot ✅ (F-05), `JARVIS_HOME` for runtime state ✅ (F-08), doc counters ✅ (F-09). **F-10 superseded 2026-08-29 (de-gate):** the gates were removed instead of promoted (#981); the matrix/parity tests run advisory on PRs and post-merge. Restoring a gate needs both halves — the workflow patch from [`docs/restore/`](restore/README.md) *and* the check name re-added in branch protection ([`docs/OWNER_TASKS.md`](OWNER_TASKS.md) → "De-gate merges").

> Plus **SEC-5** (F-06 WorldView bridge auth ✅, F-07 plugin egress now strict by
> default ✅). Deferred: **SEC-5b** (manifest the still-unmanifested networked
> plugins) and **CLN-2/CLN-3** (F-11 god-object splits, post-1.0 by owner decision).

> Adding `user`/`admin` guards does **not** break localhost usage (localhost is
> allowed without a token) and the HUD's `afetch` already sends the admin token,
> so a tokened deployment keeps working too. The risk in the remediation is
> guard *drift* during `web.py` extraction — which is exactly what the F-03
> matrix test prevents.
