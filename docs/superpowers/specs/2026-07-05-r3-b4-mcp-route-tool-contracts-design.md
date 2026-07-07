# R3-B4 MCP Route-Tool Contracts Design

## Goal

Add a reusable automation-contract gate to MCP mutating route tools before any in-process route write can run.

## Non-Goals

- Do not widen the MCP mutating route allow-list.
- Do not change read-only MCP route tools.
- Do not replace the existing double kill-switch, identity check, kernel hook, or audit path.
- Do not add generic channel-send transport coverage in this slice.

## Current Seam

`agents/core/mcp/route_tools.py` already protects mutating MCP route tools with:

- an explicit write allow-list,
- `JARVIS_MCP_ROUTE_TOOLS` plus `JARVIS_MCP_MUTATING_TOOLS`,
- a per-identity check matching the HTTP user guard,
- an optional Action Kernel denial hook,
- audit rows for success, error, and existing refusals.

The remaining gap is that a valid mutating MCP route call does not evaluate the newer reusable `ContractTemplate` fabric before the write adapter runs. Other high-risk automation seams now use that layer, so this path should too.

## Approach

Add `MCP_MUTATING_ROUTE_CONTRACT` in `route_tools.py` and evaluate it after identity succeeds but before kernel mediation and before the write adapter. The contract payload must be sanitized: include kind, tool name, route path, method, filtered argument keys, and argument count only. Do not include raw text, metadata values, or request bodies.

Denied decisions fail closed with a controlled message, audit as `refused-contract`, and never call the write adapter.

## Risk

This is an external write boundary, so the main risk is accidentally changing the current success path or making local development unusable. Keeping the contract constraints shape-only and `requires_approval=False` preserves the existing behavior for admissible calls while adding an explicit live denial seam.

## Verification

- Red/green test for a patched contract denial blocking `route_memory_remember`.
- Adjacent MCP route-tool and MCP client contract suites.
- Ruff, py_compile, status sync, and diff checks.
