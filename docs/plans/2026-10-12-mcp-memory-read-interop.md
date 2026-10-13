# MCP memory read interoperability

Updated: 2026-10-13 UTC.
Goal: let the existing default read-only MCP consumer search shared hub memory
without granting write access.
Implementation base: `26877eb4ddec7a405ba93105506b67a652efc943`.
Branch: `codex/shared-memory-mcp-read-hints-20261012`; the published commit and PR
identify the review revision. This record describes the first of two increments.

## Diagnosis and change

`RouteTool.descriptor()` omitted `annotations.readOnlyHint`, while
`MCPServer._trust_denial()` requires the literal boolean `true`. The hub's memory
search tool was consequently refused by its own default MCP consumer.

The five-line production change sets the hint only for a GET with an exact spec
in `ROUTE_TOOL_ALLOWLIST`. Custom specs, changed paths, verbs or authority
declarations receive `false`. Mutating routes and agent tools gain no permission.
Authentication, trust checks, tool filters, disabled routes and kernel gates are
unchanged. There is no new endpoint, storage service, synchronization daemon,
credential or client configuration.

The fourteen-case regression uses the real `MCPServer` consumer and
`JarvisMCPServer` producer with JSON exchanged in process. Memory reads use the
real handler and `MemoryManager`, in-memory stores and deterministic local hash
embeddings. Three independent consumers discover the catalog, then retrieve the
same synthetic Cedar project fact. Refusal cases cover writes, agent execution,
unknown tools, disabled/filtered routes and unreviewed custom specs.

This is not a sandbox for arbitrary Python callbacks: a trusted application can
bind a different callback under a copied approved spec. Memory search does not
mutate stored facts, but approved reads can perform provider I/O and ordinary
cache/log bookkeeping. The annotation does not promise zero I/O or zero cost.

## Verification

```bash
python -m pytest tests/test_mcp_readonly_interop.py tests/test_mcp_route_tools.py tests/test_mcp_trust.py tests/test_mcp_tool_filters.py tests/test_mcp_auth_audit.py tests/test_route_tools_auth_parity.py -q --tb=short
```

The final focused review run passed 122 cases. The first increment's completed
serial backend run recorded 25,555 cases: 25,493 passed, 58 skipped, one xfail,
three browser/DNS failures and zero errors. Those three failures were reproduced
on the clean base. A separate incomplete parallel attempt had two SQLite/audit
worker crashes and an xdist error; its root cause remains unproven. Its partial
counts are not completion evidence and are not added to any other run.

The final combined implementation was subsequently verified serially with
25,589 cases. Its authoritative result and reproducible command are in
[the local pilot record](2026-10-12-local-pilot-doctor.md#verification).
No full-suite result is described as entirely passing.

Changed paths for this increment: `agents/core/mcp/route_tools.py`,
`tests/test_mcp_readonly_interop.py`, the HA-4b backlog entry, this record and
generated status projections. Dependencies use the existing hash-pinned locks.
Rollback: revert the descriptor annotation and its tests/docs; no data migration.

## Runtime boundary and next step

The selected pilot computer is **System76**. The installed model, provider and
running hub there remain to be verified when access is available. This selection
does not establish access or authorize persistent connectivity.

Nerva already has Ollama and LM Studio adapters and strict-local routing. Start
with the existing `doctor --local-pilot` command on System76. Once prerequisites
pass, an authorized synthetic request must demonstrate a real local response
with a matching provider/model trace, followed by a real MCP memory read.
The stored `cloud_fallback=never` setting does not override explicit cloud-agent
policies; use a strict-local agent for the runtime pilot.

This patch does not connect ChatGPT, Claude or external Hermes installations,
merge their private histories, synchronize Markdown memory, or register machine
presence. The shared memory location and client transport/account compatibility
still need runtime acceptance. No new HUD/mobile surface or OpenAPI route is
introduced. No real-model inference or cross-machine acceptance was performed.
