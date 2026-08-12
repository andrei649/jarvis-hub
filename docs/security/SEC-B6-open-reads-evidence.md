# SEC-B6 — open-read classification evidence

> The route-auth gate (`tests/test_route_auth_matrix.py::test_no_unclassified_open_read`) proves
> **membership**: every open GET is either in `INTENTIONALLY_OPEN_READS` or carries `user_guard`. It
> cannot prove the **truth** of a classification — that an "intentionally open" handler really exposes
> no personal content. This document is that evidence, per handler response substance, so a reviewer
> can check the classification without re-reading every router. Ordered by the same groups as the test.
>
> **Method:** each row states what the handler's response body *contains* (read from the handler
> source at this PR's base), and why that content is non-personal. "Personal content" = a specific
> user's data: message/turn text, memory/notes/KG facts, task/mission/review contents, per-agent run
> history, SOUL text, connected-account tokens. Aggregate counters, rates, capability catalogs,
> liveness booleans and config-presence flags are **not** personal content.

## Load-bearing individual justifications

| Route | Handler returns | Why open is correct |
|-------|-----------------|---------------------|
| `GET /agents` | roster: name, tier, model, heartbeat bool, aggregate `stats`, skill **names** | no turn/memory content; the same roster the app shell needs pre-auth |
| `GET /plugins` | per-plugin `configured` **booleans** + labels | presence flags only — never a key value or secret (verified: `honesty.py` `_NEEDS` gating, ADV-069) |
| `GET /api/security/governance`, `/kill-switch`, `/loop-breaker`, `/api/trust/status`, `/security`, `/security/status` | governance posture, kill-switch state, loop-breaker state, mic/strict-local trust signal | **deliberate transparency** — H18.18 reads these from mobile without a token by design; every *write* on these surfaces stays admin-guarded. An open read of a safety *state* is the product being inspectable (MOONSHOT §5.3) |
| `GET /api/security/capabilities/check` | boolean admissibility of a *proposed* capability action | evaluates a hypothetical; returns no stored user data |
| `GET /api/oauth/status`, `/api/oauth/auth-url`, `/api/oracle/status` | connect-flow presence booleans + public provider auth URLs | pre-auth by nature (you call them *before* you have a token); no token value returned. **Contrast:** `/api/oracle/conflicts` returns actual conflict content → guarded (`user`) |
| `GET /api/worldview/status` | liveness booleans (connected, api_url) | **Contrast:** `/api/worldview/overview` returns recon/alert content → guarded (`user`) |

## Group justifications

- **App shell + static** (`/`, `/v1`, `/v2`, `/v2/{path}`, `/admin`, `/favicon.ico`, `/sw.js`) — serve
  markup/bytes. `/admin` is the page *shell*; every admin API behind it is `admin`-guarded.
- **FastAPI scaffolding** (`/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`) — route schema,
  no stored data.
- **Public protocol surfaces / token-in-path** (`/.well-known/agent-card`,
  `/.well-known/oauth-protected-resource`, `/api/mcp/server`, `/api/widget/{token}`,
  `/api/widget/{token}/config`) — public protocol metadata, or a capability token in the path *is* the
  authenticator.
- **Liveness / ops meters** (`/healthz`, `/readyz`, `/metrics`, `/api/resilience`,
  `/api/health/components`, `/api/status`, `/status`, `/api/local-docs`) — process/health aggregates
  and degradation flags; no user content.
- **Catalogs shipped in code** (`/api/agent-templates`, `/api/memory/tool-spec`,
  `/api/memory/eval/corpus`, `/api/voice/capabilities`, `/api/voice/wyoming`, `/skills`,
  `/skills/imported`, `/sandbox/status`) — static/derived catalogs. `/api/memory/eval/corpus` is the
  **owned synthetic** eval corpus (`DEFAULT_CORPUS`), never live user memory.
- **Aggregate observability** (`/api/analytics/{cost,locality,model-tiers}`,
  `/api/metrics/{capabilities,kernel,north-star}`, `/api/quality`, `/api/review/stats`,
  `/learning/stats`, `/bench`, `/bench/stats`, `/memory/stats`, `/heartbeat/status`,
  `/api/arena/leaderboard`, `/api/eval/datasets`, `/api/eval/datasets/{name}/runs`,
  `/api/eval/datasets/{name}/compare`, `/api/autonomy/escalation/targets`) — counts, rates,
  percentiles, scores, channel *names*. No message/turn/memory content. **Contrasts that were
  guarded:** `/api/quality/scores` (per-request scores), `/api/arena/match/{id}` (match body),
  `/learning` (per-agent optimizations) → all now `user`.

## The 13 routes moved to `user_guard` (the delta this PR ships)

Each returns a specific user's content, so each now requires `X-User-Token`:

`/api/agents/history`, `/api/agents/{id}/history` (per-agent run history) · `/api/agents/{id}/soul`
(SOUL text) · `/api/quality/scores` (per-request quality) · `/api/review/queue` (review items) ·
`/api/missions`, `/api/missions/{id}` (mission workspaces + audit trail) · `/api/workflows`
(user-defined pipelines) · `/learning` (per-agent prompt optimizations) · `/api/arena/match/{id}`
(match record) · `/api/oracle/conflicts` (conflict content) · `/api/reflection/status` (daily
reflection result) · `/api/worldview/overview` (recon/alerts).

## Known follow-up (not shipped here)

The forget **export** manifest and the purge **KEEP** allowlist are maintained separately; a future
divergence would be silent. Recommended: a test asserting `export_manifest ⊆ (purged ∪ KEEP)`. Tracked
in the chapter-15 hermetic run record. Out of scope for this SEC-B6 slice.
