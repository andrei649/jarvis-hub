# B2.1 Point-in-Time Live Issue Movement Gate — Design

**Date:** 2026-08-07

**Issue:** #846 (program #757; blocker plan #778/B2; predecessor #847)

**Status:** Revised working design after independent security and integration
HOLD. Implementation, hosted proof, independent exact-head review and
integration are still pending. The control has read-only GitHub authority and
no GitHub write, runtime, completion or release authority.

## 1. Goal

Add the strongest repository-side B2 control possible without GitHub write
permission or an owner-side merge-queue/ruleset change. Every pull request
deterministically classified as Nerva must, before it can produce the existing
required `test (ubuntu-latest)` context on a non-draft head, prove that:

1. the canonical program manifest and generated view moved together;
2. the movement scope and implementation issue are derived from the semantic
   manifest diff rather than trusted from pull-request prose;
3. #757, #778, the derived stream epic when applicable, and the derived
   implementation issue contain owner-authored exact-head candidate receipts;
4. the pull-request attestation binds the repository, PR, base SHA, head SHA,
   candidate manifest digest and exact bytes of those live receipts; and
5. all authority, execution, completion and release claims remain false.

The proof is deliberately point-in-time: it means the current live PR plus
matching live receipts were observed during a named CI run for one exact head.
It does not claim that a mutable comment remained unchanged after that run or
that GitHub issue prose is immutable completion evidence.

This package also reconciles accepted repository truth left stale after the
latest integration wave:

- E1.2a/#841/#842 is accepted as `contract_ready`, while E1.2b owner evidence
  remains absent and `real_task_outcome_quality=not_measured`;
- E8.1c/#844/#845 is accepted only as static preflight evidence and is no
  longer listed as an open B2-adjacent package.

Before B2.1 may leave draft, predecessor #847 must be accepted on `main`. It
makes the active hourly conductor skip both `nerva2/` head branches and the
exact movement-attestation marker, including on its immediate pre-merge
recheck. This prevents the conductor from racing B2.1's mandatory final live
observation.

## 2. Verified live constraints

The original design-time main was
`843918848c11bbd3f0099f9504d0e0eaaa56b9d6`. After predecessor #847 was
merged, the accepted implementation base is
`e596920ec60f19d2e7f0937819c892746a1c42b2`; the canonical program-manifest
JSON and Markdown bytes are unchanged between those heads, and live main has
zero open pull requests.

The active repository ruleset (`17879112`) requires these contexts:

- `test (ubuntu-latest)`;
- `test (windows-latest)`;
- `frontend`;
- `hud-v2-build`;
- `Analyze (python)`.

It does **not** require `Nerva Roadmap Integrity / validate`, does not contain a
`pull_request` rule, and classic branch-protection reports unconfigured. The
existing Nerva roadmap workflow is path-filtered. Therefore placing B2.1 only
in that workflow would be advisory and bypassable by omitting a listed path.

The active `.github/workflows/pr-auto-merge.yml` also merges every non-draft
`CLEAN` PR on an hourly schedule. B2.1 cannot rely on a manual final rerun until
#847's Nerva/manual-integration exclusion is present in the default-branch
workflow. #847 is a separate, smaller authority package and a hard predecessor,
not an edit hidden inside B2.1.

Selected enforcement path: a new `nerva-movement` job runs from `ci.yml` on
every pull-request event. Both matrix `test` jobs depend on it with
`if: always()` and, on pull requests, fail explicitly unless its result is
`success`. This
propagates a failed or cancelled movement gate into the already-required Ubuntu
context without changing the live ruleset.

Direct pushes are outside this PR-specific guarantee. No design text may claim
that the current ruleset requires a pull request or makes comments immutable.

## 3. Guarantee boundary

| Property | Guaranteed by B2.1 | Not guaranteed |
|---|---|---|
| Workflow coverage | `ci.yml` emits a movement result for every PR; no workflow-level path filter | Intent inference for an intentionally disguised PR on an unregistered path |
| Merge check | Gate result is propagated into required Ubuntu/Windows test contexts | A repository setting that requires PRs or merge queue |
| Receipt truth | Exact body bytes and metadata observed live at one CI run | Continuous invalidation after a later comment edit/delete |
| Scope binding | Stream/control, epic and implementation issue derived from manifest diff | Free-form issue body, labels or complete comment history |
| Authority | Read-only current-PR and comment fetches only | GitHub writes, approvals, merges, runtime action or completion authority |

An owner-account compromise and a deliberate attempt to disguise Nerva work by
using both a non-Nerva branch and an unregistered new path remain residual
operational risks. Repository branch convention, exact-head independent review
and the final pre-merge rerun are required compensating controls. B2 remains
`PARTIAL` unless the live program explicitly accepts this point-in-time scope or
an owner-side PR/merge-queue rule later closes those gaps.

## 4. Selected architecture

### 4.1 Current-PR read and deterministic all-PR classifier

In live mode the event file supplies only the bounded repository identity and PR
number used to build one fixed pull-request GET URL. The checker fetches the
current PR and validates its repository, number, open state, body, draft flag,
base SHA/ref, head SHA/ref and author fields before classification. It parses the
attestation from that current REST body, not the possibly stale event body. A
rerun of an old workflow therefore cannot silently reuse an older attestation;
head/base movement fails against checkout and current readiness is observed
live.

The checker then computes the exact base-to-head name-status diff with
fixed-argument, `shell=False` Git calls using
`git diff --name-status --no-renames -z <base> <head> --`. Every status record,
NUL boundary and path is decoded and validated before any skip decision. An
unknown status, invalid UTF-8, absolute/traversing/backslash/NUL path, case-
collision or malformed record fails for every PR, including one not yet
classified as Nerva.

A PR is classified as Nerva if any closed-world signal is present:

- `pull_request.head.ref` starts with the canonical `nerva2/` prefix;
- the body contains the exact
  `<!-- NERVA2:MOVEMENT-ATTESTATION:START -->` marker;
- a changed path is under `docs/nerva2/`;
- a changed path is a baseline/candidate program-manifest static input; or
- a changed path matches an exact path or prefix in the union of the validated
  exact-base and exact-head movement policies (current Nerva contracts,
  checkers, tests and runtime modules).

The union also contains a small hard-coded bootstrap/static-input set, so a
candidate cannot hide a path by deleting its registry entry. For the exact
bootstrap base only, the absent manifest policy is projected to a canonical
hard-coded seed list whose digest and ordered entries must exactly match the
candidate's initial registry. Every seeded exact path must be tracked and every
seeded prefix must cover at least one tracked path. This one-time
materialization is exempt from the same-PR-new-path rule; any candidate entry
beyond the seed must cover a path added by #846 itself.

After bootstrap, registry exact paths and component-boundary prefixes are
sorted, unique, portable, wildcard-free and append-only: removal, narrowing or
replacement fails. A new entry may be appended in either movement kind only
when it covers at least one path added by that same PR; branch prefixes and all
other classifier semantics are immutable. A non-Nerva classification reports a
deterministic skip after the current-PR and complete-diff validations. The
workflow itself still succeeds or fails visibly for that PR; it is never
omitted by a workflow path filter.

A draft Nerva PR with no attestation is `draft_hold` and may run ordinary CI.
If an attestation is present, it must validate even while draft. A non-draft
Nerva PR must pass the complete live movement proof.

### 4.2 Scope derived from the semantic manifest diff

The checker loads strict baseline and candidate manifests and derives one of
two scopes. B2.1 is the only bootstrap: exact base
`843918848c11bbd3f0099f9504d0e0eaaa56b9d6` may have the accepted legacy
manifest-v1 shape with no `movement_gate`. For that base only, the missing gate
is projected as the pinned canonical classifier seed plus an empty program-
control issue list. The candidate must materialize that seed, add nested
`movement_gate.schema_version=1`, `enforcement_state="required"`, the immutable
gate semantics and `program_control_issues=[846]`. Existing #839 remains the
immutable repository-manifest `evidence_snapshot.control_issue`; it is not
synthesized as a B2.1 program-control movement. After this bootstrap, a missing,
unversioned or ordinary-candidate downgrade fails closed.

The exact legacy base is part of the security contract, not a convenient stale
base. It remains the historical classifier source only. Immediately before
implementation and again before publishing the candidate, `origin/main` must
still equal the accepted current base `e596920ec60f19d2e7f0937819c892746a1c42b2`.
If it advances, work stops for design review and explicit re-pin; the branch is never
silently rebased past the only legacy shape allowed by the checker.

The candidate movement gate also pins #847 as a required operational invariant:
its workflow path, focused policy-test path, exact `nerva2/` branch prefix and
exact attestation start marker are closed-world fields. While
`enforcement_state="required"`, the program-manifest checker requires those
tracked paths and the focused test verifies both list-time and immediate-
recheck exclusions. Both paths join the manifest static-input set, so later
changes are classified as Nerva. The invariant may become non-required only in
the typed `safety_disabled` transition.

`stream`

- exactly one `streams[]` object changes;
- the stream ID is derived from that object and must be declared identically;
- the epic is the candidate stream's canonical `epic_issue`;
- the union of all issue IDs newly introduced by issue references and new
  completion/accepted-evidence records is exactly one issue, and every new
  evidence record is bound to the current PR;
- the implementation issue must differ from #757, #778 and the epic; and
- changes to any other stream are rejected.

Within that stream, `id`, `name` and `epic_issue` are immutable. Existing issue
references, completion evidence, prerequisite edges and accepted evidence are
append-only and byte/semantic preserving; they cannot be deleted or rewritten.
Prerequisite gate transitions and stream status/eligibility/blocker changes may
occur only where the existing manifest state machine validates them. Registry
paths may only grow under the monotone rule above.

`program_control`

- `streams`, `authority`, runtime feedback, known drifts and invariants are
  semantic-identical to the baseline;
- exactly one new implementation issue is appended to the manifest's
  closed-world program-control references;
- that issue is derived as the implementation issue and must differ from #757
  and #778; and
- every prior program-control issue is preserved in order; and
- only monotone classifier path additions may accompany the one new control
  issue. All other movement-gate fields and root fields are immutable.

This B2.1 package is `program_control` and derives #846. Its E1.2a/E8.1c
correction is confined to `BACKLOG.md`; it does not rewrite stream semantics.

For either scope, both canonical manifest JSON and generated Markdown must
change against the exact base, the Markdown must be byte-current, and the
existing whole-program checker must accept the exact candidate. Metadata-only
or role-substitution movement fails.

### 4.3 Strict current-PR attestation

The body returned by the live pull-request GET carries exactly one closed-world
JSON object bounded by
`<!-- NERVA2:MOVEMENT-ATTESTATION:START -->` and
`<!-- NERVA2:MOVEMENT-ATTESTATION:END -->`. Offline fixtures supply the same
validated REST shape. The attestation binds:

- schema version and the derived movement kind;
- derived stream ID for `stream`, absent for `program_control`;
- exact repository and PR number;
- exact lowercase 40-hex base and candidate heads;
- SHA-256 of the canonical candidate program-manifest bytes;
- fixed program issue #757 and blocker-plan issue #778;
- the derived epic, when applicable, and derived implementation issue;
- a closed-world role map whose entries contain `comment_id`,
  `comment_body_sha256` and `updated_at`; and
- immutable false authorization, execution, completion and release fields.

Required roles are `program`, `blocker`, `epic` and `implementation` for a
stream movement, and `program`, `blocker` and `implementation` for a
program-control movement. Duplicate comment IDs, role/issue aliases and extra
roles are rejected.

### 4.4 Append-only candidate receipts

Each declared issue comment contains one closed-world JSON receipt bounded by
`<!-- NERVA2:MOVEMENT-RECEIPT:START -->` and
`<!-- NERVA2:MOVEMENT-RECEIPT:END -->`. A receipt does **not** contain its own
comment ID; GitHub allocates that ID only after creation. It binds:

- schema version, repository, issue number, PR and role;
- derived movement kind, stream/epic scope where applicable and implementation
  issue;
- exact base/head SHA and candidate manifest digest; and
- immutable false authority/release fields.

The REST envelope is validated separately and may contain unknown GitHub fields
for forward compatibility. Required envelope facts are exact:

- requested comment ID equals `response.id` and the attested ID;
- `issue_url` identifies the derived role issue;
- `user.login == "andrei649"` and `author_association == "OWNER"`;
- `created_at == updated_at == attested updated_at`, rejecting edited comments;
- SHA-256 of the exact UTF-8 `body` equals the attested body digest; and
- parsed receipt fields match every derived/event/manifest binding.

Receipts are created once after the head is frozen and never edited. A changed
head requires new comments and a new attestation. Deletion or editing fails on
the next fetch; historical green remains only evidence of what that run saw.

### 4.5 Bounded read-only REST transport

The standard-library client owns the HTTPS read. It accepts `--live` with the
event file and `GITHUB_TOKEN`, or `--snapshot-dir` with offline REST fixtures
that exercise the identical response validator.

`--live` and `--snapshot-dir` are mutually exclusive. Snapshot mode reads no
token, opens no network connection and validates current-PR plus comment
fixtures through the same envelope validators. Event files, live PR bodies,
comment bodies, marker blocks, token length, response count and aggregate bytes
all have explicit caps.

Live transport:

- builds only fixed pull-request and issue-comment GET URLs after bounded-
  integer validation;
- disables redirects and environment proxies;
- pins GitHub JSON accept/API-version/user-agent headers and
  `Accept-Encoding: identity`;
- uses the standard verified TLS context and accepts only an absent
  `Content-Encoding` header or the exact value `identity`;
- rejects an oversized token or CR/LF/control bytes in it, a changed final URL,
  non-200 response, timeout, rate limit, malformed JSON or missing fields;
- reads at most `MAX_RESPONSE_BYTES + 1`, with per-response and total-count
  limits; and
- emits bounded sanitized errors without token, body or URL query material.

The receipt schema is closed-world; the GitHub REST envelope is strict only for
consumed fields so harmless API additions do not break the gate. The workflow
adds an external timeout around the step as the hard total deadline; per-read
timeouts alone are not treated as protection from a slow trickle. Redirect
tests prove the Authorization header is never resent, and proxy tests prove
environment proxy variables are ignored.

### 4.6 Required-CI propagation and least privilege

`.github/workflows/ci.yml` keeps workflow-level `contents: read`. The new job
overrides only:

```yaml
permissions:
  contents: read
  issues: read
  pull-requests: read
```

All token scopes are read-only. Pinned `actions/checkout` uses the read-only
`github.token` transiently and `persist-credentials: false` prevents Git
credential persistence. Only the checker `run` step receives `GITHUB_TOKEN` as
an explicit environment variable; every Git subprocess receives a scrubbed
environment without token or proxy variables. Other actions can access the
job-scoped `github.token` under GitHub's normal model, so no stronger token-
isolation claim is made.

Explicit PR activity types preserve `opened`, `synchronize` and `reopened` and
add `edited`, `ready_for_review` and `converted_to_draft`. Existing per-PR
concurrency cancels superseded runs. The movement job is skipped on `push`; the
matrix test jobs still use `if: always()`, but their dependency guard requires
movement success only when `github.event_name == 'pull_request'`. Push-to-main
therefore runs the unchanged test matrix without live permissions or receipts.

### 4.7 Exact-head and point-in-time integration protocol

The checker proves the live PR head equals event head and checked-out HEAD before
and immediately before success, the live base equals the event base and is an
ancestor, the live PR is open/currently ready for final proof, manifest/view
changed, and the candidate digest matches. The final log records a bounded run
observation tuple: PR, head, manifest digest, comment IDs and observation time,
without PR/comment bodies.

Because issue-comment edits do not invalidate an existing PR check, auto-merge
is forbidden for this control. B2.1 remains draft until live default-branch
inspection proves #847's conductor exclusion is merged and active. The
independent integrator must explicitly
rerun the required CI workflow on the unchanged head immediately before merge,
wait for the fresh movement job to GET the current PR and receipts plus all
required contexts, confirm zero review threads/current-main ancestry, and then
merge. A rerun's event payload may be old; the mandatory live PR GET is what
binds the run to the current body, head, base and draft state.

That narrows but cannot eliminate the comment-mutation race. A stronger atomic
guarantee requires an owner-side merge queue/PR-required ruleset and a
`merge_group` design, or GitHub write authority to publish/invalidate checks;
both are outside this package.

## 5. Threat model and fail-closed behavior

| Threat | Required behavior |
|---|---|
| Shell/script injection in body, branch, comment or title | Parse bounded data only; never interpolate it into shell source. |
| Duplicate/partial markers or duplicate JSON keys | Reject. |
| Unicode/control ambiguity, non-finite values, bool-as-int or oversized input | Reject before semantic validation. |
| Malformed diff/status/path before classification | Reject for every PR before any non-Nerva skip. |
| Cross-repository, PR, role, issue, stream or epic substitution | Derive scope from manifest diff and reject every mismatch. |
| Candidate removes/narrows classifier coverage | Classify against baseline/candidate union and require monotone additions. |
| Stale head/base, replayed receipt or changed manifest | Reject exact SHA/digest mismatch. |
| Workflow rerun has a stale event body | GET and validate the current PR; parse only its current body. |
| Receipt edit after creation | Require `created_at == updated_at` and attested body digest on every run. |
| Comment edit/delete after green | Fresh final rerun is mandatory; continuous invalidation remains explicitly unproven. |
| Untrusted author | Require exact owner login and `OWNER` association. |
| Redirect/proxy/API error/timeout/rate limit/truncation | Fail closed with bounded errors. |
| Candidate changes checker/workflow | Fresh exact-head independent review plus required Security/CodeQL remain mandatory. |
| Draft before receipts exist | `draft_hold` only; GitHub cannot merge a draft. |
| Direct push | Outside this PR gate; never described as prohibited by current settings. |

## 6. Repository surface

Owned files:

- `docs/superpowers/specs/2026-08-07-b2-live-issue-ledger-design.md`;
- `docs/superpowers/plans/2026-08-07-b2-live-issue-ledger.md`;
- `docs/nerva2/NERVA_ISSUE_MOVEMENT_V1.md`;
- `scripts/check_nerva_issue_movement.py`;
- `tests/test_nerva_issue_movement.py`;
- `.github/workflows/ci.yml`;
- `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json`;
- `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md`;
- `scripts/check_nerva_program_manifest.py` and focused tests only where the
  movement-gate schema requires them;
- `BACKLOG.md`; and
- mechanically generated status files only if collected test truth changes.

Predecessor #847 separately owns `.github/workflows/pr-auto-merge.yml`, its
focused policy test and its own rollback. B2.1 does not duplicate that diff.

The path-filtered Nerva roadmap workflow remains an adjacent static-integrity
lane; B2.1 does not pretend it is a required context. There is no runtime, API,
provider, dependency, HUD/mobile or production behavior change.

## 7. Test strategy

TDD starts with the strict parser and pure response validator. Coverage must
include:

- legacy-base bootstrap, valid stream, valid program-control, draft-hold and
  non-Nerva cases;
- branch-, path-, manifest-static-input- and marker-based classification;
- baseline/candidate policy union, append-only registry evolution, removal,
  narrowing, wildcard and unrelated broad-prefix rejection;
- #847 manual-integration workflow/test paths and exact branch/marker policy
  remaining mandatory while enforcement is `required`;
- malformed status/path/UTF-8/case-collision failure before non-Nerva skip;
- a Nerva branch that omits manifest/view movement failing once non-draft;
- one changed stream, canonical epic derivation and new implementation-issue
  set derivation; multi-stream, history deletion/rewrite and delivery-changing
  program-control rejection;
- duplicate/partial markers, duplicate keys, unknown fields, invalid scalar
  types, Unicode/control ambiguity and all size/depth/count caps;
- wrong repository, PR, role, issue, author, association, base/head, manifest
  digest, body digest, timestamps or derived scope;
- stale/replayed/cross-role/cross-issue receipts and duplicate comment IDs;
- stale event versus current live PR body/head/base/draft, edited/deleted
  receipts, redirects, proxies, changed final URL, unexpected content encoding,
  HTTP/rate errors, total timeout and `MAX + 1` truncation;
- literal shell metacharacters remaining inert and secrets absent from errors;
- head movement immediately before success;
- exact CI workflow events, job-level permissions, non-persisted read-only
  checkout credentials, movement dependency and explicit required-test failure
  propagation; and
- live default-branch proof that #847's conductor skips both `nerva2/` and the
  exact attestation marker before B2.1 becomes ready; and
- immutable false authority/release fields.

Adjacent verification includes program-manifest, roadmap, repository-ledger and
status-sync gates, Ruff, `py_compile`, YAML parsing, Bandit,
`git diff --check`, the full repository suite, hosted exact-head CI/Security/
CodeQL and fresh independent security/integration review.

## 8. Live use protocol for this PR

1. Accept and merge predecessor #847, then verify its exact conductor exclusion
   from the default branch.
2. Reconcile live #846 to this accepted design, then commit the design before
   implementation.
3. Reassert `origin/main` is still the accepted current base
   `e596920ec60f19d2e7f0937819c892746a1c42b2`; otherwise stop and re-pin through
   design review.
4. Add RED hostile tests, then the minimum checker, manifest policy and CI job.
5. Open #846's PR as draft; receipt-free `draft_hold` is expected, not proof.
6. Freeze one candidate head after local QA and complete a first independent
   code/security review.
7. Post new append-only receipts to #757, #778 and #846.
8. Add their IDs, exact body digests and timestamps to the PR attestation.
9. Trigger `edited`, obtain a green hosted live read, and obtain final
   exact-head independent decisions.
10. Mark ready only after re-verifying #847, then explicitly rerun required CI
    once more on the unchanged head immediately before integration. The checker
    must GET the current PR and receipts during that run. Do not enable
    auto-merge.
11. Revalidate receipts, ancestry, checks and threads; squash-merge only if all
    are unchanged and green.
12. Post factual merge-SHA deltas after merge. Those are reconciliation, not
    candidate receipts or completion authority.

## 9. Rollback and completion truth

Rollback is a bounded two-phase forward safety transition, not a blind full-
commit revert:

1. while the required gate is still active, a separately reviewed
   `program_control` rollback PR appends one rollback issue and changes only
   `enforcement_state` from `required` to the versioned `safety_disabled`. It
   must bind `rollback_of_issue=846`, a bounded reason, fresh owner receipts and
   exact-head checks. The checker permits this one typed transition but rejects
   missing state, an ordinary downgrade or a return from `safety_disabled`
   without a new schema/design;
2. only after that state is on `main`, a second reviewed cleanup removes the
   `test` dependency and live job/checker/contract while preserving the
   manifest's disabled historical record.

Both phases retain the factual E1.2a/E8.1c BACKLOG corrections and historical
candidate comments. #847 is independently revertible only before B2.1 is
accepted. While `enforcement_state="required"`, its conductor exclusion is a
required operational invariant and cannot be reverted first. After the B2.1
state reaches `safety_disabled`, #847 may be reverted separately if desired.

A full squash revert is forbidden because it would knowingly restore false
repository status. There is no runtime, database or production migration.

Merging this package can accept only the B2.1 point-in-time PR-control slice.
It does not make comments immutable, require all changes to arrive by PR,
complete B2/E1/E8/Nerva, satisfy B3-B10, grant runtime or GitHub write
authority, or establish release readiness.

## 10. Primary references

- GitHub workflow permissions and `GITHUB_TOKEN`:
  https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- GitHub script-injection boundary:
  https://docs.github.com/en/actions/concepts/security/script-injections
- GitHub issue-comment REST endpoint and permissions:
  https://docs.github.com/en/rest/issues/comments
- GitHub pull-request event activity types:
  https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Required checks and path-filter behavior:
  https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks
- Merge-queue `merge_group` requirement:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue
