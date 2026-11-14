# Independent V70 remediation review

2026-11-13 UTC. Read-only review of current `/workspace/jarvis-hub`, V69 source manifest, remediation XML/exit receipt, private test launcher and generated documentation. This reviewer wrote only this report; no production/security/Windows/Git changes, permission operations, or expensive tests were performed. The fresh four-worker full rerun is underway according to the coordinator; this report does not assert its result.

## Review outcome

No blocker found in the limited remediation. The observed changes preserve V69 code, select a test environment satisfying the existing filesystem guards, give the test process a private descendant reaper, and refresh the stale generated API chapter. The focused evidence is successful and covers every original failed/error case. This is local remediation signoff within that scope, not a publication/merge/deployment decision or a full-suite green claim.

## Independently checked evidence

- Parsed `/tmp/nerva-v70-remediation.xml`: 501 testcase nodes; 466 passed, 35 skipped, zero failures and zero errors. Suite time 45.337 seconds. These totals match `REMEDIATION-EXIT.json`'s exit code 0 and its 20 selected test modules.
- Matched each of the original 353 failed/error node IDs from `FULL-BACKEND-SUMMARY.json` against the remediation XML by module/classname and complete parametrized case name. All 353 are present and passed; none is absent, skipped, failed or errored. Thus the 35 skipped cases do not conceal one of the originally failing cases.
- Fresh SHA256 verification of all 438 V69 `source-manifest.json` entries gives no mismatch, including expected deleted paths. `git status --porcelain=v1 -uall` enumerates exactly 439 dirty paths; the sole path outside the V69 manifest is `docs/test-manual/14-api-surface-sweep.md`. No V69 path disappeared from the status set. `-uall` is necessary to avoid collapsing a new test file into its parent directory.
- This proves no additional source-content change to the cumulative security/kernel/runtime work in V69. Those existing cumulative changes remain present and require their original review; they were not reverted or newly modified to get the focused tests green. No additional tracked executable-mode change was observed; raw diff mode-zero entries are the same eight already-manifested deleted generated chunks.
- `/`, `/tmp`, `/workspace`, `/workspace/scratch` and the integration directory retain the UID/GID/modes previously observed in `PROVIDER-ENV-RCA.md`: `/tmp` remains UID65534 mode01777; integration remains UID1000 mode0700. The unsafe temp ancestor was not repaired by modifying its ownership or permissions. This snapshot plus unchanged source supports the claimed environmental relocation. It is not a historical audit of every filesystem permission or every transient file.

## Test launcher assessment

Reviewed `/workspace/scratch/nerva-v70-integration/run-reaped.py`. It calls `prctl(PR_SET_CHILD_SUBREAPER,1)` on its own launcher process, forks/execs the requested test command, waits for its child/adopted descendants and performs a bounded two-second nonblocking drain. It has no `kill`, signal-sending, chmod/chown or guard-patching operation. It returns the direct child's actual exit code.

`REMEDIATION-EXIT.json` records `TMPDIR=/workspace/scratch/nerva-v70-integration` and `--basetemp=…/pytest-smoke`. Both remove the rejected `/tmp` ancestor from test-owned provider roots. The private launcher supplies a parent that reaps exited orphan descendants, rather than changing process-group termination behavior in production. Recovery of the G17/native-Chrome cases under this launcher is valid evidence for those test conditions; it does not establish that all deployment hosts have equivalent init/reaping behavior. No launcher was executed by this reviewer.

## Generated chapter correctness

The sole new repository diff is `docs/test-manual/14-api-surface-sweep.md`, +44/-42 lines. The generator `scripts/gen_api_sweep.py` and source snapshots are unchanged from V69. This reviewer ran `.venv/bin/python scripts/gen_api_sweep.py --check`: exit 0, chapter is current. `git diff --check -- docs/test-manual/14-api-surface-sweep.md` also exited 0.

Source/diff inspection shows two previously omitted owner routes, `GET /sessions/page` and `GET /sessions/{session_id}/transcript`, both listed as `admin`. This agrees with their router decorators and V69 route/auth snapshots. App-route headline becomes 876, snapshot union including FastAPI doc routes becomes 880, admin tier becomes 422, sessions group becomes 17 routes, and following generated row IDs shift consistently.

Independent enumeration found exactly 880 numeric API rows and verified that every route in the union of `route_surface.json` and `route_auth.json` appears exactly once. The snapshots contain 876 app routes; their union has 880 routes. This documents existing endpoints; it changes no endpoint or access guard. Documentation SHA256 at review: `0105cca4a257130867c8c1f1ea4a1b70b5f3c716d7b83fa06dc2062cfbab4ecc`.

## Signoff limits and next evidence

The original full run remains an honest failed result (36,678 cases; 353 failures/errors), followed by a successful focused 501-case remediation rerun. Preserve both receipts. Await the fresh full-run XML/exit code before reporting a full backend result. A focused rerun, even one covering every original failure, does not test all cross-module/order/concurrency interactions of the entire suite.

This review adds no Windows checkout evidence, browser/device/live-provider coverage, remote integration approval or conflict-resolution claim. No operation was denied or has an uncertain execution outcome. No further code/security/permission change is indicated by this review; the only pending item is the independent full-rerun result and any failures it may reveal.
