# Tool profile dispatch integration evidence

- Generated: 2026-10-09 UTC.
- Goal: refuse newly dispatched agent tools whose current profile revoked access,
  including revocation during the awaited `tool_started` event.
- Base: `c72f1761427f5d19686e38b356b17f7f7fb963d2`.
- Source checkpoint: `a5642a12c8dee2b28d46acaf6c279a18e1151d42`.
- Worktree: `/workspace/jarvis-hub-profile-execution-recheck`.
- Branch: `codex/profile-execution-recheck-20261009`.
- Delivery: local only; existing draft PR #1247 has not received this unit.

The three implementation files are `agent_runtime.py`, `tool_rpc.py`, and
`autonomy_coordinator.py`. The provider offer and H661 bookkeeping stay stable
between folds; a separate current profile check runs at call admission before
preflight/intake/handler. Direct/script calls, approved execution, in-flight work,
and the SEC-B5 taint lifetime are outside this boundary. The plan documents the
explicit-hook requirement for standalone runtimes.

Focused behavioral verification passed 196/196 across ten modules. Independent
gpt-6-sol/high review found no Critical/Important issue and passed the eight new
cases. The full backend command at the source checkpoint was:

```bash
/workspace/scratch/backend-copy-venv/bin/python /workspace/scratch/pytest-subreaper.py \
  /workspace/scratch/backend-copy-venv/bin/python -m pytest tests/ \
  -n 4 --dist loadfile --timeout=90 -q --tb=short \
  --junitxml=/workspace/scratch/profile-execution-recheck-backend-final.xml
```

Result: **21,076 passed, 37 skipped, one failed, zero errors** (21,114 cases,
266.299 seconds). The sole failure was
`test_orchestrator_bindings.py::test_external_binding_writer_inventory_exactly_matches_production_calls`.
The added constructor argument moved exactly 12 existing coordinator callsites by
one line. The failure reproduced in isolation. The subsequent correction changes
only those 12 coordinates in `orchestrator_bindings.py`; no binding, authority,
runtime behavior or test assertion changes. The file's existing H515 evidence pin
was already stale and is preserved.

After repair, the complete `test_orchestrator_bindings.py`, `test_status_sync.py`,
and `test_hermes_sprint_status.py` union passed **136/136**, zero skipped/errors,
in 14.429 seconds. The failing full-run node is present and passing in
`/workspace/scratch/profile-execution-recheck-final-gates.xml`. Ruff, whitespace,
project/Hermes freshness and the exact 21,114 backend count also pass. The full
suite was not rerun after this inventory-only correction; its original failed
checkpoint is not relabeled green.

Frontend/mobile implementation has not changed from the earlier verified lineage.
Inventory remains frontend 1,962, mobile 284, routes 554; those suites were not
executed again for this backend unit. No live provider or device acceptance is
claimed. Next action: continue the open local backlog; publication remains a
separate action from this local evidence checkpoint.
