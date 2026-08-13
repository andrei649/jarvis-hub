# Hermetic MCP RPC governance evidence — 2026-08-13

Scope: G36 / ADV-132 at the Max `bold-quill` candidate. This is offline evidence;
no live MCP client, owner token, cloud service, hardware, or destructive action was used.

## Complete direct-dispatch inventory

| MCP tool family | Availability | Direct mutation | Governance verdict | Enforced controls |
|---|---|---:|---|---|
| `ask_<allowed-agent>` | server enabled; configured agent allow-list | no direct adapter | governed | agent allow-list; orchestrator runner; parsed direct skill commands refused before runner |
| `route_status` | `JARVIS_MCP_ROUTE_TOOLS=1` | no | governed | curated read-only allow-list; reflected live-handler schema |
| `route_memory_search` | same | no | governed | curated read-only allow-list; reflected live-handler schema |
| `route_dashboard` | same | no | governed | curated read-only allow-list; reflected live-handler schema |
| `route_codeintel_search` | same | no | governed | curated read-only allow-list; reflected live-handler schema |
| `route_memory_remember` | both route and mutating switches | yes | governed, fail-closed | mutating allow-list; identity; contract; audit; enabled and bound Action Kernel; `GRANT` only |

`JarvisMCPServer.tool_inventory()` generates the machine-readable form exposed by
`GET /api/mcp/server`. Tests assert that its names exactly equal `tools/list`; a new
advertised tool cannot silently escape classification.

## Confirmed findings and remediation

1. With `JARVIS_ACTION_KERNEL` unset, the prior `MutatingRouteTool` skipped the
   bound kernel and invoked the write adapter.
2. With the flag set but no kernel bound, the prior path still invoked the adapter.
3. A kernel `QUEUE` result was treated like `GRANT`; the adapter ran even though
   the policy required approval.
4. `ask_*` forwarded raw text into the orchestrator command fast-path. A direct
   skill command could therefore execute a skill absent from the MCP tool list.

The candidate refuses all four paths before mutation. Only an explicit kernel
`GRANT` may invoke a mutating route adapter. A queued action is not auto-resumed;
until a separately governed approval/resume design exists, it stays refused.

## Transport and metrics proof

- Server disabled + no token: HTTP 403.
- Server enabled, OAuth off, user token configured + no token: HTTP 401.
- User token unset + non-local resolved client: HTTP 403.
- The real bound kernel with default `AutonomyPolicy` and external MCP origin emits
  one additional `mcp.mutating` `queue` metric; adapter invocation remains zero.
- Identity and contract failures precede the kernel; every mutating refusal is
  written to the MCP audit channel without copying argument values.

## Verification commands

```text
.venv/bin/python -m pytest tests/test_h10_5_mcp_server.py tests/test_mcp_route_tools.py tests/test_mcp_kernel_wave.py tests/test_r3_b4_mcp_route_tool_contracts.py tests/test_kernel_bypass_regressions.py tests/test_action_auth_matrix.py tests/test_route_auth_matrix.py tests/test_h16_1_mcp_oauth.py tests/test_codeintel_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_admin.py -q
158 passed; one existing Starlette/httpx deprecation warning
```

## Threat, failure, and rollback boundaries

- A stolen valid bearer can still reach conversation/read tools; existing OAuth,
  user-token, localhost/proxy-origin, rate, and deployment controls remain relevant.
- Agent-generated downstream actions remain owned by their broker/action contracts;
  this slice closes only hidden direct skill dispatch at the MCP agent seam.
- Inventory is process/configuration-specific: disabled conditional tools are absent,
  and become classified rows when bound.
- Reverting the code reopens both kernel bypasses. If rollback is unavoidable,
  first disable MCP server mode and both route-tool switches; otherwise forward-fix.
