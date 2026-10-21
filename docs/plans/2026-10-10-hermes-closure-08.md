# Hermes full-contract closure — batch 08

Generated 2026-10-10 UTC. Goal: close frozen H456, scheduled tool bounds and
per-job reasoning, through the existing runtime and authoring surfaces. Base and
initial head: `9febf8ad52a47f691ac46719c6d25f1647680949` (150/697 accepted).
Branch: `codex/hermes-closure-08-20261010`. Final source head: `8064ed8284a8434e13a4b7adb112ceee19981ce8`.
Next action: continue H067 in isolated batch09.
No whole-contract credit before review and integrated verification. Local only.

## Donor and native adaptation

Frozen donor `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`, MIT. Root inspected
`cron/scheduler.py:445-535` and `cron/jobs.py:1683-1702`; scheduler SHA256
`4f6d86815d38b683c0f1b64e9b0c444ae5654eabb1c006a4375f9387d9c57ab5`
matches the existing reference. Source and license are cached under
`/workspace/scratch/hermes-697/donor-59b2aeef6c7a/`. Reuse the precedence,
mandatory exclusions and model-independent effort selection, adapting them to
Nerva's strict settings store, installed catalog, closed-lifetime scopes and
existing transport clamps. Do not copy donor MCP unions, permissive spelling,
approval bypasses or a second scheduler. No new effects or kernel grants.

## Settled tool policy

New settings: `llm.platform_toolsets` JSON defaults to `{}`, accepting only an
optional `cron` list of distinct known group IDs; `agents.disabled_toolsets`
tags defaults to `[]`, accepting distinct known group IDs; and
`autonomy.allow_agent_scheduling` defaults to false and requires an actual bool.
The disabled group setting is an operator restriction on scheduled model work.
Validate both owner writes and stored runtime values. Runtime reads one strict,
coherent snapshot; an unreadable/malformed policy must fail the model phase,
never widen through recovered last-good or permissive default data. A readable
legacy store missing these new rows uses their declared defaults. Doctor reads
without creating/reseeding state and reports unavailable policy truthfully.

Precedence: explicit non-null `enabled_toolsets` (including `[]`), then an
explicit cron setting (including `[]`), then all currently registered names.
Expand groups and subtract operator-disabled members. Always remove literal
`clarify` and `messaging`; remove `cronjob` unless the scheduling flag is true.
That toggle lifts only loop prevention, never authorization. Always return a
finite frozenset, including legacy defaults, and intersect through the existing
scope at offer/runtime/RPC boundaries. An unavailable selected allow-group
refuses; an operator deny-group may contain currently unregistered members.

Keep basic/files/terminal/video unchanged. Add curated exact groups:
web=(web_search,web_extract), recall=(session_search,search_memory),
code=(execute_code), skills=(skills_list,skill_view,skill_propose),
planning=(desktop_plan,operator_plan), desktop=(desktop_run),
osint=(osint_enrich), image=(image_generate), voice=(speak), notes=(memory),
checklist=(todo), canvas=(canvas_point), cronjob=(cronjob).
Confirm each native spelling against registration; optional absent groups remain
unavailable. No dynamic prefix expansion or new tool registration. Mandatory
interactive tools remain outside selectable groups. Catalog selection is an
upper bound; posture, agent patterns and signed effect approvals still narrow it.

## Settled reasoning and surfaces

`options.reasoning_effort` accepts only an exact string from the existing LADDER:
none/minimal/low/medium/high/xhigh/max/ultra. Missing inherits current defaults;
null, empty, bool and aliases reject. Only model-bearing ask actions may use it.
Store validation checks spelling, not the model currently loaded. Wrap the entire
scheduled model phase in the existing closed-lifetime reasoning scope plus a
job-only required marker. A nested absent scope must not clear an inherited
required marker or evade revocation. Backend defaults must never be mutated.

Cloud transports keep their current model clamp, unsupported/undeclared omission
and below-minimum refusal semantics. Vocabulary overrides remain capabilities,
not preferences. Do not claim a universal cost ceiling on undeclared models.
LM Studio and Ollama currently have no verified effort wire control: an explicit
job pin must refuse before text/tool/stream generation HTTP, including prepared
routes, fallback and retries. No-pin local work retains its existing behavior.
Typed refusal must survive generic degradation handlers. No new local model wire
knob or stronger global cloud policy is part of this unit.

CLI create/edit `--reasoning-effort` accepts a rung or `default` (delete key),
folded into explicitly supplied full `--options`, matching the existing toolset
replacement contract. No implicit GET/replace race or new API route. The shared
HUD OptionsEditor gains an exact-rung/default select; default deletes the key,
never sends null/empty. Keep the model-only limitation visible and prevent a
contradictory skip-model configuration. Existing settings UI can author validated
JSON/tags/toggle values without a new settings component.

Doctor retains `toolset_upper_bound`, reports source job/cron/legacy and removed
members, requested effort and strict policy errors, and updates its supported
options/catalog text. It never promises grants or effective offers beyond the
later posture/profile gates. API options validation remains the store authority.

## Ownership, proof and rollback

Core: repair_1247 (gpt-6-sol/high), `job_toolsets.py`, `settings_db.py`,
`autonomy/jobs.py`, `autonomy/jobs_health.py`, `llm/request_context.py`,
`llm/base.py`, new H456 policy/reasoning tests and existing affected core tests.
Surface: review_1233 (gpt-6-sol/high), `cli/nerva.py`, frontend job-builder/jobs
and focused frontend tests, a separate new CLI/API test module. Do not edit
`tests/test_job_toolsets.py` from the surface lane. Root owns plan, documentation,
generated status/parity, critical integration and whole/collateral evidence.
Optional gpt-6-luna/medium reviewer is read-only. No subdelegation; one writer per
file, no push/remote merge/deployment/provider calls/personal data.

Red-first acceptance: actual ungated clarify offer is removed and hallucinated
RPC is refused before preflight; explicit job/cron/legacy precedence and empty
lists; operator deny intersection; live registration and injected future
messaging/cronjob names; unavailable groups and unreadable/corrupt policy; nested,
concurrent and closed scopes. Reasoning tests cover store/API boundaries, real
scheduled cloud request payloads, weaker clamp, no default mutation, local zero
generation HTTP for explicit pins and successful no-pin calls, prepared routes,
fallback, tool loops and expired child/retry dispatch. CLI/HUD tests exercise
creation/edit/clearing and preserve unrelated options. Run affected backend and
frontend selections, typecheck/build, an actual disposable offline product smoke,
then one frozen full backend integration milestone for these common boundaries.
Report overlaps and external-runtime limits accurately. Rollback is one local
scheduled-policy feature unit; existing jobs and settings remain readable.

## Implementation and focused review

The core and authoring paths implement the settled contracts. The core selection
passes 208 tests, including real runner-to-cloud MockTransport payloads and all
local generation modes refusing explicit job pins before HTTP. CLI/API checks
pass 3 new and 106 existing cases; the changed HUD selection passes 26 cases.
TypeScript, production build and Ruff pass. Red-first core/API/HUD failures were
observed; only artifacts actually saved are claimed in the scratch reports.

Root's additional regression runs a real local Python interpreter and real nested
ToolRPC: with files/web disabled, both nested calls refuse while echo succeeds.
It fails against batch07 and passes here. Its existing sandbox fixture supplies
a test isolation-authorizer shim; this is not proof of Docker/WASM isolation or
a native owner-host execution. Read-only surface, core and transitive reviews
found no blocker; root reviewed the authority scopes and transport guards.

A disposable actual CLI → FastAPI lifespan → job runner → orchestrator smoke
passes cron defaults, operator denial, explicit empty groups, legacy mandatory
exclusions, local reasoning refusal and clearing, owner auth and invalid input.
Four generation responses came from offline HTTP MockTransport; two unrelated
startup network probes were blocked. Temporary state was deleted. The existing
30-second settings refresh was called synchronously. A pre-existing startup-order
bug leaves clarify unregistered even when enabled; the smoke explicitly calls
its real registration helper after startup to exercise exclusion. This setup
limitation is preserved in `live-policy-smoke.json`; repair is a separate unit.

Built Jobs also passes a local Chromium check with a static fixture server and
mocked API: saved effort, default deletion, custom creation, skip-model clearing,
and hard reload. Fourteen hashed asset responses had no failures; no page errors.
This verifies the built UI, not live backend effects. Eight route/OpenAPI/typegen
guards pass; routes remain 629.

Artifacts: `/workspace/scratch/hermes-697/batch08/`. The full frontend suite passes all 2,181 tests;
backend collection is 25,935, mobile count 359 is reused because its tests are unchanged.
The frozen backend milestone is pending; no new whole-contract credit is recorded yet.

## Integration milestone and acceptance

Frozen source `16bfdc1282554ada805968383ced004046173b2c` completed all 25,935
backend cases: 25,875 passed, one failed and 59 skipped/xfail. All 5,715 tracked
and nonignored input files were verified unchanged before any repair. The sole
failure was an existing approval test whose 40ms deadline could expire before
durable delivery acknowledgment. Its fixture now waits for the actual receipt,
then advances only that request module's clock beyond the recorded deadline.
Production code and original assertions are unchanged. The original failed node
and all 46 adjacent owner-once cases pass at final source 8064ed82. This is a
completed full run with focused repair evidence, not a green full-run claim.

backend-validation.json binds the original XML, frozen-input verification and
repair/focused.xml. Root reviewed the timing correction and both core/surface
reviews. Whole H456 is accepted; 60 previously-current changed evidence pins
were reviewed and refreshed, while 122 already-stale pins remain untouched.
H146/H449 record the implemented code group/transitive bound, and H620 records
reasoning progress, with all their wider remaining clauses left open. The frozen
697-row inventory and raw digest remain unchanged.

The guarded assessment advances from 150 to **151/697 complete (21.7%)**:
151 equivalent, 228 partial, 56 missing, zero excluded, 262 needing review;
546 unfinished. Current test counts: backend 25,935, frontend 2,181 (fresh full
pass), mobile 359 (unchanged tests, reused count); 629 routes and 18 agents.
The code, built UI, browser and actual offline product checks are recorded above.
All 86 final metadata cases pass after adding explicit source citations to the
renewed H456 review; Hermes/status synchronization and whitespace checks pass.
The initial missing-citation metadata failure is preserved in scratch artifacts.
Everything is local;
no push, remote merge, live-account/provider action or deployment occurred.
