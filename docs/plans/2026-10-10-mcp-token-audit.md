# MCP token issuance audit — H512 continuation

Generated 2026-10-10 UTC. Base and initial head:
`332b16ca857a3fd126a89be411e2e6ca17de4e91`. Branch:
`codex/h512-mcp-token-audit-20261010`. Local development is authorized by the
owner's backlog continuation request and AGENTS.md; publication is a separate step.

Goal: submit one value-free `token_issued` event after `/api/mcp/token`
successfully signs an MCP credential. This route does not use TokenStore, so its
existing lifecycle events cannot cover this operation. Reuse the bounded,
best-effort authentication audit queue and current hash-chained sink.

Design: the event contains only `tier=user`, `outcome=success`, `reason=issue`,
`count=1`, `revoke_env=false`, and the exact literal `surface=mcp`. The tier
describes the credential minted, not a subject identity. The admin guard keeps
its separate authorization event. Extend the literal-only surface projection to
`token_issued` in both submission and serialization; managed-token events without
an explicit surface keep their existing shape. Do not permit arbitrary surface
values or expand the projection to rotation/revocation events.

Invalid TTL, absent orchestrator, denied authorization and signing failures emit
no issuance event. Preserve existing response bodies, headers and status codes.
Never pass token, subject, scope, resource, TTL, request metadata or error text to
the audit queue. A failed, blocked or saturated sink cannot block token issuance.
This records successful signing, not a durable token-store commit or guaranteed
event delivery.

Non-goals: new endpoints, authentication predicates, token persistence/revocation,
new UI, schema migrations, OAuth login/logout/refresh/WebSocket lifecycle work,
Windows fixes without diagnosed evidence, or full H512 completion.

Likely paths: `agents/core/routers/mcp.py`,
`agents/core/security/auth_audit.py`, `tests/test_mcp_auth_audit.py`, and a focused
`tests/test_mcp_token_audit.py`; bounded backlog, evidence, parity and generated
status updates follow validation. Root owns scope, interfaces, documentation and
integration. The implementation agent owns only those four Python files.

Verification: demonstrate missing-event regressions before implementation;
exercise real route authorization and signing, exact row/chain content, secret
omission, unsuccessful issuance, bounded/nonblocking queue and sink failures.
Run existing MCP/OAuth/auth/token-lifecycle/audit suites, Ruff, route and generated
status guards; independently review the final delta. Run the complete backend
suite serially after the combined local slice, with no provider credentials.

Rollback: revert the route submission and the token-issued surface projection
together with their tests/docs. Existing events remain readable and no stored
credential or schema needs rollback. Dependencies are the existing auth audit
queue, MCP resource server and admin guard. H512 stays partial.

Implementation and independent review used separate `gpt-6-sol/high` agents;
root retained scope, interface, documentation and integration ownership. A
`gpt-6-luna/medium` investigator separately bounded the Windows log-access issue.
No agent delegated work or used a provider service.

The red-first test run demonstrated three missing-event/projection failures.
The final focused MCP audit tests passed 20/20; the existing MCP/OAuth/auth/token/
audit integration selection passed 248/248 with no skips, failures or errors in
10.959 seconds. Reports: `/workspace/scratch/backlog-20261010/h512-red.log` and
`h512-related.xml` in that directory. Independent review found no concrete
authorization, privacy or blocking defect. The four previously current rows
H502/H545/H551/H554 were re-reviewed against the unchanged cited behavior and
coordinates; five relevant MCP suites passed 67/67 before refreshing only their
changed MCP-router pins. Unrelated stale evidence remains stale.

A fresh, isolated local server started successfully. Its actual HTTP token route
returned 200 with `no-cache, no-store, must-revalidate`, and the existing admin
audit reader returned exactly one MCP issuance row with the six fixed fields.
The token and subject sentinel were absent from the audit response. The server
was stopped and disposable runtime state removed. No public endpoint/schema or
frontend implementation changed; the HUD/mobile parity notes describe the
existing reader and the remaining native-reader gap.

Ruff, whitespace, Hermes-report derivation and generated-status checks pass.
Backend collection is 25,546 (five new tests); frontend/mobile counts are reused
unchanged at 2,177/359. The initial full-backend run collected 25,546 cases:
25,475 passed, 59 skipped, 12 failed, zero errors in 432.904 seconds. All failures
were voice interpreter-binding tests: the coordinator's copied executable was
named `python-local`, outside the product's existing Python-name matcher. The
exact twelve failures reproduced on unchanged main with that same executable.
A standard `venv --copies` retains the normal `python` name and an ordinary inode;
all 167 cases in the three affected voice suites then passed. No product or test
assertion changed. The final full run uses that standard-name copied interpreter,
the same pinned dependency files and a Linux child subreaper. This also avoids the
mounted interpreter's out-of-range inode and unreaped container children already
documented in the preceding integration.

Main's pre-existing Windows `Test` failure in run 37987272283 remains unresolved.
A fresh official GitHub log redirect was obtained, but the environment proxy
refused the blob connection with 403; the connector also returned Transport
closed. No failing test name or source-level cause could be recovered. No
speculative Windows code change or test suppression belongs in this slice.

Final full-backend verification (2026-10-10 UTC): **25,487 passed, 59 skipped,
zero failures/errors**, out of **25,546** cases in **436.816 seconds**. JUnit:
`/workspace/scratch/backlog-20261010/backend-full-standard-python.xml`. The
initial failed run and unchanged-main reproduction are retained beside it;
the successful run did not deselect or weaken any test. Route/OpenAPI/lifespan,
Hermes evidence and generated-status guards are included in the complete suite.
Standalone Bandit was unavailable in this environment and was not run.

Final product/test paths are the four Python paths listed above. Delivery also
updates this plan, BACKLOG.md, the H512 build-queue entry, its assessment and four
reviewed collateral pins, HUD/mobile parity notes, the two generated Hermes
reports, project-status.json and its four generated documentation consumers.
No additional capability is counted as equivalent: H512 is reviewed partial,
the headline remains 116/697, and unrelated stale evidence is preserved.

Next action: preserve this reviewed candidate in a local commit. Publication,
Windows CI diagnosis and the broader H512 contract remain separate follow-ups.
