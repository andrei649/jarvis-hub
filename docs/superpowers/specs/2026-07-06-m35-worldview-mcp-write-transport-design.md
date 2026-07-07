# M3.5 WorldView MCP Write Transport Design

## Goal

Make the already-built WorldView MCP write tools reachable from JARVIS without weakening the read-only WorldView HTTP bridge. The slice wires `watch_aoi` and `reconstruct_event` through the existing stdio MCP client, using the cross-language-pinned `WORLDVIEW_MCP_SECRET` capability token format.

## Non-Goals

- No direct REST write methods on `WorldViewPlugin`; that plugin remains read-only.
- No UI or mobile surface.
- No change to the TypeScript MCP auth format.
- No live WorldView deployment claim; local tests use fakes for the MCP transport and keep the real TS auth covered by the existing cross-language vectors.

## Architecture

Add a small Python wrapper in `agents/core/mcp/worldview_write.py`:

- `WorldViewMCPWriteClient.watch_aoi(...)`
- `WorldViewMCPWriteClient.reconstruct_event(...)`
- `WorldViewMCPWriteClient.from_orchestrator(orch, agent_id="argus")`

The wrapper performs checks in this order:

1. Plugin gate: `PermissionGate.check_call("worldview", agent_id)`.
2. Action Kernel: `Action(kind="worldview.mcp.write", risk_tier=2)` with capability name `plugin:worldview` and the agent's broker token when available.
3. HMAC token: mint `worldview:watch` or `worldview:reconstruct` via `agents.core.security.worldview_mcp.mint_capability`.
4. MCP transport: call `MCPManager.call_tool("watch_aoi" | "reconstruct_event", args_with_token)`.

If any gate denies or queues, the wrapper returns a structured blocked/queued result and never calls MCP. The wrapper registers a `worldview` stdio MCP server lazily when the orchestrator has not already registered one. The default command is `node dist/server.js` with cwd `worldview/mcp`; `WORLDVIEW_MCP_COMMAND` and `WORLDVIEW_MCP_CWD` override it for local installs.

## MCP Client Support

`MCPServer` gains optional `cwd` and `env` fields. They are passed only to `asyncio.create_subprocess_exec`, preserving the no-shell hardening from #578. The WorldView wrapper uses this to pass `WORLDVIEW_MCP_SECRET` to the child process without mutating global process environment.

## Argus Reachability

`ArgusInterface` gains optional `worldview_write` wiring and two explicit methods:

- `watch_aoi(aoi_id, rule, lead=None, origin="generated")`
- `reconstruct_event(from_t, to_t, bbox="", layers=None, origin="generated")`

These methods delegate to the write client. Read methods continue using the read-only plugin.

## Error Model

The wrapper returns dictionaries, never exceptions for ordinary denial:

- `{"status": "forbidden", "reason": "plugin_denied"}`
- `{"status": "blocked", "reason": "kernel_required" | "kernel_unavailable" | "missing_worldview_mcp_secret" | "kernel_denied"}`
- `{"status": "queued", "reason": "approval_required", "card": ...}`
- `{"status": "ok", "tool": ..., "result": ...}`

## Tests

- Authorized `watch_aoi` call injects a scoped HMAC token, passes a broker capability into the kernel, and calls MCP once.
- Authorized `reconstruct_event` call mints `worldview:reconstruct` and forwards bounded replay args.
- Plugin-denied, kernel-off, kernel-denied, kernel-queued, and missing-secret paths never call MCP.
- `MCPServer.connect()` passes `cwd` and secret env to `create_subprocess_exec` while still avoiding shells.
- Argus delegates write methods to the write client and advertises the write methods only when wired.
