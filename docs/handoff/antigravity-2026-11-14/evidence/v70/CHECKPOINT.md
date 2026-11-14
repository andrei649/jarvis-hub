# V70 final cumulative integration verdict

Verified 13 November 2026. The cumulative delivery is mechanically integrable on the pinned current main and has a green complete Linux backend run in a suitable test environment. It is uncommitted/unpublished; there is no candidate GitHub SHA or PR CI receipt. Windows checkout contents remain unobserved.

## Git and scope

Remote main1338833d5a344d277c43828a9d9314e10af792f1 and gateway branch686fcbf4f25ebfbb416b3a35dff29045163cffbd were rechecked at completion. Main is the local HEAD merge base; six gateway commits are above main. PR1359 remains draft/open/unmerged on that head. Local branch codex/hermes-continuation-20261112 has181modified tracked files,8deletions,250untracked files:439dirty paths, zero staged. Complete main delta463paths includes gateway prerequisites and all new runtime/test/asset files.

The only repository repair in this assessment is regenerated docs/test-manual/14-api-surface-sweep.md (44insertions/42deletions). No runtime/security-source change, source reset/rebase/staging/commit, security-control weakening, system-permission change, Windows write, publication, merge/deploy or service activation was performed. Prior cumulative kernel/security changes remain in the candidate and need deliberate review; this large candidate is not a security-neutral CLI-only PR.

## Resolved obstacles and exact evidence

- Direct main integration ambiguity resolved: main-to-v70.patch applies to a complete isolated main tree. FINAL-MAIN-APPLY-RECEIPT.json confirms all7,302tracked/new paths match the source candidate after application, with463changed paths and patchSHA256fa5282c490a55fddda600489486d14adf9d254ee7d96417735b4e9635aab25ab. final-main-source-manifest.json pins changed bytes/deletions.
- Required untracked files/assets included. Isolated HUD+Workspace build succeeded using existing dependencies;27generated files were byte-identical before/after and to the source checkout. No installs.
- Initial full test run truthfully preserved:36,217passed/212failed/141errors/108skipped of36,678.346provider/action-auth cases traced to `/tmp`UID65534mode01777, correctly rejected by existing guards for UID1000;3terminated fixture processes remained zombies under non-reaping PID1;4API chapter tests caught stale generated route documentation.
- Remedies are test plumbing plus generated documentation: fresh owned TMPDIR/basetemp, private outer Linux subreaper (only own descendant wait/reap, no signals), and the normal API-doc generator. Existing unsafe ancestor permissions and guards unchanged. Independent review matched every original353bad node to the501-case controlled rerun: all353passed, none missing or skipped. Whole rerun466passed/35skipped/zero failures/errors.
- A second complete run was then performed rather than combining partial results: FINAL-BACKEND-RECEIPT.json exit0, full source snapshot7,302paths unchanged before/after. `/tmp/nerva-v70-final-backend.xml`:36,570passed,108skipped,zero failures/errors,36,678total. Exact-JUnit backend-count guard passed and all23Hermes area suites passed. No keyword filter or disabled safety assertions.
- Fresh full mobile Jest420/420 passed. Frontend, E2E and mobile TypeScript exit0. FINAL-POSTCHECKS.json verifies the source snapshot remains unchanged after these checks.
- Whole-repository Ruff passed with0findings; canonical Bandit0newfindings/errors; lockfile check, selfdev policy validate/selftest, API chapter check, Hermes metadata check, generated status and whitespace checks all passed. Logs/receipts included.
- Frontend Vitest3,178 (2,883browser+295native) is reused V66 evidence, not a fresh V70 execution. Its32changed frontend paths match current bytes; current mobile source matches V66, and isolated fresh build/typechecks strengthen linkage. This is source-level/fixture acceptance, not live browser/device proof.

108skips remain explicit in FINAL-SKIP-REASONS.json:35require isolated Playwright+installed Chrome,9fish,8bubblewrap namespaces,7liveNeo4j,7dedicated Docker containment,6rustc, Windows-native lanes and other opt-in/host checks. They were not silently converted into passes or enabled by activating services. Metadata inventory697 remains171equivalent/482partial/8missing/36excluded; passing area suites is not a claim that the partial backlog is complete.

## Windows and external limits

No actual Windows checkout/HEAD/dirty hashes was available in this executor. Dot's historical11:29UTC note found no lost code in3untracked files but cannot clear current conflicts. compare-checkout.py and windows-comparison-input-final.json supply a read-only463path comparison against candidate/main/gateway, including line-ending distinctions. Linux selftest matches463candidate paths; static repository names have0casecollisions/Windows-invalid names. Windows script execution is unclaimed. See PR-PATH.md; never overwrite unknown Windows work.

Gitleaks, semgrep and pip-audit are unavailable locally and were not installed/run. Their future triggered GitHub checks remain required evidence on the eventual published candidate SHA. Branch-protection settings were not queried. Linux full tests/typechecks/builds do not establish Windows E2E, physical devices, live channels, containment or provider-account acceptance. No legacy unsafe history was reconstructed; V66 archive provenance findings remain valid.

## Minimum remaining path

1. Obtain the read-only comparison from the actual Windows checkout, or explicitly scope the initial review to the verified Linux candidate while retaining the Windows gap.
2. Coordinate overlap with draft#1359. The cumulative candidate includes its six gateway commits; choose the documented main-based or stacked continuation lane when publication is explicitly requested. Do not take over/reset Claude's branch or the dirty original checkout.
3. On the chosen isolated target branch, apply exactly ONE correct-base patch: main-to-v70.patch on main1338833d, or continuation.patch on gateway686fcbf4. Include all new files and generated asset replacements. A narrower feature PR needs its own dependency-complete extraction/test evidence.
4. Only after publication authorization, create branch/commits/PR and obtain all triggered CI/security checks on that actualSHA. This assessment stages/commits/pushes nothing and performs no merge/deploy.

See independent DELTA-AUDIT.md, EVIDENCE-AUDIT.md, PROVIDER-ENV-RCA.md, PROCESS-RCA.md and REMEDIATION-REVIEW.md for dated findings and limitations. Earlier reports intentionally preserve their then-pending/red state; this final verdict and exact final receipts provide the current result. MissionControl handoff r06 is included; Drive upload/scheduling unconfirmed.


# Historical cumulative checkpoints through V69

# Local continuation checkpoint — 2026-11-12

Goal: continue executable Nerva/Hermes contracts, retaining the frozen 697-row
inventory. This is local development, not publication or live-provider acceptance.

Base/head: `686fcbf4f25ebfbb416b3a35dff29045163cffbd`, branch
`codex/hermes-continuation-20261112`. At task start, remote main was rechecked as
`1338833d5a344d277c43828a9d9314e10af792f1`; PR #1359 was open/draft on the
base SHA at that check. The starting local checkout `07b045d8` was clean. No access to Claude's
workspace is available; unpushed edits there cannot be excluded.

## Latest continuation checkpoint

Implemented locally above the first delivery: native Discord built-ins and safe
lifecycle handling; alias/fallback-before-bundle precedence; live inbound media
limits with safe-mode enforcement; owner single/stacked skill commands (up to 5)
and paginated discovery; main HTTP/SSE/pending/title outbound safety; authoritative
empty HUD finals. Served HUD assets were rebuilt under Node 22. All earlier job
and Slack changes remain. The historical sections below retain intermediate
failures and their corrections; they are not current completion claims.

Frozen v2 proof (before the continuing slices below): cumulative gateway/adjacent
acceptance union **3,419 passed**, zero
failures/errors/skips; gateway area verifier **2,779 passed**, zero skips. Complete
frontend **2,968 passed** on both Node 24 and Node 22; Node 22 typecheck/main HUD
build passed. Canonical Bandit baseline check has zero new findings or errors;
local preflight with synthetic smoke/frontend prerequisites passes all 12 checks.
Backend collection is 34,745, frontend 2,968, mobile 365 (mobile reused, unrun).
Neither the full backend suite nor mobile suite was executed.

Plugin command execution/registration and private native skill menus have since
been implemented in the ongoing continuation below. Attachment-byte scanning and
separate provider protocols remain open or in progress; consult the latest section.
Live Discord/Slack/Telegram/email acceptance requires configured accounts and
an authorized live run; native device and service-manager acceptance is unrun.
No credentials, schedules or publication were changed. The complete executable
backlog and 697-contract objective remain open.

## First delivery: literal scheduled output

Requirement: script-only job output equal to `[SILENT]` reaches the transport;
agent silence remains suppressed, and every delivered text still passes the
outbound sanitizer. No changes to provider activation, routing, or authority.

Paths: `agents/core/autonomy/jobs.py`, `agents/core/channels/base.py`,
`tests/test_job_gates.py`, `tests/test_h069_outbound_safety.py`.
The strengthened existing job regression uses a wrapped ChannelAdapter with a
strict send signature. It failed before implementation (`[] != ['[SILENT]']`).
The delivery seam now marks already-policy-checked job output only for wrapped
adapters; the wrapper consumes the marker before sanitizing and calling transport.
Plain sinks retain their original call contract.

Acceptance: full script reconcile path, agent silence with/without a script,
plain sinks, Telegram transport delivery, marker consumption, and secret/control
character sanitization. Final focused union: **162 passed**, no skips or failures.
Rollback: revert only this batch's four-file working diff against the base SHA.

Transfer limitation: the Library archive was resolved, but its materialization
helper returned `download failed`. No local archive bytes or checksum were
verified; the fix was independently reproduced from the checked-out code.

## Reconciliation and next batch

The cumulative handoff's November 4 accounting and paused implementation state
are historical. Current `hermes_status.py summary` reports 697 inventory rows:
170 equivalent, 483 partial, 8 missing, 36 excluded (661 accepted in that report).
These are recorded verdicts, not new live proofs. This continuation does not
remove inventory rows or grant equivalence credit.

The November 10 feature-area decision replaced evidence hashes with feature
acceptance suites; `hermes_restamp.py` is retired. Use the current status tools,
not the obsolete hash-restamping instructions. The eight missing rows include
device sync, committee inference, browser broker, pets, host failover and macOS
TCC anchoring; checkbox count alone is not backlog completion.

## Completed local H057 slice: Slack native slash ingress

One implementation agent (`gpt-6-sol`, high; no subdelegation) implemented the
command projection/fallback and Slack ingress. Coordinator integrated startup,
reviewed the pairing/access/pending-input boundaries, and owns this checkpoint.

Owned runtime paths: `agents/core/commands.py`, `agents/core/quick_commands.py`,
`agents/core/channels/slack.py`, and `agents/web.py`. New regression file:
`tests/test_h057_command_completion.py`. Native slash envelopes are ACKed first,
validated for the authenticated workspace, member, channel and registered name,
deduplicated by trigger, and passed through the existing bounded queue/Gateway.
They cannot answer a pending free-text question. `/nerva <sub>` resolves before
access checks; session/preappend commands require their direct form. Response
URLs and payload role claims grant no authority and create no alternate send path.
The live registry is wired by hub startup; the native list is bounded to 50.

Pinned donor: `docs/research/hermes-inventory-v2026.8.31/07-gw-slash.md:245-253`
for Slack reserved names and fallback demotion. No external Slack registration
was performed. Setup instructions and host/mobile/HUD parity intent are updated.
H057 and H069 remain partial; all verdict counts remain unchanged.

## Final verification and environment diagnosis

- New Slack regressions: 12 passed. Final Slack union with the actual optional
  `slack-sdk==3.44.1` and mocked network: **59 passed**, no skips/failures.
- Final milestone: **2,880 collected, 2,871 passed, 9 skipped, zero failures or
  errors**, 171.331 seconds. This is the 109-entry gateway acceptance area plus
  affected job, binding, network-client, route and status/preflight checks (119
  unique test-file entries). `hermes_status verify --area gateway --junit ...`
  independently reports **2,602 passed, 9 skipped** in the gateway area.
- All nine skips require the absent optional Discord SDK. They are unverified,
  not passes. These counts overlap with focused runs and must not be added.
- Final source hashes match the snapshot taken before the milestone; no Python
  source/test edits occurred during either common-suite execution.
- Ruff on changed Python files, canonical full-repository Bandit 1.9.4 against
  the unchanged baseline, `git diff --check`, Hermes generated-report checks and
  status synchronization pass. Preflight passes all 10 backend checks, including
  real isolated Orchestrator/readyz with synthetic inference. Local venv setup
  initially lacked pip; installing pip repaired that environment prerequisite.
- Whole-repository collection refreshed **34,645 backend tests**. Frontend 2,965
  and mobile 365 are reused tracked counts, not newly executed suites. No full
  backend/frontend/mobile run, release package, live Slack/provider or native
  device acceptance is claimed.

The first milestone is preserved: 2,864 passed, 7 failed, 9 skipped. Five failures
were secure-root refusals because this sandbox exposes sticky `/tmp` as owned by
UID 65534, neither root nor the executing UID 1000. All 50 action-authority tests
pass with `--basetemp` under a private owned `/workspace/scratch` directory.
The two hook termination failures were killed `sleep` children left as zombies
by this container's non-reaping PID 1. The same assertions pass beneath a local
Linux subreaper runner; neither product termination code nor tests were weakened.
The complete final milestone uses both environment corrections. The portable
delivery archive includes the tiny `test-init.c` runner and reproduction command.
The initial positional Bandit invocation used `./` filenames that did not match
the existing baseline; its canonical recursive repository invocation passes with
zero findings/errors and no baseline edits.

Receipts: the portable archive includes the JUnit results for first/final common
runs, focused jobs/Slack and environmental repros, the exact command, source hash
manifest, preflight and full Bandit output. Primary local final JUnit:
`/tmp/nerva-gateway-final.xml`; exact command: `/tmp/nerva-gateway-final-command.json`.

## First delivery: remaining work and next action

The executable backlog and full Hermes objective are **not complete**. Next
coherent executable slice is H057 Discord native app commands: inspect
`DiscordChannel.start`, `_handle_message`, `_deliver_turn` and startup in
`agents/web.py`; reuse the frozen inventory at `07-gw-slash.md:256-265`.
Project the registry within 100 slots, ACK interactions, and keep ordinary
pairing, command access, inbox and approvals. Test cap/overflow, pending-input
isolation and unpaired/guest refusal before claiming integration.

H057 also retains plugin/skill namespaces and registry-before-bundle dispatch
precedence. Telegram mention rewriting (`07-gw-slash.md:267-275`) has no useful
hyphenated-command case until those namespaces exist. H069 retains attachment
byte scanning and the actual HUD stream gate. H089 live systemd/launchd acceptance
is unrun. Library input transfer remains unavailable, but did not block the
independent regression/fix. No new owner decision was needed for this batch.

No stage, commit, push, merge, deploy, PR edit, paid activation or external
schedule change was performed. The branch remains local on the base SHA.

## Continuation requested after the first delivery

Owner requested Discord native commands and further executable backlog work,
preserving verified changes and local-only restrictions. The first portable
archive remains an immutable checkpoint; new work continues above those bytes.

Current coherent batch: Discord built-in native application commands, capped at
100, normal Gateway pairing/access/inbox/approval, neutral ephemeral receipt,
pending-input isolation, lifecycle fencing and bounded replay protection.
One Sol High implementer owns `channels/discord.py`, a command projection helper,
and `tests/test_h057_discord_commands.py`; coordinator owns startup, docs and review.
Offline real-SDK validation uses discord.py 2.6.4; no live registration is run.

Adjacent reproduced correctness defect: bundles named `h` and `nerva` shadowed
the `/h` alias and `/nerva help` fallback in normal and streamed turns. Four real
Orchestrator regressions failed before the coordinator's fix. The bundle name
reservation now uses the command grammar; explicit `/bundle h` still loads the
bundle. Paths: `agents/core/orchestrator.py`,
`tests/test_h057_bundle_precedence.py`. The focused bundle/command union passes;
final batch receipt follows integration. Rollback only these continuation deltas,
preserving the earlier `[SILENT]`/Slack checkpoint. H057 remains partial.

### Discord and inbound media implementation checkpoint

Continuation changes above the first delivery:
- `channels/discord.py`, new `channels/discord_commands.py`, `agents/web.py`:
  100-slot native built-in tree, neutral ephemeral receipt, governed Gateway
  ingress, pairing/tier checks, pending-input isolation, replay and lifecycle
  guards, hidden-command health counts. Real SDK offline tests: 78 passed.
  The test module keeps stable collection and skips when the optional SDK is absent.
- `agents/core/orchestrator.py`, `tests/test_h057_bundle_precedence.py`: aliases
  and `/nerva` reserve their names before bundle lookup; explicit bundle loading
  remains. Four failed regressions before correction; final focused union 119 passed.
- `channels/media_limits.py`, `media_reader.py`, `inbound_voice.py`, `email.py`,
  `settings_db.py`: shared live `channels.max_inbound_media_bytes`, integer
  1..20 MiB, 8 MiB default. Telegram bounds actual streamed bytes; both readers
  recheck before inference; email extraction discards oversized attachment data.
  Explicit internal reader overrides are preserved. The raw email download's
  independent size cap remains. New transport/settings regressions failed before
  the change. Reader/media union: 137 passed. Settings/email/transport union:
  125 passed (`/tmp/nerva-media-settings.xml`).
- Operator notes: `docs/DISCORD_SETUP.md`, `docs/INBOUND_MEDIA.md`. Assessment,
  area suites, BACKLOG and parity notes updated; H057/H070 stay partial. Backend
  collection now 34,682; frontend/mobile counts reused, not executed.

No live Discord registration, Telegram media call, email provider call or new
external operation was run. SDK synchronization is implemented for an owner's
normal configured adapter startup, not executed by this development task.
The second common gateway/settings/email milestone is running; its final result
must be recorded before treating this checkpoint as integrated.

Second milestone result: **3,101 passed, 1 failed, 0 skipped/errors**, 173.707 s
(`/tmp/nerva-gateway-second.xml`). The failure correctly required a safe-mode
review of the new numeric media limit. `agents/core/safe_mode.py` now treats it
as `more-loosens`: safe mode keeps the stricter of the owner's limit and shipped
8 MiB default. The invariant was preserved, not exempted. Focused safe-mode/media
union passes **93/93** (`/tmp/nerva-media-safemode.xml`). A final common rerun is
required after the next source freeze.

Next coherent slice (owner-authorized continuation): H079 single installed skill
slash invocation, owner-only, after commands/aliases/quick commands and bundles.
Reuse the existing guarded turn loader, per-agent prompt re-read, taint and skill
ledger; no direct skill-code execution or second permissive read path. Coordinator
owns orchestrator and command grammar; Sol High implementer owns shared loader,
new resolver and tests. Two regressions confirmed that unknown hyphenated slash
names previously escaped the command notice and could become model text.

Adjacent H079 discovery slice: `/commands [page]` will list only admitted built-ins,
owner shortcuts and usable single-skill/bundle invocations, with bounded pages.
Guests receive only command-policy-visible rows. Owner skill discovery respects
catalog gates and namespace collisions; unreadable bundle metadata must not
advertise unusable skill shortcuts. Telegram skill labels use the supported
underscore spelling. No provider registration or command execution is added by
listing. Coordinator owns the new discovery helper, handler and tests.

H079 implementation now includes owner single-skill normal/streamed turns,
namespace precedence (registry, aliases, fallback, quick commands, bundles),
quarantine/platform refusals, per-prompt switch recheck and clean/tainted ledger
behavior. Shared loader and entrypoint union: 92 passed. Two H026 assertions were
updated to the intentional unknown-hyphen command notice (no model call), rather
than preserving the former fallthrough. Paginated discovery initially exposed an
underscore-spelling collision with a Telegram quick command; a new regression
failed, then passed after checking the final displayed spelling. The old exact
registry inventory was updated for the new `/commands` handler. Final focused
discovery/registry union: 34 passed (`/tmp/nerva-discovery-final.xml`). H079 stays
partial; plugin execution, stacking, native skill menus and live acceptance remain.
Backend collection: 34,715 (frontend/mobile counts reused).

Next H079 slice design: up to five leading skill slash tokens share the same
loader. A sixth, ambiguous, unknown or colliding slash token must refuse; any
initially hard-gated member refuses the entire stack before model access. Preserve
remaining instruction text, count all tokens toward five, deduplicate actual
member reads, and keep per-agent late rechecks. The implementer owns resolver,
shared loader and H079 skill tests only; orchestrator API remains unchanged.
No owner decision or external prerequisite is required for local implementation.

Third cumulative source-frozen milestone: **3,135 passed, 0 failed/skipped/errors**,
176.813 s (`/tmp/nerva-gateway-third.xml`, command/source hashes in matching JSON).
This includes the safe-mode correction, native Discord with the optional SDK
installed, prior Slack/job fixes, media limits, single-skill loads and discovery.
The same private owned basetemp and Linux subreaper environment corrections apply.
This is a checkpoint, not completion of all 697 capabilities. Stacking proceeds
as the next authorized local slice above this verified source state.

Parallel coordinator slice H069: the real `/chat/stream` path currently queues
raw model tokens and returns raw final prose, bypassing the chat adapter wrapper.
Implement a shared append-only outbound stream buffer using the existing safe
prefix/sanitizer rules, with final reply and notice sanitization at the HTTP/SSE
boundary. Preserve cancellation, usage and approvals; no inference/provider or
route authority changes. Regressions must exercise actual HTTP/SSE transport with
credentials split across chunks, literal silence and normal text. Attachment bytes
and other provider protocols remain separate gaps. Root owns web.py, a new stream
helper and focused tests; child continues skill stacking in distinct files.

H069 review expanded the concrete transport regression: provider-error and
cancellation-marker prefixes could leak before final classification; SSE clarify
labels, polled questions and selected session titles bypassed the prose gate; the
HUD used a truthy fallback and retained drafts when final text was empty. The
coordinator owns backend fixes; the same Sol High implementer added the App
presence-check fix and actual SSE consumer tests (9 passed; frontend typecheck
passed). Clarification controls send numeric indices, so sanitized displayed labels
preserve server-side original choices and selection authority.

Environment credential masking now includes whitespace-containing values (strict
credential-name filtering and minimum meaningful length remain). Preview sanitation
runs on the full buffer before truncation. Bracket-led possible provider errors
and incomplete cancellation markers are held. An installed opaque secret redactor
provides no safe maximum secret length, so previews wait for full sanitization;
this deliberately reduces incremental prose delivery in that configuration while
progress events remain available. Redactor failures now withhold the reply rather
than forwarding possibly unknown credentials. Telegram previews share the same
prefix gate. No attachment-byte scanning or other provider protocol coverage is
claimed by this HTTP/HUD slice.

Stacking implementation is complete locally: new regressions were red before
implementation; the H079/H026/discovery union passed 116 tests. No new context
holder or bypass of skill_view was introduced. The source-kind presentation is
truthful for bundles, single skills and stacks; all existing bundle defaults hold.

Final focused H069 HTTP/SSE/pending/Telegram union: **114 passed**, no skips/errors,
9.894 s (`/tmp/nerva-web-telegram-final.xml`). The first four web regressions failed
before the fix. Review-added marker/clarify/title cases were first executed after
fixes landed; no red-before-green claim is made for those. The title test harness
needed actual outcome timing and a corrected mock signature before it exercised
the endpoint. Three Telegram transport cases cover whitespace credentials,
provider details and cancellation prefixes. Existing safety tests remain intact.

Frontend: complete Node 24 run **2,968 passed** (`/tmp/nerva-frontend-final.json`),
including the three new real App SSE final-value cases. A local Node 22.23.5 runtime
was then materialized in `/tmp` to match the project's major version. Typecheck
and the main Vite production build passed under Node 22; served HUD assets in
`agents/web/v2` were regenerated. A full Node 22 suite is running for the final
receipt. No package/lock files changed and no global Node configuration changed.

Expanded common milestone: **3,416 passed, 2 failed, 0 skipped/errors**, 179.608 s
(`/tmp/nerva-gateway-complete.xml`). Both failures were streaming-shape assumptions
invalidated by conservative buffering with an opaque redactor: the HTTP test
required exactly two token frames, and a Telegram voice test required a preview
edit even when no draft could safely start. The HTTP contract now checks delivered
text plus authoritative final, independent of frame partitioning. The Telegram
test explicitly exercises both redactor modes and still requires exactly one voice
send after the correct final text transport. No product guard was relaxed.

Read-only GitHub recheck during final verification: PR #1359 is still open/draft,
head `686fcbf4f25ebfbb416b3a35dff29045163cffbd`, base main
`1338833d5a344d277c43828a9d9314e10af792f1`. No remote mutation occurred.

Focused streaming-order union after the test corrections: 63 passed
(`/tmp/nerva-stream-order.xml`). Complete Node 22 frontend run: 2,968 passed,
zero failed/skipped (`/tmp/nerva-frontend-node22.json`). Final backend collection
is 34,745; mobile 365 remains a reused count, not an executed suite.

The first final rerun exposed three order-dependent Telegram preview tests: a
prior orchestrator test installed an opaque broker redactor globally. The transport
unit module now explicitly isolates that global using monkeypatch, which restores
it afterwards. The separate transport safety tests and both voice redactor modes
remain in the common acceptance union. This changes test setup, not the runtime
fail-closed behavior. The final rerun below supersedes that failed attempt.

## Final cumulative acceptance — v2

- Common union: 3,419 passed, zero failures/errors/skips, 180.403 seconds,
  `nerva-gateway-verified.xml`; exact command and tested-source hashes accompany it.
- Feature-area verifier: gateway 2,779 passed, zero skipped; 1/1 selected areas pass.
- Canonical Bandit against unchanged `.bandit-baseline.json`: zero new findings,
  zero scan errors. Existing baseline findings are not presented as eliminated.
- Development preflight with Node 22, frontend prerequisites and synthetic install
  smoke: all 12 checks pass. This is not live-provider/native acceptance.
- Ruff on all changed Python and `git diff --check` pass; index remains empty.
- The 50 changed Python/frontend/served-asset source paths in the test-run hash
  manifest were unchanged after the successful run. Only checkpoint prose followed.

The cumulative v2 delivery contains the patch, exact changed-path hashes, receipts,
portable acceptance runner and Linux child-reaping test wrapper. The delivery
script applies the patch to base bytes in a disposable directory and compares
every resulting file byte-for-byte. The previous delivery remains immutable.
No stage, commit, push, merge, deployment or external schedule operation occurred.

Next batch: implement plugin command registration/execution through the installed
extension authority, then native skill menus with collision and catalog gating;
retain the normal Gateway access/approval path. These remain executable work, not
a demonstrated blocker. Live provider/device acceptance is separately pending.
This is a tested continuation checkpoint, not completion of the entire backlog.

## Continuing after v2 — plugin commands and private native skill menus

Owner requested continuous local progression after the v2 checkpoint. The v2 zip
and its receipts remain immutable historical proof. Current edits continue above
the same base, without publication or schedule changes.

H057/H079 plugin commands use the existing signed acquisition extension runtime;
the vendored subset contains provider plugins but no reusable command-registration
implementation. The frozen contract's no-shadowing/discovery semantics are adapted
to Nerva's sealed sandbox rather than importing third-party host callbacks. Runtime
now binds ADMIN commands after isolated declaration/handler proof, rechecks consent
and package identity, withdraws exact registrations, suppresses late revoked replies
and sanitizes returned text. The real activation route and acquisition composition
are covered. Initial three regressions were red; the subsequent 90-case focused
union passed. A larger 259-case union found only the exact binding-callsite inventory
shift from wiring the registry; the reviewed coordinator line offsets were updated.

Native menus: project only installed, unambiguous, catalog-allowed names through
the same dispatch predicates. Telegram skill names are private-owner-chat scoped;
Discord uses generic `/skill` and owner-filtered autocomplete so the global picker
does not disclose the owner's skill catalog. An invalid stored quick command still
reserves its name; the previous configured-only predicate was corrected.

Final integration proof for this new slice is pending; no equivalence promotion.

## H069 protocol outbound safety continuation

OpenAI-compatible chat completions and Responses now sanitize the authoritative
assistant answer before JSON, SSE and storage. Their append-only SSE protocols keep
start/status frames but release prose only after the final answer is known, so a
divergent final, late credential match, provider marker or failed turn cannot leave
raw provisional text in a client transcript. Literal `[SILENT]` yields a successful
empty answer. Saved Responses and idempotent chat replays recheck assistant prose
on read for credentials registered after storage; input, instructions, IDs, usage,
approvals and other control fields are unchanged.

Workspace sanitizes assistant prose before storing it and before JSON/history reads.
Its SSE tokens use the existing safe prefix buffer; the `done` answer remains
authoritative if a provisional prefix differs. A Workspace provider failure is
reported as its established error event and row, without leaking the marker. User
messages and citation/control metadata are unchanged.

The new real-route H069 protocol test file has 19 cases. Its initial corrected
red run had 13 failing cases (two also needed a fake callback signature fix);
the final focused union collected 182 tests across H069 protocol, G12 chat/guest,
Workspace answer/SSE/cancellation/off-loop, and the orchestrator fake: **181 passed,
one optional SDK skip, zero failures** in 27.227 seconds. Ruff on the six touched
Python files and `git diff --check` passed. The original `>=64` first-SSE-frame
assertion was changed to content assembly because safe word-boundary framing may
partition the same answer differently; a synchronous test backend was corrected
to await an async token callback. No full backend or live provider run was done for
this slice. Attachment-byte scanning and other unimplemented transport paths remain
separate H069 work. No stage, commit, push, deploy or external write occurred.

Plugin/native command integration: 152 focused tests passed with zero skips/errors,
`/tmp/nerva-command-final.xml`. The preceding broad extension/binding union had
258 passed and one inventory failure; the follow-up 57-case runtime/menu/inventory
selection passed after all three remaining offsets were corrected from the observed
AST callsites. The registry now gives plugin underscore/hyphen spellings one owned
handler; unregistering stale registrations cannot remove a newer handler.

H069 next batch: separate OpenAI-compatible and workspace chat protocols. Preserve
IDs, user inputs, usage, approvals and cancellation. Sanitize authoritative model
prose before persistence/delivery; non-retractable OpenAI deltas buffer until final.
Workspace may use the existing safe stream helper and authoritative final.

H070 document intake completed locally: a bounded private filename selects an
existing Workspace parser; magic mismatch/unsupported formats refuse before
inference, and the extractor's parser limits and timeout are reused. The model
receives at most 8,000 characters of fenced untrusted text, never the filename.
Telegram checks pairing before photo/voice/document fetches. Caption commands
remain commands and document content cannot answer a pending approval/question.
Focused existing/new media union: 156 passed; new document module: 9 passed.
Native attach/video/sticker/cache/recent-file/non-Telegram delivery remain open.

Plugin review correction: sandbox command responses quote any MEDIA: directive
after sanitizer control-character removal, preventing pure text results from
triggering host attachment reads. Its regression uses the actual media directive
parser; focused test passed. This review-added case was first run after the fix.

Common v3 milestone: **3,708 passed, 22 failed, 1 skipped**, 223.067 seconds
(`/tmp/nerva-gateway-v3.xml`). Twenty-one failures are Telegram voice/batching/topic
fixtures that had no admitted sender after the new pre-fetch pairing guard; they
must explicitly configure valid admission, not bypass the production guard. The
Workspace disconnect test used the first visible token as its disconnect trigger;
with opaque-redactor buffering that token arrives after model completion. Its
replacement must cancel a demonstrably live model task in both redactor modes,
independent of visible prose. No new capability work starts until these regressions
are resolved and cumulative acceptance is green.

Common v3 rerun: **3,731 passed, 1 existing optional skip, zero failures/errors**,
199.926 seconds (`nerva-gateway-v3-checked.xml`). The gateway-area verifier accepts
2,896 tests with zero skips. Backend collection is 34,800; frontend 2,968 and mobile
365 are unchanged, with mobile unrun. The previous complete frontend receipts are
reused because no frontend source or served asset changed in this continuation.

Canonical Bandit initially identified B110 in the Discord picker exception branch.
After the common run, `pass` was replaced with explicit fail-closed selection None;
no baseline or security exception was added. The 27 native/menu tests were rerun
and passed on that final change (`nerva-v3-native-final.xml`). The common receipt
therefore predates this one equivalent exception-branch change; a separate final
source manifest records the difference and the targeted follow-up proof.

Read-only GitHub recheck still shows PR #1359 open/draft, head 686fcbf4 and base
main 1338833d. No remote integration, publication or external schedule change.

Final v3 security/preflight: canonical Bandit passes with zero new findings and
zero scan errors; all 12 local preflight checks pass with synthetic smoke and
Node 22 frontend prerequisites. Ruff, whitespace and Hermes report checks pass.
The index remains empty. This snapshot is cumulative above the same base, and
the full backend/mobile suites and live providers remain unrun.

Next work is explicitly authorized and executable: static WebP Telegram sticker
caption/cache, then owner `/reload-skills` with staged discovery and truthful diff.
Plans must preserve live policy on cache hits and preserve the existing loader's
authority/identity until an atomic validated reload commit. Continue without
publication or reactivating external schedules.

Immutable v3 delivery: `nerva-continuation-20261112-v3.zip`, 1,705,879 bytes,
SHA-256 `03cd64f59637294d84bd1834bf2497dec1720f3ddb34b432d53202764b30284b`.
Library ID `libfile_fde3_f-c43369491c008191970f2766422864fa_4f556dba9178819182620ad30bbe8468`;
file ID `file_00000000b0548212889daec97b7fe810`. Patch application and resulting
byte comparison passed for all 100 changed/deleted paths. Current work continues
after this immutable snapshot; it is not a new git commit or publication.

V4 continuation (same base, still local/unpublished): static WebP sticker captions
are locally implemented with bounded transient cache, current admission/policy
checks and lifecycle fences. The first review found raw endpoint credentials in
the cache identity; the final key is an opaque per-reader keyed digest of the full
configuration/binding. Credential regression red then green; final focused 58/58
(`/tmp/command-contract-h070-identity.xml`), prior media union 168/168.

Owner /reload-skills stages a candidate and swaps only after policy, approval,
source and registry validation. Cancellation keeps the scan single-flight until
the worker stops. Two race regressions were red before and green after fixes;
final agent focused union 327/327 (`h084_reload/final_union.xml`). This is not a
rollback guarantee for arbitrary approved-module import side effects.

Integration found H026 fixture state crossed test boundaries: it replaced memory
transcripts but reused the shared route database. Diagnostic traceback confirmed
`Existing transcript unavailable`, the correct production refusal. The fixture
now isolates its route database too. Original slash-to-H026 order: 25 passed/1
failed; after fixture correction slash+all H026+H084: 102 passed, no skips
(`/tmp/nerva-h026-order-green.xml`). No production session checks were relaxed.

Next scoped work: owner-only local /debug report (existing support bundle/redactor;
no upload), and Discord attachments through the actual queued reply broker, with
approval-bound content and inbound recipient checks. An active-adapter-scope-only
implementation was rejected during design because ordinary replies leave that
scope before broker execution. Common acceptance waits for these source changes
to settle; earlier receipts are not represented as covering future changes.

Owner /debug is locally implemented: redacted bounded system/log report, generated
private file, no upload. Initial new regressions: six failures before implementation;
focused diagnostics/support/log/slash/reload/bundle union 173 passed; final debug
module 9 passed (h084_debug/focused.xml and final_new.xml). Safe output currently
requires POSIX directory-relative nofollow support; Windows gets an explicit refusal,
not an unsafe fallback. This remains an H084 platform limitation.

Discord approved owner-DM attachments are locally implemented on the actual
queued reply path, preserving literal MEDIA text on ordinary direct sends. Current
paired-owner/SDK-recipient checks precede reads and repeat before transport;
approved ordered metadata and bytes are revalidated at execution. Scoped permits
are same-task and revoked on exit. Review caught a duplicate-content ledger-key
collision: stable ordinal now preserves distinct filenames; retry/delivery-failure
regressions use a real ledger. Filename redaction and lifecycle refusals are tested.
Focused broker/adapter/email/network union: 101 passed, no skips
(`/tmp/command-contract-h070-discord-focused.xml`). No live Discord send occurred.
Seven coordinator binding callsite offsets moved by two lines; exact AST inventory
failed before refresh and passed after (`nerva-v4-bindings-red/green.xml`).
Common milestone now runs after these source changes are frozen.

Common v4 milestone on unchanged source manifest: **4,014 passed, one existing
optional skip, zero failures/errors**, 206.052 seconds (`nerva-gateway-v4.xml`).
The common union includes all gateway tests and expanded skill-signing/approval,
load-set, support/log, inbox and email regressions. Backend collection is 34,840;
frontend remains 2,968 and mobile 365 (reused count, mobile unrun). No frontend
source or served asset changed since v2; its complete frontend receipts are reused.
All changed Python files pass Ruff and git diff --check. This is a bounded
integration suite, not a complete backend run or live-provider acceptance.

Final v4 acceptance: gateway feature-area verifier reports 2,936 passed, zero
skips. Canonical full agents/scripts Bandit baseline check has zero new findings
and zero scan errors. All 12 local preflight checks pass (synthetic smoke, Node 22
prerequisites); this does not establish production or live-provider acceptance.
The one common-suite skip is the optional OpenAI SDK parser test (SDK absent).
Source hashes still match the common-suite manifest; the git index is empty.
Next: owner /egress read-only status, then live-wanted MCP reconnect/tool diff;
saved-config reread must not resurrect removed or intentionally disconnected servers.

Immutable v4 delivery: `nerva-continuation-20261112-v4.zip`, 1,894,000 bytes,
110 changed/deleted paths, base 686fcbf4. SHA-256:
`70ecff14b5abfff56d5c863482dd6c07a07630fd4d2d8b22e256445764dee4a0`.
Library ID `libfile_fde3_f-4f63a4ef665081919afe23af09bc06de_4f556dba9178819182620ad30bbe8468`;
file ID `file_000000004ae082128de59b2aad019784`. Clean-base apply/check and every
resulting byte comparison passed. The private Library delivery is not git
publication; the index remains empty and no paused schedules were resumed.

V5 authorized continuation begins: owner /egress read-only status (ledger tallies,
credential provenance names and bounded local handles, no secret resolution), and
/reload-mcp refresh of live wanted servers using existing lifecycle controls.
Do not infer proxy traversal from env variables; do not reload saved configs in a
way that can resurrect removed/disconnected servers. Coordinator owns integration
and shared registration; implementers retain distinct file ownership.

V5 focused implementation: /egress reports only instrumented traffic/provenance
and configured proxy hints; no active-route or credential-availability claim.
Six regressions red before implementation; focused union 178/178 under umask 022.
That union initially failed two H381 tests under inherited 077 (167 cases/2 failures);
H381 alone reproduced 22 cases/2 failures. The fixtures requested mkdir(0755) but
umask yielded 0700. Root explicitly chmods the three test directories to0755 so
unchanged-directory protection is tested, not weakened. H381 now passes22/22 under
inherited077 (`nerva-egress-permissions.xml`).

/reload-mcp refreshes live wanted servers with existing guarded lifecycle, current
policy/identity checks, immutable definition/multiplicity diffs and truthful failure
state. Focused48/48, then aggregate/replaced-manager regressions were red2/2 and
green with23 maintenance tests. Its long-secret label regression was green-only.
Saved-config reread and automatic reactivation are not part of this command.

/diff uses current session project/worktree, hardened read-only Git and bounded
redacted output. It distinguishes errors from clean tracked state and excludes
untracked files explicitly. Malicious embedded fences/MEDIA stay literal. Eight
regressions red before registration;70 focused diff/registry/worktree tests pass.

Post-v4 review found native metadata descriptions were clipped before masking or
not masked at all. Seven red regressions confirmed known-secret prefix leakage;
shared native_metadata now sanitizes before normalization/caps and hides unsafe
identifiers without changing dispatch.59 initial native/registry tests passed.
Three further Slack canonical/alias cases were red before its corresponding fix.
This is a v5 correction; immutable v4 does not contain it.

Expanded native metadata union:74/74 passed, zero skips
(`/tmp/nerva-native-metadata-final.xml`). Peer review found no /diff security blocker.
MCP peer review found a failed HTTP initialize path discarded its transport before
cleanup; two real-path mocked transport regressions were red before the fix and
green after, with49 focused MCP/transport tests passing. No external calls.

Full frozen slash-command record reread (07-gw-slash.md1299-1313) exposed missing
/diff modes and incorrect initial default: donor default is unstaged working tree,
not HEAD. Before v5 acceptance, finish working/staged/all/stat and bounded untracked
name reporting, and explicitly report session-baseline availability. Optional
/egress status, /version (/v) and owner /profile are also in the frozen record and
are being implemented, not silently treated as complete by the shorter ledger.

V5 completed scope before common acceptance: /diff working/staged/all/stat and
bounded untracked-name listing, optional /egress status, USER /version (/v), and
ADMIN /profile using actual serving profile/home. /diff session explicitly refuses
without a valid baseline; this remains open. Final adjacent union88/88
(h084_diff/final2.xml); final native metadata union74/74. Diff rendering caps now
match the frozen record:60 lines/3000 characters. Review found no concrete diff
security blocker. The shared hardened Git runner merges stderr/stdout; only
successful bounded output can reach the sanitized/fenced report.

A targeted Bandit precheck flagged an unnecessary subprocess import used only
for exception typing in diff_commands. Removed that import; generic failures
still produce a fixed unavailable notice. No baseline or security exemption was
added. The final diff module was rerun before the common milestone.

### v5 integrated milestone — 2026-11-12

Base/head remain 686fcbf4f25ebfbb416b3a35dff29045163cffbd; fresh read-only GitHub check confirms PR 1359 open, draft, unmerged, main base 1338833d5a344d277c43828a9d9314e10af792f1. Combined gateway/MCP and adjacent safety suite: 4,670 passed, one existing optional OpenAI SDK skip, zero failures/errors (4671 total; /tmp/nerva-gateway-v5.xml). All 94 recorded tested source hashes unchanged after the run. Feature acceptance: gateway 2988 passed; MCP 434 passed. Canonical Bandit baseline comparison: zero new findings/errors. Development preflight: 12 passed including synthetic install and Node 22 dependencies. Ruff across changed Python and git diff --check passed. No full backend/mobile/live-provider run.

Current delivery adds egress diagnostics, MCP reload preserving stop intent and closing failed transports, bounded diff modes, profile/version, and metadata redaction before provider truncation. Immutable v4 does not contain the metadata correction; use the cumulative v5 patch alone. Next authorized work is /platform failed-channel controls and /update through existing irreversible approval; no external restart/update performed. Inventory remains 697 with no promotions.

V5 immutable delivery: /workspace/scratch/nerva-continuation-20261112-v5.zip, 2,090,972 bytes, SHA-256 1ffa50478c6fa0b9bcd3db54b879684063080bbd0d69e4f2cb74cbae0edbd4d2. Library ID libfile_fde3_f-35cfe8c4977c8191aef65d1b779e17dc_4f556dba9178819182620ad30bbe8468; file file_000000005bb08212a1ad001e1b15ba23. Clean-base apply check, actual apply and byte verification covered 121 paths. Private handover only; index and remote untouched.

### Next local unit — H083 platform and H084 update intake

Goal: failure-only in-process channel pause/resume with bounded lifecycle, and owner chat update intake into the existing human irreversible card. Non-goals: stopping healthy channels, changing external schedules, performing a runtime update/restart, claiming requester streaming or post-restart notification. Two gpt-6-sol/high implementers, no subdelegation, distinct files: command_contract owns channel manager/lifecycle budget/platform handler and focused tests; protocol_safety owns update handler and focused tests. Coordinator owns registry/inventory/integration and critical review. Tests use fake transports and existing H624 queue fixtures; preserve all v5 work. Rollback unit: new handlers/registrations and the channel-manager runtime control additions, not the earlier cumulative changes. Dependencies: current health snapshots, bounded lifecycle helper, hub_update_apply.request_apply and irreversible human approval.

V6 focused evidence so far: update handler20 passed including actual enforce-mode TaskQueue refusal for the currently unclassified hub.update kind (/workspace/scratch/h084_update/enforce.xml). Fake governed-intake tests are labelled as such; no actual update pipeline ran. Shared command/native metadata regression union51 passed (/tmp/nerva-v6-registry.xml). First invocation named a nonexistent Discord test file and collected nothing; corrected to test_h057_discord_commands.py before this receipt. Two H677 stale-fixture failures reproduced separately in /tmp/nerva-v6-h677-fixtures-red.xml and passed in green.xml after real sender pairing and StickerCaptioner initialization; product admission/stop safeguards unchanged. H083 remains under final race review before integrated verification.

Critical review expanded the v6 update unit with a concrete pre-existing trust race: hub_update_apply verified the target before a potentially slow backup, then merged without re-reading trust. protocol_safety now owns hub_update_apply.py and new test_h624_update_trust_boundary.py for a final-effect trust recheck and mocked regression. No runtime update/restart or Kernel registration change is authorized by this test work. H083 peer review additionally identified an orphaned old listener on running-adapter replacement and a concurrent-stop boolean race; these are being fixed with deterministic regressions before the common run.

H083 implementation frozen after review: 23 new platform tests and 64 focused tests passed (/tmp/command-contract-h083-final.xml and final-focused.xml). Includes late/cancelled starts, unsuccessful closes despite _running=False, safe-mode flips, replacement of running adapters, stale ownership, and concurrent shutdown gating. Initial missing-module red receipt is collection-only; later race regressions have green receipts but no preserved red XML, so they are not claimed as retained red→green evidence. Root changed only the explanatory manager comment after this focused run; common source hashes will cover the final source.

H624 trust boundary: four behavioral regressions failed before and passed after the final target recheck (/workspace/scratch/h084_update/trust_red.xml and trust_green.xml), using actual temporary pinned trust state and mocked backup/Git/restart effects. Re-verification precedes the final HEAD/tree fence, and revoked trust restores a prepared stash and refuses the merge. This reduces stale authority across the long backup; it does not claim filesystem-wide atomicity against arbitrary external trust/repository writers.

### v6 integrated milestone — 2026-11-12

Base/head: 686fcbf4f25ebfbb416b3a35dff29045163cffbd, local uncommitted continuation. Common gateway/MCP plus H677 lifecycle, H624 trust-boundary and adjacent safety acceptance: 4,769 passed, one existing optional OpenAI SDK skip, zero failures/errors (4770 total; /tmp/nerva-gateway-v6.xml; 244.573 s). All103 recorded source hashes matched after completion. Gateway/MCP area verification passed. Canonical Bandit: zero new findings/errors; development preflight:12 passed. Backend collection34940, reused unchanged frontend2968/mobile365 counts; these counts are not full-suite runs.

Existing H624 update suite plus four initial trust regressions separately passed42/42; final trust exception regression gives5/5 focused. The common run includes all5 trust tests but does not repeat the GPG-bearing H624 suite. Its disposable fixture GPG agents were stopped only by their owned test homedirs after pytest ended so the subreaper could exit. No live update/restart/channel operation or schedule activation occurred. Full backend/mobile and live provider/device suites remain unrun.

Next coherent local batch: exact hub.update Kernel classification/manifest and signed intake/execution proof preserving the human tier-three floor, plus generation-bound Slack/Discord readiness-to-disconnect signals. These are implementation tasks, not authorization to execute an update or operate live channels. H083/H084 and the frozen697 objective remain partial with no promotions.

V6 immutable delivery: /workspace/scratch/nerva-continuation-20261112-v6.zip, 2,257,306 bytes, SHA-256 5d13c0c4150e80a31fa9264f95853c9c748bb730adfb5b8ee681df5ff18dfe29; clean-base apply and byte comparison covered130 paths. Library ID libfile_fde3_f-5e80d5d500688191a6b5375f0c6fd58f_4f556dba9178819182620ad30bbe8468; file file_00000000fcb4821280d26dcaa68799bc. Private artifact only; no stage/commit/push/merge/deploy.

### Next local unit — exact update mediation and SDK failure signals

Goal: remove the actual strict-intake blocker for hub.update without weakening approval, and let /platform recognize a real Slack/Discord disconnect after observed readiness. Non-goals: wildcard action registration, changing trust/approval policy, executing an update or live channel operation, requester completion streaming or restart notification. protocol_safety (gpt-6-sol/high) owns exact Kernel registry/manifest/snapshot, action-auth tests and new signed intake/execution tests; optional exact refusal vocabulary only if needed. command_contract (gpt-6-sol/high) owns Slack/Discord adapters plus a new SDK failure test file. No subdelegation; coordinator owns integration, critical review, docs and counts. Rollback units are independent: exact action registration and generation-bound SDK health signals, preserving v6 source. Tests must show initial SDK not-ready is not a failure, stale callbacks cannot alter replacement state, and strict update intake/execution requires current signed evidence plus a human tier-three decision.

Further H084 frozen-contract reconciliation (read-only code findings, not completed features): `/pause off` currently engages ESTOP with the literal reason off rather than calling `/resume`. ESTOP chat/ops handlers use owner/admin checks directly, whereas the separately registered admin.kill_switch route uses Kernel authority; the frozen governance clause remains open for ESTOP. This needs a careful owner-authority path that still lets an owner lift a pause; no control was loosened or real pause lifted. These are next executable design/implementation gaps, not hidden equivalence credit.

H084 governance detail: security.kill_switch_set already documents owner release as intentionally unmediated so a halt cannot deny its own recovery. The residual ESTOP alignment concerns engagement authority; implementing it must preserve that owner recovery rule, not introduce a Kernel gate that bricks resume.

### v7 source freeze before full backend acceptance — 2026-11-12

Base/head remain686fcbf4f25ebfbb416b3a35dff29045163cffbd; fresh GitHub read confirms PR1359 still open/draft/unmerged, main base1338833d5a344d277c43828a9d9314e10af792f1. Exact hub.update registration includes no sibling/wildcard. Current signed human task, bound worker/queue, AUTO-only Kernel seal, host presence and policy/receipt/halt are rechecked before consequential effects. Both initially signed task downgrade and initially off-mode queue tightening/replacement fail closed. Nonhub workers cannot claim update/rollback cards. Post-merge revocation uses reset --keep and only restores dependencies if installation was attempted; incomplete rollback is reported. The strict AUTO-only choice conservatively follows the existing terminal/host receipt restriction documented in autonomy.mode.RECEIPT_NOTE; no new ask-mode exception was introduced.

Focused proof: exact Kernel/action-auth/manifests/H517/H624/update union240 passed before the final narrow legacy queue-fence fix; final affected union74 passed after that fix (/workspace/scratch/h084_update_legacy_final.xml). New effect file47 passed at its earlier checkpoint. Retained behavioral red receipts cover classification, nonhub claims, late authority and legacy queue changes. New late-effect tests mock physical effects; the existing H624 suite uses disposable Git/GPG fixtures, never the working checkout.

Slack/Discord readiness source: prior native/adapter union75 passed; final probe-exception regressions failed2/2 before and passed in9/9 new SDK tests after. /pause recovery/completion new+existing slash union40 passed, with retained behavior red receipts. Bare pause uses a fixed response rather than echoing a stored private reason. No live channel or host ESTOP was operated. Whole-repository Ruff and diff check passed. Collected backend count35015 (not yet a full run), reused unchanged frontend2968/mobile365.

The next verification is the complete tests/ backend suite with four workers, no keyword filter, the CI90-second per-test bound and owned temp state. Source remains frozen during it. This is broader than the previous4770-test milestone; no success is claimed until its JUnit receipt is checked. Full frontend proof remains reused from unchanged v2 source; mobile/live-device execution remains unrun.

### v7 full backend diagnostic — 2026-11-12

Initial complete backend receipt /tmp/nerva-backend-v7.xml:35015 cases,34887 passed,20 failed,108 skipped,0 errors,943.966s. All tested source hashes match /tmp/nerva-backend-v7-source.json. Runner exited1 after owned fixture GPG agents were closed by their exact test homedirs. This is a failing diagnostic, not acceptance. The earlier chat claim based on a log tail missed prior failure markers; corrected after scanning the complete log.

Repair scope: exact hub.update refusal/verification/readiness integration; deterministic safety-buffered streaming/recall/cancellation tests; env_config proxy reads; explicit shared-folder modes under umask077; OCR PID-file readiness; generated-skill clock pin; browser unit tests without live DNS; safe-mode-reader inventory after review. A genuine pre-existing Unicode fallback undercount was reproduced with optional tokenizer disabled:3000 supplementary characters estimated751 tokens, bypassing a4096-token window. Correct fallback conservatively counts non-ASCII UTF-8 bytes while preserving ASCII estimates. Physical backend-send refusal regression retained before correction. No production security gate is relaxed.

V7 repairs focused: three streaming modules104passed; exact update H27/readiness21passed; coordinator affected union1263 cases had1261passed,1skip and one additional opaque-redactor ordering expectation failure. That additional file was corrected with explicit buffered/unbuffered parameterization and91cases pass. Unicode/latency focused51passed. The new update reality case uses real signed queue/Kernel/human acceptance and mocked physical effects; revocation during backup proves no Git/restart. Initial complete-suite and intermediate failing receipts remain preserved. Next is a second full backend run, suffix-v7-final, after generated counts refresh.

### v7 integrated verification — 2026-11-12

Second full backend run /tmp/nerva-backend-v7-final.xml:35016 tests,34907passed,108skipped,1failed,0errors,914.627s. All recorded sources matched. Its sole failure was H310's assumption that the last input URL enters the PDF parser queue last; concurrent fetch completion controls admission order. The corrected test preserves four successful documents, one parser_busy/retry, time budget and slot release, and asserts all result URLs remain in input order. The entire49-test H310 module passed afterward (/tmp/nerva-v7-pdf-final.xml). No production source changed after the full run; only that test file changed.

Derived combined acceptance /tmp/nerva-v7-combined-acceptance.xml replaces exactly those49 cases and is explicitly NOT a single full green run. Its provenance records input hashes, source comparison and replacement identities:35016covered,34908passed,108skipped,0failures/errors across the full run plus focused repair. All23 Hermes area suites pass using that combined coverage; overlapping area counts must not be summed. Original failing receipts remain intact. Test-count gate35016passed; frontend2968/mobile365counts reused unchanged, not rerun. Ruff and diff check pass; canonical Bandit0new findings/errors. Preflight12passed with Node22; an initial preflight using the system Node failed only its Node check and is retained separately. Index remains empty, no publication or schedule changes.

Next executable unit: saved-config MCP reread with owner exact-plan confirmation and preserved boot load-set/owner-stop intent, described in /workspace/scratch/nerva-v8-mcp-design.md. Session diff, restart notifications, provider/device evidence and remaining697 contracts stay open. No equivalence promotions.

V7 immutable private delivery: /workspace/scratch/nerva-continuation-20261112-v7.zip;4523394bytes;SHA2564805f65a59ea370011282f85264cc4c82edaf5792609f90b2377ff780472a7f6. Clean-base apply/check/byte comparison159paths passed. Library ID libfile_fde3_f-8494caa4511081919ada184426cc75ae_4f556dba9178819182620ad30bbe8468;file file_00000000c8fc82128e110272cdc09ff3. This archive supersedes v6 for cumulative continuation; no remote code mutation.

### v8 begun — saved MCP config reread

Goal: owner-confirmed exact-plan saved MCP reread with boot load-set policy, preserving stopped/session server intent. No live provider calls, permanent always-approval switch, public writes or schedule changes. Independent rollback unit over immutablev7. command_contract(gpt-6-sol/high) owns manager/client plus saved_reload module/new reconcile tests; protocol_safety(gpt-6-sol/high) owns command handler/nonce module/new command tests; coordinator owns boot/held-row wiring, old-test adaptation, registry/docs/integration. No subdelegation.

Shared API: manager.prepare_saved_reload(configs) returns inert validated plan with fingerprint/summary; apply_saved_reload(plan,still_current=async callback) shares reload lock and rechecks authority/live identity around awaits. Handler filters with boot manager.saved_reload_load_set, uses same-owner single-use expiring confirmation and invokes saved_reload_commit_held only for current completed state. Newly registered servers stay disconnected. Root boot snapshot tests reproduced3missing-API failures before implementation (/tmp/nerva-v8-boot-red.xml). Full697 stays incomplete; no promotions.

V8 focused integration before final pre-connect fence:159passed (/tmp/nerva-v8-focused.xml). Root boot suite52passed before adding the composed saved-settings test; that real boot/settings/owner preview-confirm case passed separately, with no transport started. Manager13focused passed; handler14focused passed (overlapping tests; do not sum). Review fixed per-await owner-intent races, repeat cancellation, structured result rows, and tracked12-second close timeout/quarantine. Final review identified an additional warm_cleaner await before connect; optional pre-connect validator and registry/epoch recheck are being added with deterministic regressions before source freeze. Cleanup failure remains quarantined; cancellation waits owned teardown and may wait indefinitely for a permanently resistant close. No live transports/providers used.

### v8 integrated milestone — 2026-11-12

Final saved MCP reread includes post-warmup pre-connect authority/identity fencing and owned cleanup when cancelled after opening a replacement or previously disconnected transport. Deterministic red/green receipts cover these races; final manager+legacy module34passed. Common gateway/MCP plus adjacent security/config/command/streaming/workspace regression:5443cases,5442passed,1existingoptionalSDKskip,0failures/errors,293.435s (/tmp/nerva-gateway-v8.xml). All135recorded source hashes match. Gateway/MCP acceptance passes. Ruff, diffcheck and canonical Bandit0new findings/errors pass; Node22preflight12pass reused unchanged fromv7. Backend collection35052, unchanged frontend2968/mobile365counts. V8 is not a new full-backend/mobile/live-provider run. Index/remote remain untouched.

Saved reload is a two-minute single-use owner confirmation, not a permanent always-approval preference. New registrations stay disconnected; stopped/session state and boot load-set policy are preserved. A12-second close timeout leaves cleanup tracked; failed closes remain quarantined, and cancellation may wait for a permanently resistant teardown. These limits and live reconnect acceptance remain open, with no equivalence promotions.

Next contract clarification: verified donor tagv2026.8.31 tools/checkpoint_manager.py (blob1061874b41019ab4342cc1b2f07a21d3586e6d12) session_diff selects the earliest retained project checkpoint and explicitly labels this approximate, not exact to the current conversation. The prior plan requiring a new exact session baseline was stricter than the frozen donor. Next implementation can reuse Nerva's retained complete terminal-scope preimages, compare to the bounded current tree through read-only verified storage, and clearly report missing baseline/exclusions; do not use historical diff_group output or GitHEAD as a substitute. Donor excerpt preserved at /workspace/scratch/hermes-session-diff-reference.txt.

V8 immutable private delivery: /workspace/scratch/nerva-continuation-20261112-v8.zip;4711138bytes;SHA2566c73966e28bdc2a8f22171ebfc239d1d157e0d808ac911198c3e7ba86833ea73. Clean-base apply/check/byte comparison164paths passed. Library ID libfile_fde3_f-620c73c937608191b970a7862c8711c2_4f556dba9178819182620ad30bbe8468;file file_000000004b6c8212a6ed280ab8b26cf6. Source remains local/uncommitted; private artifact only.

### v9 begun — approximate project checkpoint diff

Goal: /diff session against earliest retained valid full-project terminal checkpoint, matching the verified donor's explicitly approximate semantics. Non-goals: new exact-chat ledger, baseline synthesis from per-file entries, GitHEAD fallback, capture/write operations, or claiming coverage for files excluded by checkpoint policy. Read-only checked storage and current-tree scan, root identity/privacy/bounds/redaction preserved. Rollback unit: new comparator and session handler path, leaving existing working/staged/all modes andv8 intact.

protocol_safety(gpt-6-sol/high) owns FileCheckpointHistory comparator, optional checkpoint_session_diff module and new backend tests; command_contract(gpt-6-sol/high) owns diff_commands handler and new command tests. Coordinator owns existing-test adaptation, docs/ledger/counts/integration. No subdelegation. API session_diff(root,stat_only,max_bytes)->ok/reason,diff,stat,baseline,excluded,approximate. Probes cover current vs historical contents, additions/deletions, oldest/pruned bases, scope/corruption/exclusions, owner command composition and no history creation on missing baseline. All local, no publication or schedule activation.

### v9 integrated milestone — 2026-11-12

Implemented approximate earliest-retained full-project terminal checkpoint comparison for /diff session, including projects without Git. Read-only immutable SQLite view refuses live WAL/invalid history; verified preimages and current-tree scan preserve scope/root identity, exclusion union and cumulative128MiB preimage bound. Full bounded output is sanitized before display; empty-file changes show actual counts. Focused union31passed, with red-before-green empty-file and aggregate memory-limit regressions preserved.

Common gateway/MCP plus adjacent and checkpoint/file-tool regression:5990cases,5989passed,1existingoptionalOpenAI SDKskip,0failures/errors,293.430s (/tmp/nerva-gateway-v9.xml). All139recorded source hashes match. Gateway/MCP area acceptance passed; Ruff/diffcheck clean; canonicalBandit0new findings/errors. Backend collection35071; unchanged frontend2968/mobile365counts reused, no new frontend/mobile/full-backend/live-provider run. Inventory697 unchanged and no promotions. No staged/committed/pushed code or schedule changes.

Next executable unit: exact hub.update shared-database intake singleton. Design /workspace/scratch/nerva-v10-update-singleton-design.md; both ordinary and mediated INSERT transactions will refuse any still-executable existing update, including deferred, without reusing task IDs or signed payloads. Typed busy result reaches command before remember-card/audit. No live updater/restart operation authorized or attempted.

V9 immutable private delivery: /workspace/scratch/nerva-continuation-20261112-v9.zip;4881736bytes;SHA2567314f86bf610571fd253ee09f58d369015fc586662528860b62548ff2f3f9c91. Clean-base apply/check/byte comparison168paths passed. Library ID libfile_fde3_f-4928caef1848819186d0e4734fb3b8a0_4f556dba9178819182620ad30bbe8468;file file_00000000f2c88212a8e85f8e77f3f6e7. Artifact captures v9 only; subsequent work below is not inside it. No publication.

### v10 begun — atomic update-card intake singleton

Goal: exact hub.update duplicate prevention across processes sharing the autonomy queue database, including proposed/blocked/approved/running/deferred and unknown nonterminal states. Refuse duplicate intake without reusing a task ID or binding a freshly computed plan to an old card. Preserve all Kernel/receipt/human approval floors. No schema migration, terminal resurrection or cross-database coordination. Non-goals: performing updates/restarts or implementing requester progress yet.

protocol_safety(gpt-6-sol/high) owns queue.py plus new singleton tests; command_contract(gpt-6-sol/high) owns irreversible.py/update_commands.py plus new composed mapping tests. Coordinator owns integration/criticalreview/docs. No subdelegation. Both insert paths use their existing BEGIN IMMEDIATE transactions; only exacttyped HubUpdateActive maps to update_in_progress. Tests cover separate processes, statuses, signed event rollback and no second card/audit. Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd remains unchanged; local-only rollback unit over immutablev9.

V10 focused integration:129passed,0skips/failures/errors in /tmp/nerva-v10-focused.xml. Separate-process singleton red8failed/5passed then green13passed; command mapping/composition24passed (overlapping, do not sum). Root reviewed exact-kind SQL guard after authorization/replay checks and before insertion, terminal-state predicate and no ID reuse. Owned fixture GPG agents were closed by exact focused basetemp homedirs after pytest; no unrelated processes touched. Expanded common regression now running; no acceptance claim yet.

### v10 integrated milestone — 2026-11-12

Common gateway/MCP/checkpoint plus expanded autonomy/queue/Kernel/update regression:6758cases,6757passed,1existingoptionalOpenAISDKskip,0failures/errors,322.221s (/tmp/nerva-gateway-v10.xml). All143recorded source hashes match. Gateway/MCP acceptance, Ruff,diffcheck andcanonicalBandit0new findings/errors pass. Backend collection35088, frontend2968/mobile365counts reused unchanged; no new complete backend/frontend/mobile/live-provider run. Owned test GPG agents closed only by this run's exact basetemp homedirs. Inventory697 unchanged, no promotions/publication/schedule changes.

Next concrete correctness unit: H081 atomic keyed delivery claim and fail-closed persistence, including existing governed channel.reply and Telegram/Discord file sends. Review found SELECT-before-write-transaction race, best-effort claiming, unchecked attempting and pruning/recovery gaps; no new restart implementation is claimed. Design /workspace/scratch/nerva-v11-delivery-design.md. Preserve bounded24h/finitecapacity semantics and unkeyed best-effort compatibility.

V10 immutable private delivery: /workspace/scratch/nerva-continuation-20261112-v10.zip;5064051bytes;SHA256af4ed7ebc076b4e483777edab3b0b83f2321b6722710b2d8b8b8ec828229d0e3. Clean-base apply/check/byte comparison172paths passed. Library ID libfile_fde3_f-74ce844d33a48191aef575f3fdbfa21b_4f556dba9178819182620ad30bbe8468;file file_00000000367482128f6ba91a635e8b76. Artifact captures v10 only; subsequent v11 edits are not inside it. No code publication.

### v11 begun — durable keyed delivery claims

Goal: shared-database atomic delivery claims, strict key validation, checked pending-to-attempting persistence and conditional recovery, with recent keyed evidence protected by finite500-row quota for documented24h window. Keyed manager/text and Telegram/Discord attachment sends withhold if evidence unavailable; unkeyed best-effort compatibility retained. Existing approval/recipient/sanitization gates remain. No bodies stored, no external sends or restart.

protocol_safety(gpt-6-sol/high) owns delivery_ledger.py/newclaims tests; command_contract(gpt-6-sol/high) owns manager.py/newfailure tests; coordinator owns Telegram/Discord attachment callsites/newmedia regression, existing Discord fixture adaptation, integration/criticalreview/docs. No subdelegation. Rollback is this local claim/delivery unit over immutablev10. Root initial media receipt contains3real Telegram fail-open regressions and4Discord failures due to not-yet-landed shared ledger API; do not call the latter defect reproduction. Discord will be rerun against complete ledger API before product change. Full /restart remains subsequent, with exact governance, durable requester route/intent, post-DONE effect and active-turn drain still needed.

V11 focused evidence: ledger/G15 union56passed; manager/G15 union57passed; root media/new+H070Discord+G16 union82passed. These overlap; do not sum. Root Discord rerun after sharedAPI landed produced4real red regressions (/tmp/nerva-v11-discord-claim-red.xml), then fix withheld file sends on missing/open/stale claims and classified raised transport as unknown. Telegram3red->3green. Existing Discord fixture now uses isolated real ledger rather than mocking it absent. Conditional claim/recovery, protectedfailedretryhistory and spawnedprocessrace tested; no live sends. Common expanded integration now running; no final acceptance claim yet.

### v11 integrated milestone — 2026-11-12

The previously interrupted wait did not cancel pytest. Final receipt verified after continuation:6798cases,6797passed,1existingoptionalOpenAISDKskip,0failures/errors,323.674s (/tmp/nerva-gateway-v11.xml). All147recorded source hashes match. Gateway/MCP area verification,Ruff,diffcheck andcanonicalBandit0new findings/errors pass. Backend collection35128, frontend2968/mobile365counts reused unchanged. No new complete-backend/frontend/mobile/live-provider run. Exact owned fixture GPG agents closed after completion. Inventory697 unchanged; no promotions/publication/schedulechanges.

Next executable unit: owner receipt history in existing HUD Channels panel, bounded metadata API and authoritative shared-database dead-target state. Design /workspace/scratch/nerva-v12-receipt-hud-design.md. Full restart remains open; no live restart/update/send attempted.

V11 immutable private delivery: /workspace/scratch/nerva-continuation-20261112-v11.zip;5267552bytes;SHA2564a0cf7fa2e2b9809e60a2b358f2200976afa68331454861c1b63b83b9c0f2a38. Clean-base apply/check/byte comparison176paths passed. Library ID libfile_fde3_f-422b3beb5b688191a90ec8985ae1c6cf_4f556dba9178819182620ad30bbe8468;file file_00000000243482129f324ef28d2146d2. Later v12 edits are not inside this artifact.

### v12 begun — owner delivery receipt history

Goal: lazy read-only receipt disclosure in existing HUD Channels panel, truthful retained counts and delivery states, no body/retry/send controls. Backend uses authoritative shared-database dead-target state and bounded list plus derived retention metadata. Preserve auth/no-cache/limit compatibility. Rollback unit over immutablev11; no live transport or external changes.

command_contract(gpt-6-sol/high) owns channels-config.tsx/newchannel-deliveries component/tests; protocol_safety(gpt-6-sol/high) owns delivery_ledger.py/integrations.py/newreceipt snapshot tests; coordinator owns parityguard/docs/status/fullfrontend/typecheck/build/commonbackend/criticalreview. No subdelegation. Exactresponsecontract retained stats/deliveries/dead_targets/health plus dead_targets_truncated and retention(window_seconds,protected_limit,protected_count,retention_seconds,ordinary_row_limit). Fullrestart remains subsequent.

V12 focused evidence: backendreceipt/G15/claim union60passed; actualHTTP auth/parity/routematrix union44passed. Newfrontend+existingChannelspanel9passed. Firstcompletefrontend2972passed; initialtsc found only newtestfetchmock typingTS2352. Fixture changed to realResponse/signature, focused9andtypecheckpassed; productbuildpassedunchanged. Completefrontend rerun onfinalfixture nowrunning, followedbycommonbackend. Sourcehashsnapshot covers614frontend/buildfiles. GitHubPR1359freshreadremainsopen/draft/unmerged,head686fcbf4f25ebfbb416b3a35dff29045163cffbd,mainbase1338833d5a344d277c43828a9d9314e10af792f1,updated2026-11-12T06:13:20Z; dirtycheckoutpreserved.

### v12 integrated milestone — 2026-11-12

Final completefrontend2972/2972passed on correctedResponse fixture;614frontend/buildsource hashes unchanged. Typecheck-final and bothHUD/Workspaceproductionbuild passed. Initialtest-onlyTS2352failure retained separately. ActualHTTP auth/parity44passed. Commonbackend6802cases,6801passed,1existingoptionalOpenAISDKskip,0failures/errors,324.558s;all153recorded sourcehashesmatch. Gateway/MCP acceptance,Ruff,diffcheck,canonicalBandit0newfindings/errors passed. FreshNode22preflight11checks passed (install_smoke not rerun; v7 smoke remains historical). Countsbackend35132/frontend2972/mobile365, mobilecountreusedwithoutmobileexecution. No newcompletebackend/liveprovider/device run.

HUDreceipthistoryreadgapclosedlocally;backendsharedDBdead-targetauthority/boundedsnapshot verified. No equivalencepromotion; frozen697unchanged. No stage/commit/push/merge/deploy/liveupdate/restart/send/scheduleactivation. NextV13 adds ephemeraladmission/boundeddrain prerequisites, then exactgovernedTelegramownerDMrestart+postbootnotice; futureworknotinsidev12artifact.

V12 private cumulative archive: `/workspace/scratch/nerva-continuation-20261112-v12.zip`, 5776750 bytes, 182 paths, SHA256 `369417a44cef32d0f08f003ddc9cb9ef6e21505d1cead5db9694e0f1fa56cabf`. Clean-base apply and resulting-byte verification passed. Library `libfile_fde3_f-11e805b5aaa08191a1801e1d90c1f5d3_4f556dba9178819182620ad30bbe8468`, file `file_00000000e7008212af0149f73979ec44`; version xattrs applied.

V13 in progress: ephemeral admission/drain prerequisite per `/workspace/scratch/nerva-v13-restart-drain-design.md`. Root owns Orchestrator; protocol_safety owns runtime/jobs/manual dispatch; command_contract owns subagents/coordinator. No restart command or physical effect implemented by this prerequisite.

V13 focused: root ingress/owner recovery 52 pass; corrected bindings+ingress+subagents 70 pass; actual parallel model gather/wait_for path + reasoning timeout 30 pass. Initial root union failed new undeclared setter; source now explicitly declares the runtime and writes the declared attribute directly. Coordinator binding line pins refreshed exactly; tests unchanged. Subagent union431pass and final six regressions pass; job/runtime union105pass. Counts overlap, not additive. Runtime initial red was missing-module collection, not a demonstrated behavior regression; job tests demonstrated four failures plus separate tick regression. Common integration running; source frozen. Remaining worker dispatch seam is explicitly outside V13 and blocks physical restart readiness.

V13 first common integration: 7241 cases, 7239 passed, one known optional SDK skip and one failure (`test_h057_command_grammar::test_an_observed_group_message_is_stored_as_written`). Ingress checked emergency controls with rewrite_bang and the admitted handler repeated the rewrite. Fixed product code to normalize once at ingress, preserving observed-group literal text; no test expectation weakened. Grammar plus restart ingress regression47passed; full common final rerun started on corrected source. Original failed receipt retained as `/tmp/nerva-gateway-v13.xml` and final run uses separate `nerva-gateway-v13-final` outputs. Derived Hermes reports regenerated after narrative/evidence updates. No physical restart readiness claim.

### V13 integrated milestone — 2026-11-12

Corrected common backend: 7241 cases, 7240 passed, one existing optional OpenAI SDK skip, zero failures/errors, 331.050s. All160 recorded source hashes matched; gateway3250 and MCP466 area cases passed from this JUnit. Backend count recollected35165; frontend2972 and mobile365 counts reused (no fresh JS/mobile run). Last actual full frontend remains V12. Final Ruff passed and canonical Bandit zero new findings/errors; generated status/preflight test union passed after count refresh. No fresh complete backend or live provider/device run. V13 primitive is deliberately not wired to a physical restart: worker claim closure, exact signed DONE proof and requester notification remain next. No schedule pause/resume or remote publication performed.

V13 private cumulative archive: `/workspace/scratch/nerva-continuation-20261112-v13.zip`, 6201643bytes,189paths, SHA256 `03d70b871cdb7384ab910872d1c0580f2f384c45104174eb00ab5b9cf479cb94`. Clean-base apply and byte comparison passed. Library `libfile_fde3_f-6c73a6d7f14c8191913151601338b820_4f556dba9178819182620ad30bbe8468`, file `file_00000000cc708212b8d728ddf80fb88d`; xattrs applied. Source freeze released for V14; later work is not in this immutable artifact.

### V14 begun — worker admission and original Telegram command provenance

Root owns Orchestrator/AutonomyCoordinator/web wiring and integration; protocol_safety(gpt-6-sol/high) owns worker/executor/runtime worker-kind and new tests; command_contract(gpt-6-sol/high) owns command_source/Telegram/Gateway/CommandContext and new tests. No subdelegation. Designs in scratch and V13 artifact. This unit adds no physical restart and no registered restart command; original source proof and worker claims are prerequisites for the following exact signed DONE flow. No persistent schedule changes.

V14 focused evidence: worker/consent/owner-once union86pass; original new-worker red4fail was absent constructor API, not executed behavior proof. Source suite17pass before additional generic Telegram dedup regression; adjacent191pass, then corrected new-source+H120 union34pass. Initial source suite fixture assumed guest handler invocation although registry correctly refused it; retained as fixture failure. Root wiring65pass, full Telegram→Gateway→Orchestrator→registry plus model-path union32pass. Root source fixture initially failed nonexistent inbox.close cleanup only; source assertions passed, fixture corrected. Separate original-command cache preserves generic H120 provider-ID behavior and prevents forged generic keys from poisoning verified candidates. Source frozen for common integration; no physical effect.

### V14 integrated milestone — 2026-11-12

Common backend8650cases:8649passed,1existing optional OpenAI SDK skip,0failures/errors,397.635s. All167 source hashes matched. Gateway3282 and MCP466 passed from the same JUnit. Final Ruff/diffcheck and canonical Bandit0newfindings/errors passed. Backend recollected35197; frontend2972/mobile365 reused without new JS/mobile execution. No full backend/native/live-provider run. Source+worker prerequisites are integrated; exact signed intent/DONE transition, physical effect fence, /restart registration and postboot notice remain V15 work. Frozen697 remains unchanged and no equivalence promotion was made.

V14 immutable private delivery: `/workspace/scratch/nerva-continuation-20261112-v14.zip`,6461459bytes,196paths,SHA256 `f1779f7b3a91897da35827f16ae17e7684853f8a643286b0ba545ae7f13ce557`. Clean-base apply/byte verification passed. Library `libfile_fde3_f-6306508c16bc8191bb51e669188c293c_4f556dba9178819182620ad30bbe8468`, file `file_00000000ffd88212af60c7bd107b024a`; xattrs applied. Final generated/preflight test union51passed. Source freeze released for full V15 governed restart; that later work is not inside this archive.


## V15 in progress — governed restart completion

Base/head remains `686fcbf4f25ebfbb416b3a35dff29045163cffbd`; local-only, 2026-11-12. Goal: original owner Telegram `/restart` source -> signed human approval -> committed DONE intent -> bounded admission drain -> one physical attempt -> same-owner availability notice after a different boot. Non-goals: live restart/send, service deployment, broad restart API, schedule changes. Root owns worker/physical hook/wiring; two gpt-6-sol/high implementers own queue authority and command/notifier independently. Rollback unit is the V15 additions over the preserved V14 archive. Focused ordering tests: 6 passed; worker admission/base regression: 25 passed. Real signed composition and common integration are still pending; no V15 completion claim. Next: prove commit/effect ordering, cancellation and revocation with signed queue fixtures, then integration.


### V15 integration review and corrections

Implemented an exact `hub.restart` Kernel/manifest entry with original-source signed tickets and retained replay tombstones. An approved RUNNING task arms a signed intent; the worker commits DONE and releases its execution permit/admission lease before the separate physical callback. Physical execution revalidates current authority/owner/bot and sibling update/restore exclusion, closes admission, bounded-waits, and consumes a durable attempt before the synchronous stopper. Requested or uncertain stops retain the gate/reservation until exit. Known pre-effect refusal releases its owned gate and records the unspent intent; missing/failed callbacks cannot replay DONE tasks. Historical signed completions can support a fixed keyed same-owner notice on a different boot; current policy, halt scopes and recipient are rechecked. Unknown transport outcomes are not retried. All physical/provider effects in tests are substitutes.

Two gpt-6-sol/high implementers delivered independent queue authority (20 focused tests) and command/notifier floors (21 focused tests); root reviewed/integrated and added real Kernel + signed worker composition, drain/cancellation/order and production wiring tests. The first integration precheck was 138 pass/10 fail: intended registry/snapshot/count changes plus four unsafe default-temp-root fixture failures. The owned 0700 basetemp run left only two count assertions; those were corrected without weakening gates. First broad V15 run: 8,704 total, 8,701 passed, 1 known optional SDK skip, 2 failures. Those failures exposed the missing `hub.restart` refusal-vocabulary entry and the V14 test's duplicate fake `/restart` registration. The vocabulary now explicitly distinguishes status-based refusals from unexpected apply failures; the wiring test uses the actual registered command and substitutes only the queue request boundary. Focused correction union: 138 passed. Initial Bandit found an exception-pass in the notifier; it now explicitly preserves unknown outcome. Final Bandit: zero new findings/errors; Ruff: all 161 changed/new Python paths pass. A fresh common run is in progress; its result is not yet asserted here.

Counts comparison verified 2026-11-12 against GitHub `main/HERMES_STATUS.md` and PR #1359 metadata: local 170 equivalent / 483 partial / 8 missing / 36 excluded; main 169 / 484 / 8 / 36. Main SHA remains `1338833d5a344d277c43828a9d9314e10af792f1`; PR remains open/draft/unmerged at base `686fcbf4f25ebfbb416b3a35dff29045163cffbd`. The local source additions have not been published and no row was promoted. Collection count is 35,252 backend; frontend 2,972 and mobile 365 reused, not rerun for this Python-only unit. Generated Hermes/status checks pass.

Live service restart, fixed Telegram delivery after a real new boot, provider/device/native-host acceptance remain unrun. The next planned unit is bounded DM-only plain-text restart coercion with original-text attestation; group prose must retain its documented semantics. Also verify historical cleanup when startup mediation is disabled then enabled in the same boot. Neither next item is claimed implemented by V15.


### V15 final local checkpoint

Fresh common run `/tmp/nerva-gateway-v15-final.xml`: **8,704 total; 8,703 passed, 1 known optional OpenAI SDK skip, 0 failures/errors; 386.345 seconds**. All 175 captured source hashes match final tested files. Gateway area: 3,336 passed; MCP area: 466 passed. The all-area verifier correctly reports other areas incomplete because this was a focused integration selection, not a full backend run; targeted gateway/MCP verification is green. Final source/count checks and Ruff/Bandit are green. Finished-run GPG agents were closed only under the owned V15 test directories. No full-backend/live/frontend/mobile run or remote mutation is implied.

V15 source is frozen for cumulative delivery; next implementation is the V16 plan in `/workspace/scratch/nerva-v16-plaintext-restart-design.md`. The private archive includes both failing and final receipts, source manifest and a clean-base patch application/byte comparison. Base/head remains `686fcbf4f25ebfbb416b3a35dff29045163cffbd`; code is not staged, committed or published.

V15 immutable archive: `nerva-continuation-20261112-v15.zip`, 6,937,650 bytes, 204 changed paths; SHA-256 `74071aaf4033710f5e65ea7a79562d4c8f648f652210d4b71489cf370dbceaca`. Clean-base apply/check and byte comparison passed. Private Library ID `libfile_fde3_f-1b3bef03cd508191b40a97db923e0ee8_4f556dba9178819182620ad30bbe8468`; file ID `file_00000000121481f5bc6379f41f7f1df9`; returned version xattr applied. Archive predates this self-reference only. The interrupted packaging tool response was checked read-only: the completed archive existed, ZIP CRC validation and application proof passed; packaging was not repeated.


## V16 in progress — private restart phrases and exact owner intake

2026-11-12, same base/head, local-only. Goal: the tiny bounded private Telegram phrase families `restart [the] gateway`, `restart [the] nerva gateway`, `restart nerva` (optional please, ASCII casing, trailing .!?/horizontal spaces, maximum 128 characters) enter the governed command route without reaching a model. Groups keep natural-language semantics; no fuzzy matching or arbitrary host commands. The frozen donor names Hermes; this port names Nerva, deliberately not the separately installable Hermes runtime. Original provider/inbox bytes remain unchanged; v2 source tickets sign exact original text, and v1 literal-/restart tickets remain verifiable. Rollback unit is V16 over the immutable V15 archive.

Root owns orchestrator and physical/boot helper integration; the two gpt-6-sol/high agents own source/ticket authority and Telegram transport separately. No subdelegation. Relevant paths: command_source.py, autonomy/restart_records.py, channels/telegram.py, orchestrator.py, hub_restart_apply.py and restart phrase/authority/composition tests.

The new actual Telegram→Gateway→Orchestrator→real Kernel→signed queue composition exposed a functional V15 gap: channel `inbound` origin made generic intake add taint fields after the source ticket was signed. The exact-payload gate correctly refused it, so a real original channel request could not queue. The fix does not relax generic worker/Kernel taint: only request_restart, after exact live source/owner verification and ticket issuance, classifies its fixed original human control intent as manual for the owned enqueue and restores the prior context in finally. Derived/recall/external/model origins and active model producers are refused. Private literal/canonical /restart dispatch happens before pending-input/history/project processing, reads no conversation data, and still crosses the registered owner tier, signed card and separate human approval. Generic copied-ticket inbound enqueue still fails; no kind-wide taint exception exists. Tests now traverse the real adapter and signed Kernel queue through human approval and committed DONE before one mocked physical call; a second worker tick cannot replay it.

A separate regression failed before and passed after boot metadata recovery was separated from live execution mode. It records known old-boot no-effect intents even with execution disabled; physical claim and notice floors remain independently enforced. Root ingress regressions first showed six expected failures, then passed after routing changes. Full pipeline: 14 passed; context-floor/composed union: 28 passed. Peer authority/phrase: 52 passed; source/composed: 37 passed; transport/source: 33 passed (overlapping sets, not additive totals). Common integration remains pending. No new equivalence promotion or live restart/send.


### V16 first integration and update exclusion correction

First common run `/tmp/nerva-gateway-v16.xml`: 8,773 total, 8,772 passed, 1 known optional SDK skip, 0 failures/errors, 393.527 seconds. All 178 captured source hashes matched that run. Before archiving, review identified that restart used the updater's permissive UI `current()` reader, which returns None for unreadable/malformed state. A regression reproduced the problem (11 fail, 1 pass), including a mocked physical stop when a malformed marker existed. No real stop occurred.

Restart now checks only filesystem presence: any current.json entry blocks, so no potentially large/private file is decoded. Missing-file acceptance rechecks the selected directory identity/mode/mtime; symlink/non-directory state roots and filesystem errors fail closed. The existing updater UI reader is unchanged. This is a local guard and does not claim an interprocess lock. Focused state-exclusion/physical/composed/notice union: 67 passed after the fix. Final broad integration is required before V16 archive. Model taint rules, approval defaults, inventory counts and external schedules are unchanged.

### V16 final local checkpoint — 2026-11-12

Final common integration `/tmp/nerva-gateway-v16-final.xml`: **8,785 total; 8,784 passed, 1 known optional OpenAI SDK skip, zero failures/errors; 411.337 seconds**. All179 captured source hashes match. Gateway3417 and MCP466 passed from that same JUnit. Final Ruff165changed/new Python paths, canonical Bandit0newfindings/errors, diffcheck, generated Hermes/status checks pass. Backend35333collected; frontend2972/mobile365 counts reused, with last full frontend execution V12. No complete backend or live provider/device acceptance is claimed.

V16 closes the bounded private phrase, actual original-owner intake and disabled-mode historical metadata cases locally; unreadable update state now blocks restart. Tests use mock physical stoppers/transports. Local ledger remains170equivalent/483partial/8missing/36excluded of697 (24.4%); freshly fetched main report remains169/484/8/36 (24.2%). No promotion, stage, commit, push, merge, deployment, live action or schedule mutation. Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. Checkpoint and cumulative patch are frozen for V16 private archive.

Next V17: bounded owner `/update status` fixed-vocabulary pull readout, preserving no-argument approval behavior and no effects. Detached push progress remains open. H081 automatic reply keys require native stable provider provenance, confirmed inbox writes and a separate batching design; inbox row IDs and route kwargs alone are not proof. Continue independent local implementation, preserving all prior changes.

V16 immutable private archive: `nerva-continuation-20261112-v16.zip`,7390686bytes,208paths,SHA256`dda2a6186f93a97b833d3e3c60b41580929afd3ea92b1f40a16ea7d6adaf0872`. ZIP CRC, clean-base apply/check and resulting byte comparison passed. Library`libfile_fde3_f-c66a848d1f088191bfbdf4ebe4e18e42_4f556dba9178819182620ad30bbe8468`,file`file_0000000087d481f5a79cceee1d6dd158`; returned xattr applied. Archive predates this self-reference. Source freeze released for V17; future work is not in V16 artifact.

## V17 in progress — owner update status

Local-only, same base/head. Implement bounded `/update status` readout; no-argument update still requests a human-approved card. Protocol agent owns new update_progress.py/reader tests, command agent owns update_commands.py/commands.py/status tests, root integrates and reviews. Both gpt-6-sol/high, no subdelegation. Design `/workspace/scratch/nerva-v17-update-status-design.md`. Readout must distinguish unavailable from absent, match stored progress to exact latest task, and expose fixed vocabulary only. No detached push progress or complete H084 claim. V16 archive remains immutable.

### V17 final local checkpoint — 2026-11-12

Owner `/update status` now reports bounded recorded state, matching exact latest update card and refusing malformed/unavailable/stale progress; no-argument request and human approval remain unchanged. No raw log/path/reason is projected. Reader31focused, command+existing57focused, real SQLite composition3passed (overlap; not additive). Initial root3failures showed old usage refusal; reader initial missing-module red and two early receipt-call failures were corrected and retained separately.

Final gateway integration `/tmp/nerva-gateway-v17.xml`: **3655passed, zero failures/errors/skips,179.517seconds**; gateway3488passed from same receipt. All183captured source hashes match. Final count/preflight51passed after correcting collection timing for the last2reader tests. Backend35404collected; frontend2972/mobile365 counts reused, not rerun. Ruff169changed/new Python paths passed; targeted Bandit on new reader/changed command0findings/errors; generated checks/diffcheck passed. V16 broader8784pass/1skip remains historical for its source; no new full backend or live provider/device/service acceptance claimed.

Ledger remains170equivalent/483partial/8missing/36excluded of697. Bounded pull status does not close detached update execution or push-progress gap. All source local, unstaged/unpublished. Next V18 adds literal scoped /diff path filters using current hardened Git/checkpoint boundaries; no schedule or live service change. V17 source frozen for private cumulative archive; future V18 is not part of it.

V17 immutable private archive: `nerva-continuation-20261112-v17.zip`,7497532bytes,212paths,SHA256`bcbb85cecbe328870568af17c2fb43f32a51033b8d2adb1f699e6582fead9309`. CRC, clean-base apply/check and byte comparison passed. Library`libfile_fde3_f-948b9b367e58819193340de59cf7018d_4f556dba9178819182620ad30bbe8468`,file`file_000000001a1c81f5ac8fb45b79775d75`; returned xattr applied. Archive predates this self-reference only. Source freeze released for V18.

## V18 in progress — literal project-relative /diff filters

Same base/head, local-only. Parser/Git agent owns diff_commands.py/commands.py/new path-command tests; protocol agent owns shared diff_paths validator, checkpoint_session_diff.py/history wrapper/new selector tests; root owns composed tests and existing opposite-usage assertion adjustment, integration and docs. Both gpt-6-sol/high, no subdelegation. Exact project-relative semantics chosen; Git translates project subdirectory to repository-relative literal pathspec, session stays inside project scope. Grammar supports bare paths or explicit -- for option-like names; no shell or Git magic. Bounds8paths/256UTF8bytes each/1024total; no absolute/traversal/control/backslash/glob/colon. Full original checkpoint validation/scanning and approximate-baseline warning remain. Design in V17 NEXT.md; V17 immutable archive contains none of this future implementation.

V18 focused implementation: backend validator/comparator50passed; command/registry/actual Git/session-composed union61passed after root review restored all legacy option aliases/casing and refused malformed Unicode. Initial composed test demonstrated missing selection behavior (1fail/1pass). Explicit empty backend selection compares zero rows while validating the full baseline; None remains unfiltered. Root adjusted the old opposite Usage assertion for newly supported `/diff app.py`. No equivalent promotion.

Generated backend count35484; frontend2972/mobile365 reused. Ruff touched paths and generated checks pass; canonical Bandit0newfindings/errors. Full backend milestone is next, without keyword filter. Disk was near full from completed pytest fixtures; only owned completed V7 basetemps were removed after preserving their JUnit/log/archive evidence. Read-only test directories needed owner permissions restored for cleanup; symlinks were not followed. Free space9.6GiB. Receipt `/tmp/nerva-v18-temp-cleanup.json`. Sources frozen for full run; no live effect or remote mutation.

### V18 complete-backend first run and fixture corrections

`/tmp/nerva-backend-v18.xml`:35484total,35371passed,108skipped,5failed,0errors,950.294seconds. All187source hashes matched. Failures: two H450 fallback scheduler tests still mocked old public fire seam although admitted tick now runs real protected `_fire_once`; cloud image injected mediation failure at old `_run_runnable` frame rather than `_run_runnable_admitted`; Windows OCR test mutated shared global sys.platform, making lazy pypdf/shutil imports take an invalid Windows branch on POSIX; roadmap headline still said56uncalled routes after HUD receipt wiring reduced the actual punchlist to55.

Corrections preserve product guards: scheduler tests use real JobRun results with delivery disabled and assert minute/zone/dedup/attempt count; cloud fault injection moves to actual pre-handler validation and keeps no-handler/no-capability-outcome assertions; Windows tests replace module-local sys references and assert global platform stays unchanged; roadmap count follows existing unchanged integrity test. Scheduler133focused pass, doc-integrity6pass; cloud/OCR focused result pending at this entry. No production implementation change for these5failures. Original full receipt retained. Completed V10/V11 pytest basetemps removed (JUnit/logs/archives retained) to reserve space for a fresh uninterrupted full rerun; current V18 failure fixtures retained.

Cloud/OCR correction union143passed/5native-or-optional skips of148collected; isolated initial2failures retained in `/tmp/nerva-v18-diagnose.xml`. Final Ruff177changed/new Python paths pass. Source frozen for `/tmp/nerva-backend-v18-final.xml` full rerun; no success is asserted before it finishes.

### V18 final complete-backend checkpoint — 2026-11-12

Fresh uninterrupted full run `/tmp/nerva-backend-v18-final.xml`: **35,484 total; 35,376 passed; 108 skipped; zero failures/errors; 919.899 seconds**. All 191 captured source hashes match the tested files. The runner exited 0 after closing only its owned completed-test GPG agents. Hermes acceptance reports **23/23 area suites pass** from this same JUnit; area counts overlap and must not be summed. Gateway includes 3,568 passed. Generated Hermes/status checks and diff check pass; Ruff covers all 177 changed/new Python files. Canonical Bandit on agents/scripts reports zero new findings/errors; production code was unchanged during the fixture correction round.

The 108 skips are recorded in `/tmp/nerva-v18-final-skip-reasons.json`, including isolated Chrome/Playwright, native Windows, Docker containment, unavailable namespace support, Neo4j live, Rust/fish tooling and installed Hermes sidecar requirements. A passing area may contain skipped platform cases; this is not native/live acceptance. Last complete frontend execution remains V12 (2,972 passed, typecheck/build); mobile 365 is a reused collection count, not a fresh run.

Current local ledger: **170 equivalent / 483 partial / 8 missing / 36 excluded, total 697 (24.4%)**. Fresh GitHub verification still shows main **169 / 484 / 8 / 36 (24.2%)**, SHA `1338833d5a344d277c43828a9d9314e10af792f1`. PR #1359 remains open/draft/unmerged at `686fcbf4f25ebfbb416b3a35dff29045163cffbd`. No equivalence promotion or scope reduction. All continuation changes remain local and unstaged; no commit, push, merge, deployment, live restart/send, paid activation or schedule change.

Next V19 is an acknowledgement-correctness unit: strict Telegram success proof and a permanent uncertain-draft fence, with unknown/partial ledger outcomes and no replay. A read-only fake-response probe reproduced both formatted and plain sends claiming success on missing/zero IDs and ok:false. No V19 implementation is claimed in this V18 archive. H032's native-versus-sidecar choice remains a row-specific documented dependency; the fixed 697 objective is not narrowed, and independent local work continues.

V18 immutable private archive: `nerva-continuation-20261112-v18.zip`, 8,993,333 bytes, 221 changed paths, SHA-256 `4665bd47da556dc1256a96c282594c2923f2e27d753d23666ad64ce90d37140f`. ZIP CRC, clean-base apply/check and applied-byte comparison passed. Library `libfile_fde3_f-4872ec636d208191b4c0d50d79d80e2c_4f556dba9178819182620ad30bbe8468`, file `file_000000009ce881f5b75a7131dbbcd341`; returned xattr applied. The packaging session ID was no longer available at polling; the already completed ZIP and apply proof were checked read-only and packaging was not repeated. Archive predates this self-reference only. Source freeze released for V19.

## V19 in progress — strict Telegram acknowledgements and uncertain drafts

Same base/head, local-only. Protocol agent owns delivery_ledger.py and helper tests; command agent owns Telegram transport, realistic render/stream fixtures and new acknowledgement tests; root owns actual Manager/SQLite and Orchestrator composition, review and documents. Both implementers remain gpt-6-sol/high with no subdelegation. `note_unconfirmed_ack()` records fixed missing_ack + ambiguous without erasing partial/dead/fatal flags. Telegram success requires ok:true and a positive integer message ID. A permanently uncertain draft must retain ownership of delivery so the orchestrator cannot replay the entire response; no later frame/edit/final/media/voice fallback may send after ambiguity. This unit adds no retries and does not claim draft receipt coverage or full H081 equivalence. Root read-only probe demonstrated existing false success on malformed2xx; formal regressions and final integration are in progress.

V19 review closed two additional replay gaps before common integration: HTTPX DecodingError/TooManyRedirects are RequestError rather than TransportError, so they now classify ambiguous after the explicit pre-connect exclusions; cancelled in-flight draft sends/edits latch uncertainty and re-raise cancellation. Focused request-error ledger/manager suite46passed; draft/adapter/composed suite80passed. Suspended first POST regression failed before the cancellation fix. Root adjusted existing success mocks to echo edit message IDs and corrected the push docstring to state cancellation propagation. Generated backend count35552, frontend2972/mobile365 reused. Ruff181changed/newPythonpaths and generated checks pass. V19 common gateway/MCP plus related security/autonomy/Telegram suites running with source manifest; no new live acceptance or equivalence promotion.

### V19 verified checkpoint

`/tmp/nerva-gateway-v19.xml`: 9040 total, 9039 passed, 1 skipped, 0 failures/errors, 400.706 seconds. Gateway/MCP area acceptance verified from this JUnit; this is not a new full-backend run. All195 recorded source hashes match the tested bytes. Canonical Bandit agents/scripts: zero new findings/errors; Ruff181changed/newPythonfiles, generated status and diff checks pass. Backend35552collected; frontend2972/mobile365counts reused, no new frontend changes. V18 remains the latest uninterrupted complete backend result (35376passed/108skipped of35484).

Cancelled first send, mid edit and final transport propagate cancellation and prevent later draft/media/voice attempts; HTTPX decoding/redirect errors preserve unknown delivery. Real manager keyed unknown/partial receipts and Orchestrator no-whole-reply fallback are covered offline. No live Telegram acceptance, automatic retries or durable streamed-draft receipts. H081 stays partial; ledger170equivalent/483partial/8missing/36excluded of697. Main comparison169/484/8/36 remains from V18 remote read at1338833d5a344d277c43828a9d9314e10af792f1.

V19 source frozen for cumulative private archive. Next V20: addressable visible command tokens in Telegram group help, using only current verified bot identity; preserve access filtering and other channels. No publication, external schedule change or live operation.

V19 immutable private archive: `nerva-continuation-20261112-v19.zip`,9250774bytes,225paths,SHA256`5ca586f6fc78f3ec260c5f31aa06145ddc1fae32cbfe14365dc1f6022084b218`. CRC and clean-base apply/check/result-byte comparison passed. Library`libfile_fde3_f-5c975bf66c30819180a3df70b3528872_4f556dba9178819182620ad30bbe8468`,file`file_00000000a88881f58214acc0c90a46f5`; xattrs applied. Archive predates this self-reference only. V20 freeze released.

## V20 in progress — addressable Telegram group help

Same base/head/local-only. Command agent gpt-6-sol/high owns commands.py and new help-mention tests; root owns composed default-registry/real-adapter/group-gate/access-floor regression, docs and integration. Only visible command tokens at line start are qualified using current verified live bot identity. Other channels, DMs, prose, URLs and guest owner examples remain unchanged. No dispatch/access changes. Root composed regression fails before implementation: group help emits bare /help and /whoami. Receipt `/tmp/nerva-v20-composed-red.xml`. Design/rollback in V19 NEXT.md.

V20 initial common run `/tmp/nerva-gateway-v20.xml`:4330total,4312passed,18failed,0skipped/errors,182.175seconds. All failures are V19 draft transport tests in test_h081_telegram_ack.py: a known-secret redactor installed by earlier tests correctly makes safe_stream_prefix withhold incremental text; the new transport-only tests did not isolate that process state. Prior V19 common9040result remains a real passing run under its different order, not proof of order-independent fixtures. Production safety remains unchanged; isolating the fixture and reproducing with a preinstalled redactor before rerunning integration. V20 help116focusedpassed.

V20 isolation correction: preinstalled identity known-redactor reproduced5/5 draft failures in `/tmp/nerva-v20-ack-isolation-red.xml`. Added per-test monkeypatch restoration of `_known_redactor=None` only in the ACK transport tests, mirroring composed transport fixture. Same preinstalled-redactor run48passed; ACK/H069/streaming adjacent111passed. H069 retains actual redactor buffering coverage and production security unchanged. No test count change. Final common run restarted with fresh basetemp and source manifest; initial failed evidence retained.

### V20 verified checkpoint

Final fresh common `/tmp/nerva-gateway-v20-final.xml`:4330passed,0skipped/failures/errors,178.459seconds. Gateway area verified from complete area suite in this run; all197source hashes match. CanonicalBandit0newfindings/errors; Ruff183changed/newPythonpaths passed before test-fixture-only correction and corrected test rechecked; generatedstatus/diff checks pass. Backend35570collected, frontend2972/mobile365reused. Latest full backend remains V18; V19 common9040 passed; initial V20 order-dependent test failures and fix evidence retained.

Telegram group help now gives addressable visible registered/quick command headers only with current verified live bot identity. Guest filtering, owner examples, prose, DM/web unchanged. H057 remains partial for remaining platform/operator acceptance; no live API call or native menu registration performed. Ledger170equivalent/483partial/8missing/36excluded of697. All source local unstaged/unpublished. Next V21: signed-extension-only body-free command.started observation, no veto/rewrites/owner-hook audience expansion.

V20 immutable private archive: `nerva-continuation-20261112-v20.zip`,9484780bytes,227paths,SHA256`69dcb8f56fc5bcfbbb7f118aa4ceba294a3b8a6d6605febe88a7c982168d5f80`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-1efcaaf95d38819194efda220505215a_4f556dba9178819182620ad30bbe8468`,file`file_00000000f61c81f5bedf78f107bcdb21`; returned xattr applied. Archive predates this self-reference only; V21 freeze released.

## V21 in progress — signed-extension command dispatch observation

Same base/head; two gpt-6-sol/high implementers, no subdelegation. Protocol agent owns manifest/events schema and subscription tests; command agent owns dispatch emission/new dispatch tests/existing event-emission assertions; root owns actual-bus composition, integration/docs. New command.started carries canonical registered command name only after existing access/admin/oversized-refusal/source checks, immediately before handler. No args/principal/reply/veto/rewrite, no awaited observer delivery. Handler-specific validation and plugin effect consent remain inside handlers. No owner-hook catalogue/map expansion. Changed subscription requires fresh existing consent digest. Root composed actual-bus/hanging-observer regression fails before implementation (missing event timeout); `/tmp/nerva-v21-composed-red.xml`.

### V21 verified checkpoint

`/tmp/nerva-gateway-v21.xml`:4494passed,0skipped/failures/errors,185.375seconds. Complete gateway area verified in this run, plus extension/owner-hook/command regressions;203source hashes match. Ruff189changed/newPythonpaths, canonicalBandit0newfindings/errors, generatedstatus/diffchecks pass. Backend35587collected; frontend2972/mobile365reused. Root actual-bus composition passed; focused dispatcher127passed, schema/consent92passed (overlapping tests, not additive); final subscription9passed after removing an assertion that would have pinned an existing misleading diagnostic.

Signed-extension command.started now observes canonical lower-case registered handler entry only, body-free and with no authority/return channel. Old consent digests retained, new subscription requires fresh consent, owner hooks unchanged. H080 stays partial: no plugin veto/rewrite/reaction support, not every namespace observed, no live sandbox acceptance. Existing event diagnostic can list a synchronously dropped observer as delivered; cap/drop counter and task behavior remain correct. This independent diagnostic issue is recorded, not treated as proof of actual execution.

Fresh GitHub read during this run: main1338833d5a344d277c43828a9d9314e10af792f1 remains169equivalent/484partial/8missing/36excluded; PR1359open,draft,unmerged at686fcbf4f25ebfbb416b3a35dff29045163cffbd. Local170/483/8/36of697. Receipt `/tmp/nerva-v21-remote-comparison.json`. No publication or live activation. Next V22: consent-bound optional argument-required extension-command metadata and Telegram menu exclusion, with backward compatibility.

V21 immutable private archive: `nerva-continuation-20261112-v21.zip`,9636476bytes,233paths,SHA256`e7ad9de23c8df4b3cfe0ea3066dc762b036ffc6b6c876fc0e402dd911f3062d8`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-573fe30d23e48191a499a55719d74361_4f556dba9178819182620ad30bbe8468`,file`file_000000000fcc81f5952b376cd8234462`; returned xattr applied. Archive predates this self-reference only; V22 freeze released.

## V22 in progress — consent-bound argument-required command metadata

Same base/head/local-only. Protocol agent owns optional manifest subset and conditional consent digest/surface with tests; command agent owns SlashCommand metadata/runtime propagation/Telegram projection with tests; root owns real activation/startup-menu/guest-owner-revocation composition and integration/docs. Both implementers gpt-6-sol/high, no subdelegation. Manifest absent/empty preserves historical consent identity; nonempty declaration requires new consent. Typed dispatch remains through existing authority; Telegram projection omission is not argument validation and does not grant permission. No live republish added. Root composed regression fails on missing requires_args after successful simulated-sandbox activation; `/tmp/nerva-v22-composed-red.xml`.

Disk cleanup: removed only completed owned `/workspace/scratch/nerva-backend-v18-final` fixture tree after V18 full receipts and cumulative V21 archive preserved;141345generatedfiles/6049237383bytes removed. Sources, JUnit/logs/manifests/archives retained. Receipt `/tmp/nerva-v22-temp-cleanup.json`; no live service or unknown directory touched.

V22 root review found CLI _extension_descriptor omitted new metadata and offline doctor hid it; two regression failures `/tmp/nerva-v22-visibility-red.xml` (activation composition already passed), followed by107passed across composed/doctor/activationroute/manifest/consent after root fixes. Activation response now also exposes metadata. Precise boundary: descriptor metadata is owner-consented and bound to declaration digest, not cryptographically attested by sandbox register output; signed package/code and all existing authority checks remain. Docs/EXTENSIONS.md describes metadata, current startup-only native menu refresh, and V21 observation semantics. Protocol77focusedpassed; runtime/menu117focusedpassed plus59afteractivationmetadata (overlapping selections).

V22 initial common `/tmp/nerva-gateway-v22.xml`:4525total,4522passed,3failed,0skipped/errors,187.422seconds. Three existing H069 native-metadata cases used SimpleNamespace stand-ins lacking the new optional SlashCommand field. Root converted their shared command factory to real SlashCommand objects with default requires_args=False; assertions for secret-name refusal, description masking-before-truncation and redactor failure remain unchanged. No production guard relaxed. Final common rerun follows.

### V22 verified checkpoint

Final fresh `/tmp/nerva-gateway-v22-final.xml`:4525passed,0skipped/failures/errors,186.356seconds. Complete gateway area plus extension/command/CLI/owner-hook selections pass;208source hashes match. Ruff194changed/newPythonpaths passed before final native-fixture-only correction, corrected test rechecked; canonicalBandit0newfindings/errors; generatedstatus/diffchecks pass. Backend35606collected; frontend2972/mobile365reused. Initial3failures retained with17test fixture/projection regression green; root CLI/doctor missing-metadata regression2failures retained with107test green.

Required-argument extension metadata is optional/backward-compatible and consent-bound; Telegram projection excludes marked commands before cap, while typed owner dispatch and live permission/package checks remain. Metadata is exposed through CLI/doctor/activation responses. No live menu republish, Docker/provider acceptance or equivalence promotion. H079 remains partial. Local170equivalent/483partial/8missing/36excluded of697; main169/484/8/36 per fresh V21 remote read. All source unstaged/unpublished.

Next V23 addresses demonstrated unbounded off-loop observer callback admission: 100callbacks queued despite max_pending2 because cap checked only in _spawn. Reserve queued+running capacity before scheduling, correct immediate diagnostic to admitted scheduling, preserve payload/authority/smart context and captured-loop ownership. Existing drain snapshots only materialized tasks; no claim of queued-callback shutdown draining.

V22 immutable private archive: `nerva-continuation-20261112-v22.zip`,9892953bytes,238paths,SHA256`657e5db14294bb610b0c640219c6787573695747989f4047df73766f3d54734a`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-b739516b9aa08191824390fd5af435ee_4f556dba9178819182620ad30bbe8468`,file`file_00000000bbc481f581f079f77b968954`; returned xattr applied. Archive predates this self-reference only; V23 freeze released.

## V23 in progress — bounded queued observer admission

Same base/head/local-only. Protocol agent owns events.py/admission regressions/existing report assertions; command agent owns independent real-thread/loop tests; root owns actual registry-to-paused-loop composition, review/docs/integration. Two gpt-6-sol/high implementers, no subdelegation. Reserve queued+running capacity atomically before scheduling; release on completion/cancel/scheduling/task-creation failure; immediate delivered list means admitted scheduling, not observer success. Preserve smart-event empty context and pin task creation to captured loop; lazy first loop pin under lock when no loop captured. Closed captured loop refuses instead of silently switching. Drain snapshot limitation remains explicit, no shutdown scope added. Root composition100commands/cap2 fails before fix because old bus ignores paused captured loop and creates tasks on caller loop; `/tmp/nerva-v23-composed-red.xml`.

V23 focused verification: protocol agent reported5expected red failures and71passed union in console-only runs (no JUnit produced); root does not represent them as archived XML. Independent thread suite red4/5failures `/tmp/nerva-v23-observer-red.xml`, final7/7passed `/tmp/nerva-v23-observer-final2.xml`; adjacent54passed `/tmp/nerva-v23-observer-adjacent.xml`. Root composition red preserved. Root/independent review found no concrete blocker; emit docstring corrected to acknowledge payload-validation errors and distinguish admitted scheduling from actual observation. Final integration captures all new tests with source hashes/JUnit.

V23 initial common run found a real unrelated initialization race: test_h081_delivery_claims::test_two_spawned_processes_can_claim_one_key_only_once failed because a child hit sqlite3.OperationalError database-is-locked at ReliabilityStore PRAGMA journal_mode=WAL before its ready signal. The single-key assertion is unchanged. Observer tests passed, but common batch is not accepted yet. Protocol agent owns a narrow ledger initialization correction/new regression file; V23 observer source remains frozen. Retry only transient SQLite BUSY/LOCKED under a bounded startup budget, preserve nonlock errors and close failed connections; no network retry, schema, claim or idempotency relaxation. Root integration will rerun after this concrete correctness fix.

V23 correctness follow-up: protocol implementer was interrupted before final verification; root preserved its code and completed lock-code/timeout assertions, method spacing and test execution. `/tmp/nerva-v23-startup-final.xml`:69passed across startup regression, actual spawned-process keyed claim, receipt snapshot and G15 reliability; Ruffpassed. WAL promotion only retries BUSY/LOCKED primary codes (extended-code mask), three1second SQLite busy windows plus50/100ms pauses, restores10000ms on success, closes constructor connection on all failures. Nonlock error text cannot trigger retry. No broader SQLite policy, network resend, schema or claim changes. Initial common was4591total4590passed1failed199.289seconds; final integration rerun is required.

### V23 verified checkpoint

Final fresh `/tmp/nerva-gateway-v23-final.xml`:4600passed,0skipped/failures/errors,186.401seconds. Complete gateway area verified;213source hashes match. Ruff199changed/newPythonpaths clean, canonicalBandit0newfindings/errors. Backend35631collected, frontend2972/mobile365reused; last complete backend execution remains V18. Initial common WAL startup failure retained, deterministic lock-code/cleanup regressions and unchanged real spawned-process claim test now pass.

Observer admission now bounds queued callbacks plus running tasks, respects captured-loop ownership and reports admitted scheduling accurately. SQLite WAL initialization retries only bounded BUSY/LOCKED errors and closes failed connections; no retry of network sends or weaker claim semantics. Local170equivalent/483partial/8missing/36excluded of697; main169/484/8/36 at1338833d per2026-11-12T22:43:51Z remote read. H080/H081 remain partial; no live platform/provider/device acceptance. All source unstaged/unpublished.

Next V24: bounded owner-only quick-command, skill and bundle discovery in HUD/mobile using additive API fields, preserving existing registry rows and permission filtering. No invocation or publication during discovery.

V23 immutable private archive: `nerva-continuation-20261112-v23.zip`,10164766bytes,243paths,SHA256`7a221bdc5964ffbba5dc5bd22b48a9d02c15447e9be56010c3f4b73dae00da90`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-c8c846eeb7b081918be53a66b27c3fe3_4f556dba9178819182620ad30bbe8468`,file`file_00000000643c81f59a219b808ca2203a`; returned xattr applied. Archive predates this self-reference only; V24 freeze released.

## V24 in progress — owner shortcut discovery in HUD/mobile

Same base/head/local-only. Two gpt-6-sol/high implementers, no subdelegation: backend owns additive catalogue projection and tests; UI owns both pickers and tests. Root owns critical review, composition, schema/build/parity/docs/integration. Design at /workspace/scratch/nerva-v24-next.md. No live discovery execution/publication.

V24 focused implementation complete: backend catalogue18passed (includes root composed test), HUD16passed/native picker17passed and frontend typecheck passed. Backend agent initial red and final receipts retained; native initial4failed/12passed before implementation. Root's file named `/tmp/nerva-v24-composed-red.xml` actually passed because implementation landed during its execution; it is NOT red evidence. Root separate composed/OpenAPI guards passed. Critical review corrected raw quick-name filtering before lowercase normalization and confirmed bundle snapshot partial-source semantics. Skill pools over512 refuse projection to avoid resolving ambiguity against a partial inventory; guest requests skip private reads. Ruff found constant getattr style in helper, root replaced it with identical direct property access; final all204changed/newPythonpaths clean. Pinned OpenAPI generated offline without app lifespan; first npx failed on unwritable default cache, succeeded with owned scratch cache. No live service restart. Full frontend and integration verification pending.

V24 frontend integration: Node22 complete HUD suite2977passed/0failed/0pending; complete native-shim Vitest181passed/0failed/0pending (separate from mobile Jest365 tracked/reused). Frontend tsc and both Vite builds passed; workspace build produced no source diff. Generated frontend count refreshed from actual JSON; backend35639freshlycollected, mobile365reused, no native SDK typecheck/device claim. Full common backend integration now running on frozen source/build hashes. Fresh GitHub read2026-11-12T23:39:30Z confirms main1338833d at169/484/8/36, PR1359stilldraft/open/unmerged at686fcbf4; local170/483/8/36 unchanged.

### V24 verified checkpoint

Final common `/tmp/nerva-gateway-v24-final.xml`:4635total,0failures,0errors,0skipped,201.045seconds; all224source/build hashes match. Includes full gateway, command/extension/hook, HUD parity, route-auth, OpenAPI and lifecycle selections. Full frontend2977passed, native-shim181passed, frontend typecheck and both builds passed. Ruff204paths and canonicalBandit0newfindings; generated status/checks pass. Backend35639collected, mobileJest365reused. Last fullbackend remains V18. No live platform/provider/device acceptance.

HUD/mobile now discover bounded owner quick/skill/bundle shortcuts without execution or body disclosure; old payload compatibility and credential/scope clearing covered. H079stayspartial, local170/483/8/36of697. Main169/484/8/36at1338833d and PR1359draft/unmerged freshlychecked23:39UTC. Allsourceunstaged/unpublished. NextV25: opt-in owner-only mobile receipt metadata using existing read endpoint, no resend/dead-target actions.

V24 immutable private archive: `nerva-continuation-20261112-v24.zip`,10570924bytes,254paths,SHA256`37d5a4a6f0837f4cd872ca8ec1758bee97581980b310a12a0438045568051e9b`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-537bc13bd7588191b48054a903560f8e_4f556dba9178819182620ad30bbe8468`,file`file_000000008aa081f59dfa1f62113a90b3`; returned xattr applied. Archive predates this self-reference only; V25freeze released.

## V25 in progress — opt-in mobile delivery receipts

Same base/head/local-only. One gpt-6-sol/high implementer, no subdelegation, owns mobile API/component/Status entry and native tests; root owns critical review, independent checks and cumulative evidence. Design /workspace/scratch/nerva-v25-next.md. Existing admin-guarded metadata endpoint, no backend change, no resend/dead-target mutation. Fetch only after opening; bounded payload, scope/credential fences and generic failure UI. No real mobile device/provider acceptance.

### V25 verified checkpoint

Mobile Status opt-in receipt view implemented. Current complete native-shim suite `/tmp/nerva-v25-native.json`:190passed/0failed/0pending; focused receipt+Status30passed. Actual locked mobile dependencies installed with npm ci --ignore-scripts in local ignored node_modules, no package/lock change. Native mobile tsc passed on all final source files; all365Jest tests passed (`/tmp/nerva-v25-mobile-jest.json`). The new receipt tests are native Vitest, not included in the365Jest count. Full HUD2977 and common backend4635passed at V24; neither source surface changed in V25. No new backend behavior/test count; Bandit/Ruff reused from V24. Generated status/Hermes/diff checks pass;219currentPython/TSsource hashes match captured freeze. No real device/platform/provider acceptance.

Critical review confirmed bounded validation, native finite timestamps, extra body/key/error payloads discarded, no receipt request before opening, owner credential headers, no retries/redirect following, and scope/credential/refresh/close/unmount fences. No mutable send/clear action exposed. H081 remains partial for broader reliability contracts; local170/483/8missing/36excluded of697 unchanged. Allsourceunstaged/unpublished. NextV26: metadata-only ledger receipts on existing manager prompt/card transports, preserving their authority/native ACK contracts; no automatic resend or key derivation.

V25 immutable private archive: `nerva-continuation-20261112-v25.zip`,10621023bytes,258paths,SHA256`f4391fb8798ec8ce0484e03ee876a73cd499c7723863fc0c0d5138fe290ff7d7`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-8819a247bc24819195d1d1b0e604c0b5_4f556dba9178819182620ad30bbe8468`,file`file_00000000deb881f5985baaecdf444755`; returned xattr applied. Archive predates this self-reference only; V26freeze released.

## V26 in progress — prompt/card receipt ledger

Same base/head/local-only. One gpt-6-sol/high implementer owns manager wrapper/tests; root owns critical review, actual Telegram HTTP composition and narrow Telegram outcome notes, integration/docs. No subdelegation. Manager callback retains validated native receipt while ledger stores metadata only; cards require a usable native ACK, preserve explicit adapter failure notes, and reject supplied delivery_key because duplicate native receipts cannot be recovered. ntfy current() stays inside adapter; no retry/key derivation. Root actual Telegram composition first had incomplete stopped-adapter setup; corrected running/generation setup then reproduced a real403reportedunknown failure in `/tmp/nerva-v26-composed-red2.xml` (4passed1failed). Added Telegram preflight/failure/missingACK/accepted-prefix notes; final expanded prompts+ACK/native-transport/large-prompt run116passed. Initial focused command referenced a nonexistent file and collected no tests; receipt kept, not a product failure. Manager final12passed; adjacent91passed before final denial test. Slack/Discord unnoted declines remain conservativeunknown, not claimed precise.

V26 final review correction: first common run passed but review identified that generic `_post` exceptions were recorded as definiteerror despite transport having begun. Deterministic real-HTTP MockTransport regression `/tmp/nerva-v26-unexpected-red.xml` reproducedfailedinsteadunknown. Telegram now uses known HTTP status/request/timeout classification only, and marks unexpected exceptions unconfirmed. One added regression; fresh common rerun required. Root/agent read-only review also found existing pending-input plain fallback after malformed native ACK may repeat a prompt; plannedV27 caller-local outcome fence, with existing native return API/authority intact. No files forV27 edited yet.

V26 first common before final unexpected-exception correction: 4769total/0failures/0errors/0skips,216.362seconds. Final rerun on corrected source is in progress. Final focused117passed. Cleanup removed only six completed owned gateway fixture trees(V19,V20-final,V21,V22-final,V23-final,V24-final),127201generatedfiles/4554636132logicalbytes, after V25 archive CRC verification; no GPG agents remained. All source/archives/JUnit/log/manifests retained. Receipt `/tmp/nerva-v26-temp-cleanup.json`.

### V26 verified checkpoint

Final corrected-source common `/tmp/nerva-gateway-v26-final2.xml`:4770passed,0failures/errors,0skipped,230.681seconds; all230source/build hashes match. Gateway plus expanded pending-input, commands/extensions/hooks, HUD/route/OpenAPI/lifecycle selections. Finalfocused117passed. RuffallchangedPython passed before final two-file correction, both rechecked; final canonicalBandit0newfindings. Backend35661freshlycollected, frontend2977/mobile365actualruns retained fromV24/V25; native-shim190/mobiletscV25unchanged. Last complete backendV18, next full milestone afterV27 planned.

Prompt manager paths now have metadata-only receipts without inventing native ACKs or duplicate-native recovery. Telegram preflight/HTTP refusal/missing or unexpected ACK/accepted-prefix outcomes distinguished; Slack/Discord unnoted declines conservativeunknown. No new retries/keyderivation/live sends. H081remains partial; local170/483/8/36of697. Allsourceunstaged/unpublished. NextV27 prevents existing Telegram runtime plain fallback after uncertain or already-accepted native card delivery using caller-local outcome observation.

V26 immutable private archive: `nerva-continuation-20261112-v26.zip`,10906756bytes,260paths,SHA256`86e124f432ea9e852c30fa98e74f5d6dd513feb96059458ce644d474ea7761c9`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-ceaa3374e764819192fb8e4b7159ba8f_4f556dba9178819182620ad30bbe8468`,file`file_000000007fe081f5bb52fd61537021f9`; returned xattr applied. Archive predates this self-reference only; V27freeze released.

## V27 in progress — uncertain card fallback fence and full backend milestone

Same base/head/local-only. One gpt-6-sol/high implementer owns typed manager observation/runtime fence/unit+existing-native tests; root owns actual composed regressions, critical review/docs/integration. Root actual runtime+manager+Telegram tests reproduced4duplicate prompt POST failures for missingACK and validACK/bindrefused, each with/without ledger (`/tmp/nerva-v27-composed-red.xml`). Agent initial production branch for legacy test doubles was rejected in root review: it could treat an unreported attempted send as not_attempted. Three alternate-manager red regressions reproduced this; compatibility flag removed. Runtime always supplies fresh typed feedback initializedunknown, actual manager resets/fills proven disposition. No marker enters adapter/contract kwargs. Rootpost-ACK ledger-failure regression also passes: a bookkeeping exception cannot erase delivery truth or cause a second prompt. Current focused98passed plus root final6composedpassed (overlap; not additive). Safe real preflight text prompt remains usable. All source frozen for complete backend suite, no keyword/file filter.

V27 cleanup removed only two completed V26 gateway fixture trees after archive verification:37553generatedfiles/1275049203logicalbytes. All sources, archives, logs, JUnit and manifests retained; `/tmp/nerva-v27-temp-cleanup.json`.

V27 first full backend:35680total,35571passed,108skipped,1failure,914.882seconds. Failure was the architecture sweep newly recognizing the V24 command catalog preamble. Existing typed registry/no-cache/custom-body semantics differ from shared helper; added named exception using the sweep’s existing different-contract mechanism and strengthened behavior pins (invalid registry, exact Cache-Control). Initial extra Pragma assertion was a test-author assumption and failed4cases; replaced with actual existing Cache-Control contract, no production edit. Final focused30passed. Source review confirms no production change since full run. Completed failed-run fixture tree removed after JUnit/log preservation and scoped orphan-agent shutdown:141818files/6059559910logicalbytes. Fresh final full backend running;35681collected after added invalid-registry case.

### V27 verified checkpoint — 2026-11-13T00:55:27.934456+00:00

Complete final backend `/tmp/nerva-backend-v27-final.xml`:35681total,35573passed,108skipped,0failures/errors,936.721seconds. All235source/build hashes match the captured freeze. All23Hermes areas verified against this JUnit; backend count gate35681. The first failed full run and test-author Pragma assertion failure remain recorded, followed by30focusedpasses and this fresh full pass. Ruff changed tests passed; canonical Bandit0findings with production unchanged. HUD2977passed atV24, native-shim190/mobileJest365/mobiletsc atV25 unchanged. Exact skip reasons `/tmp/nerva-v27-final-skip-reasons.json`: includes35Chrome,9fish,8bubblewrap,7Neo4j,7dedicatedDocker containment,6rustc,6nativeWindows and other specific environments; no skipped probe claimed live.

V27 prevents plain-text duplicate Telegram pending prompts after native sent/partial/unknown outcomes, including ledger outage, binding refusal and post-ACK bookkeeping failure. Proven preflight fallback remains functional; no new send authority, retries or bodies persisted. Guard-sweep exception preserves the command catalog existing typed/no-cache/custom refusal contract. H081stillpartial. Local170equivalent/483partial/8missing/36excluded of697; main169/484/8/36 at1338833d, remotechecked2026-11-13T00:28:31UTC, PR1359draft/open/unmerged head686fcbf4. Allsourceunstaged/unpublished. NextV28 preciseSlack/Discord preflight/accepted-prefix receipt notes, then independent executable backlog; live provider/device and owner recovery-policy constraints remain per-contract blockers.

V27 immutable private archive: `nerva-continuation-20261112-v27.zip`,12402973bytes,265paths,SHA256`d4a265751502670fe103057c9723df1e6c9b342d046e3613350f3b389b94b0be`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-816338a37634819199ae4e026e441eb7_4f556dba9178819182620ad30bbe8468`,file`file_000000003ef881f5a716924d50e84d68`; returned xattr applied. Archive predates this self-reference only; V28freeze released.

## V28 in progress — precise workspace prompt outcomes

Same base/head/local-only. Two gpt-6-sol/high implementers, no subdelegation, own distinct Slack/Discord adapter files and new outcome tests; root owns integration/review/docs. Design `/workspace/scratch/nerva-v28-next.md`. Existing manager ledger API/native receipts only, no new retry/key/authority. Per verified part preserve partial evidence before lifecycle checks; definitely preflight refusals failed; malformed or arbitrary SDK failures unknown. Live workspace acceptance not claimed.

### V28 verified checkpoint — 2026-11-13T01:06:34.646743+00:00

Common gateway/commands/extensions/pending-input/lifecycle/route regression `/tmp/nerva-gateway-v28.xml`:4816passed,0skips/failures/errors,205.870seconds. All237source/build hashes match; gateway acceptance verified. Current backend35707freshlycollected; last fullV27 remains35573pass108skip. RuffallchangedPython passed; canonicalBandit0findings. Frontend/mobile unchanged fromV24/V25. Slack21focusedpass, Discord74focusedpass; overlapping selections not additive. Slackred4failures, Discordinitialred8 and explicit boolean-authorred demonstrate defects. Root review removed Discord test bypass of manager contract and corrected bool test to trustedint1 vs returnedTrue; finaltests use real manager contract.

Slack/Discord known preflight refuses failed, accepted native prefixes remainpartial across later failure/lifecycle change, malformedSDKACKs/unexpectedexceptionsunknown. Discord author/target IDs strictpositiveint and cancelled finalview stopped while cancellation propagates/reservationreleases. Rendering/preflight exceptions still conservativelyunknown; no broader error inference, retry, keys, live calls or persisted bodies. H081partial/local170/483/8/36of697 unchanged. Allsourceunstaged/unpublished. NextV29 H083startup rejects empty/template credentials beforenetwork/SDK/tasksetup; cross-profile claims/live recovery remain separate.

V28 immutable private archive: `nerva-continuation-20261112-v28.zip`,12545459bytes,267paths,SHA256`823a6d6a8083a585b275e63b35893d4d32071eb19f5056b05e22d4e25dfcb1d1`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-7979c1654ca48191937ccd2bb3a65492_4f556dba9178819182620ad30bbe8468`,file`file_00000000c7e481f5a43ce5a81ac46ebd`; returned xattr applied. Archive predates this self-reference only; V29freeze released.

## V29 in progress — credential startup preflight

Same base/head/local-only. Two SolHigh implementers without subdelegation: sharedpurehelper+Slack, Discord; rootTelegram/tests/review/integration/docs. Design `/workspace/scratch/nerva-v29-next.md`. Shared credential_is_configured only inspects whole-value placeholders/nonstring/blank, never returns/logs secrets or normalizes accepted bytes. Fixed invalid_credential health before startup; optional empty Slack app remainsmanual. Slackred10fail then107focusedpass; Discordred13fail then13new+59adjacentpass; rootTelegramred9fail1pass, final50pass includingexistingreliability. Root corrected newtest generation expectation to constructor identity (unchanged onrefusal), without changing productiongeneration. No liveactivation or claimsaboutremotetokenvalidity. Source frozen forcommon integration.

### V29 verified checkpoint — 2026-11-13T01:21:14.634869+00:00

Firstcommon4878passed,0skips/failures/errors,206.144s. Bandit flagged empty-string Slack optional-token comparison as B105; replaced equality with exactstr-and-notvalue, identical semantics, no suppression/baselinechange. Focused helper+Slack passed. Final canonicalBandit0findings and freshcommon `/tmp/nerva-gateway-v29-final.xml`:4878passed,0skips/failures/errors,206.407seconds; all242source/build hashes match; gatewayverified. RuffallchangedPythonpassed, finalSlackrechecked. Backend35769collected; lastfullV27 remains35573passed108skipped, HUD/mobileV24/V25unchanged.

Startup now refuses blank/nonstring/whole-placeholder Telegram, Slack and Discord credentials before SDK/network/tasks, fixed healthreason only; optionalemptySlackapp remainsmanual, acceptedopaquevaluesunchanged. No liveprovidercredentialvalidity/activation claimed. H083partial and local170equivalent483partial8missing36excluded of697unchanged. Allsourceunstaged/unpublished. NextV30 localTelegram cross-profile polling claims, with kernel-held siblinglock outside backup/forget and serialized lifecycle; otherSDK/listenerclaims/liveacceptance remain.

V29 immutable private archive: `nerva-continuation-20261112-v29.zip`,12829391bytes,272paths,SHA256`09065e8e4af065886e00bbba78af983df7a9667cc2a869088a81517b81e3c646`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-5b96d916a974819188111e97d6d58e7c_4f556dba9178819182620ad30bbe8468`,file`file_0000000098bc81f59c9cc52e2d244c3e`; returned xattr applied. Archive predates this self-reference only; V30freeze released.

## V30 in progress — Telegram cross-profile polling claim

Samebase/head/localonly. TwoSolHighimplementers, no subdelegation: helper+kerneltests; Telegramlifecycle+tests. Root criticalreview, filepreflight/backupboundarytests, legacycursorfixture, gitignore, docs/integration. Design `/workspace/scratch/nerva-v30-next.md`. Immutable fixed-byte siblinglock outside backup/forget; exacttokenhash, private regularinode/no-follow checks, nonblocking kernel lock, fork childcloseswithoutunlock, serializedlifecycle. Cancellation/failure retains untilactualpollstop+HTTPclose. Auxiliarydrains unchanged: pollonlyguarantee, notoutboundsendexclusivity. Kerneltests11passed includingprocesskill/fork; agentlifecycle45focusedpassed. Root FIFOopen-before-checkred failed, correctedprelstat/nonblock. Windows branch read-beforelock red failed; correctedlock-beforecontent based on Microsoft _locking docs https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170 and second-handle semantics https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex . NativeWindowsunrun; branchorderingtest is simulated, notnativeacceptance. Rootfocused73passed. Actualbackup/purge/forcerestore boundary passed after correcting fixturearchive destination outsidepurgedroot (firstfixturefailed becauseforgetdeleteditsbackup). Independentprocess remainedbusy andsameinode acrossallthreeoperations. Existingcursorrestarttest now waitsfordurablecursorbeforeorderlystop; it no longer calls sameprocesspollcancellation a processcrash. Trueprocessdeathrelease is separately tested.

Cleanup afterV29CRC removedonly completedV27fullfixturetree:141822files/6059276702logicalbytes; allJUnit/logs/sourceproofs/archiveskept, `/tmp/nerva-v30-temp-cleanup.json`. Automaticpytest-siblinglockfiledeletion was deliberately not added: parentexitdoesnotprovenodescendantholder. Tinyfixed-byte temporaryclaimfiles remain; ownedcompletedfixturetrees maybecleaned afterprocesscompletion. Productionclaimfiles neverunlink. Sourcefrozenforcommonplusnetworkclassifier/binding/pintests.

V30 firstcommon was interrupted after morethan4minutes withoutprogress/CPU near98%; controlledSIGINT to exactpytestcontroller produced partialJUnit5041reported/2failures/1error/0skips,607.881seconds. Twofailures are H381 stale/unclassified client factory after startbody moved to _start_claimed; sameapi.telegram.org-onlyhook retained, classificationrename required. Workercrashed on H084 test whose runningfixture start now correctlyno-ops, soenteredwaitneverfires; oldtest also expectedoverlappingstart. Rewrite to assertserializedstarts/noextraidentityprobe andexplicitstop/restartgenerationbinding, withboundedbarriers/properstopcleanup. No source changed untilinterruptedrunexited; partialrunnotclaimedcomplete. Remotechecked2026-11-13T01:40:18UTC stillmain1338833d169/484/8/36 andPR1359draft/open/unmergedhead686fcbf4, local170/483/8/36.

### V30 verified checkpoint — 2026-11-13T01:53:54.715765+00:00

Fresh finalcommon `/tmp/nerva-gateway-v30-final.xml`:5045passed,0skips/failures/errors,254.615seconds; all249source/build hashesmatch; gatewayverified. Expandednetworkclassifier/orchestratorbindings/HTTPpin/jobpin tests included. Interruptedfirstcommon recorded5041results and3problems; finalruncomplete. H381classification now names _start_claimed withsameBotAPIonlyhook; focused3passed. H084serializedstartup/restartgeneration test plusclaimsuite40passed; boundedwaits/properstopcleanup. CanonicalBandit0findings/RuffallchangedPythonpassed beforetestonlyfixes; finalchangedtestsRuffpassed. Backend35793collected; fullbackendV27stilllatest35573passed108skipped. Frontend/mobileunchangedV24/V25.

Telegram startup/polling claims acrossprofiles sharinginstallroot now prevent secondpoller untilfirstactualstop; failed/cancelledstart/stop retainlease. Kernelprocessdeath/fork and actualbackup/purge/forcerestore boundary provedoffline. Windowslockingcode implemented, branchordering checked againstMicrosoftdocs andsimulatedprobe, nativeWindowsnotrun; realTelegram notrun. Auxiliarydrains unchanged/noall-outboundexclusivityclaim. No tokenbodies persisted; exacttokenhashfilename/fixedbyte only. Immutablelockfiles neverautomaticallydeleted; tinytestsession siblingfilesmayremain. H083stillpartial; local170/483/8/36of697; main169/484/8/36at1338833dfresh01:40:18UTC, PR1359stilldraft/open/unmergedhead686fcbf4. Allsourceunstaged/unpublished. NextV31Discordconnectionlease mustawait SDKtasksettlement afterclose; independentH079fullcontractreview underway, noverdictpromotionyet.

V30 immutable private archive: `nerva-continuation-20261112-v30.zip`,13117289bytes,280paths,SHA256`2d675af55514225b4a899e3a8d34973611259e6e442809ac46c645ce7fc567a7`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-f85135bd2bf48191a867eed9dfc4d578_4f556dba9178819182620ad30bbe8468`,file`file_00000000cc9081f5bbb045a95a8fa880`; returned xattr applied. Archive predates this self-reference only; V31freeze released.

IndependentH079clause review (SolHigh, read-only) found currentremaining understatedcodegaps: signedacquiredextensions registerlazyownercommands, butlegacybuiltinPluginManager stillimportsconnectors eagerly andhasno commandregistrationAPI. Corecolliding skill slugs are safelyexcluded fromdispatch/discovery/menus but no collision-specificregistrationrefusallog is pinned. Rootclarification: frozencontract requiresregistrationrefusal, notinstallationban; donotrefuse otherwiseusefulskillinstallation. Native menus refreshstartup, typeddiscoverylive. Existing single/stack<=5/bundle/requiredargs/ownerboundarytests substantiateimplementedclauses. H079stayspartial; noequivalencecredit fromreview.

## V31 in progress — Discord cross-profile connection claim

Same base/head/local-only. Two SolHigh implementers without subdelegation own helper+kerneltests and Discord+lifecycle tests. Root owns critical review/docs/integration. Claim acquisition precedes SDK construction; independent fixed Telegram/Discord namespaces. Stop closes client, cancels gateway task and observes actual settlement with asyncio.wait before releasing. Failed/cancelled cleanup retains claim; manager retirement remains bounded. Focused31kernel-related and86Discord tests passed (overlap not additive). Root corrected test-only locked-file metadata read to owned handle for Windows compatibility; native Windows remains unrun. Root Ruff found/fixed import sorting. No live provider calls or outbound exclusivity claim. H083 remains partial; generated totals170/483/8/36of697. Backend35812collected.

### V31 verified checkpoint — 2026-11-13T02:11:41.025985+00:00

Common `/tmp/nerva-gateway-v31.xml`:5064passed,0skips/failures/errors,245.448seconds; all251source/build hashes match. Gateway acceptance verified; expanded network classification/binding/pins included. Final kernel31focusedpassed after correcting held-byte metadata reads to owned descriptor; Discord86focusedpassed, selections overlap. RuffallchangedPythonpassed, canonicalBandit0findings, diff/status checks passed. Backend35812collected. Latest fullbackendV27 remains35573passed108skipped; frontend2977V24/mobile365+native-shim190V25 unchanged.

Discord cross-profile exact-token claim now holds from before SDK construction until gateway task settlement after close/cancel. Failed/cancelled setup/cleanup retains ownership; serialized start/stop, namespace independence, actual subprocess crash release and manager retirement covered offline. NativeWindows/liveDiscord remain unrun; no all-outbound exclusivity claim. H083stillpartial, local170equivalent483partial8missing36excluded of697. Main last verified01:40:18UTC169/484/8/36at1338833d; PR1359draft/open/unmergedhead686fcbf4. Allsourceunstaged/unpublished. NextV32 targeted fixed aggregate collision-refusal diagnostics in owner skill projections. Legacy builtin eager plugin imports require substantive technical migration, not a new owner approval gate; retain H079partial.

V31 immutable private archive: `nerva-continuation-20261112-v31.zip`,13270057bytes,282paths,SHA256`d964750f6ede34db78bf03442ba7f5fc57707cf510fc7f9f9678404a9fd64ae3`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-ae868d682e1c8191ae97828d6ecb93a2_4f556dba9178819182620ad30bbe8468`,file`file_00000000985081f59d35ee25b3a8511d`; returned xattr applied. Archive predates this self-reference only; V32freeze released.

## V32 in progress — collision-refusal diagnostics

V31 archived before edits. One SolHigh implementer owns three existing owner skill projections and new collision diagnostic tests. Narrow clause: log aggregate fixed count for existing command namespace refusals only, never raw skill metadata. Preserve short-circuit gates/guest isolation/caps; no installation ban or dispatch changes. Root owns review/integration. Separate second agent read-only reviews Slack SDK cleanup for candidateV33; no V33 edits authorized yet.

V32 focused30passed (new4tests included), three red diagnostic failures demonstrated missing logs. Root review confirmed original short-circuit order preserved. Bandit0newfindings. Ruff found one extra blank line in the new test import block; formatting correction deferred until common run completes, then rerun focused checks. Cleanup removed only completed V28/V29-final/V30-final/V31 fixture trees after V31archiveCRC and process-holder check:76764files/2602249046logicalbytes; sources/reports/archives preserved, receipt `/tmp/nerva-v32-temp-cleanup.json`.

### V32 verified checkpoint — 2026-11-13T02:20:51.541532+00:00

Common `/tmp/nerva-gateway-v32.xml`:5068passed,0skips/failures/errors,256.008seconds; all252source/build hashes matched at completion. Gatewayverified. Afterward removed one extra blank line in new test imports; AST identity proved in `/tmp/nerva-v32-format-proof.json` and all4newtests rerun passed `/tmp/nerva-v32-format-final.xml`. Thus common receipt predates formatting-only finaltestbytechange; production unchanged. RuffallchangedPythonpassed, canonicalBandit0findings, status/diffchecks passed. Backend35816collected. LatestfullbackendV27 remains35573passed108skipped; HUD/mobile unchanged.

Owner command discovery/webshortcuts/native skill menu now emit one fixed count-only warning for actual existing taken(name/wire) refusal. No metadata leaks, new authority or installation bans. Gateorder/guestisolation/caps preserved. H079stillpartial: legacybuiltin eagerpluginmigration and liveacceptance remain. Local170/483/8/36of697unchanged; main lastchecked01:40:18UTC169/484/8/36at1338833d. Allsourceunstaged/unpublished. NextV33 exact Slack app+bot connection claims with retainedclient cleanup and actualSDK offline settlement proof.

V32 immutable private archive: `nerva-continuation-20261112-v32.zip`,13418947bytes,283paths,SHA256`84cd9267b6650e9df2f3f586594bff286abdbcac6791d7326f5d74f43fcdc6b9`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-0252aa6fc8c48191a08ac1ea240dd49e_4f556dba9178819182620ad30bbe8468`,file`file_0000000023e081f585b869f6ea03ee29`; xattrapplied. Archive predates this self-reference only; V33freeze released.

## V33 in progress — Slack Socket Mode ownership and retained cleanup

V32archived before sourceedits. TwoSolHighimplementers: fixedhelpernamespaces+kerneltests; Slackadapter/lifecycletests+necessaryfakeSDKfixtures. Root owns actualinstalledSDKoffline proof/review/integration. Exact app+bot tokens independentlyclaimed beforeSDK/auth, prefixrollback beforestartup; manualingressunclaimed. Retainactualclient/claims onfailedorunconfirmedcleanup, explicitstopretry; runner/executor settlement required. RootrealSDKred reproducedduplicateWebClientstartup(2vs1), `/tmp/nerva-v33-native-red.xml`; no liveSlackcalls. Helperredmissingwrapper then40focusedkernel-relatedpassed `/tmp/nerva-v33-claims-green.xml`; Telegram/DiscordAPIs unchanged, owningfdmetadatareads. NativeWindowsunrun.

V33 finalfocused: Slack71passed includingrootnative3, helper40passed (overlap notadditive). RootnativeSDKred duplicatedstartup, then realSDKfailedclose/unknownrunner recoverypassed. Rootrelease-review found apphandleloss ifbotrelease throws; agentadded finalrelease andprefixrollback failure regressions, each retaining exacthandles until explicitstop. RuffallchangedPythonpassed, canonicalBandit result pendingreview/fullbackendstarted. Backend35840collected; fullrunner nofile/keywordfilter,4workers,timeout90, ownedbasetemp/subreaper. Cleanup afterV32archiveCRC removed5completedoldergatewayfixturetrees74934files/2511381777logicalbytes; firstpreflight saw only runningdu reader, waiteduntilduended thenrecheckedzero holdersbeforedelete. No sources/logs/archivesremoved.

H083independent8clausereview: currentadapterclaims andSDKreadiness are localimplemented, but noexplicit channelopen/half-openbreaker, no prolongedtransient/SDKdisconnect owner escalation, named configurableconnectdeadlineabsent, and /platform durabletarget/action/outcomeauditnotpinned. SDKnativebackoffneedsbehaviorproof, webhook/SMSsharehublistener(noindependentport), email/ntfyunclaimed. Retainpartial. NextV34 design limits scope to once-per-episode sustained/fatal escalation with staleowner/epoch/threadfences; otherclausesseparate. H086readonlyreview confirmsmissingfullremoteidentity/driver/ref/one-shotartifactchain; standalonebrokerhelperwouldnotfulfillit. Remoteegress mustenforceontrusteddriverhost, notpretendhubIPpinningconstrainsremoteprocess. No new owner approval gate inferred; substantial technicaldesign remains.

V33 complete backend first run `/tmp/nerva-backend-v33.xml`:35840total/35724passed/108skipped/8failures/0errors,917.732seconds. All8 failures were teardown in3pending-input files sharing the card-only fake socket in test_pending_input_workspace_runtime.py. That fake never startsSDKworkers but lacked the3workerstate attributes; production correctlyrefusedunknowncleanup. Root added3stoppedrunner fields to that fixture only, no predicatebypass/productionchange. All48tests acrossall3consumerfiles plusnewSlackfake/native tests passed `/tmp/nerva-v33-fixture-final.xml`,11.368seconds. Existing256sourcehashesunchanged; onlyadditionalchangedsourcepath is this trackedtestfixture(previouslyunchangedfromHEAD). No freshfullrerun claimed; integrationreceipt will compose actual executed fullresults with complete48-node rerun, preservingoriginalfailedXML andexplicitprovenance. TwoorphanGPGagents fromcompletedfullfixture were terminated onlyafterpytestfinished; subreaperexited1asexpected.

### V33 verified composite checkpoint — 2026-11-13T02:49:49.361226+00:00

Executed full35840cases had8fixtureteardownfailures/108skips/35724passes; complete48-case consumer+Slack rerunpassed aftertest-onlyfixturecorrection. IndependentSolHighread-onlyreview confirmed noSDKworkers exist inthisfake, all3workerfalsefields faithfullymodelsettlement, and exactallconsumercoverage. `/tmp/nerva-backend-v33-composite.xml` preserveslatestexecutedresult pernode:35732passed108skipped0failed/error. This is **composite evidence, not a fresh full run**. OriginalfailedXML retained. `/tmp/nerva-v33-composite-provenance.json` pinsbothinputXMLhashes/timestamps,all48replacednodes,HEADandfixturechange. All256frozenchanged/untrackedsourcehashesunchanged; onlynewchangedsourcepath is theformerlybaseline testfixture; final257hashmanifest. All23Hermesareas verifiedagainstcompositeJUnit. Ruffpassed, canonicalBandit0newfindings withproductionunchangedafterinitialscan; status/diffchecks passed. Full35840collected, HUD2977/mobile365/native-shim190 retainedunchanged.

Slack claims/app+bot collision/retainedcleanup/actualSDKsettlement implementedoffline, withmanualingressunchanged andprefix/finalreleasefailuresrecoverable. NativeWindows/liveSlackunrun; skipsreasonreceiptpreserved. Local170equivalent483partial8missing36excludedof697unchanged. Remotechecked2026-11-13T02:32:25UTCmain1338833d169/484/8/36, PR1359draft/open/unmergedhead686fcbf4. Allsourceunstaged/unpublished. NextV34once-per-episode prolongedfailureescalation, includingSDKprojectedfatal andexactowner/epoch/thread/queued-dispatch fences.

V33 immutable private archive: `nerva-continuation-20261112-v33.zip`,14920772bytes,288paths,SHA256`e4dbc58b7250776c4e69398cd73894f8ab61d99bc029f7bf7a6ffc13c6b4bc00`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-bc3fa60844308191b22d167e55fa4cd8_4f556dba9178819182620ad30bbe8468`,file`file_00000000555081f5bf180ee27d832c72`; xattrapplied. Archive predates this self-reference only; V34freeze released.

## V34 in progress — sustained failure notices and stale-dispatch fences

V33archive precedesallV34sourceedits. TwoSolHighimplementers: puretracker+8clocktests; manager+6integrationtests. Root owns9actualmanager/SDKsnapshot/thread/paused-destination regressions, criticalreview/docs/integration. Rootinitial5failed1passed reproducedstalequeued/retiredcallback/recovery/rawmetadata/off-threadlostnotice defects (`/tmp/nerva-v34-fences-red.xml`). Helpermissingmoduleredthen8green. Managerfocused126passed beforefinal2rootSDKsnapshotcases; rootcombined23passed `/tmp/nerva-v34-root-final.xml` afterthose. Rootreview added stale-sample-beforeobserve identityguard and paused/cleanup destination fence; newdestinationpauseprobe firstexecutedafterfix (green, notred), renamedreceipt `nerva-v34-destination-pause-first.xml`. Existing manager-send/outboundwrapper used, noauthoritybypass. Puretracker countspositiveexact-int retries; unknown/initial0breakintervals, stablehealthy60srearms; currentfatal shareslatch.

Cleanup ofcompletedV33fullfixture firstpartiallydeleted thenhitintentionalread-onlytestdirectory; retainedarchiveCRC andnoprocessholderchecks. Owner-modeonlydirectories underthatexactbasetemp were madewritable andremaining35917files/1902200043bytes removed; earlierremovedcountunavailable, no totalclaimed. Receipt `/tmp/nerva-v34-temp-cleanup.json`. Allsource/logs/XML/archivespreserved. RuffallchangedPythonpassed; canonicalBandit found1B112 at the best-effort destination-resolution except/continue. Fixed redacted diagnostic is pending after the frozen common run; no clean scan claimed yet. Commonintegrationrunningonfreeze.

V34 firstcommon5115total/5114passed/1failure/0skips,251.296seconds. Failure was oldfatal-notice text assertion in test_g15_channel_reliability expecting lowercasechannelandrawreason; updated tocase-insensitiveknownchannel/unavailableandnorawreason, preservingactualntfyPOST/onceperepisodeassertion andaddingmanagercleanup. B112best-effortdestination-resolutionexcept/continue fixedwithredactedconstantwarning, no suppression/baselinechange. Newrootregression reproducedmissingdiagnostic beforefixandprovesfallbackdeliverywithnoprivatedetail. Newdestinationpauseprobe earlierpassedafteragentfix, notclaimedred. Production/loggingandtests frozenforfreshfinalcommonafterfocused/staticchecks.

### V34 verified checkpoint — 2026-11-13T03:13:35.698410+00:00

Fresh finalcommon `/tmp/nerva-gateway-v34-final.xml`:5116passed,0skips/failures/errors,243.130seconds; all261source/build hashes match. Gatewayverified. Firstcommon5114pass1oldmessageassertionfailure retained; fixedgenericmessageassertion+cleanup, fixedredacteddiagnosticafterB112withredregression. Finalfocused64passed, Ruffclean, finalcanonicalBandit0findings, status/diffchecks passed. Backend35864collected. V33all-area evidence remains composite35732pass108skip across35840cases (full+48rerun, notfreshfull); V34sourcechanges coveredbythisfreshgatewayexpandedselection. HUD2977/mobile365/native-shim190unchanged.

Implemented one lifecycle-owned10ssampler,300sconfirmedpositivefailurethreshold,60sstablehealthyrearm andsharedfatal/projectedfatal latch. Unknown/initial0 do notaccumulate; sourceanddestinationowner/revision/epoch/pause/cleanup/currentfailurefences preventstalequeueddispatch. Off-threadfatal handoffpreserved; fixedlabels/text/no rawreason. RootactualSDKsnapshotSlack/Discordtests andrealmanager/wrappedlocalsink testsproveboundary; no live notices. H083stillpartial; local170/483/8/36of697unchanged. Allsourceunstaged/unpublished. NextV35per-adapterexclusiveprobe circuit gate forTelegram/IMAP/ntfy, includingrequiredemailworker-lifetime andntfystreamhealth/messagehandling seams.

V34 immutable private archive: `nerva-continuation-20261112-v34.zip`,15226414bytes,292paths,SHA256`20affd55e9261d6cb43c79a672d33ebace286f15e1b470024feb50740c12c821`. CRC/clean-base apply-check/result-byte comparison passed. Library`libfile_fde3_f-16031c1045b4819181e09b6eeb59506b_4f556dba9178819182620ad30bbe8468`,file`file_00000000d62c81f59c2aa6916370c182`; xattrapplied. Archive predates this self-reference only; V35freeze released.

### V35 in progress — 2026-11-13

Continues the verified V34 archive on unchanged base/head `686fcbf4f25ebfbb416b3a35dff29045163cffbd`. Scope: per-adapter inbound circuit gates for Telegram, IMAP and ntfy, with exclusive recovery probes and explicit worker/stream ownership. Design and rollback unit: `/workspace/scratch/nerva-v35-next.md`. Two existing Sol High implementers own separate files: reconnect helper/email; Telegram/ntfy. Coordinator owns composed regressions, review and integration. No publication or schedule changes.

Root baseline regressions: `/tmp/nerva-v35-email-worker-red.xml` has three expected failures (duplicate poller on repeated start, stop returns before actual IMAP worker settlement, missing finite socket timeout). `/tmp/nerva-v35-email-manager-red.xml` adds a failing composed manager-budget check: the old adapter incorrectly reports completed stop while its worker is blocked. These are failing-before-fix evidence, not passing validation. Local ledger remains 170 equivalent / 483 partial / 8 missing / 36 excluded of 697; no completion promotion.

V35 focused progress: helper/email freeze passes 14 tests including the four root regressions (`/tmp/nerva-v35-owned-freeze.xml`); existing reliability/email selection passes 97 (`/tmp/nerva-v35-email-existing.xml`). Root ntfy manager-budget regression initially failed because a repeated stop interrupted response closure (`/tmp/nerva-v35-ntfy-close-first.xml`); retained exact teardown is under review. Legacy fake-time tests now advance the gate clock; ntfy’s seventh stream remains open until its quiet-health timer fires before asserting backoff reset. Telegram and ntfy adjusted cases each pass (`/tmp/nerva-v35-g15-clock.xml`, `/tmp/nerva-v35-ntfy-clock.xml`). These focused results are not common integration acceptance.

V35 root boundary rerun: five tests pass in `/tmp/nerva-v35-root-boundaries.xml` after retained/shielded ntfy response teardown. Failed acquired-response closure remains unconfirmed; the adapter must not release its lease on that path. Read-only review rejected speculative pinned-pool introspection for failed stream entry: an awaited client entry that yields no response retains established retry semantics; inactive pooled connections are not active subscriptions. No HTTP client/security policy was changed for that hypothesis.

Remote comparison refreshed at 2026-11-13 03:28 UTC: PR #1359 is still open, draft and unmerged at `686fcbf4`; main remains `1338833d` with 169 equivalent / 484 partial / 8 missing / 36 excluded. Receipt: `/tmp/nerva-v35-remote-comparison.json`. Local count is unchanged and all continuation changes remain unpublished.

V35 source freeze: all owned implementations and tests handed back. Focused adapter selection passes 95 tests (`/tmp/nerva-v35-adapters-focused.log`), including explicit failed response-close retention; root changed-subscription timer fence passes with blocked-close probe (`/tmp/nerva-v35-root-ntfy-final.xml`). Ruff across all changed Python files passes; canonical Bandit reports zero findings. Backend collection is 35,890; frontend 2,977 and mobile 365 counts are unchanged. Hermes/status/diff checks pass. Common integration is running against `/tmp/nerva-gateway-v35-source.json`; no integration success claimed yet.

### V35 verified checkpoint — 2026-11-13 03:35 UTC

Fresh common integration `/tmp/nerva-gateway-v35.xml`: **5,142 passed, zero skipped/failures/errors**, 257.820 seconds. All 270 source/build hashes match the frozen manifest. Gateway acceptance verified; Hermes/status/diff checks pass. Ruff is clean and canonical Bandit has zero findings. Backend collection: 35,890. Earlier V33 full-backend evidence remains explicitly composite (35,732 passed / 108 skipped); the V35 source is covered by this fresh expanded common selection, not a newly run full backend.

Implemented and reviewed: exclusive per-adapter transport leases, five-failure/120-second opening, one half-open recovery probe, Retry-After enforcement, fatal 600-second reprobes, fetch/application separation, retained IMAP workers, 15-second IMAP socket-operation timeout, ntfy 60-second quiet health and exact retained response teardown. Failed acquired-response closure stays unconfirmed and refuses restart; actual stream entry failure without a yielded response remains retryable under the HTTP client API. Root regressions cover manager cancellation, real blocking worker lifetime, blocked response close and stale subscription timer; agent tests cover fatal/rate-limited/transient recovery and application-error isolation. No live service was contacted for acceptance.

H083 remains partial. Local ledger is unchanged at 170 equivalent / 483 partial / 8 missing / 36 excluded of 697. All source remains local, unstaged and unpublished. Next V36 adds durable, redacted platform-control outcomes through the existing audit store, without changing authority or manager lifecycle semantics. Remaining connect-deadline, claim and live/native obligations stay open.

V35 immutable private archive: `nerva-continuation-20261112-v35.zip`, 15,414,344 bytes, 301 paths, SHA-256 `4a639ff4f74ff30f170777332cf61e7d8a366035108eef3e31d541601bc13087`. CRC, clean-base apply check and applied byte comparisons passed. Library `libfile_fde3_f-22a72cc13a708191ac55e801ced1f758_4f556dba9178819182620ad30bbe8468`, file `file_00000000907081f586fa94c85a108818`; version xattr applied. The archive predates this self-reference only. V36 implementation may proceed.

### V36 in progress — 2026-11-13 03:36 UTC

Goal: durable redacted `/platform pause|resume` outcomes through the existing AuditLogger, preserving admin gating and bounded manager lifecycle. Design: `/workspace/scratch/nerva-v36-next.md`. Backend Sol High owns `agents/core/platform_commands.py` and `tests/test_h083_platform_audit.py`; root owns `tests/test_h083_platform_audit_dispatch.py`, review and integration. The other Sol High agent is read-only on the next H083 configurable-deadline design. No subdelegation or publication.

Root composed baseline `/tmp/nerva-v36-dispatch-red.xml`: owner pause executes but fails the missing durable outcome assertion; guest dispatch denial passes with the existing argument-free `slash_command_denied` row. Agent baseline `/tmp/nerva-v36-platform-red.xml` has four expected audit-behavior failures. These are red evidence, not validation. V35 immutable archive remains the last accepted checkpoint.

V36 housekeeping: after verifying V34 and V35 archive CRCs and no process holders, removed only the completed V34 common-run fixture directories (39,264 files, 1,322,929,955 logical bytes). Source, logs, JUnit, manifests and archives are preserved. Receipt: `/tmp/nerva-v36-temp-cleanup.json`.

V36 source frozen after 29 focused tests, all-changed Python Ruff, zero canonical Bandit findings, and generated status checks. Backend collection: 35,896. Fresh common integration is running (`/tmp/nerva-gateway-v36-source.json`); no common acceptance claimed yet. V37 design distinguishes an actual opening deadline from per-socket timeout and preserves late transport ownership; no V37 implementation has started.

### V36 verified checkpoint — 2026-11-13 03:46 UTC

Fresh common `/tmp/nerva-gateway-v36.xml`: **5,148 passed, zero skipped/failures/errors**, 256.918 seconds. All 272 source/build hashes match. Gateway acceptance, Hermes/status checks, Ruff and diff checks pass; canonical Bandit has zero findings. Backend collection is 35,896. No new full backend or frontend/mobile run is claimed.

Owner platform controls now append fixed, redacted outcomes to the existing hash-chained audit store. Actual dispatch plus durable reopen tests verify the row after the real manager transition. Unknown targets, malformed/action-inconsistent results, exceptions and cancellation cannot manufacture success. Custom registered IDs use a full domain-separated SHA-256 fingerprint grouped into readable segments so the existing secret scanner retains the non-secret identifier; the scanner itself is unchanged. Audit failure is visible without undoing pause; a cancelled operation with failed audit emits a fixed warning. Existing non-owner denial is preserved.

Ledger remains 170 equivalent / 483 partial / 8 missing / 36 excluded of 697. Everything is local and unpublished. Next: V37 configured async opening deadlines for Telegram identity and ntfy stream entry, preserving retained task/claim/lease cleanup. Other handshake deadlines and live/native proof remain open.

V36 immutable private archive: `nerva-continuation-20261112-v36.zip`, 15,573,921 bytes, 303 paths, SHA-256 `a1780ebbd2c7c0e2832e43ca8816a44b87c871ecd62990bf90ade05e185fe3c7`. CRC/clean-base apply check/result-byte verification passed. Library `libfile_fde3_f-790b8465288c8191a0adcebca77d267f_4f556dba9178819182620ad30bbe8468`, file `file_00000000a77481f592325c2772eaecd6`; xattrs applied. Archive predates this self-reference only; V37 freeze released.

### V37 in progress — 2026-11-13 03:47 UTC

Design `/workspace/scratch/nerva-v37-next.md`: configurable elapsed-time opening budgets for Telegram startup identity and ntfy stream entry, with retained ownership of late transport tasks. Root owns the pure validator, settings registry, web wiring, parity note and composed configuration tests. Two Sol High implementers separately own Telegram and ntfy plus their new tests; no subdelegation. Shared keyword: `connect_timeout_seconds`; default 15 seconds, finite clamp 1..25. The setting is read once when hub startup wires adapters, so its label says next hub start.

Root baseline `/tmp/nerva-v37-config-red.xml` contains 18 expected failures for the absent helper/setting. Existing cancelled-start Telegram claim fixture now releases its actual held identity request before expecting successful stop, preserving the contention assertion; prior implicit cancellation is no longer mistaken for transport settlement. No V37 integration success is claimed. Mobile operator setting has no new native editor/device proof and is explicitly recorded in `mobile/PARITY.md`.

V37 focused freeze: configuration/persisted setting/real lifespan wiring 19 passed (`/tmp/nerva-v37-config-wiring.xml`); Telegram deadline/claim/credential/circuit/batching selection 88 passed (`/tmp/nerva-v37-telegram-green3.xml`); ntfy focused selection 46 passed (`/tmp/nerva-v37-ntfy-final.log`). Independent cross-review found no concrete late-result, lease/claim release or task-retention defect. Broader Telegram selection exposed a lane-only `__new__` fixture missing the V35 idle circuit; root explicitly initialized that idle circuit, and the complete H677 file passes 51 tests (`/tmp/nerva-v37-h677-fixture.xml`). No production guard was weakened.

Root and both implementers are frozen for the full backend milestone. Other adapters’ deadline design may proceed read-only, but no new implementation may change the tested source. Ruff passes across all changed Python files; full-backend acceptance and security scan are not yet claimed.

V37 full backend started with 35,923 collected tests, no keyword filter, four workers and per-test timeout90. Runner `/workspace/scratch/verify_backend_v37.py`; evidence prefix `/tmp/nerva-backend-v37`, private fixture root `/workspace/scratch/nerva-backend-v37`. Source/build manifest captured before execution. Canonical Bandit reports zero findings; generated status and Hermes checks pass. Do not change production/tests while this run is pending; no full-suite success claimed yet.

V37 full-run progress inspection found two failure markers at 15–16%; the terminal report is still pending. An earlier commentary based only on the log tail missed these markers and was corrected immediately after scanning the full progress log. Do not report this run as green. All 276 frozen source/build hashes still match. Keep the run intact for complete failure diagnostics before changing source.

After the user resumed work, the original V37 full pytest process was confirmed still running (the old interactive polling handle had expired; the test process itself had not). No duplicate suite was started. During this run, V35/V36 completed fixture trees were removed only after archive CRC and no-holder checks: 39,401 files / 1,326,567,787 logical bytes; receipt `/tmp/nerva-v37-temp-cleanup.json`. Active V37 fixtures and all source/evidence/archives remain. The email cancellation regression draft is outside the tested repository at `/workspace/scratch/test_h096_cancellation_checkpoint.py`, not yet run.

### V37 verified checkpoint — 2026-11-13 04:12 UTC

Original full backend `/tmp/nerva-backend-v37.xml`: **35,923 cases, 35,813 passed, 108 skipped, 2 failed, zero errors**, 960.404 seconds. Both failures were in `test_h490_safe_mode_posture.py`: the new numeric opening setting had not yet received its explicit safe-mode classification, and a source-text anchor expected the old no-keyword ntfy factory call. The bounded 1..25-second wait does not grant action/approval/spend/recipient authority; safe mode still removes ntfy before registration. Independent Sol High review agreed. The test now documents that classification and updates only the opening anchor, retaining every guard assertion. No production change followed the full run.

Complete rerun of safe-mode and opening-setting/wiring files: **97 passed**, 14.417 seconds (`/tmp/nerva-v37-safe-mode-final.xml`). `/workspace/scratch/compose_backend_v37.py` verifies exact case coverage, input hashes and unchanged frozen code, then produces `/tmp/nerva-backend-v37-composite.xml`: **35,815 passed / 108 skipped / zero failures across 35,923 cases**. This is **composite evidence, not a fresh full-suite pass**. Original failed XML is retained. Provenance `/tmp/nerva-v37-composite-provenance.json` pins both inputs and the test-only change: 276 frozen source/build hashes unchanged, 277 final hashes. All 23 areas verify against this executed coverage. Ruff/status/diff checks pass; canonical Bandit remains zero findings on unchanged production source.

Pytest completed before two orphan GPG test agents were terminated, scoped to this run's exact private homedirs; receipt `/tmp/nerva-v37-gpg-cleanup.json`. No active provider or external schedule was touched. Ledger remains 170 equivalent / 483 partial / 8 missing / 36 excluded of 697. All changes remain unstaged/unpublished. Next: execute the prepared email cancellation regressions, then repair deferred watermark ownership if confirmed; do not claim that investigation is already a reproduced failure.

V37 immutable private archive: `nerva-continuation-20261112-v37.zip`, 17,099,515 bytes, 308 paths, SHA-256 `b4e9a5122e0af434251e133764f79054d7b41149637a390aa9697bbcac690bd4`. CRC/clean-base apply check/result-byte comparison passed. Library `libfile_fde3_f-68f00906defc8191add32657cda40970_4f556dba9178819182620ad30bbe8468`, file `file_000000009a3481f5a555d90de4c9fb5d`; xattrs applied. The archive predates this self-reference only. V38 reproduction may proceed.

### V38 confirmed regression and implementation — 2026-11-13 04:14 UTC

Both original email cancellation repros fail on V37 code (`/tmp/nerva-v38-email-cancel-red.xml`): no handler delivered the message, yet a fresh adapter sees no UID2 because the worker already persisted it. Expanded root regressions also fail for cancellation after a completed prefix and after an earlier retryable gap (`/tmp/nerva-v38-email-prefix-red.xml`, four failures). This is now reproduced, not just an inspection hypothesis.

One Sol High implementer owns `email.py`, private H096 fetch-test adaptations and a new focused batch-checkpoint test file. Root owns the composed cancellation regressions, review, docs and integration. The worker will return a proposed checkpoint; routing owns persistence, including safe-prefix cancellation and earlier failure/defer floors. No premature-persist compatibility mode; existing plain-list fake transports may have no checkpoint. First-contact/reset and deliberately suppressed-message progress remain required. Mid-handler external delivery remains uncertain; no exactly-once claim is made. No publication or schedule activation.

V38 focused freeze: 84 email/checkpoint/worker/circuit/inbox tests and 40 reliability tests pass (`/tmp/nerva-v38-email-green3.xml`, `/tmp/nerva-v38-email-g15.xml`). Root cancellation proof includes persistence failure preserving CancelledError, fixed diagnostics and retryable unhandled mail (`/tmp/nerva-v38-root-cancel-final.xml`, five passed). Independent Sol High review found no concrete new loss path. First-contact failed SEARCH now makes no checkpoint proposal rather than inferring zero. Existing private fetch tests explicitly acknowledge accepted proposals; real-loop tests pin the persistence boundary. All changed Python Ruff and diff checks pass; integration/security checks are pending.

After V37 archive CRC and no process-holder checks, removed only the completed full-run fixture tree: 142,441 files / 6,090,182,117 logical bytes. Receipt `/tmp/nerva-v38-temp-cleanup.json`. All source, reports, XML, manifests and archives retained.

V38 frozen integration is running with gateway + platforms suites, the broader command/security/binding selection, and explicit safe-mode/boot-shutdown coverage. Runner `/workspace/scratch/verify_integration_v38.py`, evidence prefix `/tmp/nerva-integration-v38`. Canonical Bandit has zero findings; generated backend count is 35,936. No integration success claimed yet. V39 retained-worker deadline design is read-only until this checkpoint is archived.

### V38 final integration — 2026-11-13 04:26 UTC

Fresh common integration: **5599 passed, 0 skipped, 0 failed/errors**, 273.930s (`/tmp/nerva-integration-v38.xml`). All 280 frozen source hashes match. Gateway 4007 and platforms 1224 cases verified against that JUnit; generated Hermes/status checks and diff whitespace check pass. Backend collection 35936, frontend 2977, mobile 365. Ledger unchanged 170/483/8/36 of697. V38 email repair is locally verified; no live provider proof or publication. V37 full-backend evidence remains explicitly composite, not a fresh full pass. Next: V39 opening recognition deadlines per `/workspace/scratch/nerva-v39-next.md`.

V38 immutable delivery: `nerva-continuation-20261112-v38.zip`, 17289192 bytes,311 changed paths, SHA256 `e43a43f10a7bab438faf35e686363d4c6ae39ff5095876dfba6300659d606c5f`; Library `libfile_fde3_f-46ff5a666b6081918074360eb5a9ec4e_4f556dba9178819182620ad30bbe8468`. Cleanbase apply check, applied byte comparison, ZIP CRC and returned version xattr completed.

### V39 in progress — 2026-11-13 04:31 UTC

Two existing Sol High implementers own disjoint email/Slack adapters and their new deadline regressions, without subdelegation. Root owns common setting/wiring/parity, review and integration. Design `/workspace/scratch/nerva-v39-next.md` specifies one opening recognition budget and retained real thread/SDK cleanup; no thread-kill claim. Root expanded actual lifespan wiring regression first: two expected failures (label and missing email keyword), then 97 config/safe-mode tests pass after wiring all four adapters to the one validated setting. Adapter implementations and integration remain pending. V38 archive remains the last immutable completed delivery.

V39 interim review: Slack focused92 passed including actual installed SDK late cleanup. Email focused130 passed before an additional cross-review late-error classification regression; final freeze pending. Root pins/network safety143 passed (61.355s); Bandit scan zero findings before that narrow final email adjustment. Direct elapsed wake/constructor checks and worker-first timeout accounting were corrected during review. No common V39 success claimed. Remote PR1359 rechecked around04:32UTC: still open/draft/unmerged on686fcbf4; main1338833d unchanged.

V39 final freeze: Email131/131 including worker-first late-error classification; Slack92/92 including real installed SDK cleanup, wider exact-entry test timing. Cross-review findings addressed; no further concrete source defect identified. All changed Python Ruff, generated Hermes/status and whitespace checks pass; final Bandit zero findings. Backend collection35952. Common gateway/platforms integration launched with `/workspace/scratch/verify_integration_v39.py`, `/tmp/nerva-integration-v39.*`; outcome pending.

### V39 final integration — 2026-11-13 04:42 UTC

Fresh `/tmp/nerva-integration-v39.xml`: **5615 passed, zero failures/errors/skips**,283.724s. All282 frozen source hashes match. Gateway4023 and platforms1224 verified against JUnit; generated status/Hermes and whitespace checks pass. Backend35952/frontend2977/mobile365; ledger remains170/483/8/36 of697. No publication/live providers/schedule changes. V40 narrowed to ntfy inbound subscription claims keyed to actual HTTPX-normalized request URL, preserving existing replay cursor semantics. Separate actual-store proof confirms legacy email cursor identity collision (casefold user/omitted port); old rows lack identity provenance, so exact-resource claims need a deliberate technical migration policy. Scratch reproduction `/workspace/scratch/nerva-v40-identity/seen.json`; no production data touched. This issue does not block ntfy ownership work.

V39 immutable delivery: `nerva-continuation-20261112-v39.zip`,17484736bytes,313paths,SHA256 `0bfeb210456df1681fffa8fd2d976c708ba9c100add355d94c89a6bd41d5fb2a`; Library `libfile_fde3_f-229eddc48bb08191af34eff58e395c19_4f556dba9178819182620ad30bbe8468`,file `file_00000000aff881f59a15d51476db084f`. Cleanbase apply/result-byte/CRC checks passed; returned version xattr applied. Archive predates this self-reference only.

### V40 in progress — 2026-11-13 04:43 UTC

One Sol High implementer owns ntfy.py/new adapter claim regressions; second Sol High read-only review, no subdelegation. Root owns existing kernel-claim helper extension/new process tests and integration. Root reproduced two missing-behavior tests then added the ntfy-inbound namespace over the unchanged private kernel locking mechanism. Adapter derives identity from actual HTTPX-normalized GET URL (no bearer/replay query); canonical aliases must collide. Existing raw replay cursor behavior is preserved explicitly. No V40 completion/integration claimed yet. V39 remains last immutable completed archive.

V40 frozen milestone: full focused ntfy/kernel/manager selection70 passed; root manager/process3 passed; earlier kernelsecurity25 passed. Root isolated only the two intentionally unconfirmed-close fixtures with private per-test install roots; no claim forcibly released and all existing assertions retained. Read-only critical review found no concrete remaining claim defect. All changed Python Ruff and generated status/Hermes checks pass; backend35963. Full unfiltered backend launched via `/workspace/scratch/verify_backend_v40.py`, evidence `/tmp/nerva-backend-v40.*`; no full result claimed yet. Before launch, CRC-verified V38/V39 archives and no process-holder checks allowed deleting only their completed fixture directories:41660files/1409641449logicalbytes (`/tmp/nerva-v40-temp-cleanup.json`); all source/evidence/archives retained.

### V40 fresh full backend — 2026-11-13 05:06 UTC

`/tmp/nerva-backend-v40.xml`: **35963 total,35855 passed,108 skipped,zero failures/errors**,951.980s. This is a fresh full unfiltered backend pass, not composite evidence. All285 frozen source/build hashes match. All23 Hermes area suites verify against the executed JUnit (`/tmp/nerva-v40-hermes-verify.log`); skip reasons retained separately. Ruff, generated status/Hermes and canonical Bandit zero-findings checks passed. Two orphan GPG test agents were terminated only after pytest completed, scoped to this exact basetemp; receipt `/tmp/nerva-v40-gpg-cleanup.json`. Ledger unchanged170/483/8/36 of697. Frontend/mobile source unchanged since earlier recorded validations. All work remains unstaged/unpublished, no paused schedule resumed.

Next V41 addresses newly reproduced H069 multiline/oversized provider error envelopes. Scratch sanitizer candidate passed64 tests after a prose-boundary correction, but is not installed in V40; independent review prompted a separate Anthropic producer-side fixed-message candidate to avoid emitting arbitrary exception text. Native regression/apply/composed checks remain required. Full V40 success is not a claim that this newly discovered behavior is already repaired.

V40 immutable delivery: `nerva-continuation-20261112-v40.zip`,18273671bytes,316paths,SHA256 `82e6ae3cc828da4996a70508393a75fb9260718b95c6e7c3a0d5eaffe09e36f7`; Library `libfile_fde3_f-1da357b74a948191be94a089c491cbe5_4f556dba9178819182620ad30bbe8468`,file `file_0000000008f481f5ae0b53f899eaaf8b`. Cleanbase apply/byte comparison/ZIP CRC checks passed; returned version xattr applied. Archive predates this self-reference only.

### V41 native repair in progress — 2026-11-13 05:11 UTC

V40 source remained frozen during isolated candidate work. After its archive, root installed three native regression files:26cases,18 expected failures/8passes before implementation (`/tmp/nerva-v41-native-red.xml`). Both sanitizer and Anthropic patches passed git apply --check before application; H297 expectations now require fixed messages instead of raw exception detail. Native focused run:204passed (`/tmp/nerva-v41-native-focused.xml`), covering new envelopes/transports/producers, H069 existing outbound, images, quota and auth rotation. Root retained fixed shared-429 guard wording with HTTP429 category.

Parser recognizes a bounded header then scans balanced brackets/quotes linearly, preserving prose after a completed marker and limiting status scanning to4000detail characters. Anthropic emits only fixed reason/validated numeric status, never str(exception), across normal, stream, quota and exhausted-profile failures. This removes its untrusted framing ambiguity at the producer. Root Telegram final and actual OpenAI JSON/SSE tests cover multiline/oversized envelopes. Final broad gateway/platform/providers integration, security checks and contract review remain pending; no equivalence promotion claimed.

V41 composed-order follow-up: root reproduced cancellation MARKER-only lines before/after a complete provider error bypassing mapping, then being removed and leaving request ID visible. Two native tests failed before correction (`/tmp/nerva-v41-cancellation-red.xml`). The first broad integration was intentionally interrupted with SIGINT before source edits; terminal exit2, receipt `/tmp/nerva-v41-integration-interruption.json`. It is not passing evidence. Sanitizer now normalizes/removes internal cancellation metadata before whole-envelope classification; actual Telegram/OpenAI transport regressions include prefix/suffix variants. A fresh final integration will use `/tmp/nerva-integration-v41-final.*`.

Completed V40 fixture cleanup initially hit read-only test directories after partial removal; root repaired permissions only on owned non-symlink fixture directories after repeated archive-CRC/no-holder checks. Remaining32598files/1950794130logicalbytes removed; earlier partial count unknown (`/tmp/nerva-v41-temp-cleanup.json`). Source, test XML/logs/manifests and archive retained.

V41 final native focused244passed,7.351s (`/tmp/nerva-v41-native-final.xml`), zero failures/errors/skips. Final canonical Bandit zero findings; Ruff and generated status/Hermes checks pass. Backend count35999. Fresh final gateway/platforms/providers integration launched via `/workspace/scratch/verify_integration_v41_final.py`; `/tmp/nerva-integration-v41-final.*` is the authoritative pending run. No H069 promotion before this result and final ledger verification.

### V41 final integration and H069 code review — 2026-11-13 05:26 UTC

Fresh `/tmp/nerva-integration-v41-final.xml`: **8139passed,zero failures/errors/skips**,412.628s. All290 frozen source/build hashes match. Gateway4070/platforms1224/providers2508 area suites verified against this exact JUnit; coverage counts overlap and are not additive. Native focused244passed; final Bandit zero findings and Ruff/checks passed. The earlier interrupted V41 run remains explicitly incomplete.

H069 promoted only for local code equivalence after reviewing all six frozen text behaviors, reproduced security fixes and executed transport/provider coverage. Live provider/device acceptance remains unrun and binary inspection stays outside this text contract; these limitations are preserved in the review summary, not erased. Ledger now**171equivalent/482partial/8missing/36excluded=697 (24.5%)**. Main remains169/484/8/36 on1338833d, PR1359 open draft/unmerged on686fcbf4 per fresh GitHub lookup (`/tmp/nerva-v41-remote-comparison.json`). No publication or external schedule changes. V40 remains the latest fresh full backend run on its own earlier source.

Post-review ledger/generated-report regression also passed (`/tmp/nerva-v41-ledger-final.xml`); no production source changed after the fresh final integration. Next authorized lot V42 is a scratch-reviewed plugin loadset prefilter with native verification still pending; it will not grant new plugin/network authority.

V41 immutable delivery: `nerva-continuation-20261112-v41.zip`,18579184bytes,321paths,SHA256 `91967d5edea57172396bb10e642bd6ad63b43bdcc2ba47864b950424a230f3c5`; Library `libfile_fde3_f-cae4b55873a48191a1ca93a792182483_4f556dba9178819182620ad30bbe8468`,file `file_0000000042a481f598f06851fc32819c`. Cleanbase apply/result-byte/CRC checks passed; returned version xattr applied. Archive predates this self-reference only.

### V42 native plugin prefilter in progress — 2026-11-13 05:29 UTC

One Sol High scratch implementer and one read-only Sol High reviewer prepared a static lazy resolver and guarded construction for all24 built-in connector classes; no proxy registry or new command/network authority. Root copied native regressions/fresh-process probe, observed4failures/1pass on original code (`/tmp/nerva-v42-native-red.xml`), then applied candidate only after git apply --check. Env layering and stored keys precede the policy snapshot; admitted objects stay concrete, order/kwargs/WhatsApp alias/final recheck/LLM/oracle/Argus semantics retained. Shared OAuth helper remains outside excluded-connector import scope.

The native binding-inventory test then failed exactly for moved oracle_bridge and argus callsites (`/tmp/nerva-v42-binding-red.xml`). Root verified actual lines410/415 and updated only those two pinned tuples, retaining the closure guard. Focused native loadset/provenance/safe-mode/facade/binding/network tests running; no V42 completion or new H079 equivalence claimed.

V42 native focused verification: **355 passed, zero failures/errors/skips**,95.454s (`/tmp/nerva-v42-focused.xml`). Ruff on changed V42 files and git diff --check passed; generated backend collection now36004. Completed V41 fixture trees removed only after archived CRC/no-process-holder checks (`/tmp/nerva-v42-temp-cleanup.json`), preserving all logs/XML/source/archives. A fresh unfiltered full backend V42 run is prepared because plugin startup/import changes affect consumers beyond the focused tests. H079 remains partial; ledger171/482/8/36. Recorded 2026-11-13T05:38:28.899055+00:00.

### V42 full result and targeted correction — 2026-11-13T05:59:59.630879+00:00

Fresh full `/tmp/nerva-backend-v42.xml`: **36004total,35893passed,108skipped,3failed**,931.248s. All293 frozen source hashes matched. Two H273 provenance spy failures proved JARVIS_ANALYTICS_MAX_EVENTS now first reads after .env because admitted connector imports moved later; removed only its obsolete READ_BEFORE_LOAD entry/comment from env_provenance.py. Complete H273 provenance+env+new plugin tests then **140passed**,79.53s (`/tmp/nerva-v42-provenance-final.xml`). The third failure was SQLite SMTP test's2s worker-entry wait; unchanged complete test file passed **10/10**,2.86s (`/tmp/nerva-v42-sqlite-diagnostic.xml`). A cancellation/connection-lifetime defect was not established by that timeout; no test assertion or production SQLite behavior was weakened. Original failure retained. This is **not a fresh full green run**; V40 remains last fresh full green, V41 has later fresh integration. No synthetic all-green XML produced for V42. Final evidence receipt records the one additional provenance metadata file. GPG test-agent cleanup scoped to two exact completed-basetemp homedirs; logs/XML/fixtures retained. Bandit0 and scoped Ruff/diff/generated checks passed before metadata correction; metadata Ruff passed afterward.

V43 owned/coalesced Telegram postreload menu candidates remain scratch. Native baseline composition3failures, final isolated composition4passes including actual manager stop-budget retention, plus independent focused candidates. No live publication. Next integrate V43 after V42 archive, then run fresh integration/full as warranted.

Owner steering on resources supersedes AGENTS implementer-model and concurrency preferences for this session: three new gpt-6-luna/high workers now own distinct CLI, startup-composition tests and Discord-deadline investigation scratch paths. Earlier two Sol/high candidates preserved. Root retains integration/critical review; coordinator model/effort not exposed verifiably by this session. No numerical cost saving claimed. Publication/schedule restrictions unchanged.

V42 immutable delivery:19364159bytes,325paths,SHA256 `f782cf747ed1cd4ec14f9a5adeb2e08e880425f4f3a8d5c68860a0bc6cb4a084`; Library `libfile_fde3_f-4e9efaf702188191b84f9724eb7e778d_4f556dba9178819182620ad30bbe8468`,file `file_000000009fe081f5b1e7e7b3de674eda`. Cleanbase apply/result-byte/ZIP CRC passed, returned version xattr applied. Archive predates self-reference only.

### V43 native Telegram postreload refresh — 2026-11-13T06:06:45.181263+00:00

Installed three production candidates only after git apply --check, with correct header strip depths. A prior wrong-strip check applied nothing; its inadvertently started redundant baseline run was stopped (exit2), explicitly not evidence of passing (`/tmp/nerva-v43-focused-aborted.json`). Native red23cases:21failed/2passed; additional Luna/high actual managed-startup regression reproduced stale owner menu then passed with isolated candidates. Native focused **165passed**,65.73s (`/tmp/nerva-v43-native-final.xml`). Root fixed Ruff B023 by binding each iteration's captured guard; final24new regressions **24passed**,4.99s (`/tmp/nerva-v43-native-closure-final.xml`); scoped Ruff clean.

Behavior: synchronous postcommit enqueue, bounded caller wait outside reload lock, retained/coalesced adapter task, serialization with startup, per-POST exact identity/lifecycle guards, current owner projection, physical request settlement before client/claim release. Fixed a review-found stale-old-guard/new-request loss in scratch before integration. Tests include real loader/menu projection, managed startup race, caller cancellation, actual manager stop budget and owner/private scope safety. H079 remains partial and former-owner scoped menu deletion remains outstanding. No live messages/menu publication.

Prepared fresh full backendV43 to cover this integration and V42 provenance correction. V44 diagnostic/CLI and V45 Discord deadline candidates remain scratch on independent Luna/high tasks. Completed V42 fixture tree removed after archive CRC and no-holder checks (142534files,6092348849logicalbytes); all logs/XML/source/archives retained (`/tmp/nerva-v43-temp-cleanup.json`).

### V43 fresh full backend green — 2026-11-13T06:24:53.614283+00:00

`/tmp/nerva-backend-v43.xml`: **36028total,35920passed,108skipped,zero failures/errors**,932.181s. All298 frozen source/build hashes match. **23/23 Hermes area suites pass** against this exact executed JUnit; canonical backend count36028matches. Original V42's three failed cases pass here, including unchanged SQLite cancellation test; no fixture weakening. Scoped Ruff, generated status/Hermes and canonical Bandit0 checks pass. Two exact-basetemp GPG orphans terminated after actual pytest exit (subreaper argv distinguished from pytest); wrapper exit0. This is the latest fresh full green result, not a composite. Skip reasons retained. Frontend2977/mobile365unchanged since previous JS validation; ledger171/482/8/36of697, main lastverified169/484/8/36atV41.

Next V44 is signed extension inspection/CLI truthfulness, with native integration pending: separate common tool gates from command-specific registry gates, project exact live declaration metadata, bounded strict CLI command-list validation64. Sol/high initial diagnostic candidate and Luna/high CLI/followup have isolated evidence; no new status credit. V45 Discord readiness+config+fixture candidates are scratch only; root review found and corrected cancelled-admission and simultaneous SDK-exit races before integration. V46 passive HUD inspection panel is delegated scratch-only to Luna/high. All native work remains unstaged/unpublished, no paused external program resumed.

V43 immutable delivery:20174671bytes,329paths,SHA256 `6c0a631aaad84c8c456291fbf0405c4e3294ac05453be666d13a01be0eff0cce`; Library `libfile_fde3_f-4cfd0e5ed26c81918adea8cd8772b9b0_4f556dba9178819182620ad30bbe8468`,file `file_00000000ee3081f5b9a6a3347ad5c7fc`. Cleanbase apply/resultbyte/CRC verified, versionxattr applied. Archive predates self-reference only.

### V44 native extension inspection/CLI — 2026-11-13T06:28:50.045134+00:00

Native22newtests reproduced12failures/10passes beforeimplementation (`/tmp/nerva-v44-native-red.xml`). Applied final doctor+CLI patches only after git apply --check. Root review corrected conflated command/tool eligibility and exact live declaration metadata before native integration; CLI uses canonical64-declaration bound. Native complete focused set **259passed**,24.181s,zero failures/errors/skips (`/tmp/nerva-v44-native-final.xml`), Ruff clean. Actual activation-rig inspection invokes no extra runner; deactivated/revoked/replaced/commandcollision cases remain truthful. This changes read-only diagnostic metadata/CLI, not extension activation or authority. H079partial, ledger171/482/8/36. Dedicated HUD/mobile views remain explicitlypending. Fresh fullV43 is earlier source; V44 broad verification will be grouped with next nativeV45afterfocusedproof, not claimedalreadyrun.

### V45 native Discord readiness deadline — 2026-11-13T06:32:35.085315+00:00

Native10deadline regressions:9failed/1passed beforeimplementation (`/tmp/nerva-v45-native-red.xml`). Checked/applied separate adapter, config and fixture patches. Root reviewed cancellation-before-callback-release, simultaneous SDK completion and prematurehealthy races; all fixed in scratch beforeintegration. Existing successfakes now emit actualreadiness while SDK lifetime remainsactive; original claim/contention/cleanup/pause checks retained, validcredential health expectations updated to the new readiness contract. Root sortedimports and removed two unusedfixturealiases (fixtureparametersremain). Native focused **224passed**,77.69s (`/tmp/nerva-v45-native-focused.xml`), Ruff clean.

Initial deadline expiry marks not-running/connect_timeout and fences inbound/slash/menu work while retaining exact SDK/client/claim until existingstopsettlement. Normal reconnect after timelyinitialreadiness unchanged. One normalizedstartupbudget now reaches five transports. No liveprovider or externalprogram operation. H083remains partial; no newequivalencecredit. Next fresh fullbackend covers combinedV44/V45source; V43 remains last completedfreshfullgreen until that result. V46 HUDcandidate staysisolatedscratch.

### V45 full result and V46/V47 integration — 2026-11-13T06:57:01.624872+00:00

Fresh full V45 completed: **36060 total,35950 passed,108 skipped,2 failed,zero errors**,972.447s (`/tmp/nerva-backend-v45.xml`). All301 frozen source/build hashes matched before followup edits (`/tmp/nerva-v45-full-review.json`). The two failures were existing Discord SDK fakes without retained lifetime/initial on_ready. Updated only `test_default_deny_front_door.py` and `test_h083_escalation_fences.py`; full two-file rerun **58 passed**,0skips/errors/failures (`/tmp/nerva-v45-two-fixtures.xml`), scoped Ruff clean. All original access/escalation assertions retained. V45 is a failed historical full run, not retroactively green. Latest fresh full green remains V43.

V46 desktop and V47 mobile read-only extension views applied after `git apply --check`, with separate file ownership. Desktop focused **48 tests/5 files**,typecheck/build passed; full frontend pending. Mobile full **377 tests/58 suites passed**,typecheck passed (`/tmp/nerva-v47-mobile.json`, `/tmp/nerva-v47-typecheck.log`). Mobile component's initial5checks are static source contracts;7API cases execute behavior. Additional rendered lifecycle tests are being prepared with the existing native harness; no live-device claim.

Backend route/parity probe47cases found one stale allowance for newly surfaced `/api/plugins/extensions`; removed only that allowance and mapped inspection to Build. Other46passed; complete parity-file rerun **18passed**,12.424s (`/tmp/nerva-v47-parity-final.xml`). Current docs/HA-4i note local extension views without closing HA-4i or promoting H079. Ledger remains171equivalent/482partial/8missing/36excluded of697.

Three reused implementers are gpt-6-luna/high: desktop integration, mobile/Discord fixture validation, and separate read-only lazy-restart design. Coordinator reviews authority/lifecycle boundaries and owns integration. No measured per-agent billing/token data; coordinator's exact model/effort is not exposed verifiably. No stage/commit/push/merge/deploy, live sends, paid activation or paused-program changes.

### V47 final integration checkpoint — 2026-11-13T07:23:50.076043+00:00

Fresh full backendV47: **36060total,35951passed,108skipped,1failed,0errors**,942.196s (`/tmp/nerva-backend-v47.xml`). All311frozen source/build hashes match. Both prior Discord cases pass. **23/23 Hermes area suites pass** on this receipt; global run still failed its separate doc-reference check because ROADMAP retained55uncalledroutes after the new Extensions view reduced UNCALLED_BACKLOG to54. Corrected only the factual roadmap count; complete doc-reference+HUDparity rerun **24passed**, `/tmp/nerva-v47-doc-parity-final.xml`. This is separate followup evidence, not a fabricated all-green full run. Latest entirely green fresh full remainsV43.

Full native frontend **3000passed,0failed**,307files,464.04s (`/tmp/nerva-v46-frontend.json`); subsequent actual mobile-component lifecycle harness **7passed** (`/tmp/nerva-v47-rendered-native.json`) exercises collapsedno-fetch, user-onlyheaders, refresherror clearing, close/unmount and host/credential changes. Current frontendcount3007 comes from disjoint full3000+new7receipt filenames, not a claim that full3007ran. Mobile full377passed and typecheckgreen. HUD typecheck/buildgreen; generated desktoproutes rebuilt. First native rendered-test invocation used wrongcwd/npm and exited127withouttests; corrected frontendcwd run is the passingreceipt.

Generated status/Hermes, scopedRuff and gitdiffcheck pass. Two exact completed-basetemp GPG orphans terminated after actualpytest exit (`/tmp/nerva-v47-gpg-cleanup.json`). Completed V45 and older V16 fixture trees removed only after no-holder and immutableV43archiveCRC checks; logs/XML/source/archives retained. No livebrowser/device/provider proof.

V49 is isolated scratch: persistent private consentrevision, same-digest revoke/regrant fencing, exact activationepoch, serialized retirement/install, late tool-resultchecks and truthfuldoctor. Ten actual runtime/inspection/observer regressions fail currentnative and pass combinedcandidate; existing observertest now needs explicit reactivation afterregrant before independentpackage check. Shared cross-process consentmutation lock is underfinalreview. V48 activation-hintstore candidate remains unused/scratch; no restart-restoration claim. Cumulative objective unchanged171/482/8/36of697. No publication or pausedprogram changes.

V47 immutable delivery:21933638bytes,343paths,SHA256 `74efa4c67f83a5d9500239ae407a19ae60a41a254900e8f0a9e568d6414fe529`; Library `libfile_fde3_f-8e4a7d4ef8b881918a072cf0657c5643_4f556dba9178819182620ad30bbe8468`,file `file_00000000152481f58b89dc4878404a73`. Cleanbaseapply/resultbyte/ZIPCRCverified; currentLibraryhelper persisted returnedversionxattr. Archive predates thisselfreference and V49nativeintegration.

### V49 native grant-revision and retirement safety — 2026-11-13T07:31:19.465035+00:00

Applied reviewed V49patch after gitapplycheck to consent/runtime/doctor, new sharedstore_lock, two existingtest adaptations and three newtestfiles. Native focused **315passed**,22.899s (`/tmp/nerva-v49-native-final.xml`), Ruff fixeslimitedto4nestedwith simplifications. Later realToolRPC retirement test imported from reviewed scratch; it passed1case with actualToolRPCServer.handle, offline runner, cancellation/absence/rebind proof. Native common gateway+extensions+ToolRPC+docparity run nowpending (`/tmp/nerva-gateway-v49.xml`). Currentbackendcollection36090;frontend3007/mobile377retained actualpriorreceipts. CanonicalBandit0 `/tmp/nerva-v49-bandit.json`.

Criticalreview added durableprivate grantrevision and serialized full grant/revoke transactions; digestalone cannot fence revoke→same-digestregrant. Newgrantsrandom64hex; sameunrevokedvalidgrantkeepsrevision; legacyreads deterministicdomainseparatedrevision, explicitgrantupgrades; malformedexplicitrevisionfailsclosed; publicHTTP/CLI as_dictunchanged. Newsharedlock serializesthread/processwriters and retains lockinode, verifies before/afterOSlock, closesfailurefds; portable spawnprocess test, POSIX-specificinjections skipWindows. LiveWindows remainsunproven.

Runtimecapturesgrantrevision, invalidatespendingactivationepoch beforepublicdeactivationawait, serializesonlyretirement/install (sandboxproofoutside lock), rechecksfinalepoch/capacity/package, and fenceslate toolresults against exactactivation/enablement/grant/package. Commandsandobserverscheckexactgrant; doctorhidestalegrantcallables. Nativebaseline10runtime/inspectioncasesfailedthencombinedoverlay10passed. Existingobservertestnow assertsconsentchangedafterregrant then explicitlyactivates before independentlytestingpackagechange. Existingconsentdirectorysnapshot nowincludespersistent.lockfile. Cross-processhintstore V48 remainsunused/scratch; restartlazyrestoration stillnotimplemented.

Newsteering: reconcile HermesMac export repo-013 HEAD2d87d92f+dirtyworktrees withoutbulkpatches or sourceoverwrites. Parentpath `/workspace/shared/mac-handover-20261113/RECONCILIERE-DOT.md` doesnotexistinthisexecutor; read trustedparenthistory and recovereduserDrivearchiveURL. A Luna/highagent isretrievingintoisolatedscratch; exactexportbytes/reporthavenotyetbeenreadhere. No claim296changesare296missingfeatures. Currentnativeworkpreserved; no publication/pausedprogramchange.

### V49 common verification and Mac audit blocker — 2026-11-13T07:36:31.427294+00:00

The common gateway, extension, ToolRPC, documentation and HUD parity run passed: **4497 passed,9 skipped,0 failures/errors (4506total)** in204.521s (`/tmp/nerva-gateway-v49.xml`). All317 captured source/build hashes match. Runner exit0; scopedRuff, generatedstatus/Hermes and diffcheck pass. CanonicalBandit0. This is a fresh common integration result, not a full backend rerun. Earlier fullV47 retains its one historical documentation-count failure; that factual count and its entire24-test doc/parity set passed separately, and the same guards pass here.

Mac export audit could not start: the parent path `/workspace/shared/mac-handover-20261113/RECONCILIERE-DOT.md` is absent in this executor. Drive metadata identifies `Handover-dot-Hermes-Mac-2026-11-13.tar.xz`,23837868bytes,fileID1VPKpPaCYPwpxVyxnOh6qFXx3C0ldr48u. Connector raw fetch provided a file reference, but local transfer returnedHTTP403 twice, including one refreshed reference. The isolated audit directory has no archive bytes; checksum, extraction, repo-013HEAD2d87d92f, dirtyworktree content and conflicts are therefore **not independently verified here**. No automatic approval rejection occurred; this is a transfer/access blocker. No further transfer retry without new access/reference evidence. Parent already has an extracted copy in its own environment; provide it to this executor via a supported file transfer to resume the requested comparison. Do not infer296missingfeatures or apply exportpatches blindly.

Current native checkout is preserved and unpublished. V48 activation-hint store remains scratch-only; lazy startup restoration is not shipped. Ledger171equivalent/482partial/8missing/36excluded of697. Main was last independently checked atV41 (169/484/8/36 on1338833d); no new remote-state claim. Three gpt-6-luna/high implementers completed separate work with root integration/criticalreview. No measured cost/token attribution or verified exact root model/effort is available.

Additional parent handoff: deep audit paths /workspace/shared/nerva-mac-deep-audit/REPORT.md and /workspace/shared/nerva-mac-deep-audit/code-block-classification.tsv were also checked and are absent in this executor. Parent reports160untrackedpaths absent from PR1359baseline, and cache/node_modules false positives among dirtyworktrees. These are reported baseline comparisons, NOT evidence of missing local V49 features. Need the report/TSV and relevant snapshots transferred into this executor to compare actual current bytes; no Mac patches have been applied.

V49 immutable delivery:22141494bytes,349paths,SHA256 `07b217bf265f6e66cff65d0606b758d4b70df540a97197d019aa6c11997371e8`; Library `libfile_fde3_f-ad9b81b147448191b79d86629d559c62_4f556dba9178819182620ad30bbe8468`,file `file_0000000013a481f58a2391707397906f`. Cleanbaseapply/resultbyte/ZIPCRCverified and currentLibraryhelper persisted versionxattr. Archive predates thisselfreference only. All runs terminal; Macaudit stillblocked at contenttransfer, no exportedsourceapplied.

## V51 — startup restoration and persistence (2026-11-13)

Latest parent direction explicitly resumed integration after isolated V50. Integrated the reviewed V50 helpers/controller/runtime and catalog fixture correction, then completed acquisition startup composition, first-owner lazy activation, runtime hint persistence, uncomposed revocation, explicit API activation composition, menu refresh queueing and CLI persistence warnings. Startup reads bounded metadata/current consent and installs ADMIN routes only; it does not compose promotion, initialize package/profile runtime or execute candidate code. Coordinator rewiring retires exact old routes without deleting hints and fences previous host callbacks by acquisition identity.

Activation success remains separate from saving its restart hint. The API exposes bounded `restart_restore` state; the CLI warns when restoration is unconfirmed without falsely reporting that an active extension failed. Consent withdrawal removes placeholders even without a runtime. Hint removal occurs before awaited RPC retirement, preventing cancellation from leaving a same-grant restart route behind. Revoke/regrant revision fencing continues to reject stale persisted hints. Conditional late cleanup preserves replacement activation hints and checks exact activation identity under the mutation lock.

Verification chronology is explicit: the first native focused run had one binding-callsite inventory failure after coordinator line movement; refreshed all 16 observed coordinates, with no writer additions or removals. The first common run then passed **4,797 tests, 10 skipped, zero failures/errors** (4,807 total), 223.737 seconds. Canonical Bandit initially found four new silent exception branches; replaced these with bounded diagnostics/explicit failure states, with no baseline weakening. Final canonical Bandit reports **zero findings**. Post-fix focused tests passed **83/83**, including the exact binding inventory. A fresh final common run is recorded below when terminal; do not infer its result from the earlier run.

Actual collection is **36,190 backend / 3,007 frontend / 377 mobile**. Only backend collection changed. Previous frontend/mobile full-run evidence remains historical; no new full backend or live Docker/provider/device acceptance is claimed. HUD/mobile extension inspection remains read-only; activation/revoke persistence status is available through existing admin API/CLI. H079 remains partial and the fixed ledger remains 171 equivalent / 482 partial / 8 missing / 36 excluded = 697.

Separate Mac recovery review: independently reconstructed the inline tar-inspection patch against unchanged native archive_safe.py. Supplied 22 tests plus existing 102 and six adversarial cases passed, but `tarfile.members` retained copied global PAX metadata. A separate three-line cache-clearing proposal fixes the demonstrated multiplication: the 500-empty-file/2,000-PAX-key fixture falls from 27,694,349 to 1,602,501 bytes peak Python allocations (tracemalloc, not RSS). Its cache regression failed before the fix; corrected isolated suite **131 passed**, Ruff and patch apply-check passed. No archive helper or caller adoption was integrated into native V51. Source-path trust and inspection/use TOCTOU remain separate. Report, proposed combined patch, tests and probe are included under `mac-review-not-integrated` in the checkpoint.

Three implementation workers used gpt-6-luna/high on separate files, without subdelegation; root performed critical review and integrated fixes. The separate archive reviewer inherited the coordinator configuration; its exact model is not verified here. No measured resource savings are claimed. No stage/commit/push/merge/deploy, network configuration, live provider operation or paused-program reactivation occurred.

Final V51 common verification is terminal: **4,797 passed, 10 skipped, 0 failures/errors** (4,807 total), 217.432 seconds, `/tmp/nerva-gateway-v51-final.xml`. All **331 source/build hashes match** the pre-run snapshot; `/tmp/nerva-v51-common-review.json` records this and zero canonical Bandit findings. Runner exit0, Ruff clean, generated status/Hermes checks and git diff --check pass. This includes the catalog fixture file omitted from the previous V49 common suite: its two stale-signature failures were independently reproduced on unchanged V49, then corrected locally without relaxing production consent checks. Archive inspection remains isolated and is not included in the 4,807-case native count.

## V52 — snapshot-bound restore and recall-scope audit (2026-11-13)

Base HEAD remains 686fcbf4f25ebfbb416b3a35dff29045163cffbd; cumulative local changes are uncommitted. Implemented bounded regular-file snapshots in archive_safe.py and adopted them in backup restore request, stage and apply. SHA-256 binds the raw compressed/encrypted bytes to approval and staging; validation/application use the private copy. Legacy cards/stages without a digest fail closed and require a fresh explicit request. Existing extractor directory/duplicate-manifest rules, credential retention, expiry, rollback and one-attempt behavior remain. The snapshot lives through extraction and preserves encrypted suffixes. Temporary disk usage grows with raw archive size and is bounded; the same-UID arbitrary-file-access threat is outside this private-file boundary.

Independent critical review reproduced the original behavioral defect: swapping a valid archive while preserving size/mtime returned restored on pre-V52 backup.py. It also reproduced three disappearing-archive races; resolve/stat and staging errors now produce persisted failure/refusal outcomes, clean the apply journal and do not request restart. Cancellation propagation remains intact; no claim is made that cancellation stops a running Python worker thread. Three existing approval-test files now construct successful cards through restore_request; separate tests retain missing-digest refusal. Gzip fixture metadata variation was removed as a source of replacement-fixture flakiness.

Final combined backup/archive/CLI/admin-transfer/recall-scope suite: **414 passed, 0 skipped, 0 failures/errors**, 63.564 seconds, `/tmp/nerva-v52-final.xml`. All **1,228 source/test hashes remained unchanged** during that run (`/tmp/nerva-v52-source-review.json`). Earlier helper run162 passed. Initial broad357-case run had seven legacy fixture failures, subsequently corrected; it is not reported as passing. Canonical final Bandit has zero findings/errors. Ruff, generated reports and diff checks are recorded separately. No full-backend or native-Windows/live-restore acceptance is claimed; V51 gateway common4,807-case receipt remains historical.

SEC-B5 audit corrected stale documentation: current HTTP handlers and Orchestrator.process_detailed already bind/reset action origin around recall. Five new tests exercise actual recall taint, inherited origin and cancellation. No runtime taint policy changed; outer returned-result authority semantics remain an explicit open review. Hermes stays171 equivalent /482 partial /8 missing /36 excluded of697; H010 retains its existing verdict, and SEC-B5 is not declared closed.

Correction to historical V51 tar-suite counting: the original archive suite had90 testcase nodes. The corrected isolated inspector/cache suite had119 testcase nodes plus12 successful subtests, reported as131 aggregate reports. All passed; the immutable V51 export is unchanged. The recovered regular-file-only inspector/cache proposal remains unintegrated and targets V51 source, so do not apply blindly after the new snapshot helper. Backup's valid directory/legacy-manifest format uses its existing extractor. Full Mac delta transfer remains unavailable in this executor; no bulk Mac integration claim.

Two smaller-model workers (existing gpt-6-luna/high configurations) handled backup and recall/next-contract work; the inherited-model archive reviewer performed independent adversarial review, and root reviewed/integrated. Exact inherited/root model and measured costs are not available. No publication, network changes or paused-program reactivation occurred. V53 H697 terminal-session recovery is being prepared separately in scratch and is not included in native V52.

V52 final static/generated checks passed: scoped Ruff, git diff --check, status_sync --check --reuse-test-counts and hermes_status check. Actual backend collection36,228; frontend3,007/mobile377 retained earlier collection receipts.

## V53 — exact terminal-session recovery (2026-11-13)

Integrated shared browser startup/desktop recovery only for the hub's exact requested-session-missing 404. Recovery uses the existing authenticated `/memory` client, validates the replacement snapshot, and commits selection/storage/transcript together. Current fallback reads coalesce; stale A-to-B-to-A reads cannot be reused, and healed ids latch until explicit reselection. Selection, request, text-turn and lifecycle generations fence delayed replies, including a typed turn that starts and finishes before React's busy state is committed. Transient/auth/history/proxy refusals preserve the session. Invalid transcript fields cannot leave a partially changed selection. No reclaimed-session push protocol was invented; mobile terminal recovery and live acceptance remain open, with parity notes updated.

Independent behavioral baseline: unchanged native app/desktop plus the new rendered probes produced **6 passed /10 failed of16**, demonstrating dropped storage on nonterminal errors and absent desktop healing. Reviewed candidate: **103 focused tests passed** and typecheck passed. Native complete browser suite **2,831 passed**, zero skips/failures, 408.332 seconds; all **565 browser source hashes match**. The disjoint native React suite passed **197/197**, giving the frontend job scope **3,028 passed** across two runs (not one combined invocation). Native TypeScript and both production Vite builds passed. Real-manager session/continuation backend checks passed **52/52**, including exact missing404 versus corrupt-history409; direct handler tests do not claim auth-dependency or live acceptance. Mobile unit count377 is historical and distinct from native React197. Original receipts and the disjoint aggregate receipt are retained.

## V54 — scoped first-party startup diagnostics (2026-11-13)

Integrated H695 startup diagnostics using ImportError.name for `agents`/`agents.*`, preserving original exceptions, tracebacks and statuses. Messages describe possible install mismatch or code defect and state doctor's diagnostic role; there is no automatic repair. Scope covers early imports, predecessor waiting, staged-restore bootstrap and pre-server preparation. Independent review reproduced and corrected the latter bootstrap gaps. Transitive third-party, unnamed and near-prefix imports are not relabeled; configuration refusals retain exit78. The runtime server and special update rollback/fallback functions were independently AST-compared and remain unchanged. The comparison against old native source is retained as isolated evidence; its tautological form was not copied into native tests.

The common native run covered **1,412 tests:1,404 passed,7 skipped,1 failed**, 418.339 seconds (`/tmp/nerva-v54-final.xml`). All **1,296 pinned source/test hashes matched** during that run. The failure was an old exact-indentation assertion for module startup order after introducing diagnostic try blocks. Updated that test to inspect module/try-body AST order without descending into unexecuted function/conditional bodies, preserving predecessor-before-restore-before-app assertions. The whole affected test file plus both new H695 files then passed **26/26** in7.641 seconds. Production sources did not change after the common run; the only changed pinned path is that test file. This is common-run plus targeted-rerun evidence, not a claim of a new fully green common rerun or full backend suite. Seven skips are existing host conditions: IPv6 availability, inability to drop root/change ownership, and four absent-rustc cases.

Canonical Bandit over agents/scripts plus serve.py reports zero findings/errors; scoped Ruff is clean. A redundant default status collector was stopped after discovering it would rerun the completed JS suites; no success is claimed for that interrupted collector. Counts instead use the completed disjoint JS receipts plus fresh backend collection. Two GPG agents left by completed tests were terminated only after verifying their private V54 fixture paths; no real user services were stopped. Actual tracked counts are **36,240 backend /3,028 frontend /377 mobile**, with mobile's unit-run evidence historical. Final documentation/generated checks are recorded in accompanying receipts.

Ledger remains **171 equivalent /482 partial /8 missing /36 excluded =697**. H695 stays partial for dependency self-repair, install-path invariants and Windows E2E; H697 stays partial for push integration, further pollers and native/live acceptance. The entire backlog is not closed. Mac export content transfer remains unavailable in this executor; the separate recovered tar inspector is still proposed only, and no bulk Mac patch was applied. No stage, commit, push, merge, deployment, network configuration, live restore or paused-program reactivation occurred. Two existing gpt-6-luna/high workers handled isolated work; independent inherited-model review and root integration retained critical checks. Exact inherited/root model and measured costs are unavailable.

Final V54 documentation checks passed47/47 in17.549s. Generated status/Hermes checks and git diff --check passed. V53/V54 production files are frozen for the cumulative delivery.

Packaging removed one extra EOF newline from each of the two new rendered frontend test files. This formatting-only change is recorded in nerva-v54-test-formatting.json; production code/build bytes remain unchanged and no redundant test rerun is claimed.

## V55 opening checkpoint — full V54 rerun (2026-11-13)

Parent explicitly requested a complete common rerun after the indentation assertion correction. The identical44file/1,412-test scope passed **1,405 tests,7 skipped,0 failures/errors**,385.394s, `/tmp/nerva-v55-common-final.xml`. Testcase multiset matches the earlier V54 common run; all1,296 source/test hashes remained unchanged and the runner exited0. Existing seven host-dependent skips are unchanged. This is a new fully green common-scope result, separate from V54’s earlier failed run/targeted correction; it is not a full-backend run. Only completed-test GPG agents with private V55 fixture paths were cleaned up. Implementation of the next rollback-completion lot began after this rerun finished.

## V55 — exact rollback restoration completion (2026-11-13)

Base HEAD remains 686fcbf4f25ebfbb416b3a35dff29045163cffbd; work is local and uncommitted. After the full common rerun above completed, a targeted H695 audit reproduced false success: updater treated successful backup staging as completed restoration. Five regression failures and two passing controls were retained before implementation. Automatic and manual rollback now record data_restore_staged separately from data_restored and retain a private name/staged_at/SHA-256 identity. Finalization requires the exact backup.last_restore result with status restored and ok is True. Missing, malformed, stale, failed, deferred, cancelled and legacy boolean-only proof cannot confirm completion. Incomplete outcomes include inspection/manual recovery guidance, without automatic retry. Dependency-failure precedence and no-data rollback behavior remain.

Backup outcome metadata now carries the stage digest for success, failure, defer, cancellation and expiry. Five real temporary-archive regressions failed before and passed after that patch, and passed again natively. Independent updater review passed18 focused probes; the implementation worker passed12 focused cases including real temporary-root restore application before on_boot. Native combined archive/backup/updater/startup suite passed **429/429, zero skips/failures/errors**,44.173s, `/tmp/nerva-v55-rollback-final-final.xml`. This new-lot result is separate from the opening common1,412-case rerun. Source hash stability and static/generated checks are recorded in the exported receipts; neither run is a full backend test run. Only GPG helpers under this completed test run's private fixture root were stopped.

One existing gpt-6-luna/high implementer owned isolated updater changes; an inherited-model reviewer supplied separate backup metadata and adversarial review. Root reviewed and integrated both after the common rerun. Exact coordinator/reviewer model and attributable resource costs are unavailable. No publication, network configuration, live restoration, or paused-service reactivation occurred. H695 stays partial; dependency self-repair, further install-path invariants and Windows E2E remain. The fixed697 ledger is unchanged. Mobile H697 investigation was read-only: automatic successful POST resume changes hub-wide current selection, so it must not be used as a background existence probe; a safe requested-ID probe or terminal-chat refusal integration remains future work. Full Mac delta transfer remains unavailable; no bulk patch was applied.

V55 final checks: documentation/parity suite 24 passed, zero failures/errors/skips, 10.963s. Canonical Bandit (agents/scripts/serve.py) has zero findings/errors; scoped Ruff, generated status/Hermes checks and git diff --check passed. Actual collection is36,253 backend; frontend3,028/mobile377 reuse unchanged historical receipts. The final429-case run pinned1,275 unchanged source/test hashes.

## V56 — safe automatic owner-stash replay (2026-11-13)

Base/head remains686fcbf4f25ebfbb416b3a35dff29045163cffbd, cumulative V55 preserved. Two independent real temporary Git reproductions confirmed that the old helper reapplied owner changes successfully onto a different, compatibly advanced HEAD. The new receipt-bound helper requires a valid exact stash identifier, the recorded original baseline matching receipt.from/current HEAD/stash first parent, and clean tracked plus untracked state. The planner retains its existing tracked-only dirty policy. No-op stash creation cannot adopt an older stash. Refused/failed replay preserves the stash, records stash_restored=false and recovery instructions, and prevents rollback completion from hiding unrestored owner changes. Git conflicts are not reset or cleaned. Legacy receipts without the new baseline proof refuse automatic replay.

Critical review caught and corrected a too-broad planner dirty-policy change and malformed/falsy stash diagnostics before integration. The frozen implementation passed16 focused cases; independent review passed11, including exact-base success, wrong-head/parent refusal, unreadable state, malformed identifiers and simulated partial apply failure preserving conflicts. Native combined archive/backup/updater/startup suite passed **451/451, zero skips/failures/errors**,49.537s (`/tmp/nerva-v56-final-final.xml`). All pinned source/test hashes stayed unchanged; runner exit0. This is new-lot integration evidence, not a full-backend or repeated V55 opening common run. V55 common1405passed/7skipped remains separately dated historical evidence. No actual workspace stash/stage/commit occurred; Git mutations were confined to test repositories. Only leftover GPG helpers under completed V56 test fixture paths were terminated.

Parallel ownership audit found a separate H695 gap in updater install/uninstall and bootstrap: no foreign-owned-venv preflight. Its three expected-refusal tests remain red on unchanged production, using real temp trees with modeled st_uid because uid1000 cannot create foreign-owned files here. The report/test artifacts are included as future work, not integrated or claimed passing. POSIX ownership, external mutable symlinks and Windows ACL policy require their own bounded implementation; standard interpreter symlinks must remain usable. No network/pip/provider/service operation was executed by that audit. Stash preflight does not claim atomic protection against arbitrary concurrent same-UID changes. Windows E2E and full Mac transfer remain unavailable.

One existing gpt-6-luna/high implementer handled scratch code; an inherited-model reviewer independently audited and tested. Root owned integration/common tests. Exact coordinator/reviewer model and attributable cost are unavailable. No publication, network configuration or paused-program reactivation occurred. H695 remains partial; fixed ledger171equivalent/482partial/8missing/36excluded=697 is unchanged. Remaining work includes venv ownership, dependency self-repair, Windows E2E and the separately recorded mobile recovery gaps.

Final V56 documentation/parity checks: 24passed, zero failures/errors/skips, 10.519s. Ruff, canonical Bandit (zero findings/errors), generated status/Hermes and diff checks passed. Actual backend collection36,275; frontend3,028/mobile377 reuse historical unchanged results. No full backend suite was executed.

## V57 — POSIX venv mutation preflight (2026-11-13)

Base/head remains686fcbf4f25ebfbb416b3a35dff29045163cffbd; cumulative V56 work preserved. Implemented one stdlib bounded read-only ownership helper shared by updater and bootstrap. Before updater install/uninstall, an active venv is required (external active venv supported). POSIX preflight checks in-tree inode ownership against effective UID, rejects unreadable/special/unsafe linked state and scan-budget exhaustion, and detects directory metadata changes. It does not recursively follow symlinks. Internal aliases such as lib64→lib and conventional external interpreter links are supported; unrelated foreign interpreter targets refuse. Bootstrap inspects existing trees before reuse/rebuild and again before pip, loads the trusted installer-side helper with its current interpreter, and refuses a mismatched target-interpreter argument. No candidate interpreter is run to inspect ownership.

A real read-only probe exposed that the platform-managed base interpreter is UID65534 while the venv/root/link are UID1000. The exact already-running base interpreter is now a permitted regular-file target for a conventionally named interpreter symlink, without granting a blanket exception to foreign files. The actual environment passed read-only inspection in0.128s. No ownership, permissions, installed packages or services changed. Windows explicitly reports ownership_unchecked_windows and preserves previous execution behavior; native ACL and Windows E2E remain unimplemented. A preflight is not atomic protection from arbitrary same-UID concurrent mutation and does not authenticate Python code.

Original V56 audit retained three red modeled-UID regressions; bootstrap wiring also failed six pre-change probes. Worker helper/updater focused14 passed; independent bootstrap composition34 passed, including six real-link helper cases. Root retained a native real-tree/modeled-UID bootstrap refusal test, removed scratch paths, and made a Ruff-only postponed-annotation spelling change; Python3.8 grammar and stdlib-only import roots still pass. Final native combined updater/backup/archive/startup/bootstrap/helper suite **500/500 passed**, zero skips/failures/errors,48.314s (`/tmp/nerva-v57-final-final.xml`). Source hashes were stable and runner exited0. Canonical Bandit has zero findings/errors; scoped Ruff passed. This is not the full backend suite. Only completed-test GPG helpers under private V57 fixture paths were terminated.

Workers owned distinct scratch helper/updater and bootstrap paths; the bootstrap author independently reviewed the helper and root reviewed/integrated both. Implementation worker remains the existing gpt-6-luna/high configuration; inherited reviewer/coordinator model and attributable costs are unavailable. No subdelegation, publication, network configuration, live pip/restore operation or paused-service activation occurred. Fixed697 ledger remains171equivalent/482partial/8missing/36excluded; H695 remains partial for dependency self-repair, Windows ACL/E2E and further platform acceptance. Bootstrap missing-lock fallback is a separate audited follow-up, not changed here. Mac full export transfer remains unavailable; recovered tar proposal remains separate.

Final V57 documentation/parity24passed, zero failures/errors/skips,10.732s. Ruff/Bandit/generated status/Hermes/diff checks passed. Native500case run pinned1,283 unchanged hashes. Actual collection36,302backend; frontend3,028/mobile377 retained historical unchanged receipts. No full-backend run.

## V58 — explicit unlocked choice and exact smoke success (2026-11-13)

Base/head remains686fcbf4f25ebfbb416b3a35dff29045163cffbd; cumulative V57 preserved. Implemented the documented bootstrap lock contract: missing lock no longer implicitly selects loose requirements. Absent input reports requirements_missing; non-file/dangling/inaccessible metadata reports requirements_lock_unreadable before pip. Explicit unlocked remains the only way to select .txt. Readability/content failures after preflight remain subject to pip with --require-hashes, never an automatic downgrade. Independent second unit requires smoke payload ok is True rather than any truthy string/number/object. Genuine true/noise, child nonzero precedence and parse errors remain tested.

Worker initially reproduced the missing-lock downgrade, then27 focused tests passed after the final error-name compatibility adjustment. Independent lock6 passed, including full CLI JSON refusal/status1 and no runtime probes; smoke13 passed after3 native regression failures. Root composed disjoint scratch hunks sequentially and promoted repository-relative tests. Final native combined updater/backup/archive/startup/venv/bootstrap suite **524/524 passed**, zero skips/failures/errors,49.163s (`/tmp/nerva-v58-final-final.xml`), 1285 unchanged source/test hashes and exit0. Canonical Bandit has zero findings/errors; Ruff clean. These are local fake-runner tests, not a real pip/install/smoke-server operation or full backend run. Only completed-run GPG helpers under the exact private V58 test fixture root were terminated.

Wrapper compatibility review: install.sh and INSTALL.bat delegate to bootstrap and propagate failures. Separate install.ps1/UPDATE.bat paths bypass bootstrap and still use loose requirements; this fix does not cover them. UPDATE.bat ignoring pip failures is a separately documented native-Windows follow-up, unimplemented here. No Windows execution/ACL/E2E claim. docs/INSTALL.md records scope and named errors. H695 remains partial and fixed697 ledger is unchanged171equivalent/482partial/8missing/36excluded.

Existing gpt-6-luna/high worker owned lock implementation; inherited-model reviewer independently checked it and owned separate smoke correction. Root reviewed/composed and ran integration. No subdelegation, publication, network configuration, permission/ownership change, actual installation or paused-service activation occurred. Exact inherited/root model and attributable resource costs unavailable. Mac transfer remains unavailable; original recovered tar proposal stays separate.

Final V58 documentation/parity24passed, zero failures/errors/skips,11.303s. Ruff/Bandit/generated status/Hermes/diff gates passed. Actual backend collection36,326; frontend3,028/mobile377 reuse historical unchanged receipts. Full backend suite not run.


## V59 — mobile missing-session recovery (2026-11-13)

Base/head remains 686fcbf4f25ebfbb416b3a35dff29045163cffbd; all changes local/uncommitted.

2026-11-13 local V59 (H697, still partial): mobile now offers explicit Start new chat after an exact selected-session-missing response. The unsent message persists until Add to draft or Dismiss; adding preserves newer composer text and never sends automatically. A per-turn server marker confirms successful governed /new before selection changes. Older hubs without that marker preserve the old selection and show guidance. Authorization, busy/corrupt/network errors and stale owner/selection responses cannot trigger recovery. Native device acceptance, automatic terminal-pull and reclaimed-session push remain open.

A regression exposed that a changed global session ID was insufficient creation proof; the server now records the successful direct /new transition only after authorized allocation, migration and default assignment. Recovery requires the matching SSE end marker. A second red regression exposed saved-prompt replacement after History selection; ordinary text now waits for explicit Add/Dismiss, while /new, /reset and /undo remain available. The missing-session proof is ephemeral; only the scoped bounded prompt persists.

Verification: 451 backend integration tests, all 389 mobile Jest tests and all 211 native rendered tests passed serially. All 1,422 pinned source paths remained unchanged during these suites. Mobile project TypeScript passed after the final retention fix. Independent review reproduced the retention defect before the fix and passed all 11 controller probes afterward. Native rendered recovery has 14 cases. No full backend suite, live server, provider, physical device or remote/main verification is claimed. Frontend aggregate 3,042 combines unchanged historical browser 2,831 with fresh native 211.

Two existing smaller-model implementation workers owned isolated mobile controller and UI candidates; coordinator integrated and fixed retention, with a separate critical/backend reviewer. No attributable resource-savings measurement. H697 stays partial; inventory remains 171 equivalent / 482 partial / 8 missing / 36 excluded, total 697. No install, deployment, network configuration or service reactivation.

Final gates: 24 documentation/parity tests passed; scoped Ruff, canonical Bandit (zero new findings), generated status/Hermes sync and git diff --check passed. Backend collection is 36,342; test counts do not imply a full backend run.


## V60 — find recent conversations on mobile (2026-11-13)

Base/head remains 686fcbf4f25ebfbb416b3a35dff29045163cffbd; all cumulative changes local/uncommitted. Mobile History now filters loaded session metadata by title, summary, ID, agent and lineage target. Query is bounded to 256 characters; labels describe loaded recent scope, not transcript/full-history search. Refresh retains query; close/reopen or connection changes reset it. Clear and actual-empty versus no-match states are explicit. Selecting a row still invokes the existing authenticated lineage resume.

Two smaller-model workers split component implementation and independent rendered tests; a separate read-only reviewer found no new blocker. Root review corrected themed font/placeholder and empty-list wording. Seven focused cases passed and the pre-change HEAD source failed the search-input regression. The initial full native run overlapped the worker's temporary baseline import, so hash checking rejected it (211 passes/7 baseline failures); it is preserved separately and not claimed green.

Only component, tests, product/backlog/assessment/generated docs changed in this lot. No Python/backend or transport edits, installation, network changes, service reactivation or publication. Full-history indexing, pagination/browser search, and physical native-device acceptance remain open. H141/H195 remain partial; inventory unchanged at171 equivalent/482 partial/8 missing/36 excluded of697.

Final verification:218/218 native rendered tests and mobile TypeScript passed on stable component/test hashes. Frontend tracked count3,049 = historical unchanged browser2,831 +fresh native218. Backend36,342 and mobile389 are retained V59 counts, not newly run suites; no production Python or controller changes require rerunning those here.

All24 documentation/parity tests and generated status/Hermes/diff checks passed. No live-device acceptance claimed.


## V61 — access and search all loaded browser conversations (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd, cumulative local/uncommitted work. Verified gap: API/sessions returns up to20 rows but SessionsPanel sliced to12, hiding accessible conversations. V61 exposes all loaded rows and adds a bounded local title/summary/ID/agent/lineage filter. Scope text explicitly excludes transcript/full-history search. Clear and no-match states are available; tab switch resets query, reload retains it. Query edits dismiss rename and pending delete confirmation, so returning to a hidden row does not leave a destructive action armed. Existing lineage targets and governed API actions remain explicit.

Separate smaller-model implementation and regression workers, independent read-only reviewer and root integration. Baseline red demonstrated row20 was absent before implementation; tests recorded in /tmp/nerva-v61-red.log. No provider/runtime/device or whole-history parity claim. H141/H195 remain partial; frozen697 accounting unchanged. Mobile V60 unchanged. No install/deploy/network changes or service reactivation.

Final verification: complete frontend command passed3,057 tests (2,839 browser+218 native); component/test hashes unchanged. Frontend and E2E-config TypeScript checks passed; both HUD and Workspace production builds passed and local generated bundles refreshed. This is not a live E2E/device run. Backend36,342 and mobile389 counts retained from V59, those full suites not rerun for this UI-only change.

All24 documentation/parity tests, generated status/Hermes checks and git diff --check passed. No publication or service restart.


## V62 — owner browser history pagination (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd; cumulative local/uncommitted. Added admin-only GET/sessions/page, separate from unchanged legacy user/mobile list. Bounded1..100 (UI20) keyset pages sort by date then ID, including NULL-date tail; archive and lineage predicates precede limit. Strict version/archive-scoped cursor rejects malformed inputs; closed/read-failed store returns503 instead of false exhaustion. Private success/error responses no-store.

Owner web now explicitly loads older conversations, deduplicates pages, searches all loaded metadata, preserves history/retry on later-page failure and rejects repeated/malformed cursors. Initial401/403/404/405 alone falls back to independently user-authorized legacy list. The401 matches real admin guard behavior for user-only tokens;405 matches old route behavior demonstrated by the baseline regression. Guests/older hubs retain recent history; no later-page downgrade.

Independent review corrected same-tab load cancellation, old rows under new archived controls, stale mutation reloads and stuck busy state. Scope/request/page/mutation generations fence late results. All50 focused UI/session compatibility tests passed. Store/route regression proves27-row traversal, ties, NULL dates, deleted boundary/newer insertion, filtering, strict bounds and user/admin separation. Backend common run462/463 passed; sole failure required new admin route in auth snapshot. Added exactly GET/sessions/page=admin, then20/20 authmatrix passed. Route/OpenAPI snapshots each add exactly the new route; offline pinned7.13.0 type generation uses pre-existing cache, no install. Ruff passed and canonical Bandit0 new findings.

Existing mobile remains unchanged; mobile/guest paging, full-text indexing and live native/desktop acceptance stay open. No snapshot isolation claimed across pages under concurrent mutations. H141/H195 partial, inventory171 equivalent/482 partial/8 missing/36 excluded of697 unchanged. No deployment/publication/network config/service restart.

Final frontend acceptance: 3073/3073 passed (2855 browser + 218 native), both TypeScript checks and HUD/Workspace builds passed. Frozen five source/test hashes unchanged. Existing orchestrator binding suite51/51 passed. Backend collected36,356; mobile389 retained historical count, not a fresh full mobile-Jest run.

Final24 documentation/parity checks, status/Hermes sync and git diff --check passed. No deployment or service reactivation.

Packaging removed one trailing blank line from the new Python test; non-whitespace bytes unchanged, formatting receipt retained. Final manifest pins packaged bytes.


## V63 — mobile owner history pagination (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. Mobile uses existing owner keyset endpoint with strict20-row/512-cursor/ID/type validation. Explicit Load older appends deduplicated pages; search includes loaded history. Later failures preserve list/cursor for retry, repeated cursors rejected. Initial401/403/404/405 only falls back to independently authorized legacy recent list. Scope/visibility/refresh/resume fences suppress stale private data; synchronous locks prevent duplicate requests. Same-scope refresh error retains rows and query while resetting pagination. FlatList shrinks so pagination control remains available; physical-device layout is not verified.

Two new workers explicitly gpt-6.1-sol medium, independent production vs tests/review. Demonstrated red→green for missing pagination, non-string cursor coercion, and failed-refresh data loss. Independent42 pagination+7 search tests passed, with no remaining review blocker. Full native first run259/260 exposed one old duration-test fixture returning agents for the new history route; adapted that fixture to the real page response without weakening its assertions. Final full native260/260 passed with stable source hashes. Mobile TypeScript passed on the same final production bytes. Implementation worker full mobile Jest58 suites389 tests passed on final client SHA; coordinator reused its tool-captured receipt rather than rerun unchanged logic.

Frontend tracked3,115 combines unchanged V62 browser2,855 and fresh native260; not a fresh full browser run. Backend36,356 remains V62 collected count; no Python/backend changes or full-backend rerun. No backend expansion, Windows environment changes, installs, network changes, deployment or service reactivation. Guest pagination, full-text indexing and real-device acceptance remain open. H141/H195 partial; frozen697 accounting unchanged.

Final24 documentation/parity tests, generated status/Hermes checks and git diff --check passed.

## V64 — owner retained-transcript preview and JSON export (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. One coherent API+web slice: per-row preview without resume/default/unarchive and explicit JSON download from the same protected read. Admin guard, no-store, exact session identity, lease/import/rewind checks, projected user/assistant text only, automatic scanner redaction failclosed. Standard retained loader100-turn/512KiB limits preserved;2MiB serialized projection bound checked before/after scanner. This is retained current history, not a complete compacted archive. Tool/media/system fields excluded. Error output cannot contain partial redaction.

Two implementers explicitly gpt-6.1-sol medium with disjoint ownership, coordinator independent critical review. UI18new rendered regressions prove explicit download, owner transport, escaped text, stale-response fencing and accurate requested-vs-saved status. Backend11new tests use real managers/router and prove exact addressed archived/imported/rewound history, owner separation, snapshot immutability, redaction failure, limits and identity-swap refusal. Cold rewind manager recovery uses activate=False; shared continuation loader unchanged. Coordinator corrected only a Ruff import-spacing issue. Common backend499/499 passed; no full-backend run claimed. Collected backend36,367. Existing mobile Jest389 is historical, not rerun in this web/API slice.

Snapshots and generated TypeScript refreshed offline from installed pinned7.13.0 generator; no installs. Compared against appliedV63: exactly GET/sessions/{session_id}/transcript added to route/OpenAPI/auth snapshots with admin guard; all previous entries unchanged. Ruff passed, canonical Bandit0 new findings, documentation/parity24 passed. Full frontend/typecheck/build final receipt follows below.

H141/H195 remain partial;697 inventory unchanged at171 equivalent/482 partial/8 missing/36 excluded. Mobile preview/export, full archive, CLI retained export and live-device acceptance remain separate. No Windows changes, publication, deploy, network configuration or service reactivation. Mac proposal preserved separately.

Final full frontend3133/3133 passed (2873 browser + 260 native); both TypeScript checks and HUD/Workspace builds passed. Frozen five implementation/test hashes unchanged. Backend499/499 common tests, documentation/parity24 passed; backend36,367 collected, full backend not run. Mobile Jest389 historical count retained. No live device acceptance claimed.

## V65 — mobile retained transcript preview and app-folder JSON save (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. Existing V64 owner endpoint reused; backend unchanged. Mobile adds exact-row preview separate from lineage resume and explicit JSON save of the validated redacted retained-text projection to app documents. Strict schema/ID/user-assistant roles/100turn/2MiB UTF8 bounds and whitelist prevent malformed export. No TextEncoder dependency. Unique filenames avoid overwrite; no missing-directory/write-success confusion. UI clearly says retained-only automatic redaction; full compacted archive and external sharing remain separate.

Two gpt-6.1-sol medium workers with separate implementation and independent test/review ownership. Meaningful baseline RED for missing API/controls; tests exposed missing pending-preview close, fixed. API31/new native28 focused passed. Coordinator critical review inspected auth, projection, lifecycle, storage and synchronous duplicate guard. Final failure-path hardening invalidates generation; late old callbacks cannot retain export authority. Old explicit saves may finish after close but never update a new scope. No automatic fetch-triggered write. Full mobile Jest420/420 passed on unchanged API/helper bytes; initial common native passed but its frozen hash check correctly caught UI-only hardening. Final full native+tsc rerun separately receipted below. Docs/parity24 passed. Browser/backend results reused from V64 because unchanged; no new full backend/browser claim.

Inventory697 unchanged at171 equivalent/482 partial/8 missing/36 excluded. H141/H195 still partial. No publication/deploy/network/service reactivation, installs or Windows edits. No actual device or live API acceptance. Structured report supplied locally for Dot; Drive upload/scheduling not claimed.

Final full native288/288 passed and mobile TypeScript passed with all5 source/test hashes unchanged. Tracked frontend3161 = unchanged V64 browser2873 + fresh native288; full mobile Jest420 passed. Backend36,367 unchanged collected count. Final generated/docs checks and clean-base packaging verification accompany delivery.

## V66 — web/mobile history filtering and date grouping (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. Complete archive priority investigated independently: legacy compaction/raw logs lack instance/branch/committed occurrence provenance, can contain rewound suffixes, skip failures and cannot prove capture completeness. No unsafe join/recovery was added. Report packaged with future committed-ledger/coverage requirements; retained export stays unchanged.

Chosen coherent H141/H195 product slice: web/mobile exact-agent/unassigned/all and rolling7/30day/unknown/all-date filters compose with local metadata search. Strict ISO calendar validation prevents normalized impossible dates; recent inclusive now-Ndays throughnow excludes future dates. Date labels group adjacent local-calendar runs preserving API order and lineage/keyset behavior. Scope explicitly all loaded pages only. Reset controls, no-match, later-page agent choices, absent selected agents on refresh and scope resets handled. Filter changes invalidate private previews and web pending edits; resume/export behavior preserved.

Two implementation workers gpt-6.1-sol medium on separate source/test files; read-only audit third worker then exited. Coordinator reviewed actual archive evidence, date logic, sentinels, lifecycle, ordering and acceptance tests independently. RED/GREEN for absent controls/groups and mobile impossible-date parser gap; final focused web84 incl10new/mobile98 incl7new plus typechecks passed. Docs/parity24 passed. Full frontend/types/build milestone results follow below; no full-backend/mobile-Jest rerun for this UI-only batch. Existing backend36,367 and mobileJest420 counts reused from prior checkpoints.

Inventory697 remains171 equivalent/482 partial/8 missing/36 excluded; no promotions for partial loaded filters. Fulltext/source/server-wide filters, legacy complete archive and physical-device acceptance remain open. No stage/commit/push/deploy/install/network/service/Windows changes. Mission Control structured report included locally; no confirmed Drive upload or scheduler.

Final full frontend3178/3178 passed (2883 browser + 295 native), both frontend TypeScript checks, mobile TypeScript and HUD/Workspace builds passed. All4 source/test hashes unchanged. Backend36,367 and mobileJest420 are reused prior counts, not freshly rerun in V66. Final docs/parity24 and generated checks passed.

## V67 — CLI retained transcript JSON export (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. Future provenance assessed against V66: requires atomic occurrence-ledger/snapshot/rewind-head integration with instance/branch/coverage metadata; no uncommitted capture journal or historical backfill added. Independently useful H005 CLI slice: `nerva sessions transcript ID [-o PATH] [--json]` uses existing V64 owner endpoint and exact retained-only projection. Existing opt-in training export unchanged; dynamic shell completion discovers new subcommand.

Strict envelope/ID/roles/count/type validation, whitelist,100turn/2MiB compactUTF8; generic stderr preserves auth/hub exit classes, stdout JSON only. File save is create-only0600 via private0700 sibling temporary, write/flush/fsync and atomic no-clobber hardlink. HTTP/validation/fsync/link refusal cannot truncate existing output. Platform missing secure permission/hardlink primitives fails safely before temp creation; stdout still supported. No Windows file-save claim.

Two gpt-6.1-sol medium workers implementation vs independent74case tests. BaselineRED missing parser, finalGREEN. Coordinator critical review found absent-platform AttributeError risk; guarded capabilities and tests fixed before freeze. Final common314/314 passed covering new CLI, baseline CLI, shell completion, trajectory compatibility, retained backend and docs/parity. All3source/test hashes unchanged. Ruff passed, canonical Bandit0newfindings, generated/Hermes/diff checks passed. Collected backend36,441; frontend3178/mobileJest420 reused prior verification, no fresh UI/fullbackend/live result.

H005 partial;697 inventory remains171equivalent/482partial/8missing/36excluded. Fullarchive/JSONL/session-administration gaps remain explicit. No historical writes, publication/deploy, network config, service reactivation, installs or Windows changes. Structured Mission Control report r03 included; no Drive upload/scheduling confirmation.

## V68 — CLI session organization (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. Added `sessions rename ID TITLE`, `pin`, `unpin`, `archive`, `unarchive` and `sessions --archived` through existing authorized routes. ID/title validation before HTTP; backend-native title normalization, exact strict receipt confirmation, allowlisted JSON and generic errors. Malformed2xx/transport uncertainty warns may have applied without retry. Listing-only archived flag cannot silently combine with mutations/export. Existing imports/lineage/default list/transcript/trajectory behavior unchanged. No delete/prune or new endpoint.

Two gpt-6.1-sol medium workers independent tests vs implementation; coordinator critical review corrected canonical-title receipt comparison and archived-list flag misuse before freeze. RED missing parser then187new testsGREEN incl actual ASGI owner matrix and immutable imported provenance. Common849/849 passed covering CLI/completion/transcript/trajectory and archive/title/lineage/lifecycle/docs;3source/test hashes unchanged. Ruff clean, canonical Bandit0newfindings, status/Hermes/diff checks pass. Backend36,628 collected. Frontend3178/mobileJest420 reused earlier evidence; no fresh UI or fullbackend/live result.

Future capture remains separate atomic occurrence-ledger/snapshot/rewind+coverage feature. No standalone log, legacy replay/backfill or historical mutation introduced. H005 partial and697 inventory unchanged171equivalent/482partial/8missing/36excluded. No publication/deploy/install/networkconfig/service reactivation/Windows edits or actual live session mutations. MissionControl r04 report local/included; Drive upload/scheduling unconfirmed.

## V69 — bounded filtered CLI history traversal (2026-11-13)

Base/head686fcbf4f25ebfbb416b3a35dff29045163cffbd. New `sessions history` reads existing owner keyset pages beyond legacy20. Client-side exact-agent/unassigned/age/metadataquery conjunction, resultcap1..1000/pagecap1..100, explicit cursor continuation and JSON counters/stopreason. Fixed UTC age cutoff during run; missing/invalid age unknown excluded only if filtering. No fixed snapshot claim across pages/nextinvocation. Request=min100/remaining match capacity avoids dropped rows at cap. Dedup keeps firstseen order, repeatedcursor and emptypagewithcursor fail. No retry/fallback/mutation.

Strict knownfield/ID/alias/resume/cursor/types, perfield16KiB and aggregate8MiB projection, whitelist excludes rawmetadata from output/search, human terminalcontrols stripped. Buffered atomic stdout refuses late failures without partialhistory success. Coordinator reviewed invariants and corrected overly strict custom-agent naming +incremental output bound. Two gpt-6.1-sol medium workers implementation vs independent50tests, baselineRED thenGREEN with real transport/router/store beyond20/archive/lineage/guestauth and SQL unchanged.

Final common831/831 passed across newhistory/prior CLI/organization/transcript/completion/trajectory/page/archive/title/lineage/docs. All3source/test hashes stable. Ruff passed, canonical Bandit0newfindings, generated/Hermes/diff checks pass. Backend36,678 collected; frontend3178/mobileJest420 reused earlier evidence, no new fullbackend/live/UI/device run. H005 partial;697 inventory unchanged171equivalent/482partial/8missing/36excluded. Source/tool-call filters and interactivebrowse remain open. Futurecapture atomic provenance and unsafelegacyarchive gaps remain explicit; no historical reconstruction.

No stage/commit/push/deploy/install/networkconfig/service reactivation/Windows/livesessionchanges. MissionControl r05 included locally; no Driveupload/scheduler confirmation.
