# R1 Oracle + MCP Host Execution Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Oracle external repo sync and outbound MCP host execution fail closed behind contracts/kernel discipline.

**Architecture:** Add small local contract templates at the unsafe seams, inject optional kernel/enqueue hooks into Oracle, replace MCP shell execution with argv execution, and keep all behavior offline-testable with fakes.

**Tech Stack:** Python 3.12, pytest, FastAPI-adjacent modules, existing `automation_contracts`, existing Action Kernel facade.

## Global Constraints

- Feature branch only; do not push direct to main.
- TDD red before production code.
- Oracle watcher remains default-off.
- No new external services or dependencies.
- Do not touch open PR #480 workflow files.

---

### Task 1: Oracle Repo Sync Guard

**Files:**
- Modify: `agents/core/plugins/oracle_bridge.py`
- Test: `tests/test_oracle_mcp_host_exec_gate.py`

**Interfaces:**
- Produces: `REPO_SYNC_CONTRACT`, `OracleBridgePlugin._repo_sync_block(...)`, optional `kernel` and `enqueue` constructor hooks.
- Consumes: `agents.core.automation_contracts`, `agents.core.kernel`.

- [x] Write failing Oracle tests for kernel-off blocking and kernel-queue no-pull behavior.
- [x] Run `python -m pytest tests/test_oracle_mcp_host_exec_gate.py -q` and confirm failure.
- [x] Add the repo-sync contract template and guarded `_process_claude_commit()` flow.
- [x] Run the focused Oracle tests and confirm pass.

### Task 2: MCP Stdio Exec + Tool Call Contract

**Files:**
- Modify: `agents/core/mcp/client.py`
- Test: `tests/test_oracle_mcp_host_exec_gate.py`, `tests/test_mcp_client.py`

**Interfaces:**
- Produces: `MCP_TOOL_CALL_CONTRACT`, safe command argv parser, `MCPServer._command_argv()`.
- Consumes: existing `_send()` JSON-RPC path and `asyncio.create_subprocess_exec`.

- [x] Write failing MCP tests for no-shell connect, metacharacter rejection, and live contract denial before send.
- [x] Run `python -m pytest tests/test_oracle_mcp_host_exec_gate.py tests/test_mcp_client.py -q` and confirm failure.
- [x] Replace shell spawn with argv spawn and add the tool-call contract guard.
- [x] Run MCP focused tests and confirm pass.

### Task 3: Trackers and Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Produces: backlog/status evidence for R1/R4.
- Consumes: existing status sync script.

- [x] Update trackers with the new active PR scope and verification.
- [x] Run focused pytest for Oracle/MCP.
- [x] Run adjacent tests: `tests/test_o45_b1_contracts.py`, `tests/test_mcp_api.py`, `tests/test_mcp_admin.py`.
- [x] Run `python scripts/status_sync.py --check`.
- [x] Run `git diff --check`.
- [x] Commit, push, and open draft PR #578.
