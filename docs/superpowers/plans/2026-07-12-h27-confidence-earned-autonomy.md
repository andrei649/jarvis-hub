# H27.7 implementation plan

1. Add red tests for durable outcome upserts, Wilson confidence, terminal-only worker accounting,
   registry projection, default-off behavior, the 20/0.80 threshold, and every hard floor.
2. Add the outcome table/read-write methods to `TaskQueue`; keep schema migration additive.
3. Record real terminal outcomes in `AutonomyWorker` and inject registered capability stats into its
   three policy decision paths (submit, governed enqueue, edited re-gate).
4. Add the bounded earned-autonomy rule to `AutonomyPolicy` and live-sync the default-off setting.
5. Feed action confidence/outcome counts into the existing registry without changing other kinds.
6. Update H27.7/backlog/status only after focused tests and safety regressions are green.
7. Run Ruff/Bandit, focused autonomy/kernel/H27 tests, status/release gates, push draft PR, self-review,
   and merge only after complete GitHub CI.

