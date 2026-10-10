# Hermes full-contract closure — batch 05

Generated 2026-10-10 UTC. Goal: close H002's attributable one-shot usage report
while preserving its stdout, exit, session and approval contracts. Base/initial
head: `5187a0fbc888cdf563365631c3f76d2c1a3fb704` (143/697 local);
branch `codex/hermes-closure-05-20261010`. Local only: no push, merge, deployment,
paid provider calls, personal-state reads or global configuration changes.
Current state: implementation and focused verification complete; whole-contract
status is not yet promoted. Next action: freeze repository inputs for the one
serial full backend milestone, then reconcile its actual result and metadata.

Whole-contract review addendum: H002 also retains a real completion gap: a
source-assigned specialist stop can be rephrased by synthesis and escape the
CLI's text fallback. Add a request-owned finite `runtime_stops` list alongside
usage, sourced at the settled tool-loop owner return and the exact thinking
exhaustion sentinel. Copied response-producing tasks share it; detached background
tasks and closed collectors cannot modify it. Terminal orchestrator catches also
record timeout, generation failure, policy refusal and continuation refusal. The
nonstream synthesis failure catches retain their fixed stop independently of prose.
An empty list does not attest
success; legacy text checks and pending-approval checks remain. Any known stop or
malformed present stop metadata makes one-shot output incomplete, even when the
final prose resembles an answer. No retry, tool execution or approval is added.
Preserve bounded decoded usage on non-2xx HubError paths so existing failure
receipts can retain a valid measured snapshot without copying raw server bodies.

Additional owned paths: root `agents/core/turn_stops.py` and
`tests/test_h002_turn_stops.py`; integration `agents/core/llm/auxiliary_text.py`,
`agents/cli/client.py` and existing CLI-client tests; core's settled runtime seam
and usage detachment. Generated frontend types must also include H441's prior
resume/import routes, which were missing from the batch-04 generated file.

## Contract and boundaries

One-shot chat must write an attributable machine-readable spend receipt even
when its turn fails. Existing final-only stdout, no terminal reads, atomic receipt,
confirmed session ID, exit codes and queued-approval refusal remain in force.
No report flag grants authority, decides approvals or adds provider requests.
No count credit until the complete frozen contract is reviewed.

The collector counts accepted generative-inference HTTP dispatch attempts after
quota, H513 and host/protocol preflight. This includes retries, streamed generation,
specialists, response-driving synchronous auxiliary generation and synthesis.
It excludes control probes, embeddings, audio services and unrelated background
jobs; these are not generation calls in this receipt. A dispatched attempt is
not proof of billing or a successful response. Never infer dollars from global
cost-tracker deltas or infer the actual model from a final display label.

Token totals require valid provider-certified complete usage for every accepted
attempt. Missing/partial/duplicate or uncorrelatable reports make aggregate totals
unknown. A failed earlier retry cannot disappear behind the successful last one.
Explicit zero counters differ from absent counters; bool is not an integer here.
Unknown cloud pricing remains null. Use the existing exact repository price table
as an estimate with its dated basis; do not claim an invoice. Withhold a numeric
estimate for unsupported cache-write premiums instead of silently underbilling.
Local zero cost needs trusted local routing/provider evidence, not a model name
that happens to match a zero-price alias. Retain input/cache category semantics.

An observed direct command with neither generation intent nor accepted dispatch
means measured zero calls/tokens/cost. Entering generation without an attributable
owned dispatch is unknown, including a refusal inside that scope; it never proves
a hidden backend was free. No decoded hub response or no collector means unknown.
Mixed models/providers have null scalar identities and bounded per-pair breakdown.
Late child-task events cannot change a closed receipt or leak into another turn.
No prompts, credentials, URLs, tool arguments or raw responses enter telemetry.

## Shared interface (settle deviations with coordinator)

New `agents/core/turn_usage.py` exports:

- `turn_usage_scope()` context manager yielding a request-owned collector with
  idempotent `close()` and pure bounded `snapshot()`; scope exit closes/resets it.
- `model_usage_scope(*, model, route="")` for actual routed generation provenance.
- `detached_turn_usage()` for task creation that must not inherit this receipt.
- `record_dispatch(provider, request)` called at the accepted owned HTTP seam.
- `record_usage(usage)` called from text publication and tool-turn publication.

Use task-local dispatch identity within a shared request collector. Guard against
inheriting another task's pending identity; coroutine/task boundaries must be
tested with actual HTTP MockTransport, not simulated numeric receipts. Correlate
all internal retries. No new provider message fields or public backend signatures.
Pure observation must not change generation or any physical-send guard.

Server snapshot schema `nerva.turn.usage.v1`: `api_calls`, `input_tokens`,
`output_tokens`, `estimated_cost_usd`, `model`, `provider`, `usage_basis`,
`cost_basis`, and bounded `breakdown`. Optional cache/pricing-date fields are
additive. Numeric values are finite nonnegative and not bool. Core owner publishes
the exact finite basis values and breakdown schema before integration finalizes.
Settled bases: usage `measured_zero | provider_complete | unknown`; cost
`measured_zero | local_zero | price_table | unknown`. `model_usage_scope` records
generation intent and begins only at an actual generation call after preparation.
CLI validates the server object using stdlib-only code and copies trustworthy
values into the existing atomic `nerva.chat.usage.v1` receipt; preserve null on
missing/malformed/legacy payloads. Additive fields may explain provenance but must
not overwrite completion, pending approvals or confirmed session attribution.

Open the collector around actual `/chat` handling and independently inside the
SSE runner task. Finalize on success, refusal and exception; serialize the same
bounded shape on normal JSON responses and SSE end events. Disconnect closes the
scope. Bind selected model/route at actual agent generation and synthesis seams,
including the special streamed primary path. Explicitly detach post-answer title,
reflection/review and similar spawned work so scheduling does not affect receipts.
Synchronous work needed to produce the response remains within scope.

## Ownership and implementation

At most four active agents, two implementers `gpt-6-sol/high`, optional read-only
`gpt-6-luna/medium`; no subdelegation. Coordinator owns shared contracts, docs,
critical review, evidence and integration. One writer per file.

Core lane — repair_1247: new `agents/core/turn_usage.py`,
`agents/core/llm/egress.py`, `agents/core/llm/usage_context.py`,
`agents/core/agent_runtime.py`; new `tests/test_h002_turn_usage.py`,
`tests/test_llm_egress_ledger.py`, `tests/test_text_usage_context.py`,
`tests/test_text_usage_propagation.py`, `tests/test_stream_token_usage.py`,
`tests/test_cost_measurement_and_cap.py`. Notify coordinator before extra paths.

Integration lane — review_1233: `agents/core/agent.py`,
`agents/core/orchestrator.py`, `agents/web.py`, `agents/cli/nerva.py`;
new `tests/test_h002_usage_integration.py`, `tests/test_nerva_oneshot.py`,
`tests/test_turn_pending_approvals.py`, `tests/test_chat_http.py`,
`tests/test_ch02_g1_stream_fanout.py`. Core module is read-only in this lane.
Coordinate before editing any extra file. Existing tests may be read/run freely.

Root owns receipt documentation, architecture, HUD/mobile intentional CLI-export
scope, BACKLOG, assessment and generated status. This is one observable behavior
unit; rollback code with its receipt documentation and evidence, leaving owner data
and unrelated work untouched. No database migration or persisted collector.

## Verification

Red-first: complete/zero/unknown usage, exact pricing/local proof, missing retry
usage, mixed routes, bounded identities/records, duplicate and late publication,
concurrent request isolation, copied-task context and actual egress guards. Real
MockTransport should prove accepted send counting, internal retries, stream usage,
tool iterations and control-probe exclusion. No real provider calls.

Actual ASGI and CLI: precise per-turn receipt, direct-command zero, no-hub null,
multi-agent plus synthesis, approval queued after spend, failure after dispatch,
stream end/cancellation, stdlib CLI validation and atomic-write behavior. Preserve
existing taint/guardrail/replay/route pins and physical policy checks. Restart the
actual app with disposable state for smoke. Focused tests per lane, one serial full
backend milestone at frozen integration, then exact failure-driven follow-up if
needed. Frontend/mobile source is unchanged unless explicitly coordinated.

H392 recovery research remains pending: it needs these trustworthy attempt counts
and a genuine supported Codex Responses mode before whole-contract closure.

## Focused verification before the full milestone

The final core selection passes 166 cases; the integration selection passes 379,
with one additional CLI parameter checked afterward in its five-case selection.
The root selection passes 71 cases covering request-owned stops, real runtime
stop → synthesis → HTTP → CLI behavior, response compatibility and route/OpenAPI
guards. These selections overlap and are not summed. Red proofs cover missing
attribution, nested scopes, unknown POSTs, expired scope provenance, typed stops,
actual agent failure/timeout after synthesis, and two additive-response fixtures.

A disposable actual FastAPI lifespan plus CLI smoke passes direct-command zero
and generated-answer local usage. Two synthetic generation dispatches occur: the
answer and its detached background title; the answer receipt correctly counts
one. Real network connections are blocked (two startup probes); no provider call
or personal state is used. Generated OpenAPI types include usage/runtime stops,
the missing H441 resume/import routes and H329's current approval description.
Frontend TypeScript, changed-Python Ruff and `git diff --check` pass.

Artifacts are under `/workspace/scratch/hermes-697/batch05/`: `core/final.xml`,
`integration/final-focused.xml`, `root-final.xml`, `live-smoke.json`,
`frontend-typecheck.log`, and the red/focused source reports. No full backend,
full frontend, native-device, Windows, Fish or live-provider pass is claimed here.
