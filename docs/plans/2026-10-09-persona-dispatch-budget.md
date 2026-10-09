# Refuse prepared dispatch after prompt growth

- Generated: 2026-10-09 UTC.
- Goal: stop shared-compaction routes sending an initial prompt that exceeds the
  selected estimated input allowance after persona/identity refresh.
- Base: e711b432161ca3ec25b500718a351d1669df2daa.
- Tested source: 42013de7435c08f7bee91257d7c7f7fd2091366c.
- Branch/worktree: codex/persona-dispatch-budget-20261009,
  /workspace/jarvis-hub-persona-dispatch-budget.
- Delivery: autonomous local fix, no remote publication or live providers.
- Status: implementation, independent review, full backend verification and
  evidence/status finalization complete. No further action within this unit.

## Scope and decisions

The existing shared planner estimates cached system text, publishes accepted
history/clock state, then refreshes identity and persona. Fresh longer system
text can therefore exceed the old allocation. This unit adds final guards; it
does not introduce prospective file previews, move refresh before CAS, retry
compaction after publication or claim that known token estimates are exact
provider tokenization. A refused post-CAS dispatch retains its accepted summary,
clock and refreshed persona. Unknown windows remain estimates. Existing failed
CAS/history-race paths must still leave persona/state uncommitted.

PreparedRoute.check_budget(prompt, system, tools=(), cached_input_tokens=0)
will enforce the same floor(0.85 * input_budget) allowance used by planning.
Use the maximum of canonical route prompt plus rendered system, actual prompt
plus rendered system, and actual prompt plus the supplied cache input estimate;
add the current conservative tool-schema estimate. This preserves full-history
accounting when Gemini supplies a cache tail and covers separately estimated
cached material. Invalid budget inputs refuse. This is an additional check;
existing route/model/session/lifetime/capacity validation remains authoritative.

Agent.generate_response gains optional prepared_route and cached_input_tokens
parameters, supplied only for prepared dispatch; the second carries the
Gemini binding estimate to the final common guard. After its existing clock rendering, check the exact
immutable system string passed to _generate_response and the prompt, including
current runtime._server.tools() as the planner does. Normal callers keep their
existing signatures at call sites. Agent.process additionally checks before
checkpoint/residency side effects and again after residency; prepared execution
checkpoints are written only after that final preflight. Context refusals do not
record an agent/backend failure or trigger demotion. The nonstream gather
returns a refusal for that agent and awaits its peers normally; it must not
raise early and leave sibling dispatch tasks outside the planning lifetime.

Streaming checks before Gemini lease/cache lookup or creation, after policy
cache-material preparation (including its separate system/history estimates),
and after a cache binding/tail rebuild. The final Agent guard still checks its
clock-rendered string. Budget failures bypass the backend-unavailable catch.
Text and stream keep the existing CONTEXT_REFUSED_REPLY category. Its copy
becomes: "I stopped this turn because its context could not be safely prepared.
Please retry; if this persists, reduce the context size." This avoids claiming
that an already-accepted compaction failed to commit. The stdlib CLI sentinel
copy must match, while retaining the previous literal for older-hub replies.
No cache content, call, or new execution checkpoint should be created for the
already-oversized persona path. Keep prior unrelated checkpoints untouched.

This bounds the initial logical prompt estimate, including the conservative
schema snapshot and optional cache estimate. Later tool turns already have
separate runtime context checks; guardrail/provider wire framing and real model
tokenization are not promoted to exact context measurements by this unit.

## Ownership and regression coordination

- auth_audit (gpt-6-sol/high): production agents/core/route_compaction.py,
  agents/core/agent.py, agents/core/orchestrator.py; the narrow reply constant in
  agents/core/conversation_clock.py, copied CLI entry in agents/cli/nerva.py and
  the associated tests/test_nerva_oneshot.py parameter; focused new
  tests/test_prepared_prompt_budget.py. Own the shared interface and caller
  integration as one writer. First add tests only, no production until root
  verifies both final RED runs at the unchanged base.
- mobile_session_transport (gpt-6-sol/high): new
  tests/test_persona_dispatch_budget.py only. Actual mocked text/SSE orchestration
  with short loaded and longer on-disk benign SOUL/identity, real accepted
  compaction, no oversized model/cache request, fixed refusal, committed revision
  and no new execution checkpoint. Include bounded growth success and failed
  CAS/history-race no-migration controls; mock no live providers. Review the
  writer's frozen production after green.
- wall_contracts (gpt-6-luna/medium): read-only exact-base pin inventory and
  bounded affected-claim/citation list. No repository edits/tests.
- Root: scope, plan, critical integration review, documentation/status/backlog,
  meaningful downstream tests, serial full backend milestone and local git.
  At most four active agents; no nested delegation.

Focused checks also exercise canonical versus cache-tail accounting, rendered
clock overhead, tool schema growth during residency, optional/unmanaged callers,
route lifetime and current capacity checks. Existing route-compaction, H672/H670,
Gemini cache and model-generation lease regressions stay intact. Full backend
runs once after source freeze unless a failure requires a justified correction
and repeat. Refresh only previously-current pins after claim review; preserve
pre-existing stale evidence and all unrelated capability statuses.

Rollback the guard, all dispatch callers, regressions and associated evidence as
one unit. There is no persistent-data migration or new setting/API route.

## Implementation checkpoint

Root verified all five production files unchanged for both final RED runs:
builder 9/9 failures; consumer 3 failures and 6 passing controls, zero errors.
A later parallel-peer settlement regression reproduced an early gather unwind
before correction. Final writer coverage passes 267/267; disjoint downstream
integration passes 376/376; three further actual managed Gemini cache controls
pass in the final 12/12 consumer module. Combined: 646 distinct passing cases,
zero errors/skips. Independent frozen-source review has no Critical/Important
finding. The frozen-source full backend milestone passes: 21,372 passed,
37 skipped, zero failures/errors, 312.491 seconds, exit 0. All 37 skipped case
IDs match the preceding counter-availability milestone. The executed count
matches the canonical 21,409 backend cases. Hermes/status checks and diff checks
pass; client counts are reused without claiming a new client run. See
[final evidence](../project-persona-dispatch-budget-20261009.md).
