# Task mediation status integration evidence

- Generated: 2026-10-09 UTC.
- Goal: show current mediation mode and verified recorded event counts in the
  owner HUD without changing task authority or enabling mediation.
- Base: `724969839b4660dc09a37abce4964b13ae928f9f`.
- Initial source checkpoint: `4625a1b9fe33dcd1539989d3a1707ff199fbdea7`.
- Corrected source: `9d32c13e7886fea1e154a78db219417bc19241e5`.
- Branch/worktree: `codex/task-mediation-status-20261009`,
  `/workspace/jarvis-hub-mediation-status`.
- Delivery: local. Draft PR #1247 remains at `da7c8a2` and does not include this unit.

The sync admin-only `GET /autonomy/mediation` uses the initialized queue and its
existing verification method. Valid snapshots expose four named nonnegative
integer counters. Invalid/unavailable evidence has no numeric fallback; raw
events, signatures, receipts and exception details are never projected. The
Autonomy Control section reads this endpoint with admin credentials, separates
mode from evidence validity and hides counts during refresh or failure. No mode
toggle, approval or business mutation was added. Backend/queue authority and B7
acceptance remain outside this display feature. Native display is H18.32.

## Verified results

| Verification | Result |
| --- | --- |
| Focused backend mediation/HTTP regressions | 183/183 pass |
| Initial route/auth/OpenAPI/HUD/lifespan/manual gates | 42/42 pass |
| Panel regressions | 27/27 pass |
| Complete default frontend suite | 1,978/1,978 pass, 223 files; no skipped/todo/failures |
| Native React cases within that frontend suite | 137/137, 17 files; included in 1,978 |
| Production bundle build and app/E2E TypeScript | pass |
| Chromium production-bundle smoke | 2/2 pass at 1280px and390px |
| Final API/component/convention/route integration after repair | 101/101 pass |
| Ruff, whitespace, exact counts, generated project/Hermes gates | pass |

Browser tests exercise hard reload in all three modes, admin transport, invalid
and503 transitions, absent stale numbers and business writes, and viewport bounds.
Screenshots were inspected. Browser API responses are fixtures; the backend HTTP
tests separately use a real signed queue, corrupted signature, and unchanged
SQLite write count/detached head. No live provider/device acceptance is claimed.
Independent gpt-6-sol/high cross-review found no Critical/Important issue and
independently passed the15 new backend cases. A follow-up review approved the
shared-helper repair. The read-only inventory used gpt-6-luna/medium.

## Full backend checkpoint and repair

At source `4625a1b`, the complete backend ran with four workers, file distribution
and90-second per-test timeout through the subreaper:

```bash
/workspace/scratch/backend-copy-venv/bin/python /workspace/scratch/pytest-subreaper.py \
  /workspace/scratch/backend-copy-venv/bin/python -m pytest tests/ \
  -n 4 --dist loadfile --timeout=90 -q --tb=short \
  --junitxml=/workspace/scratch/task-mediation-backend-final.xml
```

Result: **21,091 passed,37 skipped, one failed, zero errors**,21,129 cases,
275.149 seconds. The skip identities match the preceding full run. The previous
H672 binding-inventory failure passes in this run. The sole current failure is
`tests/test_require_component_sweep.py::test_no_router_reinlines_the_component_503_preamble`.
It correctly rejects reimplementing the shared component-availability preamble.

The failure reproduced alone before `9d32c13` replaced that preamble with the
existing `require_component` helper. The route retains its no-store generic503;
the helper additionally follows the repository's falsy-orchestrator refusal.
No assertion/allowlist was weakened, and no frontend asset changed. The full new
API/component-sweep/autonomy/route integration union then passed101/101, zero
skipped/errors,5.023 seconds. The failed node is present and passing in
`/workspace/scratch/task-mediation-helper-final-gates.xml`. The complete backend
was not rerun after this narrow repair; the original failed checkpoint is not
relabeled green.

Other reports: `/workspace/scratch/task-mediation-status-focused.xml`,
`task-mediation-route-gates.xml`, `task-mediation-frontend-full.json`, and
`task-mediation-browser.log` in that same directory.

Inventory is backend21,129, frontend1,978, mobile284, routes555. Mobile Jest was
not rerun for this unit; its implementation is unchanged. Six previously current
H277/H487 collateral pins were reviewed and refreshed; four already-stale pins
remain untouched and all assessment claims/verdicts are preserved. Generated TS
also catches up the already implemented `/v1/capabilities` operation. Next action:
implement the separately tracked native read-only display; other task kinds,
producer migration and program acceptance remain open in DRA-59.
