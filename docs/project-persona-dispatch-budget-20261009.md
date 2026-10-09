# Prepared dispatch after persona growth

- Generated: 2026-10-09 UTC.
- Base: e711b432161ca3ec25b500718a351d1669df2daa.
- Tested source: 42013de7435c08f7bee91257d7c7f7fd2091366c.
- Branch/worktree: codex/persona-dispatch-budget-20261009,
  /workspace/jarvis-hub-persona-dispatch-budget.
- Delivery: local. PR #1247 remains the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-persona-dispatch-budget.md).

## Behavior

Shared history planning measured the loaded system text before compaction.
An accepted history/clock commit then refreshed the identity and persona from
disk. A longer benign file could consequently be sent with an allocation based
on its old shorter contents. The regression reproduces this with a 4,096-token
specialist, real accepted compaction, and actual mocked text/SSE dispatch.
The Gemini variant also reproduced lease/cache lookup/cache creation before
sending the oversized prompt.

PreparedRoute now checks the initial prompt estimate against the same 85% input
allowance used by planning. It takes the maximum of canonical prompt plus
rendered system, current prompt plus rendered system, and current prompt plus
cached-material estimate, then adds the live conservative tool-schema estimate.
This retains the full-history floor for cache tails without adding cached system
content twice. The clock is already rendered when measured; the planner's extra
64-token future-clock reserve is not added again.

Text checks occur before residency/checkpoint and after residency, before saving
the prepared execution checkpoint. The final common Agent guard measures the
clock-rendered string passed to generation. Streaming checks precede lease/cache
work, separately cover policy-prepared cache material, then check bound cache
plus rebuilt tail before generation. Existing route, model, session, capacity
and policy checks remain in force. The checks grant no execution authority.

A context refusal does not count as agent failure or trigger demotion. A refused
parallel specialist returns its fixed reply while the gather awaits the other
specialists. The shared fixed refusal now says context could not be safely
prepared, without claiming an already accepted commit failed. The stdlib CLI
recognizes the new wording and retains the older literal for earlier hubs.
It remains an exact-text compatibility layer, not a new structured outcome API.

## Limits

This is a final guard for initial prepared dispatch. It does not preview future
persona files, move refresh before CAS or reallocate history after publication.
A post-CAS refusal keeps the accepted summary, clock and refreshed instructions.
A failed CAS/history race still commits none of those changes. Another file edit
is not automatically reloaded by the guard; it follows the existing refresh
lifecycle. Refusal may require reducing context or changing the selected window.

The bound uses the existing tokenizer estimate and effective/estimated window.
It is not exact provider tokenization or full wire-framing measurement. Unknown
windows remain estimates. Unmanaged calls, synthesis, and subsequent tool turns
keep their separate behavior. No live model, cache service, device or GPU was used.

## Verification

Root verified all five production-file hashes at the unchanged base before
releasing implementation. Builder RED: 9 failures of 9, zero errors/skips,
1.259 seconds. Consumer RED: 3 failures and 6 passing controls, zero errors/skips,
2.117 seconds. The latter failures reproduce both oversized model requests and
Gemini lease/acquire/create/model counts of (1,1,1,1) instead of (0,0,0,0).
A separate refinement regression reproduced premature parallel gather unwind
before the per-agent refusal correction.

Final focused evidence:

- Writer's eleven-module union: 267/267, 7.395 seconds; includes route/clock,
  identity/refresh, residency, cache and CLI compatibility regressions.
- Root's disjoint fifteen-module integration: 376/376, 8.867 seconds; covers
  guardrails, tool runtime, session continuation/leases, accounting/usage,
  HTTP and route/OpenAPI guards.
- Consumer module: 12/12, 2.082 seconds. Nine cases overlap the writer union;
  three additional managed Gemini cases prove cache-binding success, refusal
  of oversized transformed material before cache I/O, and refusal when a
  fitting cache prefix plus rebuilt tail exceeds the allowance.

Combined: **646 distinct passing cases**, zero failures/errors/skips. Ruff passes
all eight changed Python files. The only change after that source review was a
class docstring qualification before the tested-source commit above.

Full backend milestone at the tested source: **21,372 passed, 37 skipped**, zero
failures/errors, **312.491 seconds**, exit 0. The 37 skipped case IDs exactly
match the preceding counter-availability milestone. The executed-count check
matches canonical collection: **21,409 backend cases** (+23), unchanged
frontend/native 2,009 and mobile 306, 555 routes and 18 agents. Hermes/status
checks and diff checks pass. Client counts are reused; no new client test run is
claimed. All eight source/test hashes remain identical to the frozen manifest.

## Review and evidence freshness

auth_audit (gpt-6-sol/high) owns production and focused tests;
mobile_session_transport (gpt-6-sol/high) independently writes actual dispatch
regressions and reviews frozen production. wall_contracts (gpt-6-luna/medium)
inventories exact-base pins. Root owns design, integration, documentation and git.
No Critical or Important finding remains. Root review corrected double reservation
of clock headroom and parallel peer settlement before the final source freeze.

Exactly 39 previously-current pins are refreshed; 89 already-stale pins are
preserved, including H673's agent/orchestrator and H002's CLI pins. H673 gains
two new test pins and bounded guard/remaining-limit wording. All 226 assessed
capability statuses remain unchanged. H670's Agent.process coordinate moves
1026 to 1050; eight H586 CLI references move by three lines. Other semantic
claims remain scoped to the named collateral review. No broader equivalence
or new authority claim follows from these whole-file pin updates.

Production SHA-256 at the tested source:

- agent.py: aed42f44f4bc46f09138206aa782b30d7396aee37cdda914e7370594af18fa2d
- orchestrator.py: 98722e639dbcd37f841d9f8e6e307b829a357fe3e5a9d718b8413e95d0674a37
- route_compaction.py: d7a19bcc582cd01e9d11adaf3ff08f91f835dcae8c85c1a4c7c3d32bddca5d19
- conversation_clock.py: 38ed73c554e65c8eeb00100d80dac13aad7a2bb52aa7885bb68cc1658d519931
- cli/nerva.py: 275e3dfac1b23ab63fe77216eea583dc313ce52ac826a1b54aa4c43ae03d376c

Scratch evidence under /workspace/scratch uses the persona-dispatch-budget prefix:
builder-red, consumer-red, parallel-red/green, focused, consumer-green,
integration and backend-final XML/log pairs; source-manifest.json,
base-hashes.json, ast-review.json, pin-inventory.json/md, pin-refresh.json,
claim-review.md, consumer-review.md, final-evidence-review.md and status-sync.log.
