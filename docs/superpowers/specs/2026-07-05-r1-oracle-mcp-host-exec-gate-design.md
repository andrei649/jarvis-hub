# R1 Oracle + MCP Host Execution Gate Design

## Goal

Close the residual 1.0 safety gap where an external event or owner-configured MCP server can trigger host execution without the same contract/kernel discipline used by the rest of high-risk automation.

## Non-Goals

- Do not build a full Oracle approval UI in this slice.
- Do not change MCP server mode or route-tool semantics.
- Do not broaden owner live-data/plugin setup.
- Do not make the Oracle watcher default-on.

## Oracle Bridge Design

`agents/core/plugins/oracle_bridge.py` keeps polling default-off, but external commits no longer run `git pull --rebase` or `pytest` directly. `_process_claude_commit()` first evaluates a new `REPO_SYNC_CONTRACT` over a bounded payload: `action`, `agent`, `sha`, `author_login`, and trigger verification. Denial is recorded in the `ClaudeSession` and returned as a blocked sync result.

The bridge also gets an explicit owner allowlist (`{"andrei649"}` by default). Own commits are skipped only when the author is allowlisted and the GitHub commit verification flag is true. Everything else is treated as external and must pass the repo-sync guard.

The guard fails closed when the Action Kernel is off or no kernel hook is injected. When the kernel hook returns `DENY`, the sync is blocked. When it returns `QUEUE`, the bridge optionally enqueues a `repo.sync` governed task if an enqueue hook exists, but it still does not pull/test in the watcher tick. Only a `GRANT` decision allows `_git_pull()` and `_run_tests()` to run. This gives safe default behavior today and a clean seam for a future approved executor.

## MCP Client Design

`agents/core/mcp/client.py` stops using `asyncio.create_subprocess_shell()`. Stdio commands are parsed into argv with `shlex.split`, reject obvious shell metacharacters, and are spawned with `asyncio.create_subprocess_exec(*argv)`.

The outbound client also adds `MCP_TOOL_CALL_CONTRACT`. `MCPServer.call_tool()` evaluates the contract before writing JSON-RPC to the process. A denied contract returns a structured error and never sends to the child process. The default contract is intentionally small: server/tool names must be present and safe, transport must be a known value, and argument keys must be sorted strings.

## Data Flow

Oracle external commit:

1. GitHub poll reads latest commit metadata.
2. Owner allowlist + verified flag decides whether to skip as an owner commit.
3. External trigger enters `REPO_SYNC_CONTRACT`.
4. Contract denial, kernel unavailable/off, kernel deny, or approval queue result blocks the pull/test.
5. Only kernel grant executes pull, scan, and tests.

MCP stdio:

1. Admin-configured command is parsed into argv.
2. Unsafe parse result blocks connection before spawning.
3. Safe argv spawns via `create_subprocess_exec`.
4. Tool calls evaluate `MCP_TOOL_CALL_CONTRACT`.
5. Denied calls return an error before JSON-RPC is sent.

## Risk

The Oracle behavior intentionally becomes stricter: external commits are no longer auto-applied from the watcher unless the new gate is explicitly wired to grant. That is the safety point. MCP command parsing may reject command strings that depend on shell features; those should be represented as explicit wrapper scripts instead.

## Tests

- Oracle red/green tests prove an external commit cannot pull/test while the kernel is off.
- Oracle red/green tests prove a queued kernel decision does not pull/test and can enqueue a governed task.
- MCP red/green tests prove stdio connect uses `create_subprocess_exec`, not shell.
- MCP red/green tests prove shell metacharacters are blocked before spawn.
- MCP red/green tests prove a patched live tool-call contract denies before `_send()`.
- MCP red/green tests prove non-string/mixed argument keys return a controlled contract denial instead of raising before `_send()`.
