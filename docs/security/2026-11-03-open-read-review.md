# Open-read acceptance review, 2026-11-03

Verdict: **HOLD**. This is a source review of the local integration based on
`80e74ce8594ce501c668e395d55581b3d0b1e39f`, including the earlier SEC-B6 work.
It does not assert acceptance of a different remote head. The independent
reviewer did not build that work. All 71 intentionally open GET entries were
resolved against the runtime route table and compared with the response
classification evidence. The prescribed route-auth matrix passed **21 tests**:

```sh
JARVIS_TESTING=1 .venv/bin/python -m pytest tests/test_route_auth_matrix.py -q --timeout=90
```

Those tests prove classification membership and prevent stale allowlists. They
do not establish that a response contains no personal content. The following
source findings prevent acceptance:

| Response | Current behavior | Required boundary |
|---|---|---|
| `GET /api/oracle/status` | `routers/oauth.py::oracle_status` returns `oracle_bridge.py::OracleBridge.status`, including recent session/task details, raw errors, unresolved file conflicts and the PR feed. Its evidence describes OAuth presence booleans. | Require user authentication for content, or expose a strictly non-content public projection. Add a response-level negative/positive regression and correct the evidence. |
| `GET /agents` | `routers/agents_api.py::get_agents` includes `soul_edit.description_of(agent)`, which reads the current SOUL frontmatter and can contain owner-authored text. The evidence describes roster metadata without this field. | Protect the SOUL-derived content or remove it from the public projection; preserve the authenticated roster's functionality. |
| `GET /api/security/kill-switch` | `routers/security.py::kill_switch_status` returns persisted state without projection, including the admin's free-form reason. Public safety-state transparency does not establish permission to disclose owner-authored context. | Preserve public safety state while protecting free-form owner content, with tests for the exact response boundary. |

The dataset comparison endpoint also returns user-authored case names rather
than only score aggregates. Its classification needs an explicit source review;
the current evidence does not discuss those labels. No disclosure permission is
inferred from a green route matrix.

Next action: fix the response boundaries with meaningful failing regressions,
update the per-handler evidence, and repeat independent acceptance on the final
source. SEC-B6 remains open until that review records PASS. No production state,
credentials, owner-only decisions or repository settings were changed.
