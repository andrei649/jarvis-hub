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
fingerprint covering the existing signed source set (`SKILL.md` and `main.py`), and
an approval timestamp. Atomic replacement and the existing store lock provide the
same durability contract as other local JSON stores.

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

1. Discovery classifies bundled versus external provenance as it does today.
2. Signature verification labels keyed HMAC as `signed`; an unkeyed digest remains
   `integrity-only`.
3. For external code, the loader checks keyed signature or the private approval
   record before `exec_module()`.
4. Missing, corrupt, wrong-path, stale-digest, or unreadable approval state fails
   closed: the skill remains visible with `module is None` and `sandboxed=True`.
5. Approval writes the registry first. Only after that succeeds may pending/legacy
   markers be removed and the module loaded. A crash before marker removal remains
   quarantined and is safe to retry.
6. Any change to `SKILL.md` or `main.py` changes the fingerprint and invalidates the
   record before import.

## Security invariants

- A skill tree can contain a matching plain SHA-256 signature and any forged marker;
  neither is sufficient for in-process execution.
- Copying a real approval record to another path or source revision cannot satisfy
  lookup and fingerprint verification.
- Marketplace/package bytes cannot write the private registry through discovery.
- Keyed HMAC-signed external skills keep their documented non-interactive path.
- Bundled skills retain existing advisory behavior; this boundary applies only to
  external provenance.

## Tests

- Red-first hostile user-home and imported-sidecar skills with forged unkeyed
  signatures plus forged in-tree approval markers remain quarantined.
- A copied approval record fails on path mismatch and on one-byte source change.
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
