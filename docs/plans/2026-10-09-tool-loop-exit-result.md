# H396 typed tool-loop result — first internal slice

- Generated: 2026-10-09 UTC.
- Goal: retain source-assigned reasons for one tool-loop invocation, with a useful bounded diagnostic, while preserving string callers.
- Base/head before changes: ad571c36f78253be9b3f0ede220ca699d42f9636.
- Branch/worktree: codex/tool-loop-exit-result-20261009, /workspace/jarvis-hub-tool-loop-exit-result.
- State: implemented and independently reviewed; 325 focused cases pass. First full run on cf569ed33a054845fe4f8fc8915d4656ed70bc78 had one test capture-isolation failure (a preliminary legacy invocation was counted with two concurrent invocations). It reproduced under global INFO; the test-only boundary fix passes 1/1 targeted and 9/9 in its module. Next action: repeat full verification on unchanged production; do not claim a passing full run yet.
- Delivery: local only; PR #1247 remains the earlier published unit. No provider, device, push, merge or deployment.

## Contract and boundaries

Add a frozen, slotted `ToolLoopResult(reply: str, exit_reason: ToolLoopExitReason)`
and string enum in `agents/core/tool_loop_result.py`. Add explicit-signature
`AgentToolRuntime.run_result` with the same inputs as current `run`. It owns the
existing tool-turn binding/reset and awaits typed `_run_turn`/`_run_loop` results.
Keep `run` as an explicit-signature thin wrapper returning `.reply`, so Agent,
run-only fakes and existing callers keep a real string and identical reply bytes.
Never classify by matching prose and never retain a shared last result or outcome
ContextVar. Preserve existing execution guards, provider/tool scheduling, events,
timeouts, replay scope, taint propagation, cancellation and straggler gates.

Reasons are assigned only at the branch that already returns:

| Reason | Existing decision |
|---|---|
| `model_response` | provider returned no tool calls, even empty/fixed-looking prose; this does not prove objective or tool success |
| `window_invalid` | invalid effective context window before loop work |
| `context_refused` | `_compact_context` returned false; its boolean can mean size, inactive clock or failed clock commit, so do not call all cases budget exhaustion |
| `turn_revoked` | explicit inactive inherited conversation clock at loop entry |
| `replay_refused` | caught `ReplayRefused`, both before and around the owned loop |
| `tool_call_limit` | replay-bearing provider response exceeds executable fan-out and cannot safely be trimmed |
| `no_capability` | registry projection produced no live registered capability |
| `no_tools` | final profile/job offer is empty |
| `tools_withdrawn` | accepted-compaction offer refresh withdrew every tool |
| `repeated_call` | existing repeated-call terminal breaker |
| `approval_required` | batch observation requires approval, including current warning suffix |
| `failing_tool` | existing consecutive-tool-failure terminal breaker |
| `iteration_limit` | existing model-iteration budget exhausted |
| `deadline` | outer owned loop deadline, including cancellation-resistant child |

After a normal typed result and cleanup, `run_result` makes one fixed-field INFO
diagnostic emission attempt (`tool_loop_exit`, reason and bounded agent identity).
Its fixed format is `tool_loop_exit agent=%r reason=%s`; the agent's bounded
representation escapes newlines/control characters. Tests may inspect the two
fixed arguments. Logging is best-effort and emits no additional tool event.
No prompt, reply, model-controlled tool name, argument, result, path or exception
text enters that diagnostic. Diagnostic failure must not replace a valid reply.
Only the outer owner logs: late children cannot emit a second terminal diagnostic
or alter an already-returned immutable result. Escaping exceptions and caller
cancellation propagate unchanged and do not mint normal results or exit records.
No claim of durable/exactly-once log delivery.

Do not add pending-tool-result flags/WARNING semantics, mutation footers, counts,
tokens, a new ToolEventLog event or public outcome fields in this unit. Agent and
orchestrator stay on their existing string contracts. A specialist loop reason is
not a whole-turn reason: plain generation, commands, handled refusals, parallel
agents and synthesis need separate mapping. Future presentation must extend the
existing H686 shared outcome after those semantics are settled. H396 stays partial.

## Ownership and regression work

- auth_audit, gpt-6-sol/high: sole source writer for `agent_runtime.py`, new
  `tool_loop_result.py`, and new `tests/test_tool_loop_results.py`. First write RED
  branch/API tests; no production edits before root release. Exercise all reasons
  through actual scripted runtime/ToolRPC decisions. For the new method, absence
  may be feature-availability RED, but avoid module-import-only failure and include
  actual legacy reply controls. Model prose equal to a fixed refusal must still
  classify as model_response. Preserve approval suffix and no-tools/capability
  distinctions, concurrent independent results and result immutability.
- mobile_session_transport, gpt-6-sol/high: tests-only writer for new
  `tests/test_tool_loop_result_lifecycle.py`. Start with actual `run` reaching its
  reply before asserting missing terminal diagnostics; deadline/late-child,
  cancellation, exceptions, shared-runtime concurrency, private log content,
  logging failure and Agent run-only compatibility. No production edits. Wait
  for root release and core source before final integration.
- wall_contracts, gpt-6-luna/medium: read-only exact-base evidence-pin and claim
  inventory for `agent_runtime.py` and relevant documentation. No nested agents.
- Root: reason contract, RED/hash review and release, critical integration,
  metadata/parity and evidence, full verification and git. Maximum four active.

## Verification and completion

Run focused new modules and relevant existing runtime/repeat/compaction/replay/
taint/deadline/event/Agent integration suites after source freeze. Then one serial
full backend milestone with four workers and the subreaper, retaining all skips
and failure evidence. Latest backend baseline is 21678 cases =21641 passed plus
37 JUnit-skipped; the latter are 36 guarded skips and one existing source-gap
xfail. Supplemental cached-image Docker lane passed 11/11 separately; do not
rewrite the historical full result. Backend changes justify a new full run.

Frontend/native2039 and mobile316 are reused because no client source changes.
Run Ruff, diff, relevant protocol/route/status guards, actual executed-count guard
and generated status/Hermes checks. Update H396 narrowly, its build-queue plan,
ARCHITECTURE and parity notes as appropriate. Refresh only exact-base-fresh pins
after named unchanged-contract review; preserve preexisting stale pins except an
explicit bounded H396 reassessment. Do not change inventory identities/statuses
or promote H396 from a runtime-only result.

Rollback: revert this typed runtime/test/docs unit. No persisted schema, API route,
client payload, permissions or settings change. Legacy run callers remain strings.
