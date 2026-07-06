# M3.5 WorldView MCP Write Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire JARVIS to call WorldView MCP write tools with governed, scoped capability tokens.

**Architecture:** Add a focused WorldView MCP write wrapper around the existing `MCPManager`, keep `WorldViewPlugin` read-only, and expose the write capability through `ArgusInterface`. Extend `MCPServer` with optional `cwd`/`env` process options so the WorldView child gets `WORLDVIEW_MCP_SECRET` without shell tricks.

**Tech Stack:** Python 3.12, pytest async tests, existing Action Kernel, PermissionGate, MCP stdio client, WorldView HMAC capability minter.

## Global Constraints

- No direct REST write path from `WorldViewPlugin`.
- No shell execution for MCP stdio server startup.
- No MCP side effect before plugin gate, kernel, and HMAC token mint all succeed.
- Default behavior remains fail-closed when `JARVIS_ACTION_KERNEL` or `WORLDVIEW_MCP_SECRET` is absent.

---

### Task 1: MCP Process Options

**Files:**
- Modify: `agents/core/mcp/client.py`
- Modify: `tests/test_mcp_client.py`

**Interfaces:**
- Produces: `MCPServer(..., cwd: str | None = None, env: dict[str, str] | None = None)`.

- [ ] Write failing test proving `create_subprocess_exec` receives `cwd` and merged env.
- [ ] Run `python -m pytest tests/test_mcp_client.py::test_stdio_connect_passes_cwd_and_env_without_shell -q` and confirm it fails.
- [ ] Add optional `cwd`/`env` fields to `MCPServer` and pass them to `asyncio.create_subprocess_exec`.
- [ ] Re-run `python -m pytest tests/test_mcp_client.py -q`.

### Task 2: WorldView Write Client

**Files:**
- Create: `agents/core/mcp/worldview_write.py`
- Create: `tests/test_worldview_mcp_write_transport.py`

**Interfaces:**
- Produces: `WorldViewMCPWriteClient.watch_aoi(...)`.
- Produces: `WorldViewMCPWriteClient.reconstruct_event(...)`.
- Produces: `WorldViewMCPWriteClient.from_orchestrator(...)`.

- [ ] Write failing tests for authorized `watch_aoi`, authorized `reconstruct_event`, plugin denial, kernel disabled, kernel deny/queue, and missing secret.
- [ ] Run `python -m pytest tests/test_worldview_mcp_write_transport.py -q` and confirm failures are due to the missing module/client.
- [ ] Implement the minimal client wrapper, including lazy MCP server registration.
- [ ] Re-run `python -m pytest tests/test_worldview_mcp_write_transport.py -q`.

### Task 3: Argus Reachability

**Files:**
- Modify: `agents/core/argus.py`
- Modify: `agents/argus/SOUL.md`
- Modify: `tests/test_argus_interface.py`

**Interfaces:**
- Produces: `ArgusInterface.watch_aoi(...)`.
- Produces: `ArgusInterface.reconstruct_event(...)`.

- [ ] Write failing tests proving Argus delegates write calls only when the write client is wired and reports write methods in capabilities.
- [ ] Run the focused Argus tests and confirm failure.
- [ ] Wire `WorldViewMCPWriteClient.from_orchestrator()` into `ArgusInterface.from_orchestrator()`.
- [ ] Update Argus SOUL wording from “not default path” to “available only through governed MCP write path.”
- [ ] Re-run `python -m pytest tests/test_argus_interface.py tests/test_worldview_mcp_write_transport.py -q`.

### Task 4: Documentation And Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

- [ ] Mark M3.5/#169 active/merged-state accurately for this PR.
- [ ] Run focused tests:
  - `python -m pytest tests/test_mcp_client.py tests/test_worldview_mcp_capability.py tests/test_worldview_mcp_write_transport.py tests/test_argus_interface.py -q`
- [ ] Run adjacent tests:
  - `python -m pytest tests/test_worldview_plugin.py tests/test_worldview_bridge_contract.py tests/test_argus_agent.py tests/test_oracle_mcp_host_exec_gate.py -q`
- [ ] Run touched-file ruff and py_compile.
- [ ] Run `PYTHONIOENCODING=utf-8 python scripts/status_sync.py --check`.
- [ ] Open a draft PR and wait for full CI before merge.
