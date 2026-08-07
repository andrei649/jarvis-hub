# Nerva issue movement v1

This contract documents the repository-side B2.1 control for pull request #849
and implementation issue #846. It is read-only, point-in-time evidence. It does
not grant GitHub-write, runtime, execution, completion, merge, or release
authority, and it does not make mutable GitHub comments continuously current.

## Required movement

The checker derives either one stream movement or one `program_control`
movement from the semantic manifest diff. It classifies against the union of
the exact-base and exact-head registries plus the pinned bootstrap set. Registry
coverage is append-only, sorted, unique, portable, wildcard-free, and cannot be
removed, replaced, or narrowed. A post-bootstrap registry addition must cover a
path added by that same pull request.

The only legacy-empty projection is exact base
`843918848c11bbd3f0099f9504d0e0eaaa56b9d6`. Its candidate must materialize the
canonical v1 gate and bootstrap registry. Issue #839 remains only the prior
repository-manifest `evidence_snapshot.control_issue`; B2.1 adds #846 as the
sole bootstrap `program_control` issue.

While `enforcement_state=required`, issue #847 is a static operational
invariant. The manifest pins `.github/workflows/pr-auto-merge.yml`,
`tests/test_pr_auto_merge_policy.py`, the exact `nerva2/` branch prefix, and the
exact `<!-- NERVA2:MOVEMENT-ATTESTATION:START -->` marker. The policy test must
continue to prove both list-time and immediate-recheck exclusions.

## Create receipts after freezing the head

1. Finish local verification and independent review, then freeze one candidate
   head. Record the exact base SHA, head SHA, and SHA-256 of the canonical
   manifest bytes.
2. Create new append-only owner comments on #757, #778, and the derived
   implementation issue (#846 for this bootstrap). Use the exact receipt marker
   pair and closed-world JSON accepted by `check_nerva_issue_movement.py`.
3. Do not include a comment ID inside a receipt. GitHub assigns it after
   creation. Read each new comment back and record its ID, exact UTF-8 body
   digest, and unchanged `created_at == updated_at` timestamp in the pull
   request attestation role map.
4. Never edit or reuse receipts. Any head, base, manifest, body, timestamp, role,
   or issue change requires entirely new comments and a new attestation.

## Reread and rerun protocol

The live job first GETs the current pull request and validates its repository,
number, open/draft state, base, head, branch, author, and current body. It parses
the attestation only from that current body, then GETs every declared comment
and validates the owner envelope, unedited timestamp, exact body digest, role,
issue, base, head, manifest digest, and immutable false authority fields.

After adding the final attestation, trigger the `edited` pull-request event and
wait for the live movement job plus every required context. Before manual
integration, reverify #847 from the default branch and explicitly rerun CI on
the unchanged head. Wait for the fresh live PR/comment reads, confirm current
main ancestry and zero review threads, and merge only if every exact-head result
remains green. Auto-merge is forbidden for this control.

A green run proves only what that named run observed for that exact head.
`continuous_currentness=false`: a later comment edit or deletion does not
retroactively invalidate an earlier check, so the fresh pre-merge rerun remains
mandatory.

## Forward rollback

Rollback is a two-phase forward safety movement, never a blind full revert.

1. While the gate is still required, a separately reviewed
   `program_control` pull request appends exactly one rollback issue and changes
   only the permitted registry growth, `enforcement_state` from `required` to
   `safety_disabled`, and the closed-world `rollback` record. That record binds
   `rollback_of_issue=846`, the appended rollback issue, a bounded printable
   reason, fresh owner receipts, and exact-head checks. Missing state, an
   ordinary downgrade, an unbound issue/reason/receipt requirement, or a return
   from `safety_disabled` under schema v1 fails closed.
2. Only after `safety_disabled` is accepted on `main` may a second reviewed
   cleanup remove the CI dependency and live checker while preserving the
   disabled historical manifest record. Only then may #847 be reverted
   separately.

The factual E1.2a and E8.1c backlog corrections survive rollback. There is no
runtime, database, provider, HUD, mobile, or production migration.
