# H464 round 3: open findings (brief for whoever lands it)

**Status at handover (2026-09-28):** the previous session was still fixing these on its local branch.

- **Landed?** Check with
  `git log origin/claude/cto-session-recovery-qinvkg --oneline -i --grep "grade after the task lands"`.
  Whoever lands this puts that phrase in the commit subject.
  If that commit is on the branch, this brief is done. Read its report in the commit body and move on.
- **Otherwise,** build these items red-first, with a closure check and an adversarial hunt after.

**Base:** H464 rounds 1–2 are on the branch; they landed with the handover push.
- `0825ba33`: the shipped Company Mode runtime builds from the real orchestrator. It reads the approved checklist back from
  its `goal.approve` task, and the hub parks a finished plan on its own in-flight tasks.
- `1b7afa8c`: the checklist is bound to the approved goal's fingerprint, pinned at `open_run` (ledger `_v5`).
  - One run per approval.
  - A grading margin.
  - Safe mode builds nothing.
  - Scope-checked rows.
  - Hold versus stop.
  - A read-only report path.

H464 stays **partial**. The owner decisions P31.1–3 are in `docs/OWNER_TASKS.md`.

**Production exposure:**
- Company mode is off unless `JARVIS_COMPANY_MODE` is set (`scheduler_service.py`).
- With it on, production still wires no grader: `_grade` idles with "no grader is wired". That neutralises item 1
  only. Items 2, 4 and 5 apply whenever company mode is on.

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
