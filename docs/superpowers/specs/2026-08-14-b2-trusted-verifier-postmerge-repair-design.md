# B2 trusted-verifier post-merge repair

## Goal

Keep candidate-side Step 2 permanently fail-closed. Candidate repository code must
never authenticate itself, manufacture `trusted_source=yes`, perform structural
validation through candidate code, or load a checker before an independent trust
boundary has accepted its exact byte snapshot.

## Root cause

A Python module cannot establish trust in its own source after it has started. A
candidate-side verifier has already executed top-level code before any function in
that module can inspect a digest, signature, path, or trust-anchor file. Checking
that an anchor resolves outside the repository also proves only location, not owner
authority: candidate code can create sibling files, junction aliases, and copied
anchors in a writable build environment.

Therefore there is no sound candidate-side bootstrap. Source authentication and
checker execution belong exclusively in Step 3, whose launcher, trust material, and
execution environment must be independently sourced and unavailable to the
candidate builder.

## Design

1. Remove the trust-anchor CLI option and all trust-anchor/source-authentication APIs.
2. Remove every checker import, compile, execution, rendering, and validation path.
3. Strictly decode the raw manifest only to report declared IDs, statuses, evidence
   counts, and authority booleans as untrusted informational labels.
4. Return `trusted_source=false`, `structurally_valid=false`, and
   `release_ready=false` for every candidate-side invocation, including canonical,
   missing, malformed, copied, local, external, junction-backed, and fake-root input.
5. Keep the verdict total: unreadable, duplicate-key, non-finite, non-object, and
   incompatible-checker inputs return a failed verdict instead of raising.
6. Treat an omitted `ultron_remains_sole_action_authority` field as false.
7. Keep the CLI informational: a produced verdict exits zero and cannot be used as
   an enforcing status check.

## Step-3 boundary

Step 3 requires a launcher whose executable code is not loaded from the candidate
tree. It must obtain protected owner-controlled trust material, read candidate files
as data, bind validation to the exact candidate identity and byte snapshot, and only
then execute an authenticated checker snapshot. This package neither implements nor
simulates that authority boundary.

## Files

- `scripts/nerva_trusted_verifier.py`
- `tests/test_nerva_trusted_verifier.py`
- this contract document
- mechanically generated project-status surfaces when the collected test count changes

## Risks and rollback

The intentional compatibility break removes `--trust-anchor`,
`verify_trusted_source`, `render_markdown`, and trusted structural verdicts from
candidate-side Step 2. Callers must not replace them with another repository-native
trust mechanism. Rollback is a revert of this bounded package; it mutates no runtime,
repository setting, workflow, or external authority state.

## Verification

Use hostile regression tests for absent trust-granting APIs, rejected anchor CLI
arguments, local/external anchor artifacts, checker junctions, incompatible checker
code, missing and malformed input, fake roots, and missing sole-Ultron evidence.
Then run the focused and adjacent manifest suites, Ruff, AI workflow policy, status
preflight, and `git diff --check`.
