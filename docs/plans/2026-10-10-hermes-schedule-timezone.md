# H450 — use the application's active timezone for schedules

Generated 2026-10-10 UTC. Base and initial head:
`9a5fdf298c6e63bcc38ddde4946c96998726f53e`; local branch
`codex/hermes-closure-01-20261010`. Goal: finish H450's accepted timezone
contract. The app seeds `general.timezone`, but preview and owner jobs currently
anchor naive timestamps to the server's timezone. A UTC server therefore treats
09:00 selected for US/Eastern as 09:00 UTC.

Keep the parser pure and pass an explicit ZoneInfo from production adapters.
A shared settings adapter validates the persisted app timezone; a missing row
uses the declared app default, while invalid or unreadable explicit configuration
refuses scheduling with a fixed actionable error. A runner lazily pins this app
zone for its lifetime, independently of APScheduler's host default. Its store,
status, cron registration and fallback ticker use the same zone. Preview resolves
through that active runner when present; standalone preview/store use the saved
app zone. Saving a new timezone takes effect for running owner jobs after restart,
so preview and actual jobs do not disagree during that interval. Existing
absolute one-shots retain their instants. Do not change the global heartbeat
scheduler or move stored jobs merely because a settings row changed.

Implementation agent (`gpt-6-sol/high`) owns
`agents/core/autonomy/schedule_timezone.py`, `agents/core/autonomy/jobs.py`,
`agents/core/routers/tools.py`, `tests/test_h450_app_timezone.py`, and the
timezone expectations in `tests/test_owner_jobs.py` and `tests/test_jobs_advanced.py`. Root owns this
design, docs, evidence and integration. A second `gpt-6-sol/high` agent reviews
the final change and the six currently reviewed partial job-row claims affected
by the jobs.py evidence pin. No subdelegation or publication.

TDD: first reproduce a UTC-host/US-Eastern-app mismatch through preview and job
creation, then verify naive ISO and day words, explicit offsets, create/edit,
explicit cron timezone, status/ticker agreement, restart lifecycle, and invalid
configuration refusal. Run the existing schedule, owner-job and jobs-route
regressions and related scheduler tests. The frozen H450 syntax/repeat contract
remains covered by its existing focused suite. Run one full backend milestone
after all three local implementation units and evidence updates are integrated.

Non-goals: automatic live rescheduling of previously registered jobs, new syntax,
new settings, timezone-dependent migrations, external deliveries, or weakening
approval and scheduling guards. Rollback reverts the settings adapter and the
three native consumers with their regression tests and evidence; stored UTC
one-shots need no migration.

Implementation result: four behavioral regression cases failed on the old
implementation. The final adapter resolves settings off the preview event loop,
normalizes the shipped US/Eastern alias, and serializes the first valid zone pin
across concurrent callers. Invalid first reads remain retryable after repair.
The nine new tests and seven related suites pass 246 cases. Two existing tick/
snapshot expectations now explicitly use the seeded app zone instead of the
host zone. Ruff and whitespace checks pass. The application was restarted with
an isolated temporary data/key root and host TZ=UTC: HTTP preview correctly
anchored "tomorrow at 9" to America/New_York, and the pressure route retained its
schema and no-cache headers. An initial US/Eastern smoke could not start because
this container omits that system zone alias and an existing attention component
resolves it directly; the successful complete-app smoke uses its canonical name.
The schedule adapter itself covers the alias in focused tests. No host timezone
files, external services or personal runtime data were changed.

Independent review passes 199/199 cases and finds no concrete production defect.
H450 is equivalent on current source/test evidence. The six collateral jobs rows
H115/H451/H452/H454/H455/H676 retain their partial verdicts and concrete gaps.
The integrated backend milestone collected 25,587 cases: 25,525 passed, 58
skipped, one xfailed and three failed. All failures came from an older cron-slot
fixture in tests/test_job_first_run.py that set only scheduler.timezone=UTC. The
fixture now creates isolated app settings with timezone UTC and deliberately sets
the scheduler to Bucharest. Its unchanged expected slot delays test the intended
app-zone contract. Independent review approved this narrow correction; all 261
cases in the complete six-file affected rerun pass. No production code changed
after the full run, and no second full run is claimed.

Local implementation commit: `4d0b8244`; prior pressure and visibility fixes are
`1cc04ba9` and `114af2de`. Next action: finish delivery documentation and evidence,
then retain the local branch for the next authorized backlog work.
