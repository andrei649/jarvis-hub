# Remaining Nerva backlog implementation plans

> **For agentic workers:** use the task-by-task execution method permitted by the
> current owner mandate. If the superpowers execution skills are available, use
> subagent-driven-development or executing-plans as appropriate. This index does
> not start workers; assign only a reviewed `ready` packet from the linked queue.

**Goal:** finish the existing product with smaller implementation models supplied
with bounded interfaces and acceptance tests, retaining strong review for design
and security decisions.

**Architecture:** canonical backlog/assessment remain the source of truth. A
reproducible coverage catalog maps every contract and open backlog record to its
source. Hand-authored ready packets supply the implementation decisions; a
read-only selector schedules disjoint dependency-satisfied packets.

**Tech Stack:** existing Python/FastAPI, React/TypeScript, React Native and platform
adapters. Planning query helper uses Python standard library. No new runtime deps.

**Spec:** [execution specification](2026-11-14-small-model-backlog/README.md),
[core plan](2026-11-14-small-model-backlog/core-plan.md),
[product plan](2026-11-14-small-model-backlog/product-plan.md).

## Global constraints

- Frozen inventory: 697 Hermes contracts; no reduced denominator or false closure.
- Source baseline: 587977b623cf2d1099733d57037e1c056babe1e5; inspect drift before execution.
- Preserve identity, consent, strict-local policy, data and existing work.
- Exact-SHA test evidence; no passing claims for unrun or skipped live acceptance.
- Commit/push/draft PR allowed; merge/deploy and paused-service reactivation excluded.

## Review focus

1. Default constructor/restored state must match the path used by the application,
   not only a test injecting explicit paths (SM-008).
2. Repeated/stale sync and partial failure must not overwrite newer owner data;
   design transaction/revision semantics before implementation (SM-010/011).
3. Optional dependency and callback behavior must remain compatible with existing
   CLI/turn consumers (SM-002/003).
4. Native screens must discard late responses when owner/server/session changes
   and must not retry ambiguous mutations (SM-019/023–026).
5. Product and benchmark labels must match executed behavior and real measurement,
   including manual failover and procedural image generation (SM-013–015/020).

## Execution

- [ ] Validate coverage and current source; choose a dependency-satisfied packet.
- [ ] Assign its exact owned files and prompt to a small worker.
- [ ] Review the regression, change and evidence; integrate the coherent unit.
- [ ] Update shared metadata only from actual combined results.
- [ ] Expand the next residual clause with the same acceptance discipline.

Detailed steps and expected results live in each packet; do not duplicate or
reinterpret them from this index.
