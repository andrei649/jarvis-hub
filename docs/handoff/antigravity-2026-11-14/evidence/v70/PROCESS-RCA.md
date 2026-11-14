# Process termination RCA

2026-11-13 UTC; source `/workspace/jarvis-hub`, HEAD `686fcbf4f25ebfbb416b3a35dff29045163cffbd`. Read-only investigation; no product/security/test assertion edits, permissions changes, service changes or external process kills. Only authorized test fixtures created/killed their own subprocesses during exact-node reproduction.

## Finding

These three full-backend failures are explained by this container's orphan-reaping environment, rather than evidence of a V69 process-termination regression:

- `tests/test_g17_hooks.py::test_a_switch_off_mid_run_kills_the_hooks_process_group`
- `tests/test_g17_hooks.py::test_the_timeout_kills_what_the_hook_started`
- `tests/test_browser_chromium_runtime.py::test_orphan_journal_reaps_only_exact_native_chrome_after_controller_exit`

The full-run hook assertions failed because `os.kill(pid, 0)` succeeded. The full-run browser warning at 13:27:36 says `native tree survived kill` before `reap_entry` returned False.

Direct `/proc` and psutil inspection ties the full-run hook PID files under `/tmp/pytest-of-agent/pytest-535/popen-gw0/` to sleep PIDs **2836630** (switch-off) and **2836784** (timeout). Both were **Z/zombie, PPID 1**, not executing sleeps. PID 1 is **`tail -f /dev/null`**, which does not reap adopted orphan children. Numerous older adopted zombies independently corroborate this environment behavior. No action was taken against those processes.

## Exact-node reproduction

Ran the three nodes once with project `.venv/bin/python`, `JARVIS_TESTING=1`, pytest `-q -s --tb=short --timeout=90`. An in-memory pytest observation plugin inspected fixture PID files; it did not change tests or production modules. This run used pytest temporary root `/tmp/pytest-of-agent/pytest-536`.

New fixture sleeps **2924560** and **2924563** and new orphan **Chromium 2924582** were also **zombie, PPID 1** after completion. All three nodes remained in `.pytest_cache/v/cache/lastfailed`, updated 13:41:32 UTC. The command's final terminal stream was not retained by the tool wrapper, so this audit does not invent a new JUnit receipt or exact terminal summary. The rerun process state and unchanged lastfailed entries support reproduction of the same failures. Original full-run XML remains the authoritative three-failure result.

For both original sleep PIDs, both new sleep PIDs and new Chromium, psutil returned `status='zombie'`, `is_running()=True`, and `wait(timeout=0)` raised `TimeoutExpired`. Chromium `cmdline()` raised `ZombieProcess`. These are dead adopted processes that this unrelated auditor cannot reap with waitpid.

## Source mechanism and regression boundary

`agents/core/hooks/runner.py:410` requests `process_group=True`; cancellation cancels and drains its job. `agents/core/environments/local_transport.py:410` starts a new POSIX session. `_kill` at line 503 sends group SIGKILL and waits for its direct child, then polls group existence to let the system reap descendants. In this host, orphan sleep descendants remain zombies and `kill(pid, 0)` continues to succeed, so the two hook assertions classify them as alive despite group termination.

`agents/core/browser_session.py:464` verifies exact native PID/start/profile ownership before terminating the recorded native tree. It invokes `psutil.wait_procs` then SIGKILL and another wait. An orphan native process adopted by non-reaping PID 1 remains a zombie and stays in the `alive` result, causing the observed conservative `native tree survived kill` refusal. No marker/identity safety check should be removed to make this green.

Byte comparison against `git show HEAD:<path>` confirmed all five relevant files unchanged from HEAD: hook runner, local transport, browser session, G17 tests and browser Chromium runtime tests. This establishes no direct cumulative change in those files. It does not exclude every possible indirect/environment effect; a controlled launcher reproduction is the minimal decisive next check.

## Minimal safe harness

The coordinator's proposed new private outer launcher using Linux `prctl(PR_SET_CHILD_SUBREAPER=36, 1)` is appropriate. Set it only in a newly created dedicated launcher before spawning pytest. The outer process must actively `os.wait()` throughout the pytest lifetime, reaping each terminated adopted descendant promptly. Remember the designated pytest child's PID and exit status separately; return its exact `os.waitstatus_to_exitcode()` result. After the test child exits, drain only this launcher's remaining children with bounded handling. A raw unbounded final wait could hang on an unrelated test bug, so retain an outer timeout.

This changes process supervision for its own newly created test subtree; it cannot adopt existing PID 1 zombies or unrelated service processes. It must never scan/kill global zombies or change PID 1, services, production code, browser identity fences or assertions. No requirement to install tini or alter the shared container.

Rerun exactly the three node IDs above under that launcher, preferably using the coordinator's private owned 0700 TMPDIR/basetemp as well. Retain XML, stdout/stderr, launcher exit status, and optional state observations for fixture PIDs. If green, classify the original three as container reaping failures with a separately documented controlled-harness pass; the original full-run remains red. If any fail, inspect exact rejection and process state rather than asserting that all remaining errors share this cause.

A safe reproducible invocation should have this shape (launcher implementation owned by coordinator):

```
JARVIS_TESTING=1 <private-subreaper-launcher> .venv/bin/python -m pytest \
  tests/test_g17_hooks.py::test_a_switch_off_mid_run_kills_the_hooks_process_group \
  tests/test_g17_hooks.py::test_the_timeout_kills_what_the_hook_started \
  tests/test_browser_chromium_runtime.py::test_orphan_journal_reaps_only_exact_native_chrome_after_controller_exit \
  -q --tb=short --timeout=90 --junitxml=<private-result.xml>
```

This auditor did not execute the proposed harness or rerun any broader suite. No live service or unrelated process cleanup is needed or authorized.
