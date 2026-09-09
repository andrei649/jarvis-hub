# Hermes 697 sprint status

Generated 2026-09-09. Goal: establish the owner's new sprint against every one of
the 697 inventory capabilities, with reproducible code-equivalence counts and a
GitHub entry point one click from README. Base/head before implementation:
`efc87a20634d33f2d7950b762d90854812c0a841`. Branch `codex/hermes-697-sprint`;
lease none. Final head and verification will be recorded in the PR.

The eight completed delivery PRs #1061–#1068 are already in main. This PR includes
their consolidated delivery record and the remaining local investigation handoff;
it does not replay their merged changes. Darwin work is recorded as delivered
but contributes zero to the Hermes numerator unless a Hermes row is separately
shown equivalent. The original dated research ledger is preserved.

Design: derive stable row identities from the frozen 697-row inventory. Maintain
an additive evidence-backed assessment, preserve original keep/skip/copy/update
decisions, and generate a root status page plus a browsable full inventory.
Partial work and exclusions never count as completion; no fractional completion
credit or arbitrary weighting. Report both all-697 and accepted-scope denominators,
with inherited 7 September audit evidence distinguished from current review.
Changing a source row or losing a referenced evidence file must invalidate the
generated assessment rather than silently improve the percentage.

Likely paths: `scripts/hermes_status.py`, status data/docs, `HERMES_STATUS.md`,
README/STATUS/BACKLOG/HERMES_ABSORPTION/AI_CONTEXT navigation, focused regression
tests and generated project counts. No runtime behavior, new web routes, hosted
service, security control-plane changes, upstream inventory rewrite or blanket
claim of live-service readiness.

Validation: red/green for denominator/exclusion/partial accounting, exact inventory
coverage and identity, evidence validation, data drift and reproducible Markdown.
Run existing context-query, documentation and status-sync checks. Inspect current
GitHub metadata, publish one PR and wait for automated checks. Rollback: revert
this single tracking/documentation/tooling unit; all prior runtime deliveries stay.

Delivery checkpoint, 2026-09-09: all 697 identities are represented, with 95 current
reviews. The documented baseline is 114 equivalent (6 current, 108 inherited),
365 partial, 111 missing and 107 excluded: 16.4% of all 697, or 19.3% of the accepted
590. These are provisional code-status counts, not 697 freshly audited claims.

Validation: 181 targeted tests passed on Windows/Python 3.12.13, including the 28
new status regressions, context queries, doc references, status synchronization,
channel rendering, loop guardrails, tool profiles, taint propagation and MCP filters.
All-repository Ruff passed. Backend collection is 9,723; unchanged frontend/mobile
counts are reused (1,127/137), not asserted as suites rerun for this tracking PR.
Four existing closed-pipe tests emit Windows reader-thread warnings; all assertions
pass. The installed dependency set also emits a Starlette deprecation warning.

An initial run used the primary checkout's Python 3.11 environment and exposed a
taint propagation failure at asyncio.wait_for. The supported Python 3.12 environment,
built in this isolated worktree from the hash-pinned locks, passes that regression
and the entire 181-test packet. Git's existing head.exe is included only in the test
process PATH for the context-query pipe tests. No production behavior was changed.

Next action: publish the single sprint PR and inspect its reported automated checks.
Final head, GitHub URL and hosted results are recorded in the PR; the next product
slice starts by querying the remaining contracts, not by treating partial rows as done.
