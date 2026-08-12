# Sparks — the entropy ledger

> Nerva's secondary objective, mandated by `MAX.md` §6: every Max run may ship **one** small,
> bounded delight nobody asked for. This file is the record — part changelog, part cabinet of
> curiosities. If a spark ever stops being charming, delete it in one commit and mark it here.

## The rules (hard)

1. At most one spark per run, **only after** the primary slice is green, ≤1 hour of work.
2. Never on the security/governance surface. Never weakens a gate, a budget, or a default.
3. Default-off (or purely cosmetic) if it touches runtime behavior.
4. Deletable in one commit — a spark that grows roots was never a spark.
5. It must make someone smile. That is the acceptance test, and it is not optional.

## The ledger

| id | date | run | what | where | status |
|----|------|-----|------|-------|--------|
| S-001 | 2026-08-11 | 000 | Max runs draw two-word names at random (amber-quill, feral-lantern…) — entropy as identity: every run is nameable, greppable, and slightly unpredictable | `MAX.md` §6 + branch/PR names | live |
| S-002 | 2026-08-11 | nimble-beacon | `scripts/max_run_name.py` — the entropy ritual made real: draws the two-word name (seedable, `--plain`), each noun carrying one honest wink of a tagline ("beacon — lit so the next run finds its way"). Stdlib only, no side effects but stdout, deletable in one commit. | `scripts/max_run_name.py` | live |
