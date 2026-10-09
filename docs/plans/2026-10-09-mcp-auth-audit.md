# MCP RPC authentication audit

Generated 2026-10-09 UTC. Base `c424e9a2559e4da5a912aaf5e22e3b51b39ef8b5`, branch `codex/mcp-auth-audit-20261009`.

Goal: record exactly one value-free auth-success/failure event for each completed `/api/mcp/server/rpc` transport decision, including OAuth bearer, legacy user/admin bearer, and direct-localhost posture. The route currently authenticates without the audited HTTP guards. Reuse the existing 64-slot best-effort auth queue and current hash-chained sink; do not block the request or change its 200/401/403, challenge header, auth predicates, or identity handed to the MCP server.

Implementation: each completed transport authentication branch submits one event with fixed tier `user`, bounded client IP, fixed outcome/reason and literal `surface: "mcp"`. Success submits before the RPC handler; handler failure does not become an authentication failure. Disabled or uninitialized server paths submit none. Saturation or a failed sink can drop an event, as in the existing best-effort queue; this is a submission guarantee, not a durable-delivery guarantee. Existing HTTP and token rows omit `surface`.

Scope: localized calls in `agents/core/routers/mcp.py`; an optional literal-only `surface: "mcp"` projection in `agents/core/security/auth_audit.py` for auth event types only; new focused `tests/test_mcp_auth_audit.py` and minimal existing auth test if needed. Existing HTTP guard and token-lifecycle rows must remain byte-compatible without a surface field. No event for disabled MCP or absent orchestrator, because neither reached an auth decision. No OAuth/token issuance, WebSocket, login/logout/refresh, session-store work, deduplication, or full H512 completion.

Proof plan: red-first tests for each accepted/denied path, absent-vs-invalid fixed reasons, same status/challenge/identity, exactly one row and verified chain; an injection sentinel in bearer, subject, RPC body and OAuth error must never enter the queue, serialized rows or warnings. A failing/blocking sink must not change the transport result or wait for audit I/O. Run focused H512/MCP/H273e suites and Ruff, writing JUnit to `/workspace/scratch/mcp-auth-audit-focused.xml`; root owns full-suite and ledger work. Rollback removes the new submissions and optional surface projection together; the existing auth event enum and SQLite schema remain unchanged, so rows already in the chain remain readable. No providers or credentials are needed.

Focused proof: 121 tests passed, 0 failures/errors/skips across the new MCP audit cases and existing auth-audit, OAuth, MCP server/hardening/transport and H273e suites. The test first failed on 11 unaudited paths, then passed with the implementation. Ruff and `git diff --check` passed. The JUnit report is `/workspace/scratch/mcp-auth-audit-focused.xml`. Full backend verification and H512 assessment remain with the integration owner.


Initial full-backend checkpoint: 21,027 cases in 299.699 seconds, with 20,988
passed, 37 skipped and two failures. Both failures are in the inherited
research action's capability-manifest coverage/completeness, because the prior
registry increment omitted its matching manifest. They do not exercise MCP
auth telemetry. The focused MCP/auth suite remains 121/121. This checkpoint is
not a full-suite pass; the isolated research-manifest correction must land in
this local candidate before the final full run. Independent gpt-6-sol/high
source review found no Critical/Important issue in the MCP audit delta and
confirmed the nine collateral MCP claims and source coordinates.

Second full-backend checkpoint after the manifest correction: 21,028 cases in
277.278 seconds, with 20,990 passed, 37 skipped and one failure. The remaining
failure is the inherited research kind's absent entry in the earned-autonomy
refusal vocabulary (`test_h27_earned_autonomy.py:625`). It requires an explicit
empty entry, preserving genuine websearch failures. This checkpoint is also
not a full-suite pass; the vocabulary correction and reviewed client descriptor
will be verified together at the next combined milestone. JUnit:
`/workspace/scratch/mcp-auth-audit-backend-corrected.xml`.

Combined milestone (2026-10-09), verified source `c75e031`: full backend **21,032 passed, 37 skipped, zero failures/errors** out of 21,069 cases in 290.333 seconds. Exact-count and generated freshness gates pass. This later combined run includes the corrections described above; earlier checkpoints keep their recorded results. Scope, report locations and remaining limits: [integration proof](../project-media-integrity-integration-20261009.md).
