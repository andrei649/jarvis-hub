# Cryptography 50 remediation — CVE-2026-69247

Status: exact-head remediation evidence for PR #801; final acceptance is recorded in the PR and Nerva program ledgers.

## Trigger and scope

On 2026-08-03 the repository-wide `pip-audit` gate began reporting the accepted `cryptography==49.0.0` lock entry for CVE-2026-69247. Issue #800 owns the isolated remediation. The fixed package is available, so the repository takes the upgrade path rather than adding an audit ignore or relying on an unverified reachability argument.

The package changes only:

- the core and beta source floors to `cryptography>=50.0.0`;
- the corresponding `cryptography==50.0.0` universal hash blocks and source digests in `requirements.lock` and `requirements-beta.lock`;
- the existing SecretStore Fernet compatibility test, without adding a new collected test;
- this evidence and rollback record.

E3.1, E8.0, unrelated dependencies, runtime routing, persistence and action authority are excluded.

## Lock generation boundary

The candidate uses the repository's Python 3.12, universal, hash-generating `uv pip compile` process. Existing accepted package pins are supplied as constraints except for `cryptography`. The generated `cryptography` block is then placed into the accepted lock text while unrelated package blocks remain byte-for-byte unchanged. This prevents a security remediation from silently carrying opportunistic resolver upgrades.

Both lockfiles retain their generated-file headers and receive the SHA-256 digest of their edited source file. `scripts/lock_deps.sh --check` must pass on the final branch. Hash-pinned installation on Ubuntu and Windows remains the authority for artifact compatibility.

## Compatibility surface

Repository code uses cryptography-backed behavior for encrypted secrets, OAuth/token protection, settings encryption, end-to-end synchronization and related security routes. The focused regression executes the real Fernet-backed SecretStore path and asserts that the installed major version is at least 50. The complete Python suite remains required because a major dependency release can affect additional imports or serialization paths not represented by the focused check.

Acceptance requires one exact head with:

- `pip install --require-hashes` succeeding from the regenerated core and beta locks on the repository's Ubuntu and Windows jobs;
- the focused SecretStore compatibility regression and complete Python suite passing;
- Ruff, Security (`pip-audit`, Bandit and gitleaks), CodeQL, smoke and the repository's other required checks passing;
- no unresolved review concern and no temporary generation workflow in the final diff.

## Risk

Version 50 is a major dependency transition. The primary bounded risks are API compatibility, platform-wheel availability, key/token round-trip behavior and accidental lock drift. The package makes no claim that the repository exercised the advisory's affected PKCS#7 operation; the blocking scanner and available fixed release are sufficient reason to remove the vulnerable pin.

## Rollback

Rollback is atomic:

1. restore the two source constraints;
2. restore both matching generated lockfiles;
3. restore the focused compatibility assertion and remove this record.

No data migration or external state mutation is performed. Rolling back also reintroduces the known blocking audit result, so dependent Nerva feature PRs must return to HOLD rather than suppressing the gate.

## Dependency order

After independent integration of #801, rebase #797 and #799 separately onto the accepted security commit and rerun each unchanged feature package. Do not combine their different epics, authority boundaries, tests or rollback paths with this remediation.
