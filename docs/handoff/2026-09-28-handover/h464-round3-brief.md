# H464 round 3: brief and residuals

**Landed on 2026-09-28** in `b06fbaf0` ("fix(H464): grade after the task lands at any cadence, credit without polling,
visible holds, retried intake") and `a54bb4d5` (records).
- Items 1–7 below are all done, red-first. The new test file failed 29 of 32 cases on the old code.
- 43/43 mutants were killed.
- A closure verifier confirmed each item on the production path: real queue, worker, ledger and scheduler job; 25 of 25
  reverts caught by named tests; 1,728-case cadence grid.
- An adversarial hunter found no MAJOR.
- H464 stays **partial**. The owner decisions P31.1–3 are in `docs/OWNER_TASKS.md`.

The margin rule differs from item 1 as written below: the floor is the next due sweep after a tick, plus 60 s, not
`max(cadence, interval) + 60 s`. That is because a 200 s cadence is next due 400 s after a tick. `due()` also allows
min(1 s, 1 %) of timer slack.

## Residuals after round 3 (known gaps; not yet fixed)

Company mode is off unless `JARVIS_COMPANY_MODE` is set, and production wires no grader. So M1 is latent, and M2 is rare
and bounded.

- **M1 (MINOR, latent): the grading margin cannot absorb one dropped sweep.**
  - The sweep job is registered with APScheduler's defaults: `misfire_grace_time=1`, `max_instances=1`. A fire delayed
    more than 1 s is dropped, and with it a parked run's only grading sweep.
  - Fix: add one cadence of tolerance to the margin, or register the job with `misfire_grace_time` ≥ 60 s and
    `coalesce=True`, and widen `due()`'s slack to match.
- **M2 (MINOR, bounded by the 360 s cap per approval block): one transient queue read error cuts approval-wait credit.**
  - This happens during the reconciler's per-sweep observation of an open wait: the wait source closes at its last
    observation.
  - Fix: treat a read that raised as "no observation" and leave the source open.
- **NITs:**
  - A hold still open when the run stops never gets `hold.end`, so `GET /api/company/runs/{id}` still shows it. The
    brief filters it out.
  - An ask that expired unanswered becomes a failed step and is re-asked up to 3 times. This can't happen yet: company
    asks carry no approval deadline.
  - `docs/UPGRADE.md` and the brief tell the owner to "approve the goal again". The old card can't be re-approved, so
    only a new card works. Reword it.
  - B1 stop codes (`invalid_max_steps`, `invalid_payload`) still read as jargon in the brief. Add them to the
    plain-words map.
- **Test gaps (surviving mutants):**
  - `settle_spent` must re-check the budget: a failed budget read must not stop a healthy run.
  - With 3 rows and a middle row retried, row 3 must still be queued.
  - A second failed steps read must hold, not `tick_failed`.
  - The hold dedupe must update a changed reason.
- **Pre-existing, not counted:** a row kind longer than 64 characters is stored truncated, so it never matches its own
  step and is asked again every sweep.

The original round-3 brief follows, for reference.

## Items

1. **The hub park's grading margin (MAJOR, latent).**
   - **Problem:** `run_barriers.py` sets the margin to `max(floor, 10 % × max_seconds)`. With the default 8 h budget that is
     48 min, so a run is graded before its task finishes whenever less than 48 min is left.
   - **Second problem:** the floor ignores the run's per-run interval (`ScheduleConfig`, 300 s, enforced by `due()`). At an
     `autonomy.company_tick_seconds` cadence under 300 s, a parked run can be skipped as `not_due` until its budget is
     spent, and it is never graded.
   - **Fix:** margin = `max(sweep cadence, per-run interval) + 60 s`, clamped to ≥ 60 s, with no percentage.
   - **Tests** must drive the real `due()` gate, without clearing `scheduler._last`, at cadences 60/120/300/1200 s.
     Two cases:
     - with enough time left, the run is graded after its task lands, never before;
     - with less time left than the margin, it is graded now.
   - **Docs:** update `docs/FLAGS.md` and the H464 ledger text to state the exact rule, including the deadline-bound case.
2. **A re-mint error escapes the tick (MINOR).**
   - **Problem:** `company_runtime._read_back` catches only `GoalContractError`. An approval task edited so that
     `Budget(...)` validation raises `WorkRunError` (e.g. `max_steps=0`) makes every sweep `tick_failed`. The run then stays
     `planning` forever.
   - **Fix:** any exception while re-minting the goal counts as "provably not bound": stop the run with the reason. A
     transient read failure stays a hold.
3. **Approval-wait credit depends on HUD polling (MINOR).**
   - **Problem:** the report routes are now read-only. As a result, nothing on the tick or decision path observes a blocked
     run's open approval wait, so the credit differs with and without HUD polling.
   - **Fix:** record the wait start and end durably when a run blocks and resumes (reconciler or `PendingRequests`
     decision path), and keep GETs read-only.
   - **Test:** the credit is identical with and without polling.
4. **Holds are invisible (MINOR).**
   - **Problem:** a run held because its approval task can't be read leaves no run event and no brief line. It is never
     settled when its budget is spent. No existing sweep path settles a spent run: the sweep skips `budget_spent` before
     ticking, and settling happens only inside `tick`. So this needs a new, small settle step.
   - **Fix:** write one deduplicated durable event when a hold starts, show the hold and its reason in the brief and
     report, and settle a spent held run like any spent run.
5. **Checklist row accounting (MINOR, older than H464b).**
   - **Problem 1:** a transient intake failure records a failed step, and `_done_fingerprints` counts it as done, so the
     row is skipped for good.
     - **Fix:** retry a failed row on a later sweep, bounded (N attempts, then stop with a named reason).
   - **Problem 2:** a transient failure reading the ledger's steps re-queues row 1, so the owner gets a duplicate ask.
     - **Fix:** hold the tick instead.
6. **Test gap:**
   - The v4→v5 "not tampered" assertion already exists.
   - The idempotent-return path of `open_run` must end its transaction: assert the next ledger write succeeds with no
     retry.
7. **NITs:**
   - a dotted scope kind (`file.write`) must admit `file.write.append`: a kind is in scope when it equals the scope kind or
     starts with `scope_kind + "."`;
   - the stop reason for a refused approved row should say "approved row refused by scope", not "not bound";
   - add a plain-language upgrade note that in-flight company runs from before `_v5` stop once, with a readable reason;
   - document that rolling the code back reads v5 runs as tampered (restore-from-backup is the supported rollback).

**Checks.** Run these with python3.12:
- `tests/test_h464*.py`, `tests/test_company_*.py`, `test_schedule_runtime`, `test_work_run*`, `test_work_judge`,
  `test_work_verifier`, `test_goal_contract`, `test_pending_requests`, `test_h487_human_wait*`;
- `test_nerva_cli -k company`, `test_orchestrator_bindings` (line-keyed; update moved lines after checking it is the same
  statement), `test_hermes_sprint_status`, and the H275/H490 safe-mode tests;
- 25 or more mutants;
- ruff, and bandit (python3.11 with the baseline).

**Records.**
- H464 stays partial: update its summary/remaining with content-verified citations.
- Restamp any row your change drifts.
- Run `hermes_status write` then `check`, and `python3.12 scripts/status_sync.py --reuse-js-counts` then
  `--check --reuse-test-counts`.
- Update the BACKLOG bullet for H464 rounds 1–3 via `scripts/backlog.py sections`, and the build-queue H464 text.
