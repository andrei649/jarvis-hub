# R3-B4 MCP Route-Tool Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live reusable contract gate before MCP mutating route-tool writes execute.

**Architecture:** `MutatingRouteTool.call()` remains the single write boundary. It keeps identity first, then evaluates a sanitized `MCP_MUTATING_ROUTE_CONTRACT`, then preserves the existing kernel and audit flow before invoking the adapter.

**Tech Stack:** Python 3.12, pytest, existing `agents.core.automation_contracts` primitives.

## Global Constraints

- Keep MCP read-only route tools unchanged.
- Do not add new mutating route allow-list entries.
- Contract payloads must not contain raw user text or metadata values.
- Denied contracts must block before the write adapter is called.
- Denied attempts must still be audited.

---

### Task 1: Red Test for Contract Denial

**Files:**
- Create: `tests/test_r3_b4_mcp_route_tool_contracts.py`

**Interfaces:**
- Consumes: `build_mutating_route_tools()`, `JarvisMCPServer.call_tool()`, and module-level `MCP_MUTATING_ROUTE_CONTRACT`.
- Produces: a regression test proving a patched denial prevents the adapter call.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_mcp_mutating_route_contract_denial_blocks_write_and_audits(monkeypatch):
    monkeypatch.setattr(route_tools_mod, "MCP_MUTATING_ROUTE_CONTRACT", _denying_contract(), raising=False)
    invoke, calls = _fake_remember_invoker()
    auditor = _FakeAuditor()
    tools = build_mutating_route_tools(
        {"memory_remember": invoke},
        auditor=auditor,
        read_only_enabled=True,
        mutating_enabled=True,
        identity_check=lambda _token: True,
    )
    server = JarvisMCPServer(_runner, {"jarvis": "Jarvis"}, mutating_route_tools=tools)

    result = await server.call_tool("route_memory_remember", {"text": "private body"})

    assert result["isError"] is True
    assert "contract denied: mcp_route_blocked" in result["content"][0]["text"]
    assert calls == []
    assert auditor.events[0].action_taken.endswith("(refused-contract)")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_r3_b4_mcp_route_tool_contracts.py -q`
Expected: FAIL because the patched contract is ignored and the write adapter is called.

### Task 2: Implement Contract Gate

**Files:**
- Modify: `agents/core/mcp/route_tools.py`

**Interfaces:**
- Consumes: `ContractTemplate`, `contract_denial`, `predicate`.
- Produces: `MCP_MUTATING_ROUTE_CONTRACT`, `MCP_MUTATING_ROUTE_CONTRACT_KIND`, and a fail-closed call-time denial path.

- [ ] **Step 1: Add contract template and sanitized helpers**

Add a shape-only contract that validates kind, method/path/tool names, sorted string argument keys, and non-negative argument count.

- [ ] **Step 2: Evaluate after identity and before kernel/invoke**

If evaluation raises, audit as `refused-contract` and raise a controlled contract error. If it returns a denial reason, audit as `refused-contract` and raise `contract denied: <reason>`.

- [ ] **Step 3: Run focused tests**

Run: `python -m pytest tests/test_r3_b4_mcp_route_tool_contracts.py tests/test_mcp_route_tools.py -q`
Expected: PASS.

### Task 3: Verification and Documentation

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Consumes: local test count from `scripts/status_sync.py`.
- Produces: updated project status for R3-B4.

- [ ] **Step 1: Run adjacent sweeps**

Run MCP route, MCP client contract, automation contract, and kernel bypass tests.

- [ ] **Step 2: Run static checks**

Run ruff, py_compile, status sync, and diff checks.

- [ ] **Step 3: Update trackers and commit**

Mark R3-B4 as in-progress/verified locally, sync test count, then commit and open a draft PR.
