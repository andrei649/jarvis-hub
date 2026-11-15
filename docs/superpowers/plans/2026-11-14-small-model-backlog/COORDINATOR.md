# Coordinator: economical execution without hidden design work

The strong model owns architecture, conflicting interfaces and critical review.
Smaller coding models implement ready packets. Model choice is configurable;
this document makes no claims about measured token savings. Use short contexts,
one packet per worker, and no duplicated repository-wide discovery.

## Starting point and publication

Specifications pin `587977b623cf2d1099733d57037e1c056babe1e5`: lot4 production
source plus the lot5 pause ledger. PRs #1365–#1368 are stacked and unmerged.
The new planning branch adds documents/tools only. Do not replay the old V70/V81
patches: #1365 already reconciled them. Preserve the four lot5 backup branches;
two contain explicitly untested WIP. Preparing specs does not resume paused services.

## Dispatch

Run `taskpack.py validate --check-source`, then `taskpack.py next`. A ready
specification is not completed code. Pass `--done` only for reviewer-accepted
packets with actual evidence; pass `--active` for current assignments. The selector
avoids overlapping explicit `owned_files` and unresolved dependencies. It is a
local planning helper, not a distributed lock or an automatic runner. Before
assignment inspect imports/shared interfaces too: disjoint paths can still conflict.

Workers receive WORKER-PROMPT.md, one full packet, their base SHA and ownership.
Keep two independent implementers initially. Increase concurrency only when file
and interface ownership stay clear. Route high-risk/security/identity/data-loss
packets to stronger review; never ask a small worker to approve its own policy.

## When the initial ready queue is exhausted

1. Select an unfinished contract from `catalog/index.json`, prioritizing a
   user-visible incomplete journey and its dependency chain. Use `show Hxxx` to
   read only that contract. Consult DOMAIN-GUIDES.md and any prior spec listed there.
2. Treat `remaining_verbatim` as a recorded claim, not fresh reality. Inspect
   the current caller, code and test before splitting it; some residual descriptions
   predate later additions. If already implemented, record the evidence rather than
   rewriting it. Area-suite failure reopens validation even for recorded equivalent rows.
3. Choose ONE behavior with a testable outcome. Write a packet using
   PACKET-TEMPLATE.md, assign exact symbols/errors and tests, and check the schema.
   A contract spanning several behaviors becomes several dependent packets; no
   worker receives “implement all H277” or a 50 KB backlog paragraph.
4. Classify unsupported platforms/providers separately. For the 36 historical
   exclusions, decide an architecture-compatible contract from the original
   requirement before implementation. Keep all 697 rows; do not delete exclusions
   or invent a smaller denominator to report completion.
5. Cross-reference checkbox and table records before assignment. The 93 open
   records overlap Hermes and each other. Duplicate table ids and the six rows
   in one unclassified table are preserved in coverage.json for explicit resolution.

## Review and integration

For each packet check the actual diff, identity/cancellation/persistence boundaries,
and the named regression through the production caller. Reject unexplained skips,
blanket allowlists and tests that merely copy the implementation. Fix confirmed
root causes; metadata regeneration is appropriate only after the intended code
change is reviewed. Security scanner findings require narrow classification, not
global suppression. A failing integration suite cannot be replaced by adding
unrelated passing subsets.

At each coherent milestone integrate accepted packets in dependency order. Run
focused tests while developing; affected integration suites once per combined lot;
full backend/frontend/mobile/platform suites at meaningful milestones. Record exact
SHA, command, executed result and external gaps. Centralize shared schema/status/
Hermes edits in one integrator; use the canonical generators after actual counts
are known. Do not rerun a giant suite solely for prose changes.

The completion condition is working user journeys and all accepted contract clauses
with appropriate evidence, not an empty implementation queue or a high test count.
Benchmark claims require real version-pinned competitor runs on the same scenarios;
synthetic baselines remain useful tests with correctly limited labels.

Current authority: implement, commit, push and create draft PRs; no merge/deploy,
paid provider activation or paused-service restart without the applicable authority.
The prior platform-blocked update/restart adversarial check remains explicitly
blocked. Do not repackage it as a packet to evade the platform decision.
