# B2 trusted-verifier post-merge repair

## Goal

Make the non-enforcing Step-2 verifier fail closed until an independently supplied
trust anchor authenticates the exact verifier and checker bytes. Candidate repository
content must not be able to manufacture `trusted_source=yes` or execute the checker
before that authentication succeeds.

## Non-goals

- No GitHub workflow, ruleset, status-check, issue, or runtime mutation.
- No Step-3 control-plane binding or Step-4 activation.
- No change to Ultron authority, Nerva delivery state, or release readiness.

## Design

1. Replace candidate-owned hash literals with a strict JSON trust-anchor contract.
2. Accept anchors only from a canonical path outside the repository root.
3. Read verifier and checker bytes as data, compare normalized SHA-256 digests, and
   retain the accepted checker snapshot.
4. Compile and execute only that accepted checker snapshot. Do not import the
   candidate checker at module import time.
5. Default `trusted_source` to false. Root discovery, manifest/registry load, missing
   anchor, malformed anchor, digest mismatch, and checker-load failure remain false.
6. Treat an omitted `ultron_remains_sole_action_authority` field as false.

The outside-repository path prevents the candidate tree from carrying its own pins;
it does not by itself prove who provisioned the file. Step 2 verifies the content
binding and remains non-enforcing. Step 3 must source and protect that anchor under a
credential/control plane unavailable to the candidate builder.

## Files

- `scripts/nerva_trusted_verifier.py`
- `tests/test_nerva_trusted_verifier.py`
- this contract document

## Risks and rollback

The intentional compatibility change is that invocations without `--trust-anchor`
can no longer report structural trust. The CLI remains informational and returns zero.
Rollback is deletion of this bounded package; no repository or product state is
mutated by the verifier.

## Verification

Start with hostile red tests for candidate-local/missing/malformed anchors,
checker-import-before-trust, digest mismatch, missing sole-Ultron evidence, and early
root/load failures. Then run the focused verifier suite, adjacent manifest suite, Ruff,
AI workflow policy, status preflight, and `git diff --check`.
