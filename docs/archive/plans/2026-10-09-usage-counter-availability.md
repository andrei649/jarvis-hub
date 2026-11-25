# Preserve availability of compatible response token counters

- Generated: 2026-10-09 UTC.
- Goal: stop partial compatible-provider counters being recorded as complete
  provider totals, while retaining known token lower bounds and useful anchors.
- Base / HEAD before edits: 999c942efc4a72c62b79efcdb31b67267f531417.
- Branch/worktree: codex/usage-counter-availability-20261009,
  /workspace/jarvis-hub-usage-counter-availability.
- Scope: autonomous local parser/observer/accounting fix; no publication or live
  provider use. No CLI receipt or public response-schema additions.
- Outcome: implemented and verified locally. Full source/test head: 93c386e909bebd46e9888428a654d071071899be.
- Next action: this rollback unit is complete; continue backlog work from the final documentation commit.

## Evidence contract

Add counts_complete: bool | None = None after TokenUsage's four numeric fields.
This indicates availability of the canonical counters in a parsed response,
never complete physical billing or whole-turn coverage. None preserves legacy
producers. Keep reported's nonzero predicate and as_dict's four-count output.

Only lmstudio_usage and compatible_usage set the new flag: True when both
prompt_tokens and completion_tokens are exact nonnegative ints; False for a
missing, malformed or invalid pair, including absent/nonmapping usage. Retain
valid sibling numbers; zero is a valid supplied number. Inclusive prompt totals
still leave cache fields zero, and total/detail counters are not added. Declared
OpenAI-compatible OpenRouter profiles use the parser; undeclared profiles and
other provider parsers keep legacy behavior.

Observers and AgentToolRuntime forward explicitly flagged True/False values,
including all-zero values; legacy None retains the current nonzero filter.
Scope closure, sink-error isolation and no duplicate observations still apply.
LM Studio streams with clean completion and no usage frame emit a False value
only after the existing completed/error gates. Interrupted, malformed or failed
streams retain their existing no-event behavior. A later malformed usage frame
must invalidate earlier valid counters without reviving them.

_sum_usage keeps numeric addition and combines flags: True only for True+True;
None only for None+None; False for every other combination. A first event is
retained as-is. A missing-usage response in a multi-request tool loop therefore
cannot disappear from the observed aggregate. Mixed migrated/legacy evidence
is conservatively incomplete.

_billable_from_usage returns no provider-total tuple for explicit False,
accepts explicit True even for zero, and retains the existing reported check
for legacy None. _record_interactions labels False as usage_source=estimate.
For that branch only, floor estimated input at the observed input+cache-read+
cache-write sum, and estimated output at observed output. Use max, not addition;
do not invent a cache discount. This prevents a known 100,000-token prompt with
missing output from dropping to a one-token heuristic and lowering the recorded
daily spend. Legacy None and complete valid counts retain their behavior.

Context anchors remain separate: a valid positive prompt remains useful even
if output is unavailable; missing/zero prompt counts do not clear a prior
anchor. The new flag is not a claim about every model dispatch. Physical retries,
failed requests without observations, synthesis, auxiliary work, other providers,
and per-turn pricing/CLI accounting remain explicitly outside this fix.

## Ownership and RED coordination

- auth_audit (gpt-6-sol/high): tool_protocol.py, tool_dialects.py,
  usage_context.py and base.py under agents/core/llm; new
  tests/test_usage_counter_availability.py; narrowly adapt existing
  tests/test_text_usage_propagation.py and tests/test_stream_token_usage.py for
  explicitly incomplete compatible observations. No other file edits.
- mobile_session_transport (gpt-6-sol/high): agents/core/agent_runtime.py,
  agents/core/orchestrator.py and new tests/test_usage_counter_accounting.py.
  Test actual parsed partial-positive metadata through accounting, preserving
  observed floors/spend; complete zero, legacy behavior, mixed flag aggregation,
  and a two-request tool loop whose second reply has no usage.
- Both writers first add tests and report RED at the unchanged production base.
  Root then releases production edits. No overlapping file writers. Each reviews
  the other's frozen contract; root owns integration and critical review.
- wall_contracts (gpt-6-luna/medium): read-only evidence-pin/citation inventory.
- Root: the existing cloud-tool-turn and LM Studio missing-usage equality expectations,
  documentation, backlog/parity/status, integration and git. At most four
  active agents; no nested delegation or live provider/device calls.

## Validation and rollback

Cover missing/invalid/zero/valid pairs, observer closure/concurrency, text/tool/
stream publishers, malformed final/no-usage streams, actual accounting source
and observed floors, and mixed/multi-request aggregation. Preserve answers,
tool governance, request bodies, retries, positive prompt anchors and legacy
provider behavior. Run focused suites, then disjoint downstream integration;
run one serial full backend milestone at frozen source for these shared changes.
Refresh only formerly current pins after named review; preserve stale pins and
all unrelated capability statuses. Record actual executed and collected counts.

Rollback the internal evidence field, both parsers, publisher/consumer changes,
tests and supporting documentation together. No stored-data migration is needed.

## Implementation checkpoint

Both production baselines were verified unchanged before release: foundation
RED 39 failures of 107; consumer RED 14 of 14, zero errors. Two later consumer
refinements also reproduced before correction. Frozen focused coverage passes
107 foundation + 251 consumer/runtime + 345 disjoint integration = 703 distinct
cases, zero failures/errors/skips. Independent cross-review found no Critical or
Important issue. The first full run found two old LM Studio equality
expectations (21,347 passed, 2 failed, 37 skipped); their explicit incomplete
markers are corrected in 93c386e, with the 44-case protocol module passing.
Production remains identical to a0e4272. Focused total is now 747 distinct
passing cases. Repeated full-suite run passed 21,349 cases with 37 unchanged
skips, zero failures/errors, 291.509 seconds, exit 0. Executed count matches
21,386 collected backend cases. Fresh-pin reconciliation is complete with 45
refreshed, 67 pre-existing stale preserved and no status change. Final evidence:
[compatible counter availability](../project-usage-counter-availability-20261009.md).
