# HANDOFF — runtime supervisor + LLM pricing verification

> Big-session mission: single supervisor entrypoint wiring coordinator/heartbeat/
> night-shift, crash/restart recovery with persisted state, a structured run-log,
> and a parallel LLM pricing-table refresh. 2026-08-18.

## DONE

- **M1 — Structured run-log.** `agents/core/observability/runtime_log.py`
  (`RuntimeRunLog`): one bounded JSON line per cycle, append-only, plus a
  small state file that persists the cycle counter across restarts (atomic
  tmp+replace, matching the repo's existing private-store save pattern).
  `tests/test_runtime_log.py` (7 cases).
- **M2 — Wire it into the real coordinator loop.** `AutonomyCoordinator.loop()`
  (`agents/core/autonomy_coordinator.py`) gained `_record_cycle()`, called once
  on the success path and once from the existing outer `except`. It's a
  `getattr`-optional hook — no `runtime_log` wired is a true, byte-identical
  no-op, and a logging failure never turns a successful tick into a reported
  failure. `tests/test_runtime_log_wiring.py` (4 cases) + full adjacent
  coordinator/heartbeat sweep re-run green (no regression).
- **M3 — Headless coordinator process.** `scripts/coordinator.py` boots the
  real `Orchestrator` (no HTTP layer) and calls the existing
  `start_channels()`/`stop_channels()` — the same real heartbeat scheduler +
  autonomy-coordinator loop + night-shift gate the interactive app already
  uses, just as its own OS process. `JARVIS_RUNTIME_FAKE_LLM=1` swaps in a
  deterministic fake backend (same pattern as `scripts/install_smoke.py`) for
  dev/CI use without a live LM Studio/Ollama; without the flag it boots
  exactly like `serve.py` does. `tests/test_runtime_coordinator_boot.py`
  (2 cases, boot path only — a full tick needs ≥15s wall clock, see manual
  verification below).
- **M4 — The single supervisor entrypoint.** `scripts/runtime_supervisor.py`
  spawns the coordinator and respawns it on any exit, including `SIGKILL` (a
  process cannot recover itself from `kill -9` — that's the parent's job),
  logging `spawned`/`child_exited`/`respawned`/`stopped` events into the same
  run-log. `deploy/systemd/jarvis-runtime.service` and a new
  `runtime-coordinator` docker-compose service both run it, with the OS-level
  `Restart=`/`restart:` as a second, defense-in-depth layer on top of the
  in-process respawn. `Makefile` adds `runtime-up`/`runtime-down`/`runtime-status`
  for local use. `tests/test_runtime_supervisor.py` (2 cases) — one of them
  sends a real `SIGKILL` to a real child subprocess and asserts a respawn with
  a new pid; not mocked.
- **M5 — LLM pricing table refresh (parallel subagent).** Re-verified all 55
  vendor-priced rows in `agents/core/llm/cost_estimator.py::MODELS` live
  against Anthropic/Google/OpenAI's own pricing pages. **No pricing values
  needed correction** — every row already matched. `PRICES_VERIFIED` bumped
  2026-08-17 → 2026-08-18; full row-by-row evidence with source URLs and
  retrieval dates in `docs/research/2026-08-18-llm-pricing-verification.md`.
  `tests/test_cost_tracker.py` (drift guard) re-run green.
- BACKLOG.md: H23.29 added (Version Roadmap 0.16 — HUD depth + observability
  tail). `scripts/status_sync.py --reuse-js-counts` run, regenerating
  README/STATUS/GO_LIVE_PLAN/NERVA badges and `project-status.json`
  (backend test count 6764 → 6779, +15 matching the new suites).

## Manual end-to-end verification (this session, in-sandbox)

No LM Studio/Ollama or outbound network in this environment, so the coordinator's
observer/plugin passes hit circuit-breaker timeouts rather than completing fast —
real deployments with network access will cycle much faster than the ~60-90s/cycle
seen here. Ran with `JARVIS_RUNTIME_FAKE_LLM=1`, `JARVIS_RUNTIME_CYCLE_SECONDS=15`:

1. `make runtime-up` → coordinator + supervisor boot, real Orchestrator with 17
   agents loaded, heartbeat scheduler + autonomy loop + scheduler all start.
2. **3 consecutive clean cycles** landed in `logs/runtime.jsonl`, all `ok: true`.
3. `kill -9` on the coordinator pid (found via
   `pgrep -f 'python3 .*scripts/coordinator\.py'`, not the bare substring
   `coordinator` — that also matches this sandbox's own shell wrapper text) →
   **recovered in ~1s** (new pid spawned), well under the 60s bar.
4. **State intact across the crash**: `runtime_state.json` showed `cycle: 1`
   immediately after the kill (the last cycle completed before the crash); the
   recovered process's next cycle wrote `cycle: 2`, not a reset to 0/1 —
   continuity proven, not assumed.

## Guardrails respected

No changes to kill-switch logic, earned-autonomy config/policy, permission
scopes, secrets, or CI security jobs. The coordinator's `_record_cycle()` hook
only appends an observability line after each tick already ran — it does not
change what `tick()`, `observer.observe()`, or the night-window gate decide.
No PR #918 files touched (checked `agents/core/autonomy_coordinator.py`'s
diff is additive-only around the existing tick call; no dispatch-authority
logic changed).

## Next 3 actions

1. Open the PR (draft), paste this evidence + test output, request review.
2. Owner: once network access is available, re-run the manual verification
   without `JARVIS_RUNTIME_FAKE_LLM` to confirm real-LLM boot + faster cycle
   timing in production conditions.
3. Consider adding `cached` pricing to `MODELS`' schema — the verification
   doc has all 55 cache rates ready to drop in if the team wants that column.

## Exact commands to verify

```bash
python3 -m pytest tests/test_runtime_log.py tests/test_runtime_log_wiring.py \
  tests/test_runtime_coordinator_boot.py tests/test_runtime_supervisor.py \
  tests/test_autonomy_coordinator_pending_drain.py tests/test_coordinator_profile_concurrency.py \
  tests/test_heartbeat_actions.py tests/test_cost_tracker.py -q

make runtime-up
# wait ~60-90s per cycle in an offline sandbox (near-instant with real network)
tail -3 logs/runtime.jsonl
kill -9 $(pgrep -f 'python3 .*scripts/coordinator\.py')
sleep 5 && tail -1 logs/runtime.jsonl   # a new pid in a "respawned" event
make runtime-down
```
