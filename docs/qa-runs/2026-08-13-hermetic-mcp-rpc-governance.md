# Hermetic MCP RPC governance evidence — 2026-08-13

Scope: G36 / ADV-132 at the Max `bold-quill` candidate. This is offline evidence;
no live MCP client, owner token, cloud service, hardware, or destructive action was used.

## Complete state-effect inventory

| MCP tool family | Availability | Persistent state effects | Governance verdict | Enforced controls/boundary |
|---|---|---|---|---|
| `ask_<allowed-agent>` | server enabled; configured agent allow-list | user turn before routing; normally assistant turn; possible downstream governed actions; explicit local-model lifecycle when requested | governed | transport identity/local boundary; agent allow-list; orchestrator runner; direct skill commands refused; transcript retention; lifecycle restricted to `ask_jarvis` and additionally requires verified owner identity, system-control, host contract, enabled/bound Action Kernel `GRANT`, and durable audit preflight |
| `route_status` | `JARVIS_MCP_ROUTE_TOOLS=1` | none | governed | curated read-only allow-list; reflected live-handler schema |
| `route_memory_search` | same | none | governed | curated read-only allow-list; reflected live-handler schema |
| `route_dashboard` | same | none | governed | curated read-only allow-list; reflected live-handler schema |
| `route_codeintel_search` | same | none | governed | curated read-only allow-list; reflected live-handler schema |
| `route_memory_remember` | both route and mutating switches | long-term memory | governed, fail-closed | mutating allow-list; identity; contract; durable authorization audit preflight; enabled and bound Action Kernel; `GRANT` only |

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
5. The first inventory called `ask_*` non-mutating even though the production
   runner durably stores the user turn before routing and normally stores the reply.
6. A merely bound audit object was advertised as `audit_required`, but a missing or
   raising sink on a directly constructed tool did not prevent an authorized write.
7. Independent review found a remaining HIGH bypass: `ask_*` rejected skill commands
   but did not classify the pre-routing LM Studio fast-path. An MCP request could reach
   `start_server`/`load_model`/`unload_model` without MCP-specific identity, Action
   Kernel mediation, or mandatory audit preflight.

The candidate now describes agent persistence and route mutation separately and
refuses the hidden-command/kernel/audit bypasses before route mutation. Only an
explicit kernel `GRANT` plus a successful durable `authorized` audit row may invoke
the adapter. A queued action is not auto-resumed; until a separately governed
approval/resume design exists, it stays refused.

After the owner explicitly authorized Jarvis to manage both LM Studio and Ollama,
the candidate adds a single `host.control` lifecycle boundary. MCP lifecycle intent
is accepted only through `ask_jarvis` after the same user/admin-token rule or a
transport-verified OAuth subject (localhost-only is the existing no-token dev
boundary). A server-scoped context marker prevents direct
`handle_input(channel="mcp")` calls from manufacturing that authority. Both providers
then require system-control permission, the host contract, enabled/bound Action
Kernel `GRANT`, and a durable authorization row before any subprocess/API effect.
`DENY`, `QUEUE`, missing/raising kernel, failed audit, invalid model id and live
revocation all preserve a zero controller-call count.

Ollama uses only fixed `ollama serve` argv (`create_subprocess_exec`, detached, no
shell) and localhost `/api/generate`: `keep_alive=-1` loads/pins and `keep_alive=0`
unloads. Unload is the bounded residency rollback; this slice does not add an
autonomous process-kill path.

## Transport and metrics proof

- Server disabled + no token: HTTP 403.
- Server enabled, OAuth off, user token configured + no token: HTTP 401.
- User token unset + non-local resolved client: HTTP 403.
- The real bound kernel with default `AutonomyPolicy` and external MCP origin emits
  one additional `mcp.mutating` `queue` metric; adapter invocation remains zero.
- A raising kernel is converted to a fail-closed refusal and never reaches the adapter.
- A missing or raising audit sink after kernel `GRANT` refuses before the adapter;
  only argument keys, never values, enter the mandatory authorization row.
- The production MCP builder over a real hermetic orchestrator changes a dedicated
  persisted transcript from zero to one user and one assistant turn, matching the
  advertised `ask_*` state effects.
- Hostile lifecycle tests prove the order `kernel → durable audit → effect` for LM
  Studio and Ollama. Permission denial, kernel-off, `DENY`, `QUEUE`, audit failure,
  invalid identity, non-Jarvis agent, and direct-MCP-context bypass all keep effect
  calls at zero.
- The action-auth registry, machine-readable capability manifest, readiness matrix,
  and executable reality case now classify `host.control` as reversible and
  kernel-mediated; drift snapshots and pinned proof counts fail if it is silently
  removed.

## Verification commands

```text
.venv/bin/python -m pytest tests/test_h10_5_mcp_server.py tests/test_mcp_route_tools.py tests/test_mcp_kernel_wave.py tests/test_r3_b4_mcp_route_tool_contracts.py tests/test_kernel_bypass_regressions.py tests/test_action_auth_matrix.py tests/test_route_auth_matrix.py tests/test_h16_1_mcp_oauth.py tests/test_codeintel_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_admin.py -q
162 passed; one existing Starlette/httpx deprecation warning

.venv/bin/python -m pytest tests/test_*mcp*.py tests/test_kernel*.py -q
215 passed; one existing Starlette/httpx deprecation warning

.venv/bin/pytest -q tests/test_local_model_lifecycle_governance.py tests/test_ollama_control.py tests/test_h10_5_mcp_server.py tests/test_llm_control_intent.py tests/test_llm_control_status_model.py tests/test_o45_b1_contracts.py tests/test_action_auth_matrix.py tests/test_h27_capability_manifests.py
138 passed; one existing Starlette/httpx deprecation warning

.venv/bin/pytest -q tests/test_shutdown_cleanup.py tests/test_shutdown_releases_resources.py tests/test_lifespan_smoke.py tests/test_h16_1_mcp_oauth.py tests/test_mcp_route_tools.py tests/test_mcp_kernel_wave.py tests/test_r3_b4_mcp_route_tool_contracts.py tests/test_worldview_mcp_write_transport.py tests/test_llm_control_intent.py tests/test_llm_control_status_model.py tests/test_llm_down_graceful.py tests/test_llm_warmup.py tests/test_model_manager.py
205 passed; one existing Starlette/httpx deprecation warning

.venv/bin/ruff check .
passed

.venv/bin/pytest -q tests/test_local_model_lifecycle_governance.py tests/test_ollama_control.py tests/test_h10_5_mcp_server.py tests/test_mcp_route_tools.py tests/test_mcp_kernel_wave.py tests/test_r3_b4_mcp_route_tool_contracts.py tests/test_kernel_bypass_regressions.py tests/test_action_auth_matrix.py tests/test_route_auth_matrix.py tests/test_h16_1_mcp_oauth.py tests/test_codeintel_mcp_tool.py tests/test_mcp_api.py tests/test_mcp_admin.py tests/test_llm_control_intent.py tests/test_llm_control_status_model.py tests/test_o45_b1_contracts.py tests/test_h27_capability_manifests.py tests/test_h27_capability_verification.py tests/test_capability_readiness_matrix.py tests/test_shutdown_cleanup.py tests/test_shutdown_releases_resources.py tests/test_lifespan_smoke.py tests/test_worldview_mcp_write_transport.py tests/test_llm_down_graceful.py tests/test_llm_warmup.py tests/test_model_manager.py
349 passed; one existing Starlette/httpx deprecation warning

The first hosted Ubuntu test job on candidate `abb187b` correctly caught three
intentional-drift guards: the new action case changed two pinned reality-harness
counts, and `action:host.control` was absent from the committed readiness snapshot.
The snapshot was regenerated with the repository's update command, both proof counts
were advanced by one, the three exact failing tests passed locally, and the 349-test
hermetic sweep above was rerun. A new hosted exact-head run is still required.

The local unrestricted full-suite command was not run: this execution environment
identified a collected banking-provider path that can initiate external HTTPS. No
test data or credential was sent. Exact-head GitHub CI (with its isolated
`JARVIS_TESTING=1` runners) remains required before review/integration.
```

## Threat, failure, and rollback boundaries

- A stolen valid bearer can still reach conversation/read tools; existing OAuth,
  user-token, localhost/proxy-origin, rate, and deployment controls remain relevant.
- Agent-generated downstream actions remain owned by their broker/action contracts;
  conversation persistence itself is outside the Action Kernel. It has no mandatory
  pre-write security-audit row and follows the configured transcript-retention sweep.
  Local-model lifecycle is the explicit exception and has its own identity/kernel/audit
  gates before effect.
- `JARVIS_ACTION_KERNEL` remains default-off. With it off, lifecycle requests report a
  refusal rather than silently falling back to controller execution. Enabling it grants
  only what the live autonomy policy permits; `ASK`/`OFF` still holds tier-1 effects.
- OAuth proves a subject at the MCP transport; user/admin-token deployments retain the
  same credential comparison. With no configured token, only the already-enforced
  localhost transport boundary can reach the dev posture.
- Inventory is process/configuration-specific: disabled conditional tools are absent,
  and become classified rows when bound.
- Reverting the code reopens both kernel bypasses. If rollback is unavoidable,
  first set `llm.control_enabled=false` (or `JARVIS_LMSTUDIO_CONTROL=0`), disable MCP
  server mode and both route-tool switches; otherwise forward-fix.
