# Hermes full-contract closure — batch 04

Generated 2026-10-10 UTC. Goal: continue the accepted 697-contract absorption.
Base/initial head: `bb7064fc04908781f5a491c32f7d7059d0ba19f0` (137/697 local);
branch `codex/hermes-closure-04-20261010`. Main remains 116/697.
Local only: no push, merge, deployment, paid model calls or personal-state reads.
Current source head: `1b26e3037f9d4dbd05a7f6c11eccd23de9336570`.
H398, H667 and H441 are implemented and reviewed. The complete backend milestone
exposed compatibility failures; all failed cases now pass in focused repair runs.
The whole-contract review yields **143/697 equivalent (20.5%)**, 229 partial,
56 missing and 269 needing review; 554 remain unfinished. The frozen inventory
and unrelated stale evidence remain unchanged. Generated status is reconciled
to this local checkpoint; main remains at its previously published 116/697.

## H398: external-output completeness notice and advisory risk

Retain the existing DATA fence and turn taint. Inspect original external tool
source before spill, truncation, deduplication or compaction. The typed producer
adapter recognizes literal `truncated=true` only for file_read/list/search,
kanban_list, execute_code and web_extract, and a strictly advancing integer
next_offset for skills_list. No recursive arbitrary has_more interpretation or
claim for an unregistered MCP bridge. Typed markers require the actual successful
ToolRPC envelope and a host-declared untrusted-output tool.

The raw fallback applies to any host-declared untrusted tool, including unknown
names: strings at least 1,000 characters, scanning at most the first 65,536.
Recognize the four upstream case-insensitive patterns: ellipsis followed by a
number and 'more item(s)', JSON '"has_more": true', 'saved to sandbox', and
'data_preview'. Peel the host wrapper; retain literal text parts and native dict
JSON adaptation. A host-created preview or same_as receipt cannot supply source
proof. External missing-ok handler errors remain untrusted; proven local
pre-dispatch refusals retain their separate predicate.

A fixed host-authored completeness notice survives DATA fencing, same_as, spill,
and accepted compaction. Never interpolate external prose or counts into it.
Inspect source with the existing normalized injection scanner and deterministic
native finding IDs. Internal advisory metadata is high/low risk, deduplicated
bounded IDs and redacted=false, without matched excerpts. This is a native
scanner adaptation, not a claim of byte-identical upstream threat rules. Scan
failure cannot claim low risk or weaken the existing fence/taint. Low risk never
grants authority, changes a kernel risk tier or clears taint.

Use a frozen internal result value plus a turn-local sidecar keyed by tool
message object identity. Never add unknown fields to provider message dicts.
Compaction stages sidecar changes with the existing message/clock transaction;
failed/rejected folds publish nothing. Strip/reapply the fixed prefix only when
a host sidecar proves it belongs to that message, re-fence external payload, and
prune discarded identities immediately after successful publication to avoid
object-ID reuse. Keep upstream_elided separate from context_elided.

Owner: repair_1247, gpt-6-sol/high. Source: new tool_output_advisory.py and
agent_runtime.py under agents/core. Tests: new test_h398_tool_output_advisory.py,
test_tool_result_taint.py, test_tool_loop_result_spill.py, test_web_tools.py,
and test_spill_paging.py only if needed. No orchestrator/quarantine source edits.
Root approves additional paths before handoff. No subdelegation or commits.

Red-first verification: all typed shapes and rejects; each raw marker, case,
999/1000 and 65,536 boundaries; real registered web_extract and native producer;
source before spill; missing-ok external errors versus local refusal; immutable
host wording; deterministic bounded findings with no excerpts; no risk/taint
laundering; same_as/spill/compaction survival and failed-fold isolation; identity
pruning; backend wire schema unchanged. Run affected runtime/taint/compaction
regressions, not the full suite independently.

## H441: resolve/resume/continue and foreign conversation import

Preserve the accepted free recap: last ten exchanges, names-only collapsed tool
calls, no LLM call. Keep existing HUD and channel recap. Add chat -r/--resume
SELECTOR and -c/--continue, mutually exclusive with exact --session. Exact full
local ID wins, even if literally 'latest'; then reserved latest, foreign aliases,
unique ID prefix, exact normalized title. -c invokes latest mode explicitly.
The existing sessions continue verb creates a new compaction generation and
must not be used for chat -c. Frozen scope waives per-terminal breadcrumbs/TTL;
workspace cwd restoration is not an extra H441 acceptance gate.

Owner-only POST /sessions/resolve queries the full strict session store rather
than the 20-row recent API. Latest means deterministically most recently active
eligible unarchived row. Explicit IDs/prefixes may address archived rows without
unarchiving. Bounded ambiguity 409, unknown 404, unreadable store/history 503;
no active/default mutation on selection or failure. Return validated ID and free
recap; chat sends that ID on its subsequent explicit turn. Preserve H002's
noninteractive one-turn contract: never read a terminal in chat, keep -z stdout
answer-only and recap on stderr; JSON output remains valid structured output.

@claude[:external_id] and @codex[:external_id] import a Claude Code/Codex CLI
JSONL conversation from the CLI host. They never filter Nerva by current provider
or model. A single candidate may be imported; ambiguity requires explicit choice
without an implicit chat prompt. Add sessions import --from claude|codex PATH.
Default discovery is limited to ~/.claude/projects and ~/.codex/sessions; explicit
paths are owner-chosen local JSONL. Use synthetic fixtures only during development.
Safe bounded file opening rejects symlink escape and changing source; enforce
file/line/turn/text bounds and source-specific schemas. Keep user/assistant text
and short tool names; omit system/developer messages, hidden reasoning, raw tool
arguments/results, media and malformed records. No external calls or execution.

New owner-only POST /sessions/import revalidates canonical fields and source
identity/digest. Provenance is an owner-attested source claim, not vendor-signed
proof. Never store a raw personal path or use title_source for origin. Import is
idempotent for source ID plus canonical content digest; changed content creates
a distinct import. Prefer an authoritative immutable SQLite seed: one strict
BEGIN IMMEDIATE under CheckpointManager._lock inserts session, instance, clock,
receipt, seed and hash. No success before durable readback. Hydrate that seed
using the continuation loader pattern only when no snapshot exists; a corrupt
present snapshot cannot fall back to the seed. Later snapshot writes for imported
sessions must be strict, preserve checkpoint->snapshot lock order and rollback
in-memory append on persistence error. Include deletion/backup lifecycle and
retry/restart tests. Avoid ordinary swallowing create/save helpers.

Only the server assigns bounded per-turn foreign_origin and durable session
origin/ancestry. Preserve it in Turn, snapshots, strict resume, continuation seed,
rewind, compaction and summary cache. Missing/inconsistent origin for an imported
or derived session refuses; deleting a marker cannot declassify the transcript.
A continuation carries derived provenance, not a claim that its current model is
Claude/Codex. Native sessions and turns keep their existing serialized shape.

Foreign text is untrusted historical DATA at every prompt entry. Use one escaped
bounded renderer; embedded closing delimiters or [speaker] prefixes cannot break
out. Keep the current fresh owner instruction separate. Kept turns, deterministic
and local-model summaries, shared-route planning and auxiliary history consumers
must retain this framing or omit foreign turns. Persist summary_tainted through
staging/cache/clock; never publish unaccepted summaries. At both orchestrator
turn entries, validate lineage and owner principal before history access and set
mark_turn_recall_tainted before history-dependent planners/gather/tools. Taint is
conservative across imported/derived sessions; it cannot grant tool authority.

Apply a narrow conditional owner guard based on server-owned durable provenance:
explicit AND effective default session on /chat and stream; resume before history
or shared-default mutation; active GET /memory even after an admin resume; todo,
archive/pin targets. GET /sessions omits private imported/derived rows for guests,
including titles and metadata. Existing selected-turn vision/continuation admin
guards remain. Direct/native orchestrator entries need the same origin-integrity
and principal boundary independently of HTTP dependencies. A client flag, model
name or removable metadata alone cannot decide privacy. Preserve native user-token
behavior; this is not a general session ownership redesign.

Owner: review_1233, gpt-6-sol/high. Source ownership:
- agents/cli/nerva.py and new foreign_sessions.py;
- agents/core/new session_selectors.py, session_import.py, foreign_history.py;
- agents/core/checkpoint.py and session_continuation.py;
- agents/core/memory/conversation.py, manager.py, persistence.py;
- agents/core/orchestrator.py and context_compressor.py;
- agents/core/routers/sessions.py, memory_hud.py, and agents/web.py.
The foreign_history module holds shared provenance/rendering/conditional-guard
helpers without changing security/quarantine.py or agent_runtime.py. Notify root
before extra source/test paths. Root owns all docs/generated reports/evidence.
Tests: new test_h441_resume_selectors.py, test_h441_foreign_import.py,
test_h441_foreign_taint.py; existing test_nerva_cli.py,
test_h441_session_recap.py and test_chat_http.py. Additional focused tests may be
read/run freely; coordinate before editing. No subdelegation or commits.

Red-first verification: selector precedence/full table/archived/ambiguity/failure;
-c/-r/exact exclusion, no terminal reads, stdout contracts and no chat on refusal;
real source-schema fixtures and safe files; import replay/content change/readback
and crash recovery; durable provenance after restart/continuation/rewind;
ordinary/shared/stream/compressed/auxiliary prompt DATA framing; corrupted lineage
refusal; actual Action Kernel escalation on foreign-derived history; guest denial
for explicit/default/active reads and no title enumeration; native compatibility.
No personal foreign files, paid calls or claimed native OS acceptance.

## Integration, rollback and evidence

At most four active agents including root: two implementers and optional narrow
gpt-6-luna/medium read-only reviewer, no subdelegation. Root owns interfaces and
critical review. H398 and H441 have disjoint file ownership and separate source
commits/rollback units; no invented shared changes. Root reviews any changed
contract that was already counted before refreshing only its previously current
pins. Never mass-rehash stale evidence or modify frozen inventory.

Run meaningful focused red/green proofs, relevant integration and one serial
backend milestone once sources are frozen. New API routes require route/OpenAPI
checks plus explicit mobile/HUD gaps. No frontend behavior is claimed from CLI
work; run frontend checks if its source changes. Rebuild/restart actual app for
an isolated smoke with synthetic state. Revert a source unit with its assessment
and docs to roll back; never rollback user state or unrelated working trees.

Next action: continue H002 attributable CLI usage reporting in a new local batch.
No remote publication is authorized.
Partial implementation never earns a completed-contract count.

## Scope refinements during implementation

Root authorized H441 ownership of agents/core/llm/vision_turn.py,
autonomy/reflection.py, learning/background_review.py and session_archive.py
if needed. These are real raw-history consumers/lifecycle paths. Imported or
derived history must not be promoted by reflection/review into trusted persistent
facts merely because the input was DATA-framed. A bounded omission/refusal is
acceptable until such promotion preserves provenance end to end. Recent todo
lists and active memory clearing also need the conditional privacy guard.

H130/H135 are separately being re-reviewed against the full frozen clauses;
source audit finds no gap, but there is no count credit before current checks.
Focused frontend 54 and native-component harness 39 pass (jsdom, not a native
GUI). Browser checks use the clean batch03 source head bb7064fc with the same
built HUD, while H441 sources are edited in batch04; final web.py integration
must be rechecked before refreshing the H130/H135 evidence.

## H667 bounded repair owned by root

Whole-contract review found that the existing exec cache resolver omitted the
frozen TMPDIR/TMP/TEMP fallback sequence. Root owns agents/core/exec_cache.py and
new tests/test_h667_standard_temp.py for this independent rollback unit. Keep
explicit JARVIS_EXEC_TEMP_DIR then explicit owner security.sandbox_temp_dir
precedence; then use TMPDIR, TMP, TEMP in order before managed cache. Blank or
syntactically invalid paths skip with the existing warning behavior. A chosen
absolute path which cannot be created retains the existing emergency system-temp
fallback/warning. Environment-selected roots remain unmanaged unless they are
identically the managed cache; no widening of prune ownership. No task-ID naming
change (the frozen rationale waives it while mkdtemp remains collision-safe).

Red-first tests cover ordered precedence, invalid/blank variables, managed alias,
actual sandbox directory creation from process env and exclusion from owned-cache
pruning. Run existing exec-cache, review, backup/retention and child-env cases.
H666 is separately source-reviewed; targeted checklist/mission tree regressions
are needed before its old stale equivalent verdict can count again.

H667 also updates only the sandbox_temp_dir label in settings_db.py so the HUD
correctly describes standard environment fallback. Its behavior is unchanged.

## Current verification and independent review

H667 source commit `58472345`: the new standard-temp cases first reproduced eight
failures (two existing behaviors already passed). The final seven-module selection
passes 213 cases, including actual sandbox creation, backup/retention and child
environment behavior. Independent read-only review found no remaining frozen
contract gap. The settings label change is descriptive only.

H398 source commit `2daaff71`: the final six-module selection passes 155 cases,
with a further test-only addition passing all 40 H398 cases. Critical review
reproduced a trust-boundary defect: an external handler's `ok:false` and arbitrary
payload could be mistaken for a local refusal. A shared exact native-refusal
schema now preserves DATA fencing and advisory risk for such external payloads.
Production ToolRPC web-extract/execute-code integrations, spill/deduplication,
compaction failure and sidecar identity pruning are covered. Scanner output is
native advisory metadata, never a new authority decision.

H130/H135: 63 focused backend cases pass on batch04. The H441 web.py delta only
adds chat access guards; prefix middleware, worker/manifest/HTML handling and
appearance registration are unchanged. Browser proof on frozen batch03 passes
16 base-path/proxy/PWA cases, six appearance cases and two font cases in actual
Chromium. Focused batch04 client checks pass 54 HUD and 39 native-component cases
(the latter use jsdom, not a native application). H666 focused backend passes
39 cases; focused HUD tree/mission checks pass 36. H441's CLI keeps the existing
defensive tree renderer. These are whole-contract re-reviews of stale evidence,
not claims that the prior implementation was absent.

Root owns `tests/test_h441_foreign_boundary_review.py`. Independent regressions
reproduced an imported append falsely succeeding after directory creation failed,
and a restored snapshot accepting a removed original-turn provenance marker.
The source owner repaired both and retained in-memory rollback on failure. The
same review covers suppression of foreign-derived turns from shared automatic
embedding: taint alone would not prevent their later recall by a guest. Imported
and derived sessions must be omitted from that shared recall until its records
carry enforceable owner scope.

Root assigned repair_1247 a disjoint test-only implementation lane in
`tests/test_h441_foreign_access_review.py`: actual API owner/guest boundaries,
native compatibility and kernel taint escalation. H441 source ownership remains
with review_1233. No source edits or duplicate writers are authorized in that
independent lane. Additional concrete parser checks cover real Codex
input_text/output_text and session_meta identity, duplicate event/response
representations, tool-only turns and descriptor-safe parent traversal.

All raw checks and bounded reports live under
`/workspace/scratch/hermes-697/batch04/`. H392 research is recorded separately in
`/workspace/scratch/hermes-697/batch04-h392-plan.json`; it has no implementation
or count credit in this batch. Its broad recovery design depends on trustworthy
physical-call accounting; H002 usage reporting is the next local implementation unit.

## Integrated milestone and compatibility repairs

H441 source commit: `8e1775bbb0638f9376a8436f53dabdcf715e6ede`.
The 16-module focused selection passed 236 cases; subsequent continuation and
parser changes passed their respective 86- and 20-case selections. Independent
root boundary/compaction and actual owner/guest/kernel selections passed six
cases each. Context compatibility passed 70; H277 selected-image compatibility
and access checks passed 46. Counts overlap and are not summed.

A disposable real FastAPI lifespan smoke exercised actual CLI import, ID resume,
free `/recap`, replay to the same imported session, unchanged shared default,
and guest denial on explicit/default/active reads. Synthetic transcripts only;
no model calls. Two startup network probes were blocked. Selected-image turns
on imported sessions deliberately refuse; normal native image turns retain their
behavior. Per-terminal breadcrumbs are waived by the frozen H441 rationale.

The frozen full backend run covered **25,760 cases**: **25,507 passed, 194 failed,
58 skipped and one expected failure**. All 5,688 captured repository inputs were
verified unchanged after completion. This full run was not green. Failures exposed
incomplete native-session fixtures, stale generated route/status documents, the
missing environment-override wording, and the changed unavailable-store error body
on archive/pin routes. Root restored the legacy 503 error/reason shape while
preserving owner 403 refusal, and restored the explicit environment precedence
label. Fixtures now provide real isolated checkpoint/session lineage; original
behavior and authorization assertions remain active.

Repair commit: `1b26e3037f9d4dbd05a7f6c11eccd23de9336570`. Clean focused runs
pass **825 cases**: 110 image, 361 HTTP, 195 plus 143 runtime, and 16 root cases.
Exact JUnit identities prove that **all 194 original failed cases passed**. The
root selection also adds a real encrypted backup/delete proof for a nonempty
foreign import receipt. A broader root selection passed 288 of 289 before its
remaining additive backup-schema expectation was repaired; the archive module
then passed all 73 existing cases, and the new receipt case passed separately.
No green full-run, live-provider, Fish, native Windows or native-device result is
claimed. Final collection has one additional backend test beyond the frozen run.

The two new owner routes are present in auth, route and OpenAPI snapshots; API
sweep documentation is regenerated. The HUD gate records their actual CLI callers.
Browser/mobile import pickers remain intentionally absent; shared session privacy
guards apply to those clients. Source and fixture collateral reviews preserve
existing partial gaps and refresh only previously current, reviewed pins.

Verification artifacts: `backend-inputs.json`, `backend-inputs-verification.json`,
`backend-full.xml`, `backend-failures.json`, `backend-validation.json`, the three
`compat-*` directories, H441/H398/H667 reports, browser reports, and scoped
collateral reports under `/workspace/scratch/hermes-697/batch04/`.

The final ledger update contains six whole-contract reviews (H130, H135, H398,
H441, H666, H667) and 44 bounded collateral rows. It covers all 106 previously
current changed pins across 47 rows; 264 already-stale changed pins remain
untouched. No unresolved moved-line citation remains. The source collection now
contains **25,761 backend cases**, 624 routes and 18 agents. Frontend 2,177 and
mobile 359 are existing counts; focused/browser proof is listed above, not a
fresh full frontend/mobile run. All work remains local.
