# Night Shift E5.0 — the work-run chain (ledger, verifier, judge, supervisor)

Epic: #763 · Program: #757 · Contract: `nerva.work-run.v1`

## Delivery status

**Delivered, not program-accepted.** The four modules and their tests are in the
tree and green; `nerva.work-run.v1` moves `proposed → candidate` on that basis.
Every E5 delivery gate and the B7 program gate stay open: acceptance is the
owner's/integrator's, never this slice's and never the program manifest's.

A first attempt at this row was written on 2026-09-06 *ahead of* the code — the
registry claimed `candidate` while naming four files that did not exist. That
claim was withdrawn the same day and is recorded in the manifest's reconciliation
log rather than deleted. This document describes the state after the modules
actually shipped.

## What a work run is

Nerva already runs *tasks*: one approved thing, done once. A **work run** is the
unit above that — one owner-approved goal, worked continuously across many turns,
sessions and reboots, with every step and every claim written down.

That is the capability the owner asked for ("work like a company would, but
24/7"), and it is also the capability with the largest blast radius in the
product. The chain is therefore split into four components that can each only do
one thing, so no single one of them can decide that work happened.

```
GoalSpec (owner-approved)
   │
   ▼
WorkRunLedger ── durable: runs, steps, budgets, verdicts
   ▲       ▲
   │       └── CompanySupervisor ── sequences; every effect leaves via the
   │                                 governed intake (queue + Action Kernel)
   │
   ├── WorkVerifier ── does the evidence hold?   (probes, never assertions)
   └── WorkJudge    ── was this the goal?        (fail-closed, last gate)
```

## Authority

`nerva.work-run.v1` is `delegated_execution_only`, and each module is built so
that is structurally true rather than a promise:

- **The ledger cannot start work.** `open_run` refuses a goal whose `approved_by`
  ref is unset — there is no provisional mode.
- **The supervisor cannot authorise work.** It hands every action to the injected
  governed intake and records the durable task id that came back. It never
  inspects the task payload; interpreting it would make it an authoriser.
- **A step that changed something with no task id is reported as unauthorised**,
  and both graders fail the run on it. Work Nerva was not authorised to do cannot
  be laundered into a passing result.
- **Nothing in the chain can mark a run succeeded.** Only `WorkJudge` settles a
  run, only after `WorkVerifier` passed, and the ledger refuses a judge pass with
  no verifier verdict behind it.

## Included artifacts

- `agents/core/autonomy/work_runs.py` — the durable ledger
  - strict run status transition table; terminal states have no outgoing edge;
  - hard budgets (steps, wall-clock, deadline, owner interrupts) that stop the
    run rather than overrun, with the first spent limit named honestly;
  - the interrupt budget *blocks* rather than ends a run: attention is the
    owner's, so running out means stop asking, not abandon the work;
  - one open run per goal, so a goal's budget cannot be double-spent;
  - `request_stop` is a one-way door; a stopping run accepts no further step;
  - canonical-JSON SHA-256 fingerprint per run, so a hand-edited row is
    detectable on read;
  - `snapshot()` names `unauthorised_steps` explicitly.
- `agents/core/autonomy/work_verifier.py` — does the evidence hold?
  - a check with no probe is `unverifiable`, never `passed`;
  - a probe that raises is a failure, not a skip;
  - a probe that answers anything but `True`/`False` establishes nothing;
  - the run's own steps are never evidence for its own checks;
  - `record=False` lets the supervisor look ahead without spending the run's one
    verifier verdict.
- `agents/core/autonomy/work_judge.py` — was this the goal?
  - rules applied worst-news-first, so the owner reads the most basic failure;
  - scope is a hard boundary: useful adjacent work still fails the run;
  - a fired stop condition is decisive even if the run finished first;
  - an optional rubric (an LLM grader) can only ever **withhold** a pass — a
    model saying "looks good" can never turn a failing run into a passing one,
    and a broken grader can never fail a run that satisfied every rule.
- `agents/core/autonomy/company_supervisor.py` — the loop
  - default-off twice over (`JARVIS_COMPANY_MODE` at the call site,
    `SupervisorConfig.enabled` at every tick);
  - one tick, one step — otherwise the budget is decorative;
  - stop is read before planning, so it always wins the race;
  - a refusal is a recorded step that spends budget, never a silent retry;
  - the same failure `max_consecutive_failures` times in a row ends the run;
  - with no graders wired it reports that honestly instead of declaring success.

## Tests

- `tests/test_work_run_ledger.py` — 28 cases
- `tests/test_work_verifier.py` — 14 cases
- `tests/test_work_judge.py` — 17 cases
- `tests/test_company_supervisor.py` — 21 cases
- `tests/test_company_planner.py` — 23 cases
- `tests/test_company_report.py` — 19 cases
- `tests/test_company_routes.py` — 16 cases
- `frontend/src/panels/company-room.test.tsx` — 9 cases

All hermetic: in-memory SQLite, injected clocks, hand-written planners and
probes. No test sleeps, opens a socket, or touches the data root.

## Runtime posture

Default-off. `JARVIS_COMPANY_MODE` is unset, so the runtime constructs no
supervisor and no run is ever opened; the modules are reachable only from tests
and from a future opt-in. Turning the flag on still changes nothing about who may
authorise an effect: the queue and the Action Kernel are unchanged, and a company
run's actions land in the same decision inbox as everything else.

## The reachable half

Landed in the same PR, after the four components above:

- `agents/core/autonomy/company_planner.py` — the only place a model proposes, and
  therefore where the clamps are. Scope is enforced at **proposal** time so a run
  never spends a step on work the judge would reject; a repeat of work already
  taken is refused (the fingerprint normalises casing and whitespace, so it cannot
  be dodged); a proposer that crashes, times out or answers junk proposes
  *nothing*, which the supervisor reads as "out of ideas" and grades on; and with
  no step budget left it stops proposing rather than feeding the ledger refusals.
  `ChecklistPlanner` derives its position from the ledger, so a restart resumes
  instead of replaying the list. A hand-written checklist is clamped exactly like
  a model. 23 tests.
- `agents/core/autonomy/company_report.py` — the brief. Headline is the verdict,
  not the effort; an unauthorised step leads its run *and* the whole brief; a
  blocked run says what it waits for; "nothing ran" and "company mode is off" are
  different sentences. Pure, payload-free. 19 tests.
- `agents/core/routers/company.py` + `frontend/src/panels/company-room.tsx` —
  three user-guarded routes and one Console panel. **No start route and no start
  button**, asserted by a test: opening a run needs an owner-approved goal decided
  in the inbox, and a start control here would be a second, weaker approval path
  for the most powerful thing in the product. Stop is offered, because narrowing
  never needs approval. 16 pytest + 9 vitest.

## What is deliberately NOT in this slice

- **A real proposer.** `ModelPlanner` takes an injected call; wiring a live model
  into it is a separate slice, and the clamps above are what make that safe to do
  later rather than now.
- **Scheduled continuity.** Waking a run on a schedule is a separate slice; this
  one is tick-driven by its caller.
- **Anything that opens a run from a UI.** By design, as above.
