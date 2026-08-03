# Nerva 2.0 E0.3b2c — blocker-plan closure reconciliation

> **Program:** #757 · **Epic:** #758 · **Blocker plan:** #778.  
> **Accepted-evidence base:** #789 / `0c7f880dea1fe254d590ce8967e45cfe453dc52f`.  
> **Status:** E0 is `DONE` when this exact transition is independently integrated.

## Purpose

Issue #778 remains the long-lived cross-epic blocker and milestone plan. E0 closure updates only its
current-state snapshot and the stale E0-related checklist items; B0–B10, M0–M8, metrics and anti-drift
content remain intact.

## Required blocker-plan posture after integration

- **B0 and B1 are resolved:** the dependency contradiction, baseline/control evidence and durable
  repository/issue ledgers are accepted through #789.
- **M0 is complete:** E0 is `DONE`, all E0 sources agree and the first bounded wave has an explicit
  dependency and authority position.
- **B2 is partial:** E0/first-wave manifests and checkers exist, but the broader whole-program
  manifest, cycle/orphan detection and generated dependency view remain open.
- **B3–B10 remain open:** Continuity Core mapping, universal cognitive-ledger contracts, SDK breadth,
  real actuation, live task-level Ultron mediation, research/calibration, Night Shift prerequisites and
  product proof remain future work.
- **Post-E0 first wave:** #780, #781, #783 and #784 may proceed in separate bounded PRs; #782 still
  waits for #781.
- **Authority remains unchanged:** Ultron / `nerva.action.v1` is the sole privileged-action authority.

## Truth boundaries

- E0 completion is planning/control completion, not runtime or release completion.
- Issue creation, documentation and hermetic checks are not implementation evidence.
- No default-off seam, reference driver or generated status is promoted to live proof.
- Live task-level mediation, real adapters, owner hardware and release evidence remain later gates.
- The builder does not merge, close #758 or edit blockers to appear removed before independent review.

## Repository evidence

- exact E0 DONE blocks in `BACKLOG.md` and `STATUS.md`;
- `E0_COMPLETION.json` with `status=done`, `close_e0=true` and accepted evidence through #789;
- a roadmap manifest with #758 removed from the first wave and #781 retained on #782;
- fail-closed tests for split status/closure, stale blockers and partial ledger transitions;
- normal generated status synchronized through `scripts/status_sync.py`;
- both Nerva integrity checkers and the ledger migrator in permanent CI.

## Verification

```bash
python scripts/status_sync.py --check
python scripts/reconcile_nerva_repository_ledgers.py --check
python scripts/check_nerva_roadmap.py
python scripts/check_nerva_e0_completion.py
pytest -q tests/test_reconcile_nerva_repository_ledgers.py tests/test_nerva_e0_completion.py
```

## Next smallest slice

After independent integration, choose one bounded **E1.0 / E2.0 / E8.0 / E9.0** slice per PR.
#782 still waits for #781. B2 and B3–B10 remain visible in #778 and are not silently absorbed by E0.
