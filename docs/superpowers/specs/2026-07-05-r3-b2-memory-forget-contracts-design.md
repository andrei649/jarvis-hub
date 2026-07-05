# R3-B2 Memory and Forget Contract Gates Design

## Goal

Close the next R3 contract-less seams by making external knowledge-graph writes and irreversible data purge evaluate live automation contracts before they mutate state.

## Scope

This slice covers:

- `/api/kg/*` mutating handlers in `agents/core/routers/memory_kg.py`
- `agents.core.data_purge.purge_data(...)`
- `POST /api/admin/forget` in `agents/core/routers/backup.py`

This slice does not cover the remaining R3 seams: A2A inbound task intake, autonomy escalation broadcast, MCP route-tool mutation, or channel-send transports. Those stay separate B3/B4 waves.

## Design

Add a `KG_WRITE_CONTRACT` beside the existing `kg.write` kernel helper. The contract is an admissibility gate over sanitized metadata only: operation name plus entity/relation/fact identifiers or text length. It runs before `_kg_kernel_denial()` and before any graph/bitemporal/updater mutation. Contract denial returns HTTP 403 with a stable `contract denied: <reason>` error. Contract evaluation exceptions fail closed with `contract_error`.

Add a `DATA_PURGE_CONTRACT` in `agents/core/data_purge.py`. The contract validates the destructive purge request shape (`action="purge_data"`, `backup_first`, `memory`, `source`, and `session_count`) before files or DB rows are touched. Function-level calls raise `PurgeError` on denial so CLI and internal callers cannot bypass the gate. The admin route checks the same contract before clearing live in-memory stores, then calls `purge_data` as today.

The default contracts are permissive for valid existing flows, so normal behavior remains unchanged. Tests monkeypatch the live contract objects to deny and prove denial happens before state mutation.

## Risks

- Double evaluation on `/api/admin/forget`: the route checks before live clear, and `purge_data` checks again before at-rest deletion. This is intentional defense-in-depth and still offline/pure.
- KG writes already have Action Kernel mediation. This PR does not alter kernel behavior; it adds the missing reusable contract layer before the kernel.
- The contracts must not include property values or raw memory text in audit payloads. KG ingest only sends `text_len`, and purge sends counts/booleans/labels.

## Tests

- New R3-B2 regression tests patch `KG_WRITE_CONTRACT` and `DATA_PURGE_CONTRACT` with denying contracts.
- KG denial tests assert no graph/fact/ingest mutation occurs.
- Purge denial tests assert rows/files remain intact and `POST /api/admin/forget` returns 403 before live memory clear.
- Adjacent sweeps keep existing KG kernel, data purge, route auth, and contract helper behavior green.
