# Small-model backlog execution specification

**Goal:** let smaller coding models deliver one clear behavior at a time without
reconstructing the project, making authority decisions, or guessing missing contracts.

**Reviewed source:** `e355da06d7c4a5275401ee2925582c195d270235` (2026-11-14),
PR #1368 with the repaired #1366/#1367 parent stack. The lot5 pause checkpoint is
preserved. The original review reports describe their dated `587977` baseline;
use [the current integration handoff](../../../reviews/2026-11-14-integration-status.md)
for later repairs, exact heads and remaining merge holds.

Six packets are locally implemented and independently reviewed: **SM-002, SM-003,
SM-004, SM-005, SM-006, SM-008**. This is not a claim of full CI, main integration
or live acceptance. SM-001 awaits exact-head executed count confirmation; SM-007
still requires its remaining scanner evidence. Planning files preserve all original
requirements and do not change the Hermes verdicts.

## What is covered

- All **697** Hermes IDs: 187 recorded equivalent, 474 partial, 36 excluded, zero
  recorded missing. **510 contracts are still unfinished**, often containing
  several behaviors; the remaining reviewed-equivalent concerns have separate planning
  flags. None of those flags alters the canonical ledger.
- **39 open checkbox records and 54 open table records** in BACKLOG, retained with
  source locations. These views overlap each other and Hermes; do not add them to
  get a feature total. Five repeated table IDs and one unclassified table with six
  rows are preserved in `catalog/coverage.json` rather than silently dropped.
- Detailed initial packets in `packets/core.json` and `packets/product.json`, with
  exact files/interfaces, dependencies, acceptance cases and verification commands.
- Domain-specific acceptance floors for all 23 areas, a packet template, worker
  prompt and coordinator procedure for expanding the remaining contract clauses.

**Important distinction:** a generated contract card is a faithful specification
input, not a fully designed implementation task. Only packets marked `ready` may
be assigned directly. `needs_design` retains explicit architecture questions;
`external` names acceptance requiring a real environment. `implemented` records
local reviewer acceptance with evidence, excludes that packet from reassignment,
and satisfies its implementation dependencies; remote CI and merge gates remain separate. This prevents smaller
models from silently inventing semantics for a broad or stale backlog sentence.

## Start here

From the repository root, using the project's Python where available:

```sh
python docs/superpowers/plans/2026-11-14-small-model-backlog/taskpack.py stats
python docs/superpowers/plans/2026-11-14-small-model-backlog/taskpack.py validate --check-source
python docs/superpowers/plans/2026-11-14-small-model-backlog/taskpack.py next
python docs/superpowers/plans/2026-11-14-small-model-backlog/taskpack.py show SM-008
```

The planning helper's own offline checks are available with
`python docs/superpowers/plans/2026-11-14-small-model-backlog/verify_taskpack.py -v`.
They validate delegation safeguards, not application behavior.

`show` defaults to 9,000 characters and explicitly numbers parts. Use `--part 2`
when requested; never implement from a truncated packet. It also accepts a Hermes
ID, e.g. `H005`, or a source-qualified BACKLOG ID from `catalog/backlog.json`.
Do not paste the full multi-megabyte catalog into a model context.

After the reviewer accepts work, select the next non-overlapping set:

```sh
python docs/superpowers/plans/2026-11-14-small-model-backlog/taskpack.py next --done SM-008 --active SM-009 --limit 2
```

`next` first validates the catalog, canonical inputs, cited evidence files and
packet-owned/read files against their fingerprints; it refuses selection on
drift. After accepted implementation changes, the coordinator refreshes the
catalog for the reviewed baseline before dispatching the next batch. Unlisted
callers can still change, so the coordinator also checks shared interfaces.
The helper only prints suggestions. It neither runs commands nor creates agents,
records completion, changes verdicts or starts services. Read [COORDINATOR.md](COORDINATOR.md)
for evidence and dependency handling, [WORKER-PROMPT.md](WORKER-PROMPT.md) for the
small worker prompt, [PACKET-TEMPLATE.md](PACKET-TEMPLATE.md) for new packets and
[DOMAIN-GUIDES.md](DOMAIN-GUIDES.md) for the applicable domain contract.

## Ordering and ownership

1. Repair confirmed CI/compatibility and sync-persistence defects. Preserve the
   exact failure reproductions; do not convert an intended new behavior into a
   baseline exception without a documented compatibility decision.
2. Review persistence/conflict and callback/security design boundaries with the
   coordinator. A small worker must not decide between data loss and a green test.
3. Integrate only the reviewed lot5 slices, then extend complete user workflows
   (native controls, honest generator behavior, governed dispatch). Untested WIP
   stays separate until its behavior is specified and verified.
4. Regenerate shared status/schema/ledger evidence once per coherent integrated
   milestone, using actual executed results. Run the appropriate combined checks.
5. Expand the remaining source contracts into bounded ready packets, in dependency
   order. Keep unsupported provider/device acceptance explicitly open.

The selector uses declared file ownership; the coordinator also checks shared
interfaces. Use one writer for central files and generated artifacts. Full suites
run serially at milestones, not once for every worker. The current mandate allows
commits/push/draft PRs but not merge/deploy or reactivating paused services.

## Regeneration and evidence

`build_catalog.py` uses the existing `hermes_status` and `backlog` parsers, so its
environment needs the project's dependencies (including defusedxml). It rewrites
only this package's catalog, never BACKLOG/assessment. Read-only `taskpack.py`
is standard-library-only. Before regenerating for a newer code baseline, update
the explicit BASE in the builder, review source changes and record why the baseline
changed; never present regeneration as a fresh capability review.

See [evidence/REVIEW.md](evidence/REVIEW.md) for package validation and limitations,
and the linked code-review reports for the defects motivating priority packets.
The baseline handover remains [Antigravity START_HERE](../../../handoff/antigravity-2026-11-14/START_HERE.md).
