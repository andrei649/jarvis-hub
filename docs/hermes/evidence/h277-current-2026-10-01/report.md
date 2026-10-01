# H277 shared-runner verification on current main

Generated 2026-10-01. Goal: revalidate the shared approval-judge scheduling,
revocation and capacity guarantees after the original handover was integrated.
This report does not close H277 or the full Hermes objective.

## Snapshot and result

- Source commit: `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`.
- Source fingerprint: `f87d23fba5410bff8231c682ed6fdce1ad9f23dc6a97b1425a06c71d5a0a6e8c`.
- Baseline: **203 passed**, with the normal socket and timeout guards.
- Mutations: **14 killed, 0 survived, 0 invalid**.
- Restoration: **3,982 copied file hashes verified**, no deleted paths.
- Python: isolated Python 3.12 environment, recorded in each command log.

The source came from `git archive` of the exact commit, with no working-tree
overlay. Concurrent permission/video work is outside this snapshot. Each mutation
was applied serially only in the disposable source tree and restored in `finally`.
The plan hash was checked before execution. Syntax, import, setup and unmatched
anchor failures do not count as kills.

The original capacity-release-on-decision anchor now occurs in both the decision
and expiry blocks with different indentation. The initial check correctly rejected
that mutation before any execution. The adapted anchor includes the decision's
following event branch and matches exactly once. The preserved
[initial checks](initial_anchor_checks.json), [validated checks](anchor_checks.json)
and [plan](plan.json) show this mapping; no production source was changed to make
the mutant apply.

Exact commands and outcomes are in [results.json](results.json) and its per-case
logs. [source_manifest.json](source_manifest.json) and
[restoration.json](restoration.json) retain the full fingerprint evidence.
The historical September 27 campaigns remain unchanged.
Saved logs normalize trailing whitespace only; each result also records the
original command/output log's SHA-256 before that normalization.

## Current handover assessment

A separate read-only audit ran the four focused H277 role, role-route, action-judge
and task-judge suites successfully: **310 tests**. The task-judge cases exercise
ToolRPC through a persisted blocked card and enforce-mode kernel QUEUE with the
signed receipt and execution fingerprint unchanged. The original handover's claim
that those paths have no judge is historical. Specialized custom intake paths
still require their own evidence; this is not universal approval-path coverage.

Video remains a declared role without a consumer at this snapshot. Pinned Hermes
uses `video_analyze` for understanding video, distinct from H516 generation.
Provider/authentication/fallback breadth remains unfinished. Native mobile opinion
and settings surfaces remain broader project follow-ups, rather than an extra
requirement invented for the original H277 inventory row.

## Reproduction and continuation

The runner refuses to overwrite an existing prepared snapshot. For a new campaign,
copy the runner and plan to a new evidence directory, deliberately choose its source
commit, and revalidate every mutation anchor before running. Invoke the runner with
the intended Python environment, first `prepare`, then `run`.

Next action: implement and verify the real video-analysis consumer, then continue
the provider/fallback contract. If shared judge source changes, these results stay
bound to the source above and must not be silently relabeled as current.
