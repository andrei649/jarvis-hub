# HANDOFF — Always-On autonomy runtime operationalization

**Goal:** wire the existing coordinator + heartbeat + night-shift into one supervised,
observable loop that survives restarts, and (parallel workstream) re-verify the LLM
provider cost table against official pricing pages.

**Base SHA:** `dd9c164` (`fix(cost): complete and correct the model price tables (#920)`,
already on `main`) · **Head SHA:** this branch's tip, see `git log -1`.
**Risk tier:** R2 (new ops surface + tests; zero changes to the B7 mediation path —
`queue.py` / `worker.py` / `autonomy_coordinator.py` are untouched).
**Changed paths:** see `git diff --stat main...HEAD`.

## What shipped

### 1. Always-On runtime (coordinator + heartbeat + night-shift, one supervised loop)

The three pieces already existed (`AutonomyCoordinator.loop()` — coordinator + H6.6
night-shift gate; `HeartbeatScheduler` — agent heartbeats) but had no dedicated
supervised entrypoint, no structured log, and no crash-safe state. This PR adds the
operations layer around them, **without touching their internals**:

| File | Purpose |
|---|---|
| `agents/core/autonomy/runtime_coordinator.py` | Headless entrypoint (no HTTP). Boots the same `Orchestrator` as `agents/web.py` (config → `Orchestrator` → `load_agents()`), starts `HeartbeatScheduler` + `AutonomyCoordinator.loop()` exactly as `Orchestrator.start_channels()` does, then runs its own read-only **cycle recorder** on the `system.autonomy_tick` cadence. |
| `agents/core/autonomy/runtime_log.py` | Structured run-log: `append_record`/`read_records`/`summarize_recent` — one JSON line per cycle at `logs/runtime.jsonl` (`$JARVIS_RUNTIME_LOG` to relocate). Corrupt/truncated lines (a `kill -9` mid-write) are skipped, never poison the log. |
| `agents/core/autonomy/runtime_state.py` | Crash-safe state: `boot_id`, `cycle`, `last_status`, `consecutive_clean`, atomic tmp-file + `os.replace` writes, corrupt files quarantined (never block boot) at `$JARVIS_HOME/runtime/state.json`. |
| `scripts/runtime_supervisor.py` | Portable, dependency-free crash-recovery wrapper: spawns the coordinator as a child, restarts on any exit (including `kill -9`) with exponential backoff (2s→60s, reset after 30s of healthy runtime), writes supervisor lifecycle events to the same run-log. The child's own module path contains "coordinator" — `pgrep -f coordinator` finds it directly. |
| `Makefile` | `runtime-up` / `runtime-down` / `runtime-status` / `runtime-logs` / `test`. |
| `deploy/systemd/jarvis-runtime-coordinator.service` | Production systemd-native equivalent (`Restart=always`) for hosts that have systemd; `make runtime-up` is the portable default (dev, CI, containers without an init system). |
| `deploy/systemd/README.md`, `deploy/README.md` | Document the new unit and the "run one or the other, never both against the same `JARVIS_HOME`" rule (two copies would double-drive `AutonomyCoordinator.loop()` against the same `autonomy.db`). |

**Deliberately non-invasive:** `runtime_coordinator.py` never mutates `TaskQueue` /
`AutonomyWorker` / `AutonomyCoordinator` — the recorder only calls existing read-only
APIs (`TaskQueue.stats()`, `HeartbeatScheduler.get_status()`) and computes deltas
locally. Zero lines changed in the B7 mediation path.

**Cost table refresh (parallel subagent):** re-verified all 55 cloud rows in
`agents/core/llm/cost_estimator.py` (Anthropic/Gemini/OpenAI, superset of the 32
requested) against live official pricing pages. Result: 54 exact matches, 1
`RETIRED_UNLISTED` (a documented intentional proxy row, `gemini-3.1-pro`) — **no price
corrections needed**. Bumped `PRICES_VERIFIED` to `2026-08-18`. Full row-by-row
evidence (source URL + retrieval date per row): `docs/research/2026-08-18-llm-pricing-verification.md`.

## Verification — run live, not simulated

```
$ python3 -m pytest -q                              # exit 0, full suite green
$ make runtime-up
runtime supervisor starting — tail logs/runtime.jsonl to watch cycles
$ sleep 240; tail -4 logs/runtime.jsonl
{"phase":"cycle","cycle":1,...,"status":"clean",...}
{"phase":"cycle","cycle":2,...,"status":"clean",...}
{"phase":"cycle","cycle":3,...,"status":"clean",...}
{"phase":"cycle","cycle":4,...,"status":"clean",...}
$ kill -9 <coordinator pid>
$ sleep 90; tail -4 logs/runtime.jsonl
{"phase":"supervisor","event":"child_exit","returncode":-9,"ran_seconds":273.3,...}
{"phase":"supervisor","event":"child_start","child_pid":12624,...}
{"phase":"supervisor","event":"coordinator_boot","boot_id":2,...}
{"phase":"cycle","cycle":5,"boot_id":2,...,"status":"clean",...}   # counter RESUMED, not reset
$ make runtime-down                                  # clean SIGTERM stop, pidfile removed
```

Observed in this session (real run, `JARVIS_TESTING=1`, scratch `JARVIS_HOME`):
- Boot takes ~30-35s in this sandbox (LM Studio/Ollama backend probes time out with
  no local model server running — expected, degrades gracefully, never crashes).
- 4 consecutive `clean` cycles before the kill, 1 more immediately after
  (5 consecutive total straddling the restart) — exceeds the "3 consecutive clean
  cycles" bar.
- `kill -9` → supervisor detected the exit and had a fresh coordinator booted and
  logging again in **~3.5s** (well under the 60s bar). `boot_id` incremented 1→2;
  `cycle` counter resumed at 5, proving `runtime_state.py`'s atomic-write survives
  a hard kill.
- `make runtime-down` → graceful SIGTERM → coordinator exits 0 → supervisor logs
  `supervisor_stop` → pidfile removed. No orphaned processes.

**Timing note for re-running verification:** the default `system.autonomy_tick` is
60s and boot itself takes ~30-35s without a local LLM backend reachable, so getting 3
cycles needs roughly `sleep 220` rather than the `sleep 180` in the original ask —
budget for that, or lower `system.autonomy_tick` in `settings.db` for a faster
verification loop.

```
$ python3 -m ruff check agents/core/autonomy/runtime_log.py agents/core/autonomy/runtime_state.py \
    agents/core/autonomy/runtime_coordinator.py scripts/runtime_supervisor.py \
    tests/test_runtime_log.py tests/test_runtime_state.py tests/test_runtime_coordinator.py \
    tests/test_runtime_supervisor.py
All checks passed!
```

New tests: `tests/test_runtime_log.py`, `tests/test_runtime_state.py`,
`tests/test_runtime_coordinator.py`, `tests/test_runtime_supervisor.py` — 29 tests,
all offline (the supervisor tests spawn real short-lived subprocesses to exercise the
actual crash-restart and SIGTERM paths, not mocks). Full suite: `python3 -m pytest -q`
→ exit 0.

## Known limitations / follow-ups

- **Two deployment shapes, pick one per `JARVIS_HOME`:** `jarvis-hub.service` (dashboard
  + engine in one process, existing) vs. `jarvis-runtime-coordinator.service` /
  `make runtime-up` (headless engine only, new). Running both against the same data
  root double-drives the autonomy tick. Documented in `deploy/systemd/README.md` and
  the module docstring; not technically enforced (no cross-process lock) — a follow-up
  could add one if operators find this footgun in practice.
- **`STATUS.md` / `docs/ARCHITECTURE.md` test-count headers were not re-synced** —
  `scripts/status_sync.py` also cross-checks frontend (Vitest) counts and failed here
  on a missing `npm`/toolchain in this environment (exit 127), unrelated to this
  change. Backend collection is clean: `pytest --collect-only -q -p no:xdist -o
  addopts=` → `6793 tests collected` (pre-existing count already far above the
  `~3,845` last hand-synced in `docs/ARCHITECTURE.md` — that staleness predates this
  PR). Re-run `python scripts/status_sync.py` on a box with the frontend toolchain
  installed to refresh both headers together.
- Heartbeat *last-run* timestamps are not persisted across restarts (out of scope —
  `HeartbeatScheduler`'s APScheduler jobs already reschedule fresh on boot,
  unchanged by this PR); the run-log does capture live scheduler status
  (`scheduler_running`, job count) every cycle.

## Next safe action

Independent review of `runtime_coordinator.py`'s boot sequence against
`agents/web.py`'s `lifespan` (confirm no future drift between the two boot paths),
then merge.

```text
delivery=draft ci=pending(local pytest green) governance=review_required lease=none
next=independent review
```
