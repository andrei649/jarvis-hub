# Hermes campaign — cumulative implementation handoff

## Active continuation — 2026-11-12

Owner-requested local work has resumed above PR #1359 head
`686fcbf4f25ebfbb416b3a35dff29045163cffbd`, on
`codex/hermes-continuation-20261112`. See the current cumulative
[implementation checkpoint](evidence/2026-11-12-local-continuation.md) for scope,
changed paths, tests, limits and next actions. No external schedule was resumed.
The November 4 pause and counts below are preserved as history, not current
checkout state. November 10's feature-area acceptance suites now govern evidence;
the old per-file restamping workflow is retired. No inventory rows are removed
and no completion is inferred from historical CI or test counts.

Updated: 2026-11-04T09:30:00Z. Application root: `jarvis-hub/` under
`/Users/andrei649/Documents/Nerva`. Working branch: `security/open-read-projections`.
Starting HEAD: `446cc7cb626d5b2a2093b15c377733cb313bb6b3`; initially clean.
Observed main: `07b045d8af3bee4064fee0fc625bbfd9fcd40e58` after fetch.

**PAUSED by owner on 2026-11-04.** The owner authorized committing and uploading
the existing development checkpoint to draft PR #1341, then stopping. This is
checkpoint publication, with no ready/merge/deploy authorization. Resume only
after a new owner request, using
[`../handoff/hermes-2026-11-04/CONTINUE.md`](../handoff/hermes-2026-11-04/CONTINUE.md).
No scheduler was resumed.

H655, H022, H334 and H492 have complete local delivery receipts. H492's earlier
frozen backend passed 31,594 cases with 119 existing skips and zero failures/errors;
its exact source/input/count checks passed. That result predates H027. H027's
complete seventeen-operation implementation and focused review are saved, but
its ledger review and full backend gate are unfinished. Recorded verdicts remain
152 equivalent, 432 partial and 113 missing; H027 receives no new credit at this
pause. Current edited evidence still requires impact review. Main, CI, live and
native acceptance must be reported independently.

## Current authority and implementation plan

The owner's 2026-11-04 request authorizes local implementation, instruction/schema
repairs, tests and necessary fixes. Do not stage, commit, push, merge, deploy,
activate providers, incur costs, change global configuration or external schedules.
The full frozen 697-capability inventory remains accepted; partial contracts earn
no completion credit. Earlier publication authorization does not apply to this work.

1. Finish the current Usage/catalog/privacy integration checkpoint: preserve its
   source and receipts, diagnose any real failure, and record the interrupted full
   run as incomplete. Establish separate timestamped main/working counts via tools.
2. Make `autonomous-development-objective.md` the canonical execution workflow;
   redirect the other active entry points and local automation templates to it.
   Preserve dated history, paused schedules and existing security/delivery controls.
3. Separate recorded verdict, evidence impact/freshness and external acceptance in
   the status schema, commands, tests and generated reports. Migrate explicitly,
   retain prior receipts and provide rollback plus a no-new-credit reconciliation.
4. Reuse diff/citation analysis for impact decisions with reasons and executed
   checks. Unknown impact stays pending; changed hashes alone imply no regression.
5. Add a bounded, reproducible local preflight/smoke entry point using Python 3.12,
   dependency/configuration checks and actual product CLI/API paths. Report missing
   prerequisites and unexecuted gates without exposing credentials or runtime data.
6. Freeze and deliver a complete next contract batch from the current Hermes queue,
   reusing pinned donor code/tests and existing authorization paths. Verify the
   combined batch, update relevant parity/backlog/evidence, then continue the queue.

Ownership: coordinator owns shared interfaces, preflight and integration; at most
two implementation agents own disjoint accounting and instruction files. No child
agents. Focused regressions during work, broader integration at the milestone;
never disable/skip/xfail/relax a failing test. No unrelated enhancements.

Rollback: preserve the starting Git tree and pre-migration ledger bytes under the
local ignored cache; restore only this request's explicitly owned edits when
needed. Schema migration must also support restoring its original byte snapshot.

## Starting evidence and limits

Working CLI result at the timestamp above: 148 equivalent, 436 partial, 113 missing,
0 verification-stale rows under the old accounting; 697 total, 642 current reviews.
Main counts are pending a revision-aware tool query and are not inferred from this
branch. `scripts/ledger.py stats` confirms the immutable 697-row donor inventory.
`scripts/backlog.py counts` reports 39 open checkbox rows; this excludes other table
formats and is not a count of all remaining projects.

The previously started 31,515-case backend run has no completion receipt or JUnit
file and its log ends at 79%; no process remains. It is incomplete, not a pass or
an established functional regression. Earlier focused/UI results remain attached
to their original source revisions; a new source change does not refresh them.

Draft PR #1341 is historical publication of the starting checkpoint. This request
does not authorize changes to it. Native devices, live providers, frozen packages
and SEC-B6 independent post-merge/current-main acceptance remain distinct gates.

Next action: implement the status/impact contract and canonical workflow alongside
the bounded preflight, then close one selected complete Hermes batch.

Current integration verification: read-only GitHub inspection on 2026-11-04 found
all five PR workflows successful for `446cc7cb`: CI (`41697394090`), security,
lockfiles, self-development policy and H011 Windows native read primitives.
These are CI receipts for that published head, not local results for later edits,
native-device acceptance or authority to change the draft PR. No blocking failure
was found in the existing integration checkpoint; workflow implementation proceeds.

## Workflow repair checkpoint — 2026-11-04

Current main was queried through `hermes_status.py summary --ref origin/main`:
`07b045d8af3bee4064fee0fc625bbfd9fcd40e58`, 146 equivalent, 438 partial,
113 missing, zero stale evidence. Working source remains uncommitted above
`446cc7cb`: recorded verdicts 148 equivalent, 436 partial, 113 missing. One
partial row's documentation evidence needs impact review; this is not a new
functional regression. These observations were captured during 02:16–02:30 UTC.
H220/H696 are existing local/draft work, not newly completed in this repair.

The canonical instructions and local prompt templates now follow the current
local-only campaign. Dated drivers/queues remain explicitly inactive history;
the paused routine was not activated and external schedulers were not changed.

The new `scripts/development_preflight.py --frontend --smoke --json` exercised
the actual CLI help and isolated Orchestrator/readyz/chat smoke. Eleven prerequisite
checks passed, including active Python 3.12 venv, applicable installed lock
versions, dependency consistency, process front-door/hardening configuration,
Node 22 and frontend tools. Unit/smoke regressions passed 14 cases. Secret output,
wrong-venv false acceptance, missing hardened audit key and JSON notice pollution
have focused regressions. Persisted private configuration, full suites, live
providers, native devices and upstream Hermes runtime are explicitly unexecuted.

Accounting v3 is applied: recorded verdicts, freshness/impact and scoped external
acceptance are separate. The explicit migration preserved all 697 IDs and the
exact 148 credited-ID set, with no new functionality or completion credit.
Original assessment SHA-256:
`1cb248f94173ba19fe5b98840566ba8fdb1e2aa72ef1c4fc217d999f7afc94e9`;
migrated SHA-256:
`dc5c81a39e6a81ab5694957084c3f434c865aeb2cd6888a5336cbd77cbbc7f89`.
Exact rollback input is `.git/codex-local/workflow-20261104/assessment-v2.json`;
`hermes_restamp.py rollback-migration` requires that backup and the expected
migrated digest, and refuses later changed records. Preserve newer receipts
before any later rollback. Migration/reconciliation artifacts are in that same
local cache directory. The initial complete 241-case workflow integration passed
with no failures/errors/skips, including regenerated-report sync; its result is
in the execution transcript. A later rerun replaced its original log/JUnit paths;
those paths must not be cited as the original run's receipt. Preserve distinct
artifact filenames for subsequent checks.
Impact receipts use reviewed source/dependency paths, not the whole worktree;
unrelated edits must not stale them, while missing or changed dependencies do.
The changed-path map selects affected contracts and exposes unmapped paths as
unknown; it grants no completion credit. No files are staged or committed.

## Frozen next capability batch — H022

User behavior: `nerva security` and `nerva security audit` enumerate the current
install's auditable Python distributions, declared plugin/extension Python pins,
and pinned npx/uvx MCP packages. They query OSV, report findings ordered by
severity, and return nonzero for the selected `--fail-on` threshold. This is the
complete frozen H022 contract, not a new inventory or a weighted partial.

Required clauses and adaptations:

- Default audit covers all three surfaces; explicit skip flags disclose their
  omissions. Parse declared exact pins without executing plugin/MCP packages.
  Unsupported/unpinned/corrupt metadata is named coverage uncertainty, never a
  fabricated clean component. Preserve the existing stricter default threshold
  and conservative unknown severity handling; do not loosen audit tests.
- Add minimal digest-bound descriptor-pin metadata where Nerva currently keeps
  only consent digests. Registration/catalog recording is not provider activation;
  store no credentials or full private descriptor bodies. Preserve existing
  registration, consent, disable and removal semantics.
- OSV calls use the shared HTTP choke point, durable egress record and actual
  `plugin.egress` authority. An authenticated admin hub audit route supplies the
  existing kernel binding; CLI requests do not fall back around refusals.
  Unavailable hub/network yields a named offline/incomplete result. Installation
  is never coupled to this optional audit. No live install is modified for tests.
- Use the pinned donor's parsing and CLI patterns, retaining its MIT attribution:
  `hermes-source-59b2aeef6c7a/.../hermes_cli/security_audit.py` and
  `hermes_cli/subcommands/security.py`, commit
  `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.

Owned product paths: `agents/core/security/dep_audit.py`, `agents/cli/nerva.py`,
`agents/core/routers/security.py`, new
`agents/core/extensions/manifest_catalog.py`, narrow extension registration
hooks and the shared consent-store declaration path, and focused audit/CLI/catalog/route tests. Coordinator owns generated
snapshots/types, parity/backlog/ledger integration and this cumulative handoff.

Acceptance: actual CLI default/explicit/offline/skip/threshold behavior; all
three inventory surfaces including malformed/unknown pins; sorted findings;
real admin guard and kernel denial before HTTP; isolated granted route through
the shared client and persisted egress; catalog registration/removal invariants.
Run focused regressions then combined integration/release gates. Required live
network/host proofs remain separate scoped acceptance, not inferred from fixtures.

Prerequisites: network audit needs the authenticated governed hub and OSV access;
offline inventory does not. No paid account or MCP runtime execution is needed.
Rollback is the batch-owned code delta and its metadata; preserve private catalog
data rather than deleting it. Start product edits after the workflow core passes.

## Frozen workflow capability batch — H655

The frozen read-only contributor contract requires all four clauses: architecture
entry/core/subsystem/directory/data-flow overview; subsystem → source directories
→ doc-to-read ownership map; current contributor setup/style/cross-platform/
security/PR guidance; loadable repository-local `.agents/checks/*.md` checklists.
The existing architecture overview already supplies the first clause. Implement
the other three through `CONTRIBUTING.md`, `docs/CODEBASE_OWNERSHIP.md` and those
checklists, referencing the canonical workflow and verified preflight. This is
the remaining concrete workflow contract, not credit for documentation volume.
No blind restamp or promotion is authorized by the evidence hash change alone.

H655 and H022 implementation ownership is disjoint. The workflow core passed
before product coding began. Their source and rollback units remain distinct;
combined release/integration checks follow their focused acceptance checks.

## H655 delivery checkpoint — 2026-11-04

H655 now completes all four frozen contributor-workflow clauses. The architecture
and subsystem/source/doc map, current setup/security/platform/process guidance and
loadable local review checklists are implemented and independently reviewed. The
actual bounded frontend/smoke preflight passed eleven checks. Its full review is
recorded with an explicit uncommitted-source receipt; the previous partial review
and hashes remain in history. A real delivery finding in the receipt tool was
fixed: explicitly declared new public Markdown guides can be bound without staging;
ignored, private, runtime and symlink paths remain refused. Seven focused positive
and refusal cases passed. No staging or publication was needed.

Recorded implementation is now 149 equivalent, 435 partial, 113 missing. During
H022 edits, 137 evidence rows became impact-pending (the compatibility view shows
99 current equivalent, 351 partial, 110 missing, 137 needs-review). These changed
hashes do not establish 137 regressions, and the 149 recorded verdicts are not
presented as freshly verified. Review the actual H022 diff/dependencies after its
source freezes, retaining unknown impact. Main remains the separately observed
146/438/113 result at `07b045d8`; working HEAD remains `446cc7cb` plus local changes.
No H655 runtime/platform/provider receipt is required by this read-only repository
contract; unrecorded acceptance must not be confused with a passed live check.

The complete current backend suite has not yet run for these new bytes. The
241-case workflow result predates the seven new receipt cases and H022 edits;
combined integration checks are still required. H022 is the active executable
batch; its two writers own disjoint audit/CLI/route and descriptor-catalog paths.
The 248-case rerun during H022 passed 247 and failed one unchanged real-ledger
expectation: H566's effective partial state is impact-pending after shared CLI
edits. Do not weaken the assertion; complete its impact review after source freeze
and rerun. This is not a demonstrated functional regression. The complete failed
receipt is `workflow-during-H022-junit.xml` with its corresponding log in the
local cache. No skip or xfail was introduced.

The H022 inventory review found that activation-only metadata would miss owner
declarations for never-activated extensions. Existing acquired packages are
signed stdlib-only artifacts and carry no Python dependency vector; descriptors
enter through the shared CLI/HTTP consent and activation paths. The catalog writer
is therefore extending the existing consent-store path to retain declared pins
before activation, without treating consent as installation or new authority.
Legacy missing descriptors must stay an explicit prerequisite to re-register the
exact declaration; no dependency vector is reconstructed from its old digest.
The two implementation threads use the existing Sol/high resource allocation;
the focused read-only v3 accounting review used Luna/medium and found no blocker.

H022 integration preparation: intentional route/auth/OpenAPI snapshots add only
the admin audit endpoint. The HUD/mobile ledgers and parity gate classify it as a
host-CLI inventory bridge, not a native-package audit or a missing browser panel.
All 93 combined route/OpenAPI/typegen/HUD/auth/action parity cases passed, with
no failures/errors/skips (`H022-parity-junit.xml`). The npm typegen wrapper failed
in offline mode because registry metadata was not cached; running the already
installed, version-checked `openapi-typescript` 7.13.0 against a temporary loopback
schema-only server succeeded. No product lifespan or provider was started, and the
server was closed. Later validator/source changes still require a final schema
regeneration and the relevant final checks. Donor MIT bytes are retained beside
`dep_audit.py`. A focused independent route/transport review found no authority
blocker; this does not establish live OSV acceptance.

## H022 implementation checkpoint — 2026-11-04T04:00Z

Newly complete: H022. Bare/default and explicit CLI audit cover the invoking
interpreter's distributions, managed owner-declared/registered extension pins
and exact pinned npx/uvx MCP packages. Common repeated package-valued options are
resolved before the launched program; a red regression caught program arguments
replacing the real package identity and now passes. Catalog persistence happens
before consent durability and before runtime exposure, with no new installation
or activation authority. Corrupt/legacy/unsupported metadata stays unavailable;
offline/incomplete results retain known findings and never claim a clean audit.

The real CLI → HubClient serialization/admin credential → FastAPI validation →
bound Action Kernel → shared HTTP transport path passes with a synthetic OSV wire.
A known advisory returns exit 1, then a real owner halt returns 5 before another
HTTP call. A separate reopened egress-store reader sees two allowed and one blocked
attempt under strict egress with the optional global kernel flag off. Focused
independent authority and frozen-contract reviews found no remaining code blocker.
The theoretical unknown descriptor never supplied to Nerva is not a declared
component: signed acquired artifacts are stdlib-only and have no separate external
pin source. This does not close H566/H356 installation or discovery requirements.

The 14 affected behavioral reviews were rewritten from source with old receipts
retained; only H022 changes verdict. Recorded implementation is 150 equivalent,
434 partial, 113 missing. H655 is the other newly completed ID in this campaign.
No ID has a demonstrated functional regression. Another 116 rows have explicit
moved/unrelated impact decisions based on unchanged citations, the exact diff and
function AST comparison, not blind hash replacement. Their recording is underway.
Sixteen historical reviews with no resolvable citations remain visibly unknown:
H015, H044, H049, H057, H064, H079, H199, H350, H413, H454, H480, H483, H620,
H666, H682 and H684. Their recorded verdicts remain preserved.

Checks actually run: combined CLI/audit/extension suite 300 passed; after the
argv-boundary fix, audit plus entrypoint 45 passed; route/OpenAPI/type/HUD/auth/
action parity 93 passed. Frontend TypeScript, all 2,803 Vitest cases and production
build passed. The final bounded preflight passed with eleven checks. The final
request-validator schema was regenerated afterward, so the TypeScript check must
be repeated for that final generated input; tests/build do not execute erased type
declarations. Ruff passed. Bandit found only new flag-string/read-only Git false
positives: flag variables were renamed and fixed, shell-free Git sites were reviewed
and annotated; its full unchanged-baseline scan now passes. No test assertion was
relaxed, skipped or xfailed. The complete current backend suite is still pending.

Production preparation is for HEAD `446cc7cb` plus the explicit local source
manifests, not main or a new published revision. Supported development checks ran
on non-root macOS Python 3.12/Node 22. Required current full-backend and final
generated/type/status gates, Windows/Linux/native acceptance and live OSV on the
intended authenticated host remain distinct. Upstream Hermes runtime availability
is untested and supplies no native Nerva credit. Rollback: revert only this batch's
owned source delta, preserve the private declaration catalog and receipt history,
and use the explicit migration backup/guard for schema rollback. Nothing is staged,
committed, pushed, merged or deployed. H334 is the next executable product contract
after this integration gate; unknown evidence rows remain a separate bounded task.

## Combined integration run — 2026-11-04T04:30Z

The final source and assessment are frozen while the full backend suite runs.
Exec session `53583` owns the non-root four-worker run with the existing 90-second
per-test timeout; do not start a second run or change source/assessment underneath
it. Terminal status is written to `backend-full-run.json`; full log/JUnit are
`backend-full.log` / `backend-full-junit.xml` in the local workflow cache. It is
running, not passed. The tracked count is 31,605 collected, not a passing-test claim.

The 116 reviewed impact decisions completed with no refusal. The status-count
refresh touched only generated counts/base stamps in README/STATUS/NERVA and
project status. Two partial rows (H011/H063) were explicitly reviewed for those
physical citation edits, preserving their functional limitations and exact old
reviews; no completion credit changed. Final status write/check and fast status
sync check pass. Recorded counts remain 150 equivalent / 434 partial / 113 missing;
the conservative view is 143 equivalent / 425 partial / 113 missing / 16 pending.
No functional verdict was reopened. The sixteen pending IDs remain listed above.
The general status generator's legacy commit stamp denotes observed main/base;
collected local counts do not turn it into CI proof for the local source.

H022's explicit runtime receipt verifies isolated macOS CLI/API/kernel/egress
composition with synthetic OSV, bound to final source and the 47-case result.
Separate scopes require the current complete backend, real OSV on the intended
authenticated/no-transparent-proxy host, and native Windows/Linux CLI acceptance.
No scope is cleared by a different environment's result. Quoted Windows .cmd/.exe
launcher strings now have red-to-green parser tests; native Windows remains pending.

Both previously failing unchanged regressions pass after impact review/metadata
freeze, including the real-repo read-only assertion. The batch impact reader now
shares one load/history; the new explicit batch acceptance command validates every
manual decision and writes atomically, preserving prior receipts and refusing an
entire group for any unknown/missing/relevant or changed-source entry. Twelve
focused atomic-writer cases pass. The agent's earlier full-module attempt had one
concurrency failure while our ledger writer was active; no assertion was relaxed,
skipped or xfailed. The upcoming complete run includes that module unchanged.

Final generated TypeScript and Ruff pass. The unchanged-baseline full Bandit scan
passes, with a final changed-sites scan after the portable parser/batch-tool edits.
The graph was rebuilt locally after source freeze. Its prior broad whitelist had
included vendored kanban source; the new explicit scope excludes all three upstream
trees, generated API types, dependencies and private/runtime-data paths. Inspection
of the active graph confirms zero excluded paths across 3,049 source paths; the new
audit/catalog/evidence-tool symbols are present. No deep/paid pass, hook/init,
instruction-file rewrite or global setting was performed; caches remain ignored.

After this full run, verify its exact result against the tracked backend count,
complete only its matching acceptance scope if it passed, refresh generated reports
after that metadata write, and continue H334. Preserve the current pending source,
provider and platform limits; the 697-contract objective is unfinished.

## Full-run findings and retry — 2026-11-04T05:00Z

The first complete run finished with 31,483 passed, 3 failed, 119 existing skips
(31,605 collected; zero errors; 911.482 seconds). Its original log, JUnit and
`backend-full-run.json` are preserved. The 62-file source snapshot/manifest is
`backend-source-manifest.json`, fingerprint
`bf1f206631c754d0601bd473e1b7bf4e14db0dc8ccded525df1089e26aa5daa4`.
An after-run check confirmed its source bytes, HEAD and assessment input unchanged
before fixes. Large records were excluded from direct backup reads; the assessment
digest came from the authorized status CLI.

One failure was the encoding gate matching the new Git-tree helper's custom
`read_text` name as if it were Path text I/O. Its implementation already decoded
UTF-8 explicitly. The internal helper/callers are now named `read_utf8`; the gate
and every assertion remain intact. The complete restamp plus encoding suite passes
179 cases, and the status/impact reader suite passes 60, with no skips/failures.

Two OCR frame probes reached the 0.3-second document deadline before processing
their page-start frame. The original fixture passes in isolation; the full log
does not isolate interpreter startup from scheduling delay. The fixture now uses
a fixed native printf/sleep child through the real owned spawn/session/pipe/kill/
reap path. The page deadline is still 0.03 seconds, the document deadline still
0.3 seconds, and exact codes plus the page-deadline assertion are unchanged.
Production extraction code and its separate shell=False/global-deadline tests
were not changed. Four-worker targeted checks pass 7 cases; the affected OCR/
extraction/Windows suites pass 177 with 6 existing skips. Independent review of
the actual diff found no weakened boundary. No skip/xfail mark or timeout increase
was added. H444/H536 retained their partial verdicts via two explicit reviewed
decisions applied with the new atomic batch command; their format/OCR/platform
gaps remain open. No functional verdict was reopened or new credit gained.

The updated graph was checked/rebuilt using the same safe local exclusions;
Ruff, full unchanged-baseline Bandit, generated Hermes checks and fast project
status checks pass. Frontend sources are unchanged from their passing suite/build.

Retry two is active on frozen source fingerprint
`a5b6eef352232a7895bc6ef3c716ef45ea0c9fcb0e1b938ecd5801de8e4acd50`,
captured before launch in `backend-source-manifest-2.json` with an exact local
source snapshot. Session `90037` owns the same four-worker/non-root/90-second
command. Its distinct artifacts are `backend-full-run-2.json`,
`backend-full-2.log` and `backend-full-2-junit.xml`. Do not overwrite either run's
receipt or call the retry passed before its terminal result. The matching full
runtime acceptance scope remains pending; live OSV and native Windows/Linux
acceptance also remain pending. Finish this gate before coding H334.

H334 read-only preparation confirms the existing generic staged quarantine is
real (`reference_files={}` takes the staged branch). Fix only its actual mutable
refs/raw HTTP/request-time kernel gaps. Keep exact fingerprint-bound separate
owner approval, including when a kernel decision permits quarantined staging.
Do not infer that an unused direct-save branch is a production bypass.

## Integration accepted; next frozen batch — 2026-11-04T05:15Z

The complete retry passed: **31,486 passed, 119 existing skips, zero failures or
errors**, 31,605 collected, 869.833 seconds. The tracked backend count matches the
actual JUnit. The complete source path set and bytes, HEAD and assessment input
match the pre-run manifest exactly. The prior failed result remains preserved.
Only the matching macOS/Python 3.12 complete-backend acceptance scope was verified;
real OSV/no-transparent-proxy and native Windows/Linux scopes remain pending.
Post-acceptance Hermes report generation/check and fast project status check pass.
The acceptance/report refresh changes bookkeeping after that frozen result; it
does not claim that main or CI contains this uncommitted source. Recorded totals
are still 150 equivalent, 434 partial, 113 missing; sixteen old citation-impact
unknowns remain unresolved. H655/H022 are the two new functional deliveries here.

H334 is now selected, with its full original requirements unchanged: import from
an upstream project at an immutable verified pin; cross request-time `skill.install`
and shared SSRF-guarded egress; preserve the permanent separate owner-approval
floor; replace DEV_MODE-only admission with actual production governance. The
existing Hermes release v2 pin and staged quarantine already work and earn no new
credit. Generic GitHub/OpenClaw mutable refs/raw HTTP and the default-off remote
kernel gate are the concrete remaining implementation gaps.

Implementation/acceptance unit:

- Validate bounded repo/slug/path, immutable commit and per-file SHA-256 before
  I/O. Preserve legacy artifact formats through explicit pinned entry paths, and
  verified reference bytes where supplied; no mutable branch/tree fallback.
- Use the common DNS/IP/TLS/ledger client with a mandatory request-scoped egress
  callback. It must require a real bound kernel GRANT for every network request,
  independent of the optional global flag; missing context and denial fail closed.
- Bind install decisions to validated expected pin/provenance before fetch and
  recheck before staging. QUEUE/GRANT may stage only quarantined bytes; neither
  bypasses exact fingerprint-bound separate owner approval or activates code.
  No long-lived importer authority attribute may be mutated per request.
- Keep the real standalone CLI authorizer: it already calls kernel.authorize
  independently of the global flag and rereads the persisted kill switch before
  each local write. Do not refactor that correct path based on obsolete gaps.
- Wire the existing owner import UI/API for explicit generic pins; keep the
  ordinary pinned Hermes selection simple. Refuse missing/mutable pins visibly.
  Unused sync helpers need explicit pin/authority inputs rather than unsafe I/O.

Ownership proposal: two existing Sol/high implementation threads own importer/
pin helpers/tests and remote route/tests respectively; coordinator owns the
shared required-egress client, necessary existing audit adaptation, UI wiring,
metadata/parity and integration. Shared interface: immutable remote pin plus a
per-call server-created authorization context with install and egress callbacks;
JSON input never supplies authority. Freeze exact Python names with both writers
before edits. No child delegation or publication.

Checks: invalid/mutable pin/digest/redirect/SSRF refusal before effects; actual
admin and real kernel under flag0/1, kill/revocation between fetch and stage;
separate owner review even on GRANT; unchanged Hermes pinned import, local CLI,
quarantine/no-replace and UI flows. Run focused checks, related integrations and
the required milestone gates. Retain upstream licenses. No network/provider or
user-data import is activated for tests. Live intended-host upstream acceptance
is a later explicit scope.

Rollback: preserve the accepted local baseline and restore only the H334-owned
delta (HEAD for previously unchanged files, the saved local snapshot for shared
files already changed here); retain private quarantine/catalog/approval evidence.
External prerequisite for a generic real import is its operator-approved exact
commit/file digests and reachable governed upstream. Do not reduce the frozen
contract or invent credit when those are absent. The 697 objective remains active.


H334 integration is in progress. The required-egress shared client is implemented
and reused by the existing H022 audit, with no change to the legacy optional
client's semantics. Only an explicit None from its mandatory callback permits
I/O; missing callbacks, exceptions and other results refuse. Base manifest,
DNS/IP pinning, TLS and per-hop stream/redirect ledger checks remain intact.
The 176 related HTTP/audit regressions pass (no skips/errors/failures), including
the actual H022 CLI/API/kernel path. A focused independent source review found
no blocker. The H334 UI's 17 cases pass: no background import/probe, immutable
generic and reference pins, admin credentials, literal refusals, quarantine-only
success and rejection of an unexpected activation response. TypeScript and the
production build pass. Full UI and real H334 API/importer integration checks are
still running; no H334 completion verdict has been recorded.

The 190 generated source-catalog pages now describe current admin/kernel/network
admission without DEV_MODE; pin metadata and owner review requirements are
unchanged. The generator's six consistency tests and deterministic drift check
pass. This is guidance repair with no new functional credit. Prior full-backend
acceptance remains bound to its saved source manifest; shared HTTP/import edits
require the new integration/milestone checks before being reported as verified.


## H334 local implementation checkpoint — 2026-11-04T05:54Z

Newly complete functional contract: H334. The actual admin UI/API imports the
server-pinned Hermes catalog and explicitly pinned generic sources through
current installation and network authority, with digest/identity checks and
quarantine. Owner approval is still a separate exact-fingerprint step; grant and
queue do not activate code. Real API/importer/transport tests cover default-off
flags, inbound origin, owner halt between fetch and stage, safe-mode exclusion
and a persisted startup load-set. The standalone local migration CLI retains
its independent kernel/halt/hash check. The full frozen 697 inventory, licenses
and all prior receipts remain unchanged; H334 is the only newly credited ID
since H655/H022. No functional verdict was reopened in this batch.

Recorded counts: **151 equivalent, 433 partial, 113 missing**. Conservative view:
**144 equivalent, 424 partial, 113 missing, 16 impact-unknown**. The same sixteen
old citation gaps remain unresolved; no hash was accepted blindly. Thirty moved
or unrelated impact decisions and 25 scoped source reviews retained prior
verdicts except the implemented H334 promotion. The exact before/after credited
ID set is reconciled in the local cache: only H334 was added and none removed.
This bookkeeping/freshness restoration is not additional functional delivery.
Working HEAD remains `446cc7cb626d5b2a2093b15c377733cb313bb6b3` plus unstaged local
changes. The separately observed origin/main is `07b045d8` at 146/438/113;
publication, current-main CI and live production readiness are not implied.

Passed: 176 shared HTTP/audit regressions; frozen related skills/CLI/owner-review
integration 273 passed and one existing live-gated skip, with its source manifest
unchanged; final real route/shared-client/H022 entry seams 29/29 (including the
two additional safe-mode/persisted-load-set cases); full UI 2,803/2,803;
TypeScript, production asset build, Ruff, unchanged-baseline Bandit, catalog
drift/consistency and eleven-check isolated preflight. The first combined skills
run overlapped the last writer edit and returned seven refusals; that transient
receipt is retained separately, and the frozen rerun passed. No assertion,
timeout, skip or xfail was loosened. The production build includes the served
HUD assets; generated cache/vendor trees remain outside the graph.

The impact tool exposed a narrow accounting bug: an already tracked public root
`.env.example` receipt was rejected as private. The guard now permits only that
exact tracked template (or the requested committed-tree copy), keeps all other
`.env*` components private, and invalidates changed template bytes. Six real
throwaway-Git cases cover this; the red run also caught a nested-env refusal gap.
Independent review found no blocker. The broader accounting run passed its new
cases but failed the real generated-report freshness assertion while reports
were stale; regenerate/check and rerun without changing that assertion.

The entire backend milestone for these final bytes is pending next. Separate
structured acceptance records retain live OSV and upstream GitHub/intended-host
prerequisites, Windows/Linux execution and frozen distribution/native acceptance.
Synthetic HTTP, a macOS source test and upstream Hermes availability do not
establish those scopes. The full campaign remains active. H349 local usage
origin and owner lifecycle controls is the next shared-path batch under read-only
preparation; no next-batch product edits begin before this integration gate.


The final accounting regression exposed a real selected-root defect: default
arguments captured the original REPO, allowing summary to load one inventory
and assess another root. Both load and assess now resolve the root at call time;
the existing committed/working-tree test additionally asserts its exact temporary
inventory size. Its seven focused root/public-template/privacy cases pass. This
fix changes no capability verdict or acceptance scope. Full accounting rerun and
generated-report checks follow on quiescent metadata. Backend inventory is now
31,656 collected cases, separately from any passing count.

H349 preparation stopped before implementation/credit. The bounded frozen
ledger and pinned donor source show a served non-deduplicated skill_view bumps
both view and use, and the usage sync flag is consumed by the eligible opted-in
sync workflow. Nerva currently bumps view only (though views restart its stale
clock), and H345's real opted-in sync front door/transport remains absent. These
requirements are added back to H349's unfinished list; no inert flag or narrowed
contract earns equivalence. All historical usage data and prior review receipts
remain preserved. H492 is being checked as an independent finishable next batch.


Final focused accounting regression now passes **241/241**, after the selected-root
fix. The generated project count check is in sync at 31,656/2,803/363. The two
count-only document impacts were explicitly reviewed without promoting their
partial checkpoint/session contracts. H349's missing full-contract clauses are
recorded without changing its partial verdict. The next complete backend run is
source-frozen; no product or ledger edits may overlap it.


## H334 verification freeze and production boundary

At 2026-11-04T06:05:03Z the non-root Python 3.12 full backend milestone
started for HEAD `446cc7cb626d5b2a2093b15c377733cb313bb6b3` plus the 283-path
local source manifest. Its fingerprint is
`1c988c03c1b34d52ebb7b5428c8967c1187112f33e27365b6855de1ff4844efb`.
The local runner saves exact public source bytes/deletions, protected-record
input SHA through the approved status command, expected collected count 31,656,
full output and JUnit. It checks source path set/bytes, HEAD, assessment input
and count again on completion. Product, test and ledger files stay frozen
during this run; only this cumulative handoff may receive progress updates.
No successful full result exists for this fingerprint until that final check.

Supported local verification is macOS Python 3.12.14, non-root, with Node 22 for
TypeScript/UI/build. The backend child inherits the shell tool environment;
its receipt claims Python/macOS backend execution, not native Windows/Linux or
a provider. Required final checks are the full backend result/count/source
verification and unchanged Ruff/Bandit/report gates. Live authenticated OSV,
real governed upstream import on the intended host, native platform and frozen
distribution/device acceptance remain separate explicit prerequisites. Owner
release gates remain untouched. No CI for these uncommitted bytes, production
deployment, PR update or merge is authorized or established. The legacy general
project-status main/base hash is not CI evidence for local test counts; exact
working source provenance is the frozen manifest and status CLI source object.

If this batch must be rolled back, restore only its public source delta from the
accepted pre-H334 local snapshot (`backend-source-snapshot-2` for already-modified
files, HEAD for previously unchanged files), rebuild matching served assets,
and rerun the relevant gates. Keep private skill/quarantine/catalog state,
owner decisions and historical records. Do not reset/clean the checkout or replace
the current assessment with the old v2 backup: guarded migration rollback
correctly refuses after subsequent receipts, and restored source needs an
honest fresh impact decision. Nothing is staged or published.


H334 full milestone result, 2026-11-04T06:16:58Z: **31,533 passed, 4 failed,
119 existing skips, 0 errors**, 31,656 collected, 708.769 seconds. The exact
source path set/bytes, HEAD, assessment and count remained unchanged. This is a
valid failed receipt, not an interrupted or overlapped run. The four failures
are an old log-message source anchor for strict identity, an obsolete private
fetch helper fixture, a library call missing now-required authority, and four
raw-HTTP exceptions whose transports no longer exist. Repair the test setup to
exercise the real governed path while retaining identity/422/problem-clearing
assertions, and remove obsolete exemptions while leaving the no-bare-client
assertion intact. No test may be skipped, loosened or turned into an xfail.
H492 implementation stays gated on closing this full integration result.


The H334 full-run test repairs are frozen and independently reviewed. All 238
combined cases pass, without skips/errors/failures. The frontmatter check now
performs a real pinned synthetic fetch and refuses a fallback-only identity with
an empty install directory. H350b preserves 422 problem fields and later 404/old
problem clearing through the real pin/kernel/shared transport, additionally
proving one fetch and no write. The direct bad-name case tests both missing
authority and an explicitly authorized invalid slug. H381 removes four obsolete
bare-httpx exceptions while keeping every structural guard. Product code and
case count are unchanged; no assertion, timeout or skip/xfail policy was loosened.
Only H327/H381 test-evidence impacts were accepted with explicit reasons; no
functional credit or remaining clause changed. A fresh complete backend run must
now pass on its own saved manifest before H492 begins.


## Next frozen candidate H492 — implementation gated on H334 integration

Intended behavior: the owner can refuse websites through existing admin Settings;
URL-taking tools honor that policy before network activity. Cross-origin redirects
carry only safe headers, including after the HTTP library adds credentials. The
full frozen contract is retained, not only its former three-line remainder.

- Keep existing manifest host allowlists, explicit LAN opt-in, public-address DNS
  pinning/per-hop validation, TLS and kernel/ledger control; add explicit CGNAT
  and RFC2544 refusal plus translated/mapped IPv4 classification. No new proxy
  or H281 configuration is part of this batch.
- For request and stream redirects, enforce Accept/User-Agent plus required Host
  at the actual final request boundary. Caller auth/cookie/query kwargs and
  stored target cookie jars must not reintroduce credentials across origins.
  Retain legitimate same-origin behavior and current cross-origin body refusal.
- Implement `security.website_blocklist` with enabled/domains/shared_files via
  the existing owner settings path. Bare rules match apex/subdomains; wildcard
  rules use fnmatch. Shared list files, bounded parsing, profile isolation and a
  monotonic cache no longer than thirty seconds are required. Existing env
  restrictions remain effective. Missing/malformed/unreadable enabled policy
  produces a named fail-closed result, not empty-success or provider rescue.
- Apply the same decision to shared HTTP before DNS on every hop, production
  browser policy for navigation/subresources, search result filtering and extract
  redirects, including the real agent tool path. Fixtures must not bypass the
  production guard. No provider activation or global configuration write.

Existing code: `http_client.py`, `security/ssrf.py`, `BrowserPolicy`, existing
web provider/ToolRPC paths and strict `settings_db.read_setting`. Pinned donor
59b2aeef6c7a supplies website matching/shared files/cache, URL classification and
final-boundary redirect behavior; retain its Nous Research MIT notice for adapted
code. Do not copy its fail-open invalid/file behavior or indefinitely cached
disabled state. Shared helper contract before implementation:
`security.website_policy.website_refusal(value: str | None = None)` returns
None, `website_blocked` or `website_policy_unavailable`; None input performs the
readiness check without inventing a target. A healthy missing store uses the
empty default without creating runtime files. Unexpected guard failure remains
a named refusal at consumers. Validate the owner JSON before persistence.

Proposed separate leases: h696 owns shared HTTP redirect/final-wire enforcement,
SSRF classification and their tests; h220 owns policy/settings and browser/web
adapters with their tests. Coordinator owns shared-interface integration, actual
settings/API/tool entrypoint proof and metadata. No child delegation or more than
two implementation agents. Begin only after H334's complete gate closes.

Acceptance includes same-origin preservation; 302/307/308 custom headers, auth,
cookies, params and seeded pooled-cookie final-wire negatives for both HTTP
paths; private/routable/mapped/translated address cases; owner settings auth and
invalid-value no-write; exact/suffix/glob/shared-file rules, bounded malformed
inputs and profile/cache isolation; blocked initial/redirect host produces no
DNS/transport; real browser/search/extract obey refusal without rescue. Use
synthetic transport with real guards, focused regressions and combined milestone
gates. Live upstream/native acceptance stays separate. Rollback restores only
the H492 source delta to the accepted H334 snapshot, preserving settings and
private data; the new setting is inert when its consumer is reverted.


H334 retry started at 2026-11-04T06:25:10Z, Python 3.12 with Node 22 in the child
PATH. It binds 286 public changed/deleted source paths to fingerprint
`bb9adc7844ae9dd742f60d585feb579ecd89914514f0825020c34abfee625bf7`,
with the same 31,656 expected cases. No product/test/ledger edits overlap it.
The source graph was explicitly checked/rebuilt after the targeted test repairs,
using the existing scoped exclusions; caches remain local and uncommitted.


Ref-specific count clarification, observed 2026-11-04T06:34Z via approved status
commands: local `main` remains at `68b351f6679bb609838b40078da74acde38fa022`
(141 equivalent, 443 partial, 113 missing, no impact pending). Fetched
`origin/main` is `07b045d8af3bee4064fee0fc625bbfd9fcd40e58` (146/438/113,
no impact pending). Working HEAD is still `446cc7cb` plus its frozen local
source, with recorded 151/433/113 and conservative 144/424/113 plus sixteen
impact unknowns. Earlier references to main at 146 mean the explicitly fetched
origin/main tree, not the older local branch. No branch switch, reset or
background branch advance was used to hide that difference.


## H334 complete local integration checkpoint — 2026-11-04T06:38:13Z

The second frozen full backend milestone passed: **31,537 passed, 119 existing
skips, zero failures/errors**, 31,656 collected, 778.851 seconds. HEAD, the entire
286-path source set/bytes, assessment input and collected count matched the saved
manifest exactly. The tracked count verifier passed. The matching current
macOS/Python 3.12 runtime scopes for H022/H334 are verified; the prior pending
and failed/historical receipts remain. Live OSV/upstream and Windows/Linux
scopes are unchanged and still pending. This is not merged, CI, native or live
production proof. No source code was changed to fix the four obsolete tests;
refusal guarantees and structural protection were preserved or strengthened.

Cumulative new functional delivery in this local campaign remains H655, H022
and H334, with recorded 151 equivalent / 433 partial / 113 missing, and sixteen
older unresolved impact reviews. No capability was functionally reopened here.
The 697 objective stays active; the H492 frozen batch now proceeds under its
separate two-agent leases and acceptance clauses above. The accepted H334
rollback baseline is `h334-backend-2-source-snapshot` plus its HEAD.


H492 implementation checkpoint (not yet credited): shared HTTP/SSRF red-first
checks pass 145 cases, including final-wire pooled-cookie/auth/query stripping,
translated address rules, per-hop owner policy before DNS, strict-egress-off
refusal and async-loop responsiveness. Policy/settings/web checks pass 80 cases;
actual owner settings-to-HTTP/browser/ToolRPC checks pass six, including immediate
ownership edits after a client cache is warm. Full UI passes 2,805/2,805; the
existing JSON editor saves parsed policy with admin headers and preserves a
refused draft. TypeScript/build/security and combined backend checks continue.

Concrete review findings were fixed before any H492 equivalence claim: `?`/`[]`
glob parsing, canonical IDNA/IP literals, bounded nonblocking regular-file reads
under a growth race, and known settings-store/row disappearance. Four loss/alias
regressions failed first and now pass. Read-only SQLite skips database creation,
schema init and migration; existing WAL databases may use SQLite sidecars, and
a read-only directory lacking them can produce a named unavailable prerequisite.
Fresh missing profiles create no runtime files. The default settings-reader
behavior is unchanged. Named TechScout refusal preserves prior findings and
last_run; acquisition is blocked; the documented best-effort gatherer continues
to omit a failed source without claiming a completed scan or adding prompt data.

The first combined H492 command selected the retired browser test filename and
collected no tests; its receipt is retained. The corrected command uses the
current browser policy/transport/kernel/runtime modules. Full source stays local;
H492 has no credit until its complete contract and integration gates are proven.


## H492 integration freeze preparation — 2026-11-04T07:29Z

The complete frozen functional contract is now implemented locally. Only H492
changes recorded status from partial to equivalent: recorded totals become
152 equivalent / 432 partial / 113 missing, unchanged 697 IDs and weights.
All older reviews and receipts remain. Ninety moved/unrelated impact decisions
were individually checked against immutable clauses and current dependency paths;
seven relevant/unknown dependencies retain their prior verdicts and every byte of
their remaining clauses after targeted review. Sixteen inherited unknown impacts
stay unresolved; no functional regression or new credit is inferred from hashes.

The corrected combined backend gate passes 364/364 with no skips/failures/errors.
Full UI passes 2,805/2,805, tsc/build pass (existing bundle-size warning retained),
and Ruff/Bandit pass without changing their baseline. The preflight adds a bounded
read-only selected-profile website-policy readiness check, withholding child output
and private values, while the real CLI and orchestration smoke remain isolated.
Thirteen preflight regressions and the actual twelve-check invocation pass. The
first two policy preflight regressions failed before implementation; receipts stay
under the local ignored cache. Full H492 backend remains pending, with explicit
runtime acceptance scopes for H022/H334/H492 marked pending on changed shared
source; previous verified H334 scopes remain historical. Native Windows/Linux and
intended-host live upstream/provider acceptance remain required separately.

Rollback: retain HEAD 446cc7cb and the accepted H334 286-path snapshot with its
manifest/fingerprint. Revert only H492-owned source/test deltas to that baseline;
preserve owner settings/runtime data, prior reviews and the v2 migration backup.
The default-off setting does not activate providers. No staged/committed/published
work, scheduler change, package update, owner-only decision or deployment occurs.


H492 full backend started at 2026-11-04T07:28:50.589179+00:00, with Node 22 in the child
PATH and non-root Python 3.12. It freezes 301 public changed/deleted paths at
`e149af8fb883f519638267ad2df39e6fa350f4be1e11bf24b4b9c8d67d315a1f`,
HEAD `446cc7cb626d5b2a2093b15c377733cb313bb6b3`, assessment SHA
`fa1786248ea5011df302d0ace98d2caf31ac41771c518137772c2b4351639fc9`, and 31,713 expected
backend cases. Its source snapshot/manifest and result/JUnit/log are in the local
ignored workflow cache. No product/test/ledger edits overlap this gate. Recorded
152/432/113 reconciles to exactly one new credited ID, H492; conservative totals
are 145 equivalent / 423 partial / 113 missing plus sixteen inherited unknowns.
No capability has been functionally reopened in this batch.


## Next batch prepared during H492 freeze: H027 (no implementation yet)

The immutable H027 row remains partial and keeps every accepted requirement. Its
seventeen operations are status, usage, run, pause, resume, pin, unpin,
list-unmanaged, adopt, restore, list-archived, archive, prune, backup, rollback,
ledger and purge. The shorter old remaining list does not remove adoption or
recovery verbs. Intended behavior is owner-visible, recoverable management of the
curator's local skill slice through the actual admin API/unified CLI and existing
approval inbox, alongside the existing active→stale→archived/proposal passes.

Reuse/adapt the pinned MIT Hermes curator, curator_backup, CLI and skill-ledger
semantics, retaining attribution. Nerva requires adaptations for protected shipped
and imported roots, immutable origin versus explicit owner adoption, per-call
Action Kernel checks and the existing exact-card ActionApprovalQueue. Read-only
status/usage/archive/ledger projections and dry-runs must not mutate state. Every
write binds reviewed targets/source state; queued/forged/stale or denied work must
not execute. Archive/prune move recoverable bytes; explicit purge requires the
irreversible owner tier and verified recovery bytes first. Rollback covers both a
selected mutation and a selected managed-slice snapshot, taking a safety snapshot
and preserving unrelated roots, later edits, signatures and owner approval rules.
Pause/resume persist only curator scheduling and never change external schedules.

Proposed leases after the current full gate: implementation A owns the curator
operation/recovery module, curator/usage integration and core regressions; B owns
a dedicated domain router, unified CLI wiring and their tests. The coordinator
owns shared wiring (orchestrator/action-decision/router registration), generated
API/auth/route/client parity, impact decisions and integration. No more than two
implementation agents; focused independent security review after meaningful
code, without rediscovering the same contract. No source edits begin during H492.

Acceptance includes every verb through real entry points, admin/user refusal,
exact-card binding and kernel halt with the optional global flag off/on, restart
persistence, protected/pinned/imported/linked and pending-review cases, exact
backup/restore bytes and usage coherence, stale/parallel request refusal, bounded
ledger reads, safe archive identities, zero-write previews, and recovery failure
injection before reporting success. Tests use disposable fixtures only. No paid,
provider, native-device or owner-only decision blocks this local implementation.
Rollback will preserve the accepted H492 snapshot/HEAD and revert only H027-owned
deltas; no owner data or prior receipts are reset. H345/H349 remain dependent on a
real governed sync consumer and receive no partial-contract completion credit.


## H492 complete local delivery — 2026-11-04T07:41:59.992659+00:00

The frozen full backend passed **31,594 cases, 119 existing skips, zero failures
or errors**, 31,713 collected in 782.310 seconds. HEAD, all 301 public source
paths/bytes, assessment input and collected count matched exactly. The count
verifier passed. Source fingerprint is `e149af8fb883f519638267ad2df39e6fa350f4be1e11bf24b4b9c8d67d315a1f`;
`h492-backend-source-snapshot` and its manifest are the new local rollback
baseline. Runtime scopes for H022/H334/H492 are verified on these bytes; prior
receipts remain historical and live/native scopes remain pending.

New functionality in this campaign is H655 (contributor workflow), H022 (governed
complete dependency audit), H334 (pinned owner-governed quarantined remote import),
and H492 (owner website policy, final-wire redirect and address guards). H492 is
the sole new equivalent in this batch; exact credited-ID reconciliation is
151→152, added `[H492]`, removed `[]`, same697 IDs and weights. Recorded totals
152 equivalent / 432 partial / 113 missing; conservative totals 145 / 423 / 113
plus sixteen inherited verification/impact unknowns. No functional contract was
reopened. Checks actually run: combined364, preflight13, actualpreflight12,
fullfrontend2805, tsc/build, Ruff, unchanged-baselineBandit, generated Hermes and
project-status/count gates, scoped Graft check/rebuild and the full backend above.
All work remains uncommitted/unstaged at HEAD446cc7cb; none of these new bytes is
claimed merged, covered by old headCI, native-device, upstream-runtime or live
provider acceptance. H027 now starts, including all17 curator operations under
its frozen contract. No provider, cost, scheduler or external publication action
is authorized or performed.

Governed H027 run adaptation: manual run first returns a truthful pending owner
card, then actually runs on that exact approved plan via the existing inbox/CLI
action decision. A donor synchronous default cannot bypass Nerva's permanent
approval floor. Actual Action Kernel authorization is mandatory regardless the
optional global hook. DENY/error/unknown refuse; GRANT never skips owner approval.
As in existing skill proposals/batches, QUEUE permits effects only once the exact
internal plan/card is approved; scheduled work has no such override and needs a
live GRANT. Purge remains tier3 with verified recoverable bytes first. The global
kernel is not changed or given an untrusted approved-payload bypass.


H027 implementation checkpoint — 2026-11-04T08:08:55.600316+00:00: all seventeen
CLI verbs and eight admin-only routes are wired and the existing approval inbox
can apply exact internally bound cards. Independent boundary review found no
blocker in the frozen router/CLI/live-kernel wiring. Existing 759 routes and their
guards/operation IDs remain unchanged; eight intentional admin routes are added,
with an explicit parity reconciliation and52 passing API/auth/typegen guards.
The cached pinned7.13.0 type generator, tsc and build pass without package changes.

Root actual CLI/HubClient/adminAPI/queue/kernel/REAL SkillLoader archive→restore
and halt-after-queue tests pass; real isolated hub boot constructs the operations
service and its status read creates no operation store. Root authority15, current
actualentrypoint/boot7 and settings+entrypoint23 focused checks pass. Registered
owner age fields now default stale30/archive90/purge0, with integer bounds; purge
remains explicit and owner-approved, never scheduled. Red proofs for absent fields,
malformed guard inputs and private-error handling are retained locally. H027 is
still partial: independent recovery tests exposed unsupported single-entry pin
and pause rollback, and core completion/recovery verification is in progress.
No H027 completion credit or full-current-backend result is claimed yet.


Impact-review efficiency repair: `hermes_restamp impact ID... --context --json`
now adds full immutable selected rows and exact recorded remaining clauses to
the existing grouped diff/citation proposal from one record load. It never
changes verdicts, history or credit. The red→green CLI test proves one load and
byte-unchanged assessment; broader accounting recorded241 passes/one failure
because generated HERMES_STATUS still represents the prior checkpoint. This
stale-report failure is retained and will be corrected only after actual impact
review, followed by unskipped re-verification. H027 WIP has recorded152/432/113
unchanged and293 impact-pending reviews (252 machine-proposed moved/unrelated,
41 unknown/relevant); this is not293 functional regressions. Grouped current
source-hunk analysis and exact clause/citation checks replace repeated discovery.
H349 is explicitly withheld from generic impact acceptance because H027 now
delivers owner CLI pin/unpin but its broader HUD/view-as-use/sync clauses remain.


H027 settled source checkpoint — 2026-11-04T09:04:10.412688+00:00: the final
targeted independent recheck is clear. Red actual entrypoint proofs caught five
rollback scope/telemetry/ABA failures, one executable-mode failure, two duplicate
copy scope failures and the stale legacy cognition status. All are fixed; private
exclusive recovery creation was source-reviewed and its new portable ordering
test passed first after the fix (no false red claim). Saved and current snapshot
members now have one-to-one identity/lineage claims; names/hashes alone never
authorize deleting a later copy. Telemetry and immutable origin remain, superseded
controls refuse, archive files/dirs are private, script modes survive, and the
existing cognition projection reads a sanitized persisted actual report.

The earlier360-case combined run had358 passes and two new-route parity
failures. The eight actual owner CLI routes are now explicitly classified using
the existing NOT_IN_HUD/MACHINE_FACING mechanism, with their real CLI purposes
and existing inbox decision continuation; no assertion or guard was loosened.
Final settled related integration passes407/407 with zero skips/failures/errors;
focused H02760, actual twelve-check preflight, Ruff and unchanged-baseline Bandit
pass. API/auth/typegen52 and corrected HUDparity18 pass; current OpenAPI matches
the pinned cached generator input, tsc/build pass. Graft explicitly rebuilt only
21 changed files from its local scoped cache; no indexing/private/global changes.

Impact proposals/contract contexts were read in groups once. The planned
bookkeeping uses214 generic decisions,58 scoped dependency reviews and six primary
curator/workflow/count reviews after resolving the duplicate H655 draft. Recorded
H027 completion requires the full frozen17-operation proof and adds no credit
for documentation, restamping or test counts. H347 keeps human-report/history,
whole-library coverage and trigger requirements; H349 keeps origin/HUD/view-as-use
and real-sync requirements. The complete backend gate is still pending and no
new source is on main, CI or production. Collected current counts are backend
31,821, frontend2,805, mobile363.

## Owner pause and draft upload — 2026-11-04

Owner requested a break, upload of the local development to the existing PR,
and a continuation prompt. All implementation/review agents are stopped. This
authorizes one checkpoint commit/push and a truthful draft PR update; it does
not authorize marking ready, merging, deployment, provider activation or
resuming a schedule. Subsequent development remains paused until requested.

The dependency-binding follow-up found and fixed two concrete accounting
defects: restoring an original evidence hash could conceal a changed explicit
dependency; a later impact receipt could omit that dependency. Red regressions
reproduced both. The final five-case focused check and the independent replay
are clear. The writer now refuses omission before mutation; context and writer
share the active footprint. Historical verdicts/receipts remain intact and no
functional credit was added. H348 is the extra missing row newly exposed for
impact review, not a demonstrated functional regression.

Final checkpoint accounting regression: **246 passed**, zero failure/error/skip.
Ruff and unchanged-baseline Bandit pass. `hermes_status write/check` and
`status_sync --check --reuse-test-counts` pass. Generated documents now use
31,825 collected backend cases (not a full passing run),2,805 frontend and363
mobile. The current report truthfully shows recorded152/432/113 and conservative
49 equivalent/248 partial/105 missing plus295 impact-pending rows. These pending
reviews are not295 functional regressions. H027 is not promoted at pause.

The 64-row fresh-review draft,214-row explicit impact draft and separate H348
draft are retained under `.git/codex-local/workflow-20261104/`, not applied.
Old evidence and active dependency paths were unioned into them. Root repaired
the two moved primary citations and H011's collected count; final dry runs,
actual reviewed writes, credit reconciliation and the complete H027 backend
gate remain the next work. Earlier H492 full-suite proof is historical for its
exact snapshot and cannot establish current H027 verification.

The portable receipt is `docs/hermes/evidence/2026-11-04-paused-checkpoint.json`;
the detailed resume prompt is `docs/handoff/hermes-2026-11-04/CONTINUE.md`.
Full local logs, exact pre-migration backup, source snapshots and pending
review reasoning remain in the ignored cache. Parent-repository
`../nerva-autonomous-routine.md` stays local/untracked, outside this application
PR; its reconciled local prompt and paused schedule state are preserved.
