# H277 post-refactor bounded mutation plan

Prepared only; no snapshot or test process created. Execution awaits the coordinator code-settled signal. Original round2 verification remains in the parent directory.

Selected: 10 prior mutations (7 moved into AdvisoryJudgements, 3 retained action-adapter checks) plus 4 new shared-capacity mutations = 14. Tests target only H277 action and task judgment files.

The new snapshot must include tracked dirty files plus the explicit new untracked shared runner, task adapter, and task tests listed in plan.json. Keep dependency symlinks, fingerprint source, validate normal pytest baseline, execute one mutation process at a time, restore each file in finally, and hash-check restoration. No unchanged provider, role, parser, prompt, or HUD mutants are selected.

Anchors are preliminary mappings only and must be checked against the settled snapshot before any run. Unmatched or invalid execution is never counted as killed.
