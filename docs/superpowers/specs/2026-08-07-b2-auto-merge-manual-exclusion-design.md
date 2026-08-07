# B2.0 Manual-Integration Exclusion Design

**Issue:** #847
**Parent:** #846 / #778 B2
**Branch:** `nerva2/b2-auto-merge-manual-exclusion`
**Accepted base:** `main@843918848c11bbd3f0099f9504d0e0eaaa56b9d6`
**Status:** design only; workflow and tests are not implemented yet

## Goal

Prevent the hourly conductor from automatically merging a current or future
Nerva movement before B2.1's final live, exact-head manual integration check.
The conductor must exclude a PR when either its current head branch starts with
the canonical Nerva prefix or its current body contains the canonical movement
attestation start marker.

This is a narrow selection-policy change. It does not validate receipts,
classify arbitrary Nerva semantics, or change GitHub rulesets.

## Existing gap

`.github/workflows/pr-auto-merge.yml` currently lists only `number`, `title`,
`isDraft`, `mergeStateStatus`, and `headRefOid`. Immediately before merge it
re-reads only `mergeStateStatus`. A non-draft Nerva PR reported `CLEAN` can
therefore be squash-merged without the manual live-evidence observation required
by #846.

## Exact exclusion contract

The two case-sensitive byte contracts are:

```text
branch prefix: nerva2/
body marker:   <!-- NERVA2:MOVEMENT-ATTESTATION:START -->
```

A PR is manual-integration-only when:

```text
headRefName starts with "nerva2/"
OR
body contains "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
```

No trimming, case folding, Unicode normalization, regular-expression
interpretation, or HTML parsing is allowed. `nerva2x/topic`, `NERVA2/topic`,
`feature/nerva2/topic`, an end marker alone, and marker fragments are not
matches. An empty body is a valid non-match; a missing or non-string body is a
malformed API record and fails the workflow.

B2.1 will define a paired body block using the exact end marker
`<!-- NERVA2:MOVEMENT-ATTESTATION:END -->`. B2.0 intentionally detects only
the exact start marker and does not parse or trust any enclosed payload. This
makes a partially written or hostile attestation conservative: once the start
marker exists, the auto-merger stops.

## Selection and immediate recheck

The workflow remains one bounded shell step and keeps the current permissions.
It removes unneeded `title` from both data and logs, and extends both GitHub CLI
reads to request `headRefName` and `body` in addition to the readiness fields.

Each `gh` stdout is accepted only when the CLI itself exits zero. Partial stdout
from a failing call is discarded. The raw payload is then slurped with `jq -s`
and must contain exactly one JSON document. Before any `view` or merge side
effect, the complete list must be one array whose every record is valid and
whose positive PR numbers are unique. Only that fully validated array is sorted
and iterated.

For every list-stage record, the script must:

1. Consume the already whole-list-validated compact JSON object.
2. Require a positive integer `number`, boolean `isDraft`,
   string `mergeStateStatus`, a 40-character lowercase hexadecimal
   `headRefOid`, non-empty string `headRefName`, and string `body`.
3. Apply the exact branch-or-marker exclusion before considering readiness.
4. Preserve the current draft and `mergeStateStatus == CLEAN` filters for all
   remaining PRs.

Immediately before a possible merge, `gh pr view` must fetch one JSON object
containing at least `number`, `isDraft`, `mergeStateStatus`, `headRefOid`,
`headRefName`, and `body`. The script validates it with the same strict rules,
confirms the returned number is the requested PR, and then re-evaluates:

1. branch prefix and body marker;
2. current draft state;
3. current `mergeStateStatus == CLEAN`;
4. current head OID equality with the list-stage OID.

Any exclusion or ordinary readiness drift skips that PR. A changed head is
skipped rather than adopting the new OID mid-run. An eligible non-Nerva PR is
still merged with `--squash --match-head-commit <list-stage-oid>` and without
branch deletion. The match-head guard closes a push race; the immediate body
and branch read is the narrowest available observation but is not an atomic
GitHub transaction with merge.

## Fail-closed behavior

API/CLI failure, invalid JSON, a non-array list response, a missing field,
wrong field type, invalid OID, empty head name, or identity mismatch exits the
workflow non-zero before the affected PR can be merged. The script must not
turn malformed values into empty strings through `jq -r` and then continue.

Untrusted PR branch and body bytes remain JSON data. The workflow does not
request or log PR titles, branches, or bodies; logs contain only a validated
positive integer PR number and fixed text. One `jq -e` predicate evaluates
`startswith($prefix)` or `contains($marker)` directly over the already
validated record. Its caller captures the status explicitly: `0` means match
and skip, `1` means ordinary non-match, and any status greater than `1` is a
fatal evaluation error. The caller resets `manual_status=0` immediately before
every list-stage and recheck-stage evaluation so a prior non-match cannot make
a later match stale. No helper invoked as an `if` condition may hide an
internal `jq` failure behind Bash `set -e` semantics. PR-supplied bytes are
never evaluated, sourced, interpolated into a shell program, used to construct
a command name, or echoed into GitHub Actions logs.

An ordinary, well-formed non-Nerva record retains the existing behavior:

- draft: skip;
- non-`CLEAN`: skip;
- `CLEAN` at list and recheck with the same head: squash merge;
- merge/API failure: fail the workflow;
- preserve the source branch;
- process the list in PR-number order.

Workflow permissions remain exactly:

```yaml
permissions:
  contents: write
  pull-requests: write
```

## Test strategy

Create `tests/test_pr_auto_merge_policy.py`. A hermetic fake `gh` executable
records list, view, and merge calls while the test executes the YAML `run`
script with real Bash and `jq`. Static assertions pin the workflow permissions,
event scope, exact prefix/marker bytes, requested fields (including the absence
of `title`), squash mode, match-head guard, and absence of `--auto`, `--admin`,
and `--delete-branch`.

Hostile cases must prove:

- a `nerva2/` branch is skipped at list time and after a non-Nerva list record
  changes to that prefix at recheck;
- a multi-record list with an ordinary non-Nerva PR followed by a Nerva PR
  skips the second record, proving predicate status cannot leak between records;
- the exact start marker is skipped at list and recheck;
- prefix lookalikes, case changes, end-only markers, and marker fragments do
  not weaken the exact policy;
- draft, non-`CLEAN`, and changed-head rechecks do not merge;
- list/view failures discard partial stdout and fail non-zero with zero merge
  calls;
- malformed, multi-document, or trailing JSON at list and recheck time fails
  non-zero with zero merge calls;
- duplicate PR numbers, missing fields, every wrong field type, invalid OIDs,
  and returned-number mismatch fail non-zero with zero merge calls;
- a valid early list record followed by a malformed late record fails before
  any view or merge side effect;
- shell metacharacters, newlines, ANSI bytes, and GitHub workflow-command bytes
  in branch/body fields remain inert and never reach logs;
- a merge-command failure fails the workflow rather than continuing;
- an ordinary non-Nerva `CLEAN` PR still produces exactly one merge call with
  `--squash --match-head-commit <expected-oid>`.

If Bash or `jq` is unavailable on a local platform, only the executable harness
cases may skip there; they must run on hosted Ubuntu. Static contract tests stay
cross-platform. Hosted Windows plus Ubuntu CI remain required integration
evidence.

Adding the test may change repository-wide pytest counts. Run
`scripts/status_sync.py --check --reuse-js-counts`; if it reports canonical
count drift, regenerate with the same script and include only its mechanical
outputs (`project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, and
`STATUS.md`). Those files must never be hand-edited for this package.

## Scope

Required files:

- `.github/workflows/pr-auto-merge.yml`
- `tests/test_pr_auto_merge_policy.py`
- this design
- `docs/superpowers/plans/2026-08-07-b2-auto-merge-manual-exclusion.md`

Conditionally included only when canonical status synchronization requires
them: `project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, and
`STATUS.md`.

No B2 checker, program manifest, BACKLOG movement, runtime/API behavior,
issue-comment write, ruleset, dependency, HUD, or mobile change belongs here.

## Integration order and lifecycle invariant

#847 is the hard predecessor of #846. The current default-branch conductor does
not yet know either exclusion, so after independent review and exact-head green
checks it can merge #847 itself under the existing `CLEAN` policy. #847 does not
depend on a B2 receipt or movement attestation. The new selection logic becomes
active only after the resulting workflow bytes are present on `main`.

After integration, verify the default-branch workflow contains both exact
exclusions before #846 may leave draft. B2.1 must be merged manually after its
fresh live recheck; auto-merge remains forbidden for that package.

Before B2.1 establishes `movement_gate.enforcement_state=required`, #847 is
independently revertible. Once that required state is accepted, the conductor
exclusion is a mandatory safety invariant and must not be reverted on its own.
First transition B2 through a reviewed, exact-head movement to
`enforcement_state=safety_disabled`; only then may #847 be reverted separately.

## Rollback

When the lifecycle invariant permits rollback, one focused revert restores the
prior conductor selection policy. If intervening test-count changes prevent a
clean revert of generated truth, rerun canonical status synchronization and
include only its mechanical result. Rollback does not edit issue evidence,
manifest truth, runtime data, or branches.

## Residual limits

This guard is not a semantic classifier for every possible Nerva change and is
not a branch-protection or merge-queue rule. It covers the reserved `nerva2/`
namespace and the canonical B2.1 attestation marker, with one immediate
pre-merge recheck. It does not make issue comments immutable, close B2, retire
any program blocker, or establish release readiness.
