# Hermes contract closure — batch 01

Generated 2026-10-10 UTC. Goal: progress toward all 697 accepted Hermes
capabilities through complete contracts, verified against current code. Base and
initial head: `9a5fdf298c6e63bcc38ddde4946c96998726f53e`; branch
`codex/hermes-closure-01-20261010`. Local work is authorized; no publication.

First delivery: H161 must retain disk pressure until recovery is confirmed for
the affected volume. A partial probe currently replaces the entire disk map, so
three healthy readings of a different volume incorrectly clear the alert.
Preserve per-volume recovery evidence when a watched volume disappears. Missing
readings cannot advance that volume's recovery; readable volumes must still
raise pressure immediately. Keep the existing thresholds, recovery margin,
ranked banner, boot-scoped dismissal and response schema.

Implementation ownership: the runtime agent (`gpt-6-sol/high`) owns only
`agents/core/resource_pressure.py` and `tests/test_h161_resource_pressure.py`.
Root owns scope, review, plan, evidence and delivery documentation. An independent
`gpt-6-sol/high` agent reviews tool/skill contracts; the optional
`gpt-6-luna/medium` investigator only narrows subsequent work. No subdelegation.

Tests: demonstrate the missing-volume regression before implementation; cover
critical and elevated pressure, missing samples during recovery, independent
volumes, immediate escalation, dismissal retention and real confirmed recovery.
Run the existing pressure backend and banner frontend suites, then route and
delivery guards. Run one serial backend suite after the integrated code batch.
Existing frontend lockfile matches the previously installed local dependencies.

Non-goals: new probes, different thresholds, new routes, speculative Windows
fixes, changing the frozen inventory or automatically refreshing every stale
hash. Contract reviews may only restore equivalent status when all accepted
behavior is supported; genuine omissions remain partial. Historical test claims
must not be presented as current executions.

Rollback: revert the pressure implementation, regression tests and its evidence
update together. No storage migration or external dependency is needed.

Second, independent delivery: H328 conditional skill activation misclassifies
actually offered Kanban tools because the exact toolset map has no Kanban entry.
The tool/skill agent owns only `agents/core/skills/visibility.py` and
`tests/test_h328_skill_visibility.py`. Add the fourteen registered Kanban names;
recognize `search_memory`, `skill_propose`, `computer_use` through `desktop_run`,
and `coding` through the existing file-write, terminal and code-execution tools.
These are visibility mappings, never new execution permission. Do not infer
toolsets from prefixes or equate web extraction with browser control. Absent
browser/Home Assistant/delegation implementations remain unavailable. Unknown
sets retain current require/fallback semantics.

Demonstrate required-skill omission and incorrect fallback offering before the
change. Exercise both gates for supported mappings, actual registry membership,
unrelated and misspelled tools, absent sets, and explicit loading under the soft
gate. Run the existing visibility, skill-tool, prompt and profile suites. This
mapping change is independently reversible from H161; the local batch will keep
the two implementation units distinguishable in its review and commit history.

Changed paths: the pressure sampler/tests, skill visibility map/tests, H450
schedule adapter/consumers/tests, assessment, generated status and delivery docs.
Verified implementation head: `9f139e0d` (2026-10-10 UTC). Next action: continue the next bounded contract closure from this verified local
baseline after saving the documentation/evidence commit. Main remains
unchanged at `332b16ca`; no push, merge or deployment is authorized for this sprint.

Implementation results: H161 adds per-volume held state and three regression
cases. All three failed on the previous implementation; all 43 pressure tests
pass after the change and in the independent review. H328 adds exact supported
toolset members and 29 regression cases, including both gates, actual runtime
registry membership, negative lookalikes and explicit soft-gated loading. Its
four-file implementation selection passes 187 cases; the independent selection
passes 186. Both touched Python deltas pass Ruff and whitespace checks. The
runtime frontend selection passes 23 cases, skill/settings frontend 12, and jobs
frontend 24. These selections overlap existing tests; their counts are not added
together as a unique full-suite total.

Twenty-two formerly equivalent but stale reviews were checked against their frozen
contracts. H004/H161/H328/H450 close after the fixes. H340/H350/H351/H504/H659/H661/H691 retain
functional equivalence on current evidence. Eleven others have concrete gaps and
are recorded partial, including missing stall-policy tracks, skill re-enabling
without its required kernel hop, a per-profile identity where the contract needs
an install-wide identity. App-timezone scheduling is now repaired under its
separate [H450 implementation plan](2026-10-10-hermes-schedule-timezone.md).
The refreshed ledger is 127/697 (18.2%): 19 current reviewed-equivalent
rows and 108 inherited equivalents. It is not a claim that all 127 were tested in
this batch. No inventory rows were removed and no scope reopening was changed.

Functional adaptations are explicit: H351 treats owner-approved exact bytes or a
keyed signature as vouched provenance while still warning on detected injection;
H504 parses real custom trust anchors instead of rejecting a valid short EC
certificate by a byte-length heuristic (certifi still has its 1024-byte floor);
H659 provides native single-owner/webhook/verified-peer retry scopes, with its
documented expiry and failed-outcome limits; H691 defaults to trusting no proxy.
These are reviewed native behaviors, not claims of identical upstream internals.

Focused review evidence includes 317 passed / 2 rustc-dependent skips in the
runtime selection, 385 passed in the tool/skill review, 120 passed in the
idempotency/routing review and 239 passed in the small-contract review. Root
checked source claims and corrected agent overclaims before updating any pin.
Fresh local HTTP smoke started the actual application with an isolated data/key
root in safe mode: pressure returned 200 with the existing schema and no-cache
headers, and the dismissal route remained in OpenAPI. No external provider or
personal runtime was used.

Unrelated stale reviews retain their original hashes. The review update replaces
historical accumulated notes with current bounded claims and pins the files that
support those claims. The frozen inventory is unchanged. The single integrated backend run collected
25,587 cases: 25,525 passed, 58 skipped, one xfailed and three failed. The failures
were old cron-slot fixtures selecting only the scheduler timezone. After the
reviewed fixture correction, all 261 cases in the affected six-file selection
pass; production code is unchanged from the full run. This is a full run plus a
focused correction rerun, not a claimed second all-green full suite.

H450 adds the validated application-zone adapter and nine regression tests. Its
final eight-file implementation selection passes 246 cases; the independent
six-file review passes 199. Preview settings I/O runs off the event loop, first
valid zone pinning is atomic, and saved timezone changes apply after restart.
A fresh isolated production app on UTC confirmed America/New_York day-word
preview over HTTP. The six previously partial jobs rows H115/H451/H452/H454/H455/
H676 were independently checked for collateral changes, remain partial with
specific gaps, and only their changed reviewed source/test pins were refreshed.

Additional bounded reviews: H661 retains equivalence for streamed execute_code
spill, bounded retention, head/tail, exact byte-paging recipes and fail-soft I/O.
Root and independent reviewers inspected both execution paths, actual reader,
offer/path gates and taint; all 215 tests in the five related modules pass in the
backend milestone. H413 remains partial: its instant/title-upgrade/CAS mechanics
pass 131 tests and its auxiliary routing passes 54, but selecting any active
local model does not guarantee the accepted small-model title call.

H004's independent implementation and rollback unit is recorded in
[the shell plan](2026-10-10-shell-completion-paths.md). It fixes recursive exact
command paths and literal Bash/Zsh candidates. Independent review also preserves
H329's partial switch verdict and H350's equivalent lint verdict; only their
changed CLI evidence pin is refreshed. The unchanged Fish generator has four
current passing generation tests and three real-shell skips. No new route or
HUD/mobile administration surface is introduced by shell completion.

Final integrated CLI verification: after reproducing the empty Zsh completion
status error on the integration commit, the five-line corrective delta makes
leaf/unknown paths finish successfully. The combined H004/Fish-generation/CLI/
skill-switch/lint selection passes 222 tests with three real-Fish skips. The
previous backend milestone plus the 261-test schedule rerun and this focused
CLI/collateral run are the verification scope; no all-green full-suite rerun on
the final CLI head is claimed. Four features are independently reversible in
local commits: pressure `1cc04ba9`, skill offers `114af2de`, schedules `4d0b8244`,
and shell completion `08bb5a5e` plus its corrective `9f139e0d`.

Next bounded investigations are documented in scratch reports: H689 needs a
shared installation identity with an explicit legacy-profile/pairing migration,
not just a path switch; H413 needs a defensible small title-model selection.
Neither is promoted here. The accepted inventory still has 570 unfinished rows;
this local batch does not claim 697/697 or publication to main.

Delivery guards: all 86 Hermes/status metadata tests pass after final integration;
Hermes-report derivation, generated project status, Ruff on all changed Python
paths, and whitespace checks pass. Final collection is 25,593 backend cases;
unchanged frontend/mobile collections remain 2,177/359. The completed backend
milestone also passed the route parity (2), OpenAPI parity (1), HUD parity (16)
and lifespan smoke (1) guards. These are subsets of the reported full run, not
additional unique-test totals. A fresh read of remote main confirms `332b16ca`
and 116/697; the local branch records 127/697 and remains unpublished.

Exactly 28 review records changed: 22 full-contract re-reviews and six existing
partial job collateral rows. H329/H350 CLI collateral review is included in those
22 rows. All inventory identities, scope reopenings and unrelated review records
are preserved. No capability was excluded to improve the percentage.
