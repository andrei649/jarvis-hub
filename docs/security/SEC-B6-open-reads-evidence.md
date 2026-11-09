# SEC-B6 — open-read classification evidence

Local remediation candidate, 2026-11-03. Base `3faa9e2d`, branch
`security/open-read-projections`. Twelve further content-bearing reads now require
the existing user guard; public kill-switch status has an aggregate projection
and full details require admin access. An independent source-body review of all
59 remaining intentionally open GETs (57 public, two token-in-path) recorded a
**local candidate PASS** at `47d2b4e6`. Subsequent commits through `682f1d08`
changed only client/admin authentication code and tests, not server GET handlers
or their callees. Post-merge/current-main and live acceptance remain unproven;
the SEC-B6 ledger item stays open pending that acceptance.

> The route-auth gate (`tests/test_route_auth_matrix.py::test_no_unclassified_open_read`) proves
> **membership**: every open GET is either in `INTENTIONALLY_OPEN_READS` or carries `user_guard`. It
> cannot prove the **truth** of a classification — that an "intentionally open" handler really exposes
> no personal content. This document is that evidence, per handler response substance, so a reviewer
> can check the classification without re-reading every router. Ordered by the same groups as the test.
>
> **Method:** each row states what the handler's response body *contains* (read from the handler
> source on the remediation candidate), and why that content is non-personal. "Personal content" = a specific
> user's data: message/turn text, memory/notes/KG facts, task/mission/review contents, per-agent run
> history, SOUL text, connected-account tokens, local document paths, imported owner manifests,
> user-authored dataset/case labels and free-form safety reasons/scopes. Aggregate counters, rates,
> code-owned catalogs, liveness booleans and config-presence flags are **not** personal content.

## Load-bearing individual justifications

| Route | Handler returns | Why open is correct |
|-------|-----------------|---------------------|
| `GET /plugins` | declared plugin operational metadata: configured/enabled flags, allowed domains/data scope, configuration source, degradation state/needs and grants | operational projection, with no credential value or stored turn/document body; this is broader than the historical configured-boolean description |
| `GET /api/security/governance`, `/loop-breaker`, `/api/trust/status`, `/security`, `/security/status` | governance posture, loop-breaker state, mic/strict-local trust signal | **deliberate transparency** — H18.18 reads these from mobile without a token by design; every *write* on these surfaces stays admin-guarded. An open read of a safety *state* is the product being inspectable (MOONSHOT §5.3) |
| `GET /api/security/kill-switch` | exactly `global: bool`, `any_halted: bool`, `halted_count: int`, read under one lock | safety state remains inspectable, without scope keys, reasons or arbitrary persisted timestamps. Full `{global, halted}` status is served only by admin `GET /api/security/kill-switch/details`; POST authority/storage are unchanged |
| `GET /api/security/capabilities/check` | boolean admissibility of a *proposed* capability action | evaluates a hypothetical; returns no stored user data |
| `GET /api/oauth/status`, `/api/oauth/auth-url` | connect-flow presence booleans + public provider auth URLs | pre-auth by nature (you call them *before* you have a token); no token value returned. Oracle session/conflict status is a separate content-bearing surface and is guarded |

## Group justifications

- **App shell + static** (`/`, `/v1`, `/v2`, `/v2/{path}`, `/admin`, `/favicon.ico`, `/sw.js`) — serve
  markup/bytes. `/admin` serves only the page shell and grants no API authority;
  each content request uses its own declared guard or public projection.
- **FastAPI scaffolding** (`/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`) — route schema,
  no stored data.
- **Public protocol surfaces / token-in-path** (`/.well-known/agent-card`,
  `/.well-known/oauth-protected-resource`, `/api/mcp/server`, `/api/widget/{token}`,
  `/api/widget/{token}/config`) — public protocol metadata, or a capability token in the path *is* the
  authenticator.
- **Liveness / ops meters** (`/healthz`, `/readyz`, `/metrics`, `/api/resilience`,
  `/api/health/components`, `/api/status`, `/status`) — process/health aggregates
  and degradation flags; no user content.
- **Catalogs shipped in code** (`/api/agent-templates`, `/api/memory/tool-spec`,
  `/api/memory/eval/corpus`, `/api/voice/capabilities`, `/api/voice/wyoming`) — static/derived catalogs. `/skills` already requires a user credential;
  imported owner manifests are not a shipped catalog and now also require it. `/api/memory/eval/corpus` is the
  **owned synthetic** eval corpus (`DEFAULT_CORPUS`), never live user memory.
- **Aggregate observability** (`/api/analytics/{cost,locality,model-tiers}`,
  `/api/metrics/north-star`, `/api/quality`, `/api/review/stats`,
  `/bench`, `/bench/stats`, `/memory/stats`, `/heartbeat/status`,
  `/api/autonomy/escalation/targets`) — counts, rates,
  percentiles, scores, channel *names*. No message/turn/memory content. **Contrasts that were
  guarded:** `/api/quality/scores` (per-request scores), `/api/arena/match/{id}` (match body),
  `/learning` (per-agent optimizations) → all now `user`.

## Twelve additional content reads guarded by this local remediation

| Route | Stored owner content retained for authorized users | Source |
|---|---|---|
| `GET /agents` | SOUL-derived descriptions beside roster metadata | `routers/agents_api.py::get_agents`, `soul_edit.description_of` |
| `GET /api/oracle/status` | session/task details, raw errors, conflict paths and PR feed | `routers/oauth.py::oracle_status`, `OracleBridge.status` |
| `GET /api/eval/datasets` | stored user-chosen dataset names | `routers/eval.py::list_eval_datasets`, `DatasetStore.list_datasets` |
| `GET /api/eval/datasets/{name}/runs` | dataset identity with run summaries | `routers/eval.py::list_dataset_runs` |
| `GET /api/eval/datasets/{name}/compare` | dataset identity and user-authored regression/improvement case labels | `routers/eval.py::compare_dataset_runs`, `DatasetStore.compare` |
| `GET /learning/stats` | prompt optimizations containing failed-turn response/error text | `routers/learning.py::learning_stats`, `LearningLoop.optimize_prompt` |
| `GET /api/local-docs` | last indexed absolute folder, skipped document basenames and configured folder keys | `routers/onboarding.py::local_docs_status`, `LocalDocsIndexer.index` |
| `GET /skills/imported` | entire owner-writable local manifest, including arbitrary extra fields and local provenance paths | `routers/skills.py::skills_imported`, `SkillImporter.list_imported` |
| `GET /api/arena/leaderboard` | persisted caller-supplied candidate labels beside scores | `routers/arena.py::arena_leaderboard`, `Arena.create_match`, `Arena.leaderboard` |
| `GET /api/metrics/kernel` | raw recent denial reasons, including owner-specific action/device scopes | `routers/analytics.py::metrics_kernel`, `KernelMetrics.snapshot`, kernel halt decisions |
| `GET /api/metrics/capabilities` | dynamically registered connected-tool descriptions, including third-party MCP text | `routers/analytics.py::metrics_capabilities`, capability registry `_tool_records`, `MCPBridge._description` |
| `GET /sandbox/status` | registered tool descriptions/input schemas from connected tools | `routers/skills.py::sandbox_status`, `ToolRPCServer.tools(live=False)` |

These reads use the shared `user_guard` before handler execution and retain their
full successful bodies with no-store headers. Missing/invalid credentials cannot
retrieve the seeded private sentinels; matching user credentials and admin
credentials retain the original payloads. `tests/test_sec_b6_read_content.py`
exercises those boundaries with isolated data and the actual guards, including
public kill-state exclusion, admin-only details and persisted private reasons.
Matrix membership alone is not acceptance of these response bodies.
Disabling live schema overrides does not turn connected-tool metadata into a
static catalog: registered descriptions and input schemas can still contain
private local-server context, so both tool catalog reads require the user guard.
The independent review's 59-route handler/body table and local test scope are
recorded in [the dated review](2026-11-03-open-read-review.md). A separate focused
guard gate recorded 108 tests, zero failures/errors/skips; broader candidate
gates and live acceptance are separate.

## The original 13 routes moved to `user_guard`

Each returns a specific user's content, so each now requires `X-User-Token`:

`/api/agents/history`, `/api/agents/{id}/history` (per-agent run history) · `/api/agents/{id}/soul`
(SOUL text) · `/api/quality/scores` (per-request quality) · `/api/review/queue` (review items) ·
`/api/missions`, `/api/missions/{id}` (mission workspaces + audit trail) · `/api/workflows`
(user-defined pipelines) · `/learning` (per-agent prompt optimizations) · `/api/arena/match/{id}`
(match record) · `/api/oracle/conflicts` (conflict content) · `/api/reflection/status` (daily
reflection result) · `/api/worldview/overview` (recon/alerts).

## Earlier export/purge follow-up

The earlier export-manifest/purge-KEEP drift follow-up was delivered in #900
(`2f81029`); `tests/test_forget_export_purge_parity.py` checks their relationship.
This is separate from response-content acceptance and does not close SEC-B6.
