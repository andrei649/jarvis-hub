# Decision — when the Action Kernel becomes the default rail (H27.3 / H27.7)

> **Status: RATIFIED (owner, 2026-09-01).** This records the promotion criteria the
> `docs/OWNER_TASKS.md` parking-lot item *"When does the Action Kernel become the default rail?"*
> asked for. Both flags stay opt-in until every criterion below is met; the flip itself is one
> agent PR, criteria-gated, with the flags kept as kill-switches.

## The question

The always-on risk-tier policy is the load-bearing gate today. The unifying Action Kernel
(`JARVIS_ACTION_KERNEL`) and the unified Action API (`JARVIS_UNIFIED_ACTION_API`) are
code-complete but opt-in (H27.3 / H27.7, docs-vs-code audit 2026-07-24). ON is not pure
hardening: a kernel GRANT rewrites `autonomy_level` ask→act so reversible actions execute without
inbox cards, and the unified flag arms real lights/playback/desktop side effects
([`docs/FLAGS.md`](../FLAGS.md)), while `docs/nerva2/RISKS.md` SEC-01 (privileged bypass) is
still OPEN. So the question is: which evidence promotes the two flags from opt-in to shipped
defaults?

## Decision: criteria-gated promotion, in one deliberate PR

`JARVIS_ACTION_KERNEL=1` and `JARVIS_UNIFIED_ACTION_API=1` become the shipped defaults — the
flags are kept as kill-switches — in **one agent PR**, only after all three hold:

- **(a) Dogfood window** — four consecutive weeks of opt-in dogfood on the owner box with both
  flags set.
- **(b) Zero kernel-caused defects** — zero kernel-caused false DENYs and zero ungoverned actions
  in `GET /api/metrics/kernel` over that window. `enabled:true` is required for the count to mean
  anything — `agents/core/kernel/metrics.py` warns that `ungoverned==0` proves nothing with the
  kernel off.
- **(c) Soak** — one 72h PASS soak (`scripts/soak_report.py` / `.github/workflows/soak.yml`)
  with both flags on.

**Explicitly not a precondition:** the A8 owner-host proof. The flip does not wait on it.

**Rationale.** Every criterion is measurable with instruments that already exist
(`/api/metrics/kernel` in `agents/core/routers/analytics.py`, the soak grader,
[`docs/METRICS.md`](../METRICS.md)), and the shape matches what the parking-lot item itself
suggested (N weeks of dogfood, zero false-DENYs). Flipping blind would change autonomy behaviour
on every install without evidence.

## Consequence

- `docs/OWNER_TASKS.md` parking-lot item ticked with a pointer here; `BACKLOG.md` owner-decision
  bullet ticked and a criteria-gated dev row ("Kernel default flip PR") added; ledger row
  ACTION-KERNEL-FLIP-CRITERIA → DECIDED.
- No code change in this decision. The flip PR reports the three measurements it rests on; until
  then both flags stay opt-in and `docs/FLAGS.md` stays authoritative on their effects.
