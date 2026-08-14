# SEC-B8 External Skill Approval Root Design

**Status:** Owner-approved for implementation through the 2026-08-14 autonomous Max mandate.

## Goal

Prevent candidate-controlled files inside an external skill directory from granting
in-process Python execution. Preserve two explicit trust paths: a valid keyed HMAC
signature, or an owner approval stored outside the skill tree and bound to the
canonical skill path plus the exact executable source fingerprint.

## Non-goals

- No marketplace, acquisition, sandbox-runner, or general plugin redesign.
- No new route, cloud service, dependency, secret, or automatic approval policy.
- No claim that an unkeyed SHA-256 digest authenticates an author.
- No migration that silently trusts legacy `OWNER_APPROVED_IN_PROCESS` markers.

## Considered approaches

1. **Require keyed signatures for every external skill.** This has the smallest
   loader surface, but removes the shipped owner-review flow when no signing key is
   configured and turns a local approval into signing-key administration.
2. **Private path-and-source approval registry (selected).** Store owner decisions
   under `data_path("security", "skill_approvals.json")`, outside every skill tree.
   This keeps approval local, explicit, inspectable, atomic, and content-bound.
3. **OS credential vault or signed database.** Stronger against a same-user local
   attacker, but unnecessary for the issue's package-controlled-byte threat and too
   heavy for this bounded slice.

## Architecture

`agents/core/skills/approval.py` adds `SkillApprovalStore`, a small `JsonStore`
subclass. Records are schema-versioned and keyed by SHA-256 of the resolved canonical
path. Each record also stores that canonical path, a stable `sha256:` source
fingerprint covering every relevant regular file by relative path, file type, and
bytes, and an approval timestamp. Only non-source lifecycle metadata
(`SKILL.sig`, quarantine/legacy-approval markers, and `EXTERNAL_SOURCE`) is
excluded; bytecode caches and every other artifact remain bound. Atomic replacement is combined with a path-scoped
in-process lock, a Windows/POSIX process lock, and reload-before-merge so concurrent
loader instances cannot lose approvals.
An existing private record also remains durable provenance for its canonical path
after source drift, so deleting an in-tree sidecar cannot reclassify changed
external bytes as bundled.

`agents/core/skills/signing.py` exposes the stable source fingerprint independently
from HMAC configuration. Its purpose is byte binding, not author authentication.
The existing `compute_digest()` uses that same content digest before optionally
applying HMAC, preventing the approval and signing definitions from drifting.

`SkillLoader` receives an injectable approval store and otherwise uses the private
default path. An external module may import only when `signature_reason == "signed"`
or `approval_store.is_approved(path)` is true. The legacy in-tree marker is ignored
for trust. An explicit owner approval records the current path/fingerprint before
removing `PENDING_REVIEW`; an existing legacy marker may make an already-discovered
quarantined generated skill eligible for explicit re-approval, but never grants
execution by itself.

## Data and failure flow

1. Discovery classifies bundled versus external provenance from the discovery
   boundary, link state, in-tree import marker, and any canonical path retained in
   the private approval registry. Fingerprint drift never removes that provenance.
2. Signature verification labels keyed HMAC as `signed`; an unkeyed digest remains
   `integrity-only`.
3. For external code, the loader checks keyed signature or the private approval
   record against one immutable source snapshot. The validated tree is materialized
   in a private temporary directory retained with the module, and its `main.py`
   is loaded from that private copy through the standard import loader; the loader
   never reopens candidate-controlled source or relative artifacts after the trust
   decision.
4. Missing, corrupt, wrong-path, stale-digest, or unreadable approval state fails
   closed: the skill remains visible with `module is None` and `sandboxed=True`.
5. Approval writes the registry first. Only after that succeeds may pending/legacy
   markers be removed and the module loaded. A crash before marker removal remains
   quarantined and is safe to retry.
6. Any change to `SKILL.md` or `main.py` changes the fingerprint and invalidates the
   record before import. Nested modules, manifests, prompts, templates, and assets
   are bound by the same rule.
7. Link- or junction-backed bundled discovery roots/entries are external provenance;
   source-tree links and non-regular artifacts cannot receive or satisfy approval.
8. Each decision reloads the registry. Missing, corrupt, or unknown-schema state
   clears authority rather than retaining a boot-time in-memory approval.
9. Excluded top-level lifecycle metadata is still validated as a single-link
   regular file before fingerprinting. Signature writes use a private temporary
   file plus atomic replacement, so a candidate hardlink/symlink cannot redirect
   an approval-time write outside the skill tree.

## Security invariants

- A skill tree can contain a matching plain SHA-256 signature and any forged marker;
  neither is sufficient for in-process execution.
- Copying a real approval record to another path or source revision cannot satisfy
  lookup and fingerprint verification.
- A junction or symlink cannot make outside bytes inherit bundled provenance.
- Concurrent owner approvals merge under shared and cross-process locks.
- Marketplace/package bytes cannot write the private registry through discovery.
- Keyed HMAC-signed external skills keep their documented non-interactive path.
- Bundled skills retain existing advisory behavior; this boundary applies only to
  external provenance.

## Tests

- Red-first hostile user-home and imported-sidecar skills with forged unkeyed
  signatures plus forged in-tree approval markers remain quarantined.
- A copied approval record fails on path mismatch and on one-byte source change.
- Nested artifact additions, renames, byte changes, and provenance-sidecar changes
  invalidate approval; linked artifacts fail closed.
- Removing an imported/marketplace sidecar after approval leaves the canonical path
  external, while changed bytes remain unapproved and unexecuted.
- A hardlinked `SKILL.sig` is rejected without modifying its other link target.
- Missing/corrupt live registry changes revoke decision-time authority, and stale
  store instances/processes merge independent approvals without loss.
- Deterministic check-to-exec mutations execute the validated module and relative
  artifacts, never swapped on-disk bytes, for both owner-approved and
  keyed-signature trust paths.
- Explicit owner approval activates a generated skill, persists across loader
  restart, and returns to quarantine after source mutation.
- Keyed HMAC-signed external skill and bundled-skill behavior remain unchanged.
- Marketplace content cannot self-approve.
- Run focused signing/quarantine/generated-skill suites, adjacent marketplace skill
  tests, Ruff, AI workflow policy, status preflight, and `git diff --check`.

## Rollback

Revert the loader/store/fingerprint changes. The private registry file is inert data
and may remain for forward recovery; reverting restores the previous marker behavior.
No runtime database or user content migration is required.

## Lifecycle residual

Approval rows and the adjacent `.lock` file are retained when a skill is removed;
this slice adds no prune/revoke route. Retained rows cannot authorize a missing,
relocated, linked, or byte-different tree, but an identical tree recreated at the
same canonical path remains approved. A future lifecycle slice should add explicit
revoke plus uninstall/prune integration if the owner wants removal to erase that
decision rather than preserve it for recovery.
