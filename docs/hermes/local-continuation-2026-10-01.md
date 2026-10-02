# Local Hermes continuation — 2026-10-01

- Goal: complete functional parity with pinned Hermes, including H277 and all
  697 accepted inventory rows plus separately identified upstream additions.
- Base: `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`.
- Branch: `codex/local-hermes-continuation-20261001`.
- Reference: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
- Publication: owner subsequently authorized pushing, PR reconciliation and merging
  on 2026-10-02. Deployment, paid/live provider calls and personal profile imports
  remain outside this integration. See the current publication report below.
- Head/evidence freshness: the base above starts this batch; subsequent local
  commits and their test snapshots must be recorded separately.

## Plan and ownership

1. Revalidate the H277 handover on current code. Keep historic mutation receipts
   unchanged. Re-run the 14 shared-runner mutations in a disposable archive of
   the exact base, counting invalid anchors/setup errors separately from kills.
2. Repair task-bound permission-grant replay. The implementation agent owns
   `agents/core/permission_ledger.py` and focused tests. Transactions must roll
   back failed effects; replay must not duplicate or restore revoked authority.
   Existing ambiguous legacy rows must not make the whole ledger unusable.
3. Design and implement a real video-analysis consumer for H277. This is separate
   from H516 video generation. The contract must cover actual tool offering and
   execution, bounded sources, role/model selection, destination/credential
   binding, consent and output provenance. Provider/fallback expansion stays in
   the full goal; an initial transport cannot silently replace that contract.
4. Review each coherent change, run focused regressions after implementation,
   then run the relevant integration/full suites serially at the milestone.
   Update only re-read Hermes evidence, BACKLOG and generated test counts.
5. Continue the remaining capability queue and reassess prior exclusions;
   neither this plan nor one completed batch closes the full-parity objective.

The coordinator owns integration and records. At most two Sol High implementers
work concurrently, with one writer per source file and no subdelegation.

## Verification and rollback

Permission tests cover actual SQLite audit/commit failures, uncertain commit,
restart, concurrent instances, payload mismatch, inactive authority and legacy
adoption. Video tests must cover real ToolRPC-to-mocked-native-transport dispatch,
not merely schema presence. H277 mutation baselines and restoration hashes pin
their own source snapshot. Existing socket/time limits remain enabled.

Rollback a local feature commit independently; retain prior user work and
historical evidence. Do not promote H277 or any compound row to equivalent while
accepted requirements remain unimplemented or unverified.

Progress: the 14 shared-judge mutations were killed on the exact base snapshot;
permission replay and restore-token durability are committed locally as `b7a15e89`
and `d2e065c4`. Video understanding now has approved native dispatch, independent
role consent and bounded vision-route inheritance. See the
[video implementation and verification report](h277-video-analysis-2026-10-02.md).

The immutable full-backend milestone passed on `78780b64`: 20,108 passed, 34 skipped
and one expected failure, with 1,836 frontend tests passing separately. Source hashes
were unchanged through the full backend run. PR reconciliation left zero open PRs;
the continuation commits were local at that earlier checkpoint.

Current video mutation coverage is frozen on `92905443`: 29 detected, two documented
survivors and zero invalid mutations; 168 baseline tests pass and all 4,130 archived
source hashes were restored. See the [exact campaign](evidence/h277-video-mutations-verified-2026-10-02/report.md).

Configured provider-chain milestone: runtime `591c9e15`, full backend snapshot
`a38d7546`: 20,306 passed, 34 skipped and 1 expected failure. All 4,218
tracked regular source hashes remained fixed; full frontend has 1,838 passing tests.
The [current report](h277-video-provider-chain-2026-10-02.md) and its receipt separate
this proof from the earlier mutation campaign. Those commits were local at that checkpoint.

Native Gemini video milestone: code `0382ef0b`, frozen full-backend commit
`c4231b64982bbab150e564794b42ee3f7797247f`: **20,402 passed, 34 skipped,
1 expected failure, zero unexpected failures**, with 61 warnings. All 4,227 tracked
regular files remained unchanged through the run; the checkout stayed clean. The
707-case focused set includes 66 pure codec and 30 signed Gemini cases. Frontend
source/schema are unchanged from the separately tested `2d9a3c39` snapshot with
1,838 passing tests, typecheck and build. See the
[immutable Gemini receipt](evidence/h277-gemini-video-integration-2026-10-02.json)
and [implementation report](h277-gemini-video-2026-10-02.md).

Approved primary video retry milestone: code `09f4dd87`, frozen full-backend
commit `5da06db66c837993a644f330f67da385ed7bf835`: **20,450 passed,
34 skipped, 1 expected failure, zero unexpected failures**,
with 61 warnings. All 4,234 tracked regular files remained
unchanged and the checkout stayed clean through the run. The focused set has
755 passing tests, including 48 new retry cases. Frontend source/schema remain
unchanged from the separately tested `2d9a3c39` snapshot (1,838 passing tests,
typecheck and build). See the [implementation report](h277-video-retry-2026-10-02.md)
and [integration receipt](evidence/h277-video-retry-integration-2026-10-02.json).

The [retry mutation campaign](evidence/h277-video-retry-mutations-2026-10-02/report.md)
uses an exact archive of the same frozen source: **11 valid cases,
9 detected, 2 surviving, 0 invalid**. Both single-gate survivors retain the other
primary-only guard; the explicitly compound removal of both is detected. Baseline
and restored baseline each pass 755 tests, and all 4,234 file hashes are restored.
The provenance-only case is result-shape evidence, not egress proof. This bounded
campaign does not expand historical H277 mutation claims.

Read-only GitHub recheck on 2026-10-02 still found zero open PRs and remote `main`
at `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`. All continuation commits remain local;
no new GitHub CI, live/provider, deployment or paid-service acceptance is claimed.

Shared local auxiliary milestone: frozen source
`0307142d37bac7ad812f1738ca12cb75617b6e2e` passed **20,505 backend tests,
34 skipped and 1 expected failure**, with zero unexpected failures
and 64 warnings. All 4,290 tracked regular files remained unchanged
through the full run. The focused selection passed 513 cases including 54 new cases;
the isolated legacy-console selection passed 40. Frontend source/schema are still
unchanged from the separately tested 1,838-case snapshot. See the
[implementation report](h277-local-auxiliary-2026-10-02.md),
[integration receipt](evidence/h277-local-auxiliary-integration-2026-10-02.json) and
[evidence review](h277-local-auxiliary-evidence-review-2026-10-02.md).

Session titles, recall rewriting, review and streamed compression can now select
independent local models through one guarded invocation helper. Each preserves its
prior default, budget, output and failure behavior. There is no new live-provider,
installed-model or native-client acceptance claim, and no new mutation campaign.

Acquisition auxiliary milestone: two more real producers now share prepared local
routing. Each chooses an independent model and freezes its model/backend across
JSON attempts, with fresh H513 authorization at each attempt and physical request.
The existing optional-model fallback and acquisition job-pin behavior are preserved.
The frozen source `e7e1310d64f60c760797e965228b442200ee556e` passed **20,537 backend
tests, 34 skipped and one expected failure**, with 64 warnings. All 4,296 tracked
regular files stayed unchanged. Focused verification passed 1,026 cases with two
skipped; 86 changed-module cases passed after an import-only adjustment. See the
[implementation report](h277-acquisition-auxiliary-2026-10-02.md) and
[integration receipt](evidence/h277-acquisition-auxiliary-integration-2026-10-02.json).

Six affected previously-current evidence rows were refreshed after source and
citation review, with no status promotions or updates to the original 207 stale
rows. Counts remain 172 equivalent, 254 partial, 64 missing and 207 requiring
review out of 697 accepted rows. H277 remains partial. Next action: reassess its
remaining discovery, SDK/parameter/credential recovery and retry requirements
against the pinned upstream before choosing the next bounded delivery. Presence
explanation remains an optional unwired seam; do not count a selector alone as a
user-facing feature. No live provider, paid route or native-client proof was run.

Local auxiliary rulings: use standing autonomous local development/delegation;
adopt the four related producers together, at the cost of a broader regression
surface; accept printable Unicode model IDs as opaque JSON data, with actual
backend acceptance still unverified. Owner subsequently authorized publication and merging; current remote acceptance must be checked separately.

Earlier video retry rulings: follow standing autonomous local authorization;
keep retries default-zero and bind enabled policy to task approval; match the
inspected asynchronous primary-only retry contract while keeping ordinary timeouts
and fallback candidates outside that retry budget.

Current publication preparation: full backend20505 passed on0307142d,34 skips,
one expected failure and64 warnings; the prior failed Git fixture run is preserved
in the integration receipt. See [publication review](publication-review-2026-10-02.md)
for the aggregate review and source normalization note. GitHub CI and merge status
are reported separately on the integration PR.

## Current local parameter recovery — 2026-10-02

Base main cd2aa666 after PR1227 integration; source5f12b1b8 on
`codex/h277-auxiliary-recovery-20261002`. The latest goal continuation keeps this
batch local. Five nonstreaming LM Studio consumers now recover explicit
temperature rejection on the same route, with one parameter repair and one
existing unload retry, at most three sends. Initial temperature is preserved;
repair deliberately omits it. Token caps, request scopes and output rules remain.
Focused union612 passed including32 new cases; bounded independent review found
no blocker. Full clean-snapshot validation passed on `3153217f3856beb3509ee30f995a243b3279cf1f`: 20569 passed,34 skipped and one expected failure; all4302 tracked regular files remained unchanged. The first failed full run and STT fixture correction are preserved in the [integration receipt](evidence/h277-auxiliary-parameter-integration-2026-10-02.json). Next: continue remaining H277 recovery/discovery requirements against the pinned reference. See the
[implementation report](h277-auxiliary-parameter-2026-10-02.md).

Exactly10 previously-current rows were inspected and refreshed; H681 remains
stale because its orchestrator/coordinator pins were already mismatched at the
base. The original207 stale rows and all capability statuses remain unchanged.
No live provider, deployment or remote publication is part of this new batch.


## Current local video empty recovery — 2026-10-02

Base `afcc652dcc0f5e0caa6ea8b826fb748848abac41`; runtime
`45d76bbef62cb347b19d8a89ee68988db74476bc`, branch
`codex/h277-video-empty-retry-20261002`. Opt-in valid-empty recovery restarts the
whole approved video chain once, including from a fallback empty, with a signed
budget and fresh authority on each send. Prepared source/question and total
180-second deadline stay fixed. Existing nonempty behavior and default-zero
contracts remain. See the [implementation report](h277-video-empty-retry-2026-10-02.md)
and [frozen source review](h277-video-empty-source-review-2026-10-02.md).

Full backend on clean `a2ddbbb251175aa6d5bd17debe9440c9c518b253`:
**20,630 passed, 34 skipped, one expected failure**, with 64 warnings. All 4,306
tracked regular files and HEAD stayed unchanged. Parent-focused regression:
647 passed, including 61 new cases; record/doc guards: 92 passed. Exact runtime
mutation campaign: 12 valid, 10 killed, two redundant-guard survivors, zero invalid;
both 500-test baselines passed and all archive file hashes were restored. The
compound removal of both bounds was caught. Pure codec and provenance mutations
are identified separately in the [mutation report](evidence/h277-video-empty-mutations-2026-10-02.md).
The [integration receipt](evidence/h277-video-empty-integration-2026-10-02.json)
preserves commands, source hashes, per-case edits/results and artifact hashes;
the replayable mutation runner is saved beside the report.

Only previously-current H277/H513 were reevaluated and refreshed, with no status
changes. Counts remain 172 equivalent, 254 partial, 64 missing and 207 requiring
review. No frontend source/schema change, live provider/device proof or coverage
percentage is claimed. The inherited Gemini behavior that ignores malformed
thought parts beside a visible answer remains separate output-normalization work.

Next action: design the bounded image valid-empty increment from the
[source investigation](h277-image-empty-investigation-2026-10-02.md), resolving
interactive/remote/unattended budget and authority differences before modifying
shared VLM behavior. Continue the full accepted Hermes backlog; this milestone
does not complete H277. All new commits remain local; canonical main remains at
cd2aa666. Prior published GitHub Windows CI was still in progress at the last check
and is not implied green by this local run.

## Current local image empty recovery — 2026-10-02

Goal remains complete local Hermes parity. Base `9313fe0c9b2d918579b0dda64f11fad59bedc9c2`;
runtime `a6a2388f037d130ec0a5bc06a5d9a3f49cf5a9ef`; additional behavioral tests
`931b6626017146ffa31ece8f2bc9b5b7865d59a7`; full verified head
`47ffd68f55c01fa3b45ba596ed94c0a9cb5b81ce`. Branch:
`codex/h277-image-empty-retry-20261002`. Generated 2026-10-02.

Opt-in image empty recovery now covers the five governed native consumers with
same prepared images/model, at most two sends, a shared deadline, fresh authority
and exact-body/final-hook checks. Changing the enabled budget invalidates composer
consent bindings and unattended grants. CLI and HUD disclose the second-call budget;
legacy default-zero shapes remain. Changed paths are the vision policy/backend,
new retry/shared predicate helpers, the video's predicate import, CLI/composer/local
panels, their tests, regenerated web assets and config/evidence documentation.
See the [implementation report](h277-image-empty-retry-2026-10-02.md) and
[source review](h277-image-empty-source-review-2026-10-02.md).

Full backend: **20,686 passed, 34 skipped, one expected failure**, 64 warnings;
HEAD and all 4,318 tracked regular files unchanged. Full frontend: **1,847 passed**;
typecheck, E2E TypeScript compilation and production build passed. Browser E2E was
not executed. Parent backend union582 and CLI117 passed; two additional scope-edge
tests passed; records/doc guards92 passed. This batch adds56 backend test cases and
nine frontend cases. Tracked test counts20721/1847 match those result artifacts.

The original mutation campaign on the runtime commit retains its honest result:
10 valid, five killed and five survived. Three overlapping cap controls and an
independent H513 scope explain redundant survivors; one uncovered final-hook-order
case prompted a new test. A separate test also covers governed text-only calls.
Both corresponding supplemental mutations were killed on the added-test commit.
Original baselines421/421 and supplemental42/42 passed; every archived source hash
was restored. See [original campaign](evidence/h277-image-empty-mutations-2026-10-02.md),
[supplement](evidence/h277-image-empty-mutations-supplement-2026-10-02.md), and the
[integration receipt](evidence/h277-image-empty-integration-2026-10-02.json).

Only31 previously-current evidence rows were reviewed/refreshed; no capability
status was promoted. Counts remain172 equivalent,254 partial,64 missing,207 requiring
review. No live-provider/device result or coverage percentage is claimed. All new
commits remain local; canonical main remains cd2aa666. No push, merge or deployment
in this increment, and no new GitHub CI claim.

Next action: formalize the bounded response-normalization contract from the
[new source investigation](h277-output-normalization-investigation-2026-10-02.md),
then implement/test it under the same authority boundary. Preserve current retry
behavior and evidence; continue the accepted backlog. H277 and the overall goal
are not complete.

## Current local native normalization — 2026-10-02

Goal remains full local Hermes parity. Base
`173a5a840f8bff27b2ef41a474837ec73e44f18c`; source
`74cc7130dee0408cddf026bfb7a004726f0c9c93`; full verified head
`f58948f189b86c21d6f0c60f0102c3c6ab38bb6b`. Branch:
`codex/h277-vision-normalization-20261002`. Generated 2026-10-02.

Native image and signed compatible/Gemini video now prefer normalized visible
text and otherwise use typed reasoning, following the pinned extraction order.
Gemini joins raw fragments before filtering; useful thought-only text returns in
one call. Explicit error envelopes, malformed mixed parts and blocked outputs
remain terminal. This supersedes earlier deliberate preservation of nonempty
Gemini thought-part permissiveness. No transport, authority, route, credential,
retry budget or schema change. Changed files are the shared native-response helper,
VLM/video parsers/dispatch, their actual consumer tests and relevant documentation.
See the [implementation report](h277-vision-normalization-2026-10-02.md).

Final backend on the clean recorded head: **20,739 passed, 34 skipped, one expected
failure**,64 warnings; all4,329 tracked regular files and HEAD unchanged. The
tracked20,774 total matches JUnit and increases by53 net cases over the preceding
image batch. Parent integration696 passed; record/doc guards92 passed. The first
integration failure was one obsolete thought-only refusal expectation, corrected
to verify useful output and one send; that failed receipt is retained. Frontend,
schema and generated assets are unchanged from the prior1847-test verified image
snapshot; no redundant frontend run or browser E2E claim.

Exact source mutation campaign: **8 valid,8 killed,0 survived,0 invalid**, all
assertion failures rather than collection/runtime errors. Baseline/final504/504
passed; every archived source hash restored. See the
[mutation report](evidence/h277-vision-normalization-mutations-2026-10-02.md) and
[integration receipt](evidence/h277-vision-normalization-integration-2026-10-02.json).
Two Sol High writers handled distinct compatible and Gemini paths; coordinator
review corrected contract details and an image test that initially only set a flag
without entering its governed request scope. Final tests exercise the actual scope.

H277 remains partial; only previously-current H277/H513/H586 were refreshed after
complete base-pin and source review. H139 remains inherited-stale. Counts remain172
equivalent,254 partial,64 missing,207 requiring review. Live-provider/device proof,
SDK/non-native breadth, discovery/credential recovery and larger uploads remain.
No push, merge or deploy; canonical main remains cd2aa666.

Next action: design real-consumer auxiliary provider discovery from the
[pinned source investigation](h277-discovery-investigation-2026-10-02.md).
Upstream text routing refuses discovery when a concrete selected main provider is
unavailable; vision separately permits its dedicated aggregator fallback. Do not
apply the text-only gate to vision or scan arbitrary logged-in accounts. Resolve
and disclose candidates before approval, preserve local-only task policy and key
host scoping, and retain every missing capability in the overall objective.


## Owner-authorized publication — 2026-10-02

The owner now explicitly requests evaluation, repair/closure and merge of open
PRs, then continuation of the Nerva backlog. This supersedes earlier local-only
publication restrictions for this work; deployment remains outside this request.
Live GitHub inspection found zero open PRs: #1207, #1226 and #1227 are merged.
The current candidate integrates the fourteen local H277 reliability commits over
`cd2aa666ed0a690e9bf9138747b95c15ffe9ee37`, preserving their implementation and test
history. Goal: publish and merge the verified reliability checkpoint, then resume
provider discovery. Non-goals: claiming full H277/Hermes parity or live-provider
proof. Paths: existing auxiliary/image/video source, tests, generated HUD assets
and evidence documents. Verify full backend/frontend suites, type checks,
production build, status/reference gates and secret scan; wait for GitHub checks
on the published candidate before merging. Rollback: revert the integration PR.
Next action: inspect review findings and current CI, then continue discovery with
distinct text/vision rules and server-owned request context.
