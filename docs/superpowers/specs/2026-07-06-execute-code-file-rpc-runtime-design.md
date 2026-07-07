# Execute Code File-RPC Runtime Design

## Goal

Connect the existing governed `ToolRPCServer`, file-RPC store, sandbox execution, child-env scrub, and output caps into one runtime path for sandboxed Python code.

## Non-Goals

- No new public HTTP endpoint in this slice.
- No SSH backend implementation.
- No replacement of the existing Docker/WASM/subprocess sandbox selection.
- No new tool governance rules; gated tools continue to use `ToolRPCServer.handle()`.
- No `BACKLOG.md` or `STATUS.md` edits while Claude's learning-loop branch owns backlog reconciliation.

## Architecture

Add a small host-side runner near the existing Tool-RPC surface:

- `agents/core/tool_rpc_runtime.py`
- `ToolRPCSandboxRuntime(server, sandbox, timeout=..., poll_interval=...)`
- `run_python(code, filename="script.py") -> ToolRPCSandboxRun`
- `sandbox_client_source(rpc_dir) -> str`

The runtime creates a per-run temp RPC directory under the sandbox work directory, prepends a tiny Python client module to the user script, starts sandbox execution, and services JSON request files with `ToolRPCServer.handle()`. The sandboxed script calls `jarvis_tool_call(tool, args)`, which writes `req_000001.json`, waits for `res_000001.json`, and returns the response dictionary.

The host loop polls `FileRPCStore.pending_requests()`, forwards each request to the governed server, writes responses, and stops when the sandbox process completes or times out. The runtime does not bypass allowlists, contracts, Action Kernel mediation, approval queues, or secret scrubbing because every request still goes through `ToolRPCServer.handle()`.

## Safety Constraints

- Tool-call count is capped by `FileRPCStore(max_tool_calls=50)` and the client also refuses after the same limit.
- Output caps remain owned by `Sandbox`; the runtime returns the normal `SandboxResult` fields.
- The child environment remains scrubbed by `Sandbox` for subprocess mode and Docker remains networkless/read-only.
- A malformed request file is ignored by the store and cannot invoke host code.
- A gated tool returns `approval_required`; it is not executed inline.

## Data Flow

1. Caller invokes `ToolRPCSandboxRuntime.run_python(code)`.
2. Runtime creates `<sandbox.work_dir>/.jarvis_file_rpc/<run_id>/`.
3. Runtime prepends the client shim and executes the script through `Sandbox.execute_python()`.
4. Sandboxed script writes request files and waits for responses.
5. Host runtime polls pending requests, calls `ToolRPCServer.handle()`, and writes response files.
6. Caller receives `ToolRPCSandboxRun(result=SandboxResult, tool_calls=N, timed_out=bool)`.

## Error Model

- Sandbox execution errors remain in `SandboxResult.stderr` and `exit_code`.
- Host-side RPC service errors are converted to response dictionaries with `ok: false`.
- Runtime timeout kills the sandbox task through existing sandbox timeout behavior; the run reports `timed_out=True` only when the outer service loop itself expires.
- If the script asks for a disallowed tool, the response is the existing `tool_not_allowed` response from `ToolRPCServer`.

## Tests

- A sandboxed script calls read-only `echo` through file-RPC and receives the scrubbed governed response.
- A gated tool request returns `approval_required`, enqueues once, and does not run inline.
- Unknown tools return `tool_not_allowed`.
- The runtime enforces the tool-call cap before host execution can exceed it.
- Large stdout remains capped by `Sandbox`.
- Existing primitive tests stay green.

## Rollback

The slice is additive. Removing `agents/core/tool_rpc_runtime.py` and its tests restores the previous state because no existing endpoint or orchestrator path is modified.
