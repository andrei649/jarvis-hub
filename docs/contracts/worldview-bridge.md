# WorldView Bridge — integration contract (v1)

> The **only** coupling between the JARVIS hub and the WorldView 4D OSINT stack. Both sides
> may evolve freely as long as this contract holds; it is enforced by contract tests on each
> side (`tests/test_worldview_bridge_contract.py` in the hub,
> `worldview/backend-api/test/bridgeContract.test.ts` in WorldView). Change the contract →
> bump `version`, update both tests in the same PR.
> Created 2026-06-10 · Owner: Andrei · Status: v1, in force.

## Parties

| Side | Code | Role |
|---|---|---|
| **Consumer** | `agents/core/plugins/worldview.py` (+ governance wrapper `agents/core/security/worldview_mcp.py`, KG sync `agents/core/memory/worldview_sync.py`, persona `agents/argus/`) | Read-only client on the chat turn |
| **Provider** | `worldview/backend-api` (Fastify REST, default `http://localhost:4000`; route registry: `src/auth/rbac.ts` `ROUTE_RULES`) | Serves the 4D OSINT layers |

## Endpoints (machine-readable — parsed by both contract tests)

```yaml
version: 1
endpoints:
  - method: GET
    path: /history/:layer
    query: [t, bbox, lod]
    returns: GeoJSON FeatureCollection (features[])
  - method: GET
    path: /recon/windows
    query: [aoi, from, to]
    returns: { windows: [] }
  - method: GET
    path: /recon/alerts
    query: [lead]
    returns: { alerts: [] }
  - method: GET
    path: /provenance/:layer/:entityId
    query: [t]
    returns: { provenance: ... }
  - method: GET
    path: /ontology/objects/:type
    query: [limit]
    returns: { objects: [] }
  - method: GET
    path: /ontology/objects/:type/:id/links
    query: []
    returns: { links: [] }
```

`:layer` ∈ `adsb | ais | tle | ew | context` (mirrors `backend-api/src/types.ts`).

## Guarantees

1. **Read-only.** The hub bridge issues `GET` only. Mutating WorldView operations
   (`watch_aoi`, `reconstruct_event`, case management) are reachable exclusively through the
   capability-token-gated MCP server (`agents/core/security/worldview_mcp.py`) — never through
   this plugin.
2. **Fail-safe, never fabricated.** If the provider is unreachable, the consumer returns
   `{"status": "unavailable", ...}` — it never raises into the chat turn and never invents
   OSINT data. Budget: 5s per attempt, ≤3 attempts, circuit breaker `plugin:worldview`.
3. **Transport & discovery.** Plain HTTP on the LAN; base URL `http://localhost:4000`,
   overridable via `WORLDVIEW_API_URL`. **Auth (F-06):** by default (WorldView auth
   disabled) the bridge sends no `Authorization` header — unchanged. When WorldView auth
   is enabled (`authSecret`), set `WORLDVIEW_API_TOKEN` to a read-scoped token and the
   bridge sends `Authorization: Bearer <token>` on every GET (see `rbac.ts` permissions:
   `read:history`, `read:recon`, `read:provenance`, `read:ontology`).
4. **Versioning.** Additive provider changes (new endpoints/fields) don't break the contract.
   Removing/renaming any endpoint or response key listed above is a breaking change: bump
   `version` here and update both sides in one PR. If the repos are ever split, this file
   moves with the **provider** and the consumer pins a version.

## Why this file exists

The two products share zero runtime — this contract (≈6 endpoints, one direction, read-only)
is the entire integration surface. It keeps the products independently loadable (for humans,
CI, and AI context — see `docs/AI_CONTEXT.md`) and makes an eventual repo split mechanical.
