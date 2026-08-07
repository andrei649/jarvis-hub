# B2.0 Manual-Integration Exclusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hourly conductor skip every PR whose live branch starts with `nerva2/` or whose live body contains the exact Nerva movement-attestation start marker, at both list and immediate recheck time.

**Architecture:** Keep the existing single workflow step and add strict JSON validation plus one pure branch-or-marker predicate. Run the same validation and predicate against list-stage and freshly fetched pre-merge records; preserve the current non-Nerva squash and exact-head behavior.

**Tech Stack:** GitHub Actions YAML, Bash with `set -euo pipefail`, GitHub CLI, `jq`, pytest, PyYAML.

## Global Constraints

- Exact branch prefix: `nerva2/` (case-sensitive, no normalization).
- Exact body start marker: `<!-- NERVA2:MOVEMENT-ATTESTATION:START -->`.
- B2.1's paired end marker is `<!-- NERVA2:MOVEMENT-ATTESTATION:END -->`; this workflow detects only the start marker.
- Both list and immediate recheck stages must evaluate current branch and body.
- Reset `manual_status=0` immediately before every list-stage and recheck-stage
  predicate evaluation.
- Missing, malformed, wrongly typed, or identity-inconsistent API data fails the workflow before merge.
- Accept output only when `gh` exits zero and `jq -s` proves there is exactly one
  JSON document. Discard partial stdout from a failing `gh` call.
- Validate the entire list and unique positive PR numbers before any `view` or
  merge side effect.
- Never request or log untrusted PR titles, branches, or bodies. Logs contain
  only validated PR numbers and fixed text.
- Non-Nerva draft/CLEAN/head/squash/match-head/branch-preservation behavior remains unchanged.
- Workflow permissions remain exactly `contents: write` and `pull-requests: write`.
- Do not touch the B2.1 checker, manifest, BACKLOG, runtime, rulesets, HUD, or mobile surfaces.
- Generated truth files change only if `status_sync.py --check --reuse-js-counts` requires them, and only through canonical regeneration.
- Once B2.1 has `movement_gate.enforcement_state=required`, this exclusion cannot be reverted until a reviewed transition sets `enforcement_state=safety_disabled`.

## File map

- Modify `.github/workflows/pr-auto-merge.yml`: strict record parsing, exact exclusion predicate, list-stage exclusion, and full immediate recheck.
- Create `tests/test_pr_auto_merge_policy.py`: static contract checks plus hermetic fake-`gh` execution tests.
- Conditionally regenerate `project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, and `STATUS.md`: mechanical pytest-count truth only.

---

### Task 1: Pin the policy with failing hostile tests

**Files:**
- Create: `tests/test_pr_auto_merge_policy.py`
- Read: `.github/workflows/pr-auto-merge.yml`

**Interfaces:**
- Consumes: the first step's YAML `run` string and a fake `gh` command on `PATH`.
- Produces: `_run_policy(tmp_path, list_payload, rechecks) -> subprocess.CompletedProcess[str]` and a recorded JSONL command trace used by all behavior tests.

- [x] **Step 1: Add cross-platform static contract tests**

Load the workflow with `yaml.load(..., Loader=yaml.BaseLoader)` so the GitHub
key `on` is not coerced to a YAML 1.1 boolean, then select
`jobs["auto-merge"]["steps"][0]["run"]`, and assert:

```python
assert workflow["permissions"] == {"contents": "write", "pull-requests": "write"}
assert 'NERVA_BRANCH_PREFIX="nerva2/"' in script
assert 'NERVA_START_MARKER="<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"' in script
assert "headRefName" in script
assert "body" in script
assert "--squash" in script
assert "--match-head-commit" in script
assert "--auto" not in script
assert "--admin" not in script
assert "--delete-branch" not in script
assert "title" not in script
```

Also assert the workflow still has only `workflow_dispatch` and `schedule`, the
same concurrency group, and no permission expansion.

- [x] **Step 2: Add the hermetic execution harness**

Create a temporary executable named `gh` that:

- returns `LIST_PAYLOAD` for `gh pr list`;
- returns the per-number JSON object from `RECHECKS_PATH` for `gh pr view`;
- appends every invocation to `TRACE_PATH`;
- can independently select list/view/merge exit codes while still emitting
  configured partial stdout for a failing list or view call;
- records `gh pr merge` arguments and returns the configured result;
- exits non-zero for any unexpected command shape.

Run the extracted script with real Bash, the fake directory first on `PATH`,
and real `jq`. Mark only executable cases skipped when either executable is
absent; static tests must never skip.

- [x] **Step 3: Add list-stage RED cases**

Use well-formed 40-hex OIDs and assert zero `view`/`merge` calls for:

```text
nerva2/b2-live-issue-ledger-enforcement + empty body
feature/topic + body containing <!-- NERVA2:MOVEMENT-ATTESTATION:START -->
```

Prove these remain ordinary non-Nerva inputs and reach `view` when otherwise
`CLEAN`: `nerva2x/topic`, `NERVA2/topic`, `feature/nerva2/topic`, the exact end
marker alone, and a one-character-short start-marker fragment.

Also list two records in order: a stable ordinary non-Nerva PR followed by a
Nerva PR. The first may reach its bounded merge path, while the second must be
skipped; this catches a stale `manual_status` left at `1` by the first record.

- [x] **Step 4: Add recheck-stage RED cases**

List a non-Nerva, non-draft, `CLEAN` PR, then return each fresh state in turn:

```text
headRefName changes to nerva2/topic
body gains the exact start marker
isDraft changes to true
mergeStateStatus changes to BLOCKED
headRefOid changes to another valid OID
```

Every case must produce one `view`, zero `merge`, and exit zero because normal
readiness drift is a safe skip.

- [x] **Step 5: Add fail-closed RED cases and the preserved happy path**

At both list and recheck stages cover invalid JSON, two JSON documents, trailing
JSON, non-object records, every required field missing, every required field
with the wrong type, empty head names, invalid OIDs, and returned PR-number
mismatch. Add list cases for duplicate PR numbers and for a valid early record
followed by a malformed late record. The late-record case must prove zero
`view` and zero merge calls, not merely stop after an earlier merge.

Make list and view failures emit partial valid-looking stdout before returning
non-zero; the workflow must discard it and fail with zero merge calls. Exercise
shell metacharacters, newlines, ANSI escapes, and `::stop-commands::`-style
workflow-command bytes in branch/body data, then prove the bytes are inert and
absent from logs. A configured merge failure must fail the workflow after
exactly one bounded merge attempt. Every other malformed case must exit
non-zero and record zero merges.

For a stable ordinary PR, assert exactly one command equivalent to:

```text
gh pr merge 123 --repo andrei649/jarvis-hub --squash --match-head-commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

- [x] **Step 6: Run the focused test and confirm RED**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_pr_auto_merge_policy.py -q
```

Expected: static and/or behavioral failures showing that the workflow lacks
`headRefName`, `body`, the exact constants, and the second exclusion check.

### Task 2: Implement the smallest fail-closed workflow change

**Files:**
- Modify: `.github/workflows/pr-auto-merge.yml`
- Test: `tests/test_pr_auto_merge_policy.py`

**Interfaces:**
- Consumes: GitHub CLI JSON records for list and view.
- Produces: exact-one-document normalization, whole-list validation, explicit
  three-way Nerva predicate handling, and unchanged
  `gh pr merge --squash --match-head-commit` behavior for eligible non-Nerva
  PRs.

- [x] **Step 1: Add exact constants and strict helpers**

Inside the existing Bash step, define read-only constants and helpers with this
shape:

```bash
readonly NERVA_BRANCH_PREFIX="nerva2/"
readonly NERVA_START_MARKER="<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"

validate_pr_json() {
  local stage="$1"
  local record="$2"
  if ! jq -e '
    type == "object"
    and ((.number | type) == "number")
    and (.number > 0 and (.number | floor) == .number)
    and ((.isDraft | type) == "boolean")
    and ((.mergeStateStatus | type) == "string")
    and ((.headRefOid | type) == "string")
    and (.headRefOid | test("^[0-9a-f]{40}$"))
    and ((.headRefName | type) == "string")
    and (.headRefName | length > 0)
    and ((.body | type) == "string")
  ' <<<"$record" >/dev/null; then
    printf 'Malformed PR JSON at %s; refusing to merge.\n' "$stage" >&2
    return 1
  fi
}

nerva_manual_status() {
  local record="$1"
  jq -e \
    --arg prefix "$NERVA_BRANCH_PREFIX" \
    --arg marker "$NERVA_START_MARKER" \
    '(.headRefName | startswith($prefix)) or (.body | contains($marker))' \
    <<<"$record" >/dev/null
}
```

The caller must not invoke this helper directly as an `if` condition. Before
every list-stage and recheck-stage call, reset and capture exactly as follows:

```bash
manual_status=0
nerva_manual_status "$record" || manual_status=$?
```

Then handle `0` as match/skip, `1` as non-match/continue, and every status
greater than `1` as fatal. The helper's sole command is the `jq -e` predicate,
so its status is propagated without relying on `set -e` inside a conditional
function.

Keep all PR-supplied branch/body values inside JSON and out of logs. Fixed text
may include only the separately validated positive integer PR number.

- [x] **Step 2: Extend and validate the list stage before readiness checks**

Request the complete field set:

```text
number,isDraft,mergeStateStatus,headRefOid,headRefName,body
```

Capture `gh pr list` separately from parsing. If `gh` exits non-zero, discard
any captured stdout and fail. Slurp the successful stdout with `jq -s`; require
exactly one JSON document whose top level is an array. Before sorting or
iteration, validate every record and prove that all positive integer PR numbers
are unique. Only after this whole-array pass may the script sort by number and
iterate.

For each validated record, run `nerva_manual_status`, capture the exit status,
and apply the three-way handling above. Log only the validated PR number and
fixed text on a match, then `continue`. Only then apply the existing draft and
non-`CLEAN` skips.

- [x] **Step 3: Replace the scalar recheck with a complete fresh record**

Use `gh pr view <number> --json` with the same complete field set. Capture its
stdout separately; a non-zero CLI status discards even valid-looking partial
stdout and fails. Slurp with `jq -s`, require exactly one JSON document, validate
the object, and require its `number` to equal the listed number. Re-run the
exact manual-integration predicate with explicit `0`/`1`/fatal status handling,
then re-evaluate `isDraft`,
`mergeStateStatus == CLEAN`, and equality between fresh and listed
`headRefOid`. Skip ordinary drift; exit non-zero on malformed data.

Keep the final command exactly bounded by the listed SHA:

```bash
gh pr merge "$number" --repo "$REPO" --squash --match-head-commit "$sha"
```

- [x] **Step 4: Run focused tests and confirm GREEN**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_pr_auto_merge_policy.py -q
```

Expected: all focused tests pass. On a machine without Bash or `jq`, static
tests pass and executable tests report explicit skips; hosted Ubuntu must later
run every executable case.

- [x] **Step 5: Commit the behavior unit after review of the focused diff**

Stage only:

```text
.github/workflows/pr-auto-merge.yml
tests/test_pr_auto_merge_policy.py
docs/superpowers/specs/2026-08-07-b2-auto-merge-manual-exclusion-design.md
docs/superpowers/plans/2026-08-07-b2-auto-merge-manual-exclusion.md
```

Use commit message `ci: exclude Nerva PRs from auto-merge` after the lead
authorizes commit creation.

### Task 3: Reconcile generated truth, verify, and integrate the predecessor

**Files:**
- Verify all scoped files above.
- Conditionally regenerate: `project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `STATUS.md`.

**Interfaces:**
- Consumes: the completed workflow/test unit and current `origin/main`.
- Produces: one independently reviewed exact-head PR that the current conductor may merge, followed by default-branch proof of both exclusions.

- [x] **Step 1: Check canonical generated truth**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe scripts/status_sync.py --check --reuse-js-counts
```

Expected: exit zero. If and only if it reports pytest-count drift, run:

```powershell
& ..\..\.venv\Scripts\python.exe scripts/status_sync.py --reuse-js-counts
& ..\..\.venv\Scripts\python.exe scripts/status_sync.py --check --reuse-js-counts
```

Expected: the second check exits zero. Review and stage only the five canonical
mechanical outputs named in the file map.

- [ ] **Step 2: Run exact verification**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_pr_auto_merge_policy.py -q
& ..\..\.venv\Scripts\python.exe -m pytest tests/ -q
uvx ruff@0.16.1 check tests/test_pr_auto_merge_policy.py
git diff --check
```

Also parse `.github/workflows/pr-auto-merge.yml` with PyYAML and run `bash -n`
against the extracted `run` script. Expected: zero failures; hosted Ubuntu runs
all Bash/jq behavior cases, and hosted Windows plus the repository-required
checks are green on the identical head.

- [ ] **Step 3: Obtain exact-head independent review**

Review the final diff for permission expansion, shell evaluation of untrusted
data, list/recheck asymmetry, prefix/marker lookalikes, lost match-head binding,
and the B2 lifecycle invariant. Resolve every actionable thread and rerun the
affected checks without changing the reviewed head afterward.

- [ ] **Step 4: Let the current conductor integrate #847**

Once non-draft, `CLEAN`, exact-head green, and independently approved, #847 may
be squash-merged by the conductor currently active from old `main`. That old
workflow does not inspect the `nerva2/` branch or marker, and #847 does not
depend on B2 receipts, so using it for this predecessor is not a semantic
bypass.

- [ ] **Step 5: Verify the safety boundary on default branch**

After merge, read `.github/workflows/pr-auto-merge.yml` from `main` and verify
the exact prefix and start-marker guards exist in both list and fresh recheck
paths. Observe the next scheduled run for a terminal result. Do not let #846
leave draft until this proof exists.

Record the lifecycle rule in the #847/#846 integration handoff: before B2.1 is
required, #847 can be reverted independently; while B2.1 is `required`, it
cannot be reverted until a reviewed movement first transitions B2 to
`safety_disabled`.
