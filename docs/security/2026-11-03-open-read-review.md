# Open-read acceptance review, 2026-11-03

Verdict: **HOLD**. This is a source review of the local integration based on
`80e74ce8594ce501c668e395d55581b3d0b1e39f`, including the earlier SEC-B6 work.
It does not assert acceptance of a different remote head. The independent
reviewer did not build that work. All 71 intentionally open GET entries were
resolved against the runtime route table and compared with the response
classification evidence. The prescribed route-auth matrix passed **21 tests**:

```sh
JARVIS_TESTING=1 .venv/bin/python -m pytest tests/test_route_auth_matrix.py -q --timeout=90
```

Those tests prove classification membership and prevent stale allowlists. They
do not establish that a response contains no personal content. The following
source findings prevent acceptance:

| Response | Current behavior | Required boundary |
|---|---|---|
| `GET /api/oracle/status` | `routers/oauth.py::oracle_status` returns `oracle_bridge.py::OracleBridge.status`, including recent session/task details, raw errors, unresolved file conflicts and the PR feed. Its evidence describes OAuth presence booleans. | Require user authentication for content, or expose a strictly non-content public projection. Add a response-level negative/positive regression and correct the evidence. |
| `GET /agents` | `routers/agents_api.py::get_agents` includes `soul_edit.description_of(agent)`, which reads the current SOUL frontmatter and can contain owner-authored text. The evidence describes roster metadata without this field. | Protect the SOUL-derived content or remove it from the public projection; preserve the authenticated roster's functionality. |
| `GET /api/security/kill-switch` | `routers/security.py::kill_switch_status` returns persisted state without projection, including the admin's free-form reason. Public safety-state transparency does not establish permission to disclose owner-authored context. | Preserve public safety state while protecting free-form owner content, with tests for the exact response boundary. |

The dataset comparison endpoint also returns user-authored case names rather
than only score aggregates. Its classification needs an explicit source review;
the current evidence does not discuss those labels. No disclosure permission is
inferred from a green route matrix.

Next action: fix the response boundaries with meaningful failing regressions,
update the per-handler evidence, and repeat independent acceptance on the final
source. SEC-B6 remains open until that review records PASS. No production state,
credentials, owner-only decisions or repository settings were changed.

## Subsequent independent local acceptance — 2026-11-03

The **HOLD above is the historical verdict** for integration `80e74ce8`; it is
preserved to show the source findings that prompted remediation. The independent
reviewer then traced every current open-read response on the frozen local
candidate `47d2b4e6ad6aab275929ae47e5094ac8b7b06195` and recorded a
**local source-body PASS**. The candidate has **59** intentionally open GETs:
57 public and two self-authenticating widget-token reads. The table below names
each handler and the substance it returns. It is the response-content review;
the route-auth matrix by itself establishes membership and guard wiring only.

The earlier Oracle, SOUL, dataset-label, and kill-switch findings were addressed
by user guards or the exact three-field public kill projection. A subsequent
63-route review found four further content-bearing reads: Arena candidate labels,
raw kernel denial reasons, and connected MCP descriptions in the capability and
sandbox catalogs. All four now require `user_guard`, retain their full authorized
responses, and have request-level private-sentinel tests with anonymous/invalid
refusal and user/admin success. The kill projection remains three typed aggregate
fields; full persisted details require admin authentication. The H296 direct
handler test also decodes the guarded sandbox `JSONResponse` and keeps its
static-schema assertions.

On `47d2b4e6`, the independent reviewer reran the prescribed route-auth matrix
and the SEC-B6 privacy module under the normal non-root Python 3.12 environment:
**34 passed**.

```sh
JARVIS_TESTING=1 .venv/bin/python -m pytest tests/test_route_auth_matrix.py tests/test_sec_b6_read_content.py -q --timeout=90 --disable-warnings
```

A separate focused integration gate recorded **108 tests, zero failures, zero
errors, zero skips** in `.git/codex-local/sec-b6-20261103/guards-junit.xml`
(route auth, privacy, H296, and route/OpenAPI parity); that gate is supporting
local evidence, not the independent source-body decision. The later commits
`ad2b0433` and `682f1d08` changed admin/client authentication code and tests
only; they did not change the server GET handler/callee bodies reviewed here.

### Current 59-route response-content table

`PASS` here means the handler/callee response substance was checked against the
documented public or self-authenticating boundary on this local candidate. It
does not mean post-merge/current-main or live-provider acceptance.

| # | Open GET | Handler → response substance | Verdict |
|---:|---|---|---|
| 1 | `/` | `web.index` → shipped HUD HTML shell | PASS |
| 2 | `/.well-known/agent-card` | `a2a.a2a_agent_card` → deliberately public signed advertised name/capabilities or disabled 404 | PASS |
| 3 | `/.well-known/oauth-protected-resource` | `mcp.mcp_protected_resource_metadata` → resource and configured authorization-server URLs | PASS |
| 4 | `/admin` | `web.admin_page` → shipped admin HTML shell; APIs separate | PASS |
| 5 | `/api/agent-templates` | `agents_api.agent_templates_list` → code-owned template keys, role, descriptions, models and plugins | PASS |
| 6 | `/api/analytics/cost` | `analytics.get_analytics_cost` → cost-tracker per-agent/model usage and estimated cost, no turn text | PASS |
| 7 | `/api/analytics/locality` | `analytics.analytics_locality` → run-history local/cloud/unknown counts and percentage | PASS |
| 8 | `/api/analytics/model-tiers` | `analytics.get_model_tiers` → agent/model IDs, tier, calls, priced/unpriced cost summary | PASS |
| 9 | `/api/autonomy/escalation/targets` | `autonomy.escalation_targets` → configured channel IDs and resolved target channel IDs | PASS |
| 10 | `/api/design-manifest` | `design_manifest.design_manifest` → tokens/classes parsed from shipped stylesheet | PASS |
| 11 | `/api/health/components` | `status.component_health` → component name → ok/failed, failed names and count summary; registry drops exception text | PASS |
| 12 | `/api/mcp/server` | `mcp.mcp_server_status` → enabled flag, exposed agent/tool names and effect inventory, no tool result | PASS |
| 13 | `/api/memory/eval/corpus` | `memory_kg.memory_eval_corpus` → code-owned `DEFAULT_CORPUS` synthetic cases and abilities | PASS |
| 14 | `/api/memory/tool-spec` | `memory_kg.memory_tool_spec` → fixed `TOOL_SPEC` declaration | PASS |
| 15 | `/api/metrics/north-star` | `analytics.metrics_north_star` → acceptance/interrupt/reject/locality/latency and night-shift aggregates, activation state/install ID | PASS |
| 16 | `/api/oauth/auth-url` | `oauth.oauth_auth_url` → public provider authorization URL or unknown-service error | PASS |
| 17 | `/api/oauth/callback` | `oauth.oauth_callback_redirect` → state-gated exchange result page naming service or fixed failure | PASS |
| 18 | `/api/oauth/status` | `oauth.oauth_status` → service labels, connected booleans and pre-auth URLs; token values absent | PASS |
| 19 | `/api/quality` | `quality.quality_status` → rolling numeric stats and alert thresholds, not per-request scores | PASS |
| 20 | `/api/resilience` | `ops.resilience_public` → breaker states/failure counts, uptime, SSRF/redaction counts, aggregate error types | PASS |
| 21 | `/api/review/stats` | `review.review_queue_stats` → queue counts and fixed rubric names, no trace preview/notes | PASS |
| 22 | `/api/security/capabilities/check` | `security.capabilities_check` → admissibility boolean and fixed current-token/kill reason for supplied hypothetical | PASS |
| 23 | `/api/security/governance` | `security.security_governance` → synthetic security scorecard and gate threshold | PASS |
| 24 | `/api/security/kill-switch` | `security.kill_switch_status` → exactly locked `global: bool`, `any_halted: bool`, `halted_count: int` | PASS |
| 25 | `/api/security/loop-breaker` | `security.loop_breaker_status` → tripped flag, threshold/window and event count; no signatures | PASS |
| 26 | `/api/status` | `status.api_status` → version, agent count, safe-mode and warmup state | PASS |
| 27 | `/api/trust/status` | `oauth.trust_status` → mic/strict-local/cloud-availability booleans | PASS |
| 28 | `/api/voice/capabilities` | `voice.voice_capabilities` → engine readiness, consent flag, voice/provider selectors and closed failure reasons; no command argv/path | PASS |
| 29 | `/api/voice/wyoming` | `wyoming.wyoming_status` → enabled/listening/reachable booleans, protocol and fixed note | PASS |
| 30 | `/api/workspace/session` | `workspace_auth.session_state` → anonymous setup/SSO booleans; user/org/CSRF only after resolving signed session cookie | PASS |
| 31 | `/bench` | `bench.get_bench` → total benchmark summary and per-agent latency/success/model aggregates; no sample text | PASS |
| 32 | `/bench/stats` | `bench.bench_stats` → latency percentiles, throughput and agent count/latency aggregates | PASS |
| 33 | `/docs` | FastAPI `swagger_ui_html` → generated docs shell | PASS |
| 34 | `/docs/oauth2-redirect` | FastAPI `swagger_ui_redirect` → OAuth docs helper HTML | PASS |
| 35 | `/favicon.ico` | `web.favicon` → shipped SVG | PASS |
| 36 | `/healthz` | `ops.healthz` → status, uptime, safe-mode flag | PASS |
| 37 | `/heartbeat/status` | `heartbeat.heartbeat_status` → schedule IDs/times and blocked flags/digest with **relative** file path, not file bytes or absolute path | PASS |
| 38 | `/manifest.webmanifest` | `web.v2_manifest` → shipped PWA branding/icons with root-path rewrite | PASS |
| 39 | `/memory/stats` | `memory_hud.memory_stats` → session/vector/KG counts, current session ID, agent-context sizes; no turns or KG facts | PASS |
| 40 | `/metrics` | `ops.metrics` → HTTP RED metrics labelled by route template, never raw request path | PASS |
| 41 | `/openapi.json` | FastAPI `openapi` → mounted schema | PASS |
| 42 | `/plugins` | `plugins.list_plugins` → operational manifest names/scopes/domains, flags, configuration-source, degradation and grant metadata; no credential values | PASS |
| 43 | `/readyz` | `ops.readyz` → readiness checks, backend name/reachability age, safe-mode/warmup | PASS |
| 44 | `/redoc` | FastAPI `redoc_html` → generated docs shell | PASS |
| 45 | `/security` | `security_hud.get_security` → guardrail enabled/scanner names and audit count | PASS |
| 46 | `/security/status` | `security_hud.security_status` → scanner/SSRF/redaction counters and mode, no finding text | PASS |
| 47 | `/status` | `status.status` → host/CPU/GPU/model, channel IDs, session **counts**, service unit/pid and slot **counts**; holder session IDs are guarded separately | PASS |
| 48 | `/sw-v2.js` | `web.v2_service_worker` → shipped worker JS | PASS |
| 49 | `/sw.js` | `web.service_worker` → shipped legacy worker JS | PASS |
| 50 | `/v1` | `web.index_v1` → shipped legacy HUD HTML | PASS |
| 51 | `/v2` | `web.hud_v2` → shipped HUD HTML or fixed not-built page | PASS |
| 52 | `/v2/manifest.webmanifest` | `web.v2_manifest` → same shipped PWA manifest | PASS |
| 53 | `/v2/sw-v2.js` | `web.v2_service_worker` → same shipped worker JS | PASS |
| 54 | `/v2/{path:path}` | `web.hud_v2` → shipped SPA HTML shell for client route | PASS |
| 55 | `/workspace` | `workspace_ui.workspace_root` → root-path-aware redirect to shell or fixed 404 | PASS |
| 56 | `/workspace/` | `workspace_ui.workspace_index` → shipped workspace shell or fixed 404/503 | PASS |
| 57 | `/workspace/{path:path}` | `workspace_ui.workspace_app` → same shipped SPA shell for client route | PASS |
| 58 | `/api/widget/{token}` | `secrets.widget_snippet` → JS only after exact widget-token lookup; path token is the credential | PASS (self-auth) |
| 59 | `/api/widget/{token}/config` | `secrets.widget_config` → widget config only after exact widget-token lookup | PASS (self-auth) |

The local PASS applies to the frozen, unpublished remediation branch through
`682f1d08`. It does not replace a post-merge/current-main source review or live
acceptance, and it does not close the SEC-B6 ledger item. Broader candidate gates
were still running when this record was written; no full-suite result is claimed.
