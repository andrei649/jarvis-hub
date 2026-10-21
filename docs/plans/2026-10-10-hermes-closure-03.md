# Hermes full-contract closure — batch 03

Generated 2026-10-10 UTC. Goal: continue the accepted 697-contract absorption
without changing the frozen inventory. Initial local count 133/697; main 116.
Base and initial head: `0f633762849411f6785bb83b3c5a517f18399811`;
branch `codex/hermes-closure-03-20261010`.
Local only: no push, merge, deployment, paid providers or personal-state edits.

## H299 / H397: result-aware turn-local stall policy

Use a pure turn-local observer in a new `agents/core/tool_loop_guardrails.py`.
Observe executed raw results in assistant call order after the entire concurrent
batch has settled. Fingerprint tool, canonical arguments and the raw result;
do not count a local cap refusal as an executed observation. Remove the argument-
only pre-dispatch refusal, which blocks calls whose results would change. Retain
all assistant/tool pairs and the existing approval/guardian terminal priority.

Warn on the third consecutive identical signature; exact failures warn at two
and halt at five, contiguous failures of the same tool warn at three and halt at
eight, successful identical no-progress observations warn at two and halt at
five. Different tools/results reset the relevant contiguous tracks; success
resets failures. No separate invented fourth-call identical-signature halt:
the failure/no-progress tracks supply the specified halt thresholds. Stable
results are the no-progress signal; changing data must remain executable.

All stall halts are opt-in through `stall_halt_enabled` (bool/callable; default
false). Root wires `llm.tool_loop_stall_halt_enabled`, default false, through the
coordinator. Unreadable toggle stays advisory. Existing `repeat_limit=0` and
`failure_limit=0` remain supported detector-off overrides; document precisely
how the legacy positive thresholds map without changing the required defaults.
No new environment bypass. Iteration/wall/context/approval limits remain hard.
Owner-configured per-tool caps remain hard and independent, including pollers;
on cap exhaustion use the existing controlled TOOL_CALL_LIMIT exit after all
tool-call IDs in the batch receive responses. Keep todo's cap/restatement and
script revision semantics.

`process`, `*_poll` and `*_get_result` are exempt from stall guidance/counters,
duplicate stubs and recovery nudges, not authorization or other ceilings. From
the second identical successful payload of at least 512 characters, use a
reference stub with source call ID, tool name and at most 120 characters of safe
canonical argument preview. Retain full errors and sub-threshold Unicode text;
redact secret-bearing keys or withhold the preview. Keep taint fencing and event
redaction. Do not store repeated raw payloads as unbounded guardrail state.

Explicit boolean ok and wrapped inner ok=false retain authority. Missing-ok
classification recognizes nonempty error data, failure/refusal statuses and
reason codes; payload-only results are successful. Test empty/ambiguous shapes
and nested wrappers. Hints use finite trusted reason classes and bounded text,
never interpolate untrusted error instructions or suggest bypassing permission.
Use existing typed FAILING_TOOL/REPEATED_CALL exits, no exception-based halt.

Implementation owner: repair_1247 (gpt-6-sol/high). Owns agent_runtime.py,
new tool_loop_guardrails.py, and tests/test_tool_loop_repeats.py,
test_tool_loop_guardrails.py, test_tool_loop_results.py,
new test_h299_h397_stall_policy.py. Notify root before any extra test path edit.
Root alone owns shared autonomy_coordinator.py/settings_db.py. Implementer
provides the constructor integration contract; no shared-file edits.

Root additionally owns `tests/test_hermes_batch03_wiring.py` and refreshes only
the moved coordinator callsite coordinates in `orchestrator_bindings.py`.
The legacy failure_limit default is now None (same-tool halt eight); an explicit
positive value customizes that track only, while zero disables both failure
tracks. repeat_limit zero disables identical/no-progress tracks, independently
of exact-failure tracking; a positive value sets the identical warning threshold.

TDD covers exact thresholds/default advice/opt-in typed halts, result changes,
counter resets, multi-call completion, poller exemptions versus hard caps,
512-character Unicode boundary, safe preview, failure classification/hints,
approval/guardian priority, todo/script revisions and isolated concurrent turns.

## H329: approved re-enable and strict runtime switches

Disable is immediate narrowing, including a durable revision change for an
otherwise redundant disable so an older pending approval cannot resurrect it.
Re-enable resolves exact installed targets/channel, strictly reads switches and
creates a once-scoped skill_switch permission.grant task. It does not mutate
switches before a human decision. Require the existing Action Kernel to be on
and bound, the governed intake and ledger to be available; refuse clearly if
any are unavailable, with no direct-write fallback. Already-on requests are
no-ops. Category requests bind the exact current members and source identities.

Use durable requests keyed to exact targets/source snapshots, channel, settings
revision and task ID. The registered permission.grant executor delegates only
skill_switch tasks to the new bridge; all other surfaces retain apply_grant.
The bridge verifies human decision, original request/task/payload identity and
current targets/revision, then applies only the approved change. Atomic settings
update, consumed-request receipt and approver/task audit share one settings DB
transaction. A failed transaction cannot leave widened state without durable
attribution. A consumed/rejected/stale request cannot be replayed after a later
disable. Grant creation alone is never permission to skip this binding.

Switch reads validate actual JSON shape instead of silently cleaning malformed
rows to empty lists. An unavailable store hides/refuses nonessential skills in
catalog, list, view and execution; the shipped essential floor remains usable.
The owner list reports unavailable switch status truthfully. CLI and HUD render
queued approval as pending, not success; the approved worker automatically
applies it. Preserve category/global/channel behavior and curator restart clock.

Implementation owner: review_1233 (gpt-6-sol/high). Owns permission_ledger.py,
skills/switches.py, new skills/switch_approval.py, skills/loader.py,
routers/skills.py, cli/nerva.py, capability_manifests.py,
frontend/src/panels/skill-switches.tsx; tests/test_h329_skill_switches.py,
new test_h329_skill_approval.py, test_permission_ledger.py,
test_action_auth_matrix.py and frontend/src/test/skill-switches-panel.test.tsx.
Root alone edits autonomy_coordinator.py and settings_db.py. Notify root if
additional paths or an authority contract adjustment is necessary before edits.

TDD covers real local intake/human decision/executor application, no decision or
machine decision, rejection, modified targets, kernel denial/off/unavailable,
audit/DB failure, stale category/source identity, duplicate/ABA task replay,
concurrent changes, strict corrupt/unavailable reads and essential floor, and
pending CLI/HUD versus immediate disable. Use only disposable state.

The frozen terminal-picker clause is retained. Add `skills config` with
interactive per-skill/per-category choices and optional channel, showing current
state and pending task outcomes. Preserve the essential floor, use the same
owner API, support EOF/cancel, and refuse noninteractive invocation without
mutations. CLI verbs plus HUD are not used to waive this accepted clause.
The implementer additionally owns new `tests/test_h329_skill_config_cli.py`.

Shared executor interface: `switch_approval.apply_approved(task, *, ledger,
loader, usage=None, intent_log=None)` is async. Root dispatches only a Mapping
payload with surface skill_switch to it; other grants call ledger.apply_grant.
The transactional H329 event is the canonical approver/task audit; IntentLog
projection is best-effort afterward and must be described truthfully. SQLite
triggers cover every switch-row mutation with a monotonic revision. No settings
DB writer refactor is needed. Notify root before changing these interfaces.

## Integration and evidence

Maximum four active agents including root; two implementers and optional narrow
gpt-6-luna/medium read-only review. No subdelegation; one writer per file. Root
owns scope, shared interfaces, critical review, all docs/evidence and integration.
Each unit is independently reversible with its evidence. Focused tests per unit,
relevant integration and one serial full backend milestone after source freeze.
Frontend changes require focused UI tests/build; no native-host claim without
native execution. Preserve route parity and record mobile/HUD pending approval.

Review collateral evidence paths before edits; never refresh unrelated stale
hashes. Update a contract only after reading its complete frozen requirement and
verifying production integration. H441 selectors remain a separately researched
gap; no claim or scope expansion in this batch without an explicit root handoff.
Source units are committed separately: H299/H397 as `c3e33a82`, H329 and its
built HUD as `d7b5ac8f`. The integrated milestone and its bounded test-only
corrections are recorded below. Next action: finish the metadata checkpoint,
then start the isolated H398/H441 batch without publishing remotely.
Collateral scope was captured before edits in the batch03 scratch report;
current valid pins only may be refreshed after bounded source review.

## Completed implementation and review

The two implementers used the authorized gpt-6-sol/high resource profile; the
read-only H315/collateral reviewer used gpt-6-luna/medium. Root settled interfaces,
reviewed security-sensitive paths and owns integration/evidence. No subdelegation.
The implementation owners also received the bounded additional paths recorded
below; shared-file ownership remained with root.

H299/H397 post-result observation preserves every batch response. Review caught
a trust regression when the broader failure classifier would strip a fence from
a missing-ok external handler error. A red-first real ToolRPC regression now
keeps the narrow explicit-refusal ingress predicate separate from stall status.
Argument previews withhold opaque commands/headers and embedded credentials;
observer indexes retain digests. Changed results continue executing.
The final 12-file selection passed 301 cases. Later H315b/c review found four
legacy assertions requiring the former hard repeat refusal or four act calls
under cap two. Test-only corrections preserve full-plan reads and todo's cap
exemption while asserting actual act effects, controlled cap exit, default
advice and optional stall halt; the corrected two-file run passed 94 cases.
Additional owned tests: test_tool_result_taint.py and H315b/c/d/h review files.

H329 uses a consistent SQLite request snapshot; redundant disable advances a
durable revision. Exact task payload/title, targets, source bytes and category
membership are rechecked before atomic switch/receipt/audit commit. Duplicate
pending requests reuse their task; a rejected terminal task permits a fresh
request. An intake whose local binding cannot persist cannot apply. The canonical
transactional audit is distinct from the optional IntentLog projection.
Strict first-read initialization marks the store. Root reproduced another boot
ordering gap: unrelated settings initialization could reseed a missing marked
switch row before strict reading. Two new failing regressions now pass after
seeding preserves those rows as missing, while legacy seeding and explicit reset
remain available. The 95-case startup/settings/approval/binding selection passed.

H329's final six-module focused backend selection passed 190; the real
coordinator/TaskQueue/AutonomyWorker test passed, using the actual bound Action
Kernel, human decision and worker tick to apply the switch, then refusing replay
after disable. This proof uses mediation-off task mode with the Action Kernel
on; it is not a separate enforce-mode/native-host acceptance claim. The final
root wiring/startup/worker selection passed eight. UI panel tests passed six and
TypeScript checking passed. The terminal picker supports per-skill/category and
channel scope, truthful mixed/off state, essential floor, EOF/cancel and
noninteractive refusal. Additional tests: test_h329_skill_config_cli.py,
test_h329_skill_worker.py, and root test_hermes_batch03_wiring.py.
Focused selections overlap; their counts are not summed.

## H315 whole-contract re-review

The frozen contract requires the full model-facing checklist after mutation,
state-mutation guardrails and owner-visible intent. TodoStore and its handler
return the full bounded list, retain session/writer/taint isolation, and refuse
non-owner access to the shared owner session. The Decision Inbox shows a bounded
preview (three plans/eight items and omitted count); authenticated selected-plan
API and CLI provide the complete list. This is not a waiver of the full-result
requirement. Plans remain in-memory work-in-flight state. Current runtime
semantics and the corrected H315 regressions are included in the batch proof.
No upstream inventory row or acceptance scope is changed.

## Verification artifacts and remaining work

Artifacts are under `/workspace/scratch/hermes-697/batch03/`: stall red/green
logs and XML, H329 focused/worker/UI logs, root wiring/startup XML, client reports,
and the frozen integrated backend output. The read-only H315/collateral reports
are alongside this directory. Integrated backend and fresh-app smoke outcomes
will be recorded after completion; no unrun suite is described as green.
The source collection currently contains 25,694 backend cases, with 622 routes
and 18 agents. Mobile code is unchanged; its 359-test count is reused, not a
fresh native run.

H392, H409 and H441 were investigated separately and remain incomplete: generic
reasoning recovery, outbound lifecycle webhooks, and durable resume selectors.
H398's missing elision notice/output-risk metadata has a prepared next-unit
design; the new taint regression alone does not close that contract.

## Integrated milestone and final assessment

Frozen source head: `d7b5ac8fea77f3c3df5e48232c2242242adbe5e4`.
The 2,931-file input manifest was checked immediately after the run: zero input
changes. The full backend run collected/executed 25,694 cases in 394 seconds:
25,573 passed, 42 skipped, one expected failure, one failure and 77 setup errors.
It was **not a green full run**. One old command-tree assertion omitted the new
`skills config` verb. The 77 setup errors shared a fixture which required the
permission handler to be the ledger's exact bound function; H329 now dispatches
skill switches through its approval bridge and delegates ordinary grants.

The first affected rerun exposed two further test helpers recovering the ledger
through the former handler's `__self__`. They now use the existing governed
fixture's actual ledger directly. Four test files changed; production code did
not change after the full milestone. The final ten-module rerun passed 209 cases
and skipped 16, including every previously failed/errored node, real signed
approval/worker/grant persistence, pending input and the dispatch contract.
The original failed log/XML and both repair runs remain in the batch artifacts;
this focused repair is not described as a second full-suite pass.

All 2,177 frontend tests passed; TypeScript and production build passed. The
existing chunk-size warning remains advisory. The freshly built `/v2` bundle
was then served by an actual disposable FastAPI lifespan. A real bundled Brief
skill was disabled, returned pending 202 on enable, received a human decision
through `/autonomy/tasks/1/decision`, and was enabled by the actual worker tick.
The canonical audit identified the task and approver. This smoke used disposable
state and blocked external connections; it is not live-provider or deployment
acceptance. No fish or native Windows run is claimed; mobile code was unchanged.

Whole-contract reviews close H299, H397, H329 and revalidate the stale H315
contract. Thirty-two collateral records refresh only changed paths whose pins
were current at the batch base. The H067 fixture repairs preserve its actual
signed consent behavior; H004's CLI discovery expectation includes the new verb.
H204 remains partial: per-agent owner grants, All/master and disable-unused
controls are still absent. H398 remains partial; its new fence regression alone
does not implement elision notices or output-risk metadata. H396's changed typed
exit test retains its contract without refreshing older unrelated stale pins.
H504's sole valid changed pin is an unrelated new section in `docs/FLAGS.md`.

Final assessment: **137 equivalent, 230 partial, 56 missing, 274 needing review,
0 excluded; 697 accepted (19.7%)**. There are 67 current reviews, including 29
reviewed equivalents and 108 inherited equivalents; 560 contracts remain
unfinished. H315 moved from stale evidence, the other three from partial.
The frozen inventory SHA-256 remains
`84f7079a8381797f89299105fc86eb2686d67cb57f2196d159eedade36be4b07`.
Main remains the separately verified 116/697 baseline. Work is local only.

Metadata checks: Hermes reports and generated project status are synchronized;
all 86 status/evidence regression cases passed. Test-only repair commit:
`dd10d840`. Ruff on the four repaired tests and `git diff --check` passed.
