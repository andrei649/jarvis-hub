# Functional change review

Use for a backend, CLI, skill, data, or workflow change. Start at the actual product entry point and follow it through the owning module, persistence and response.

- [ ] Locate the frozen requirement or reported defect and read the relevant [ownership-map](../../docs/CODEBASE_OWNERSHIP.md) guide. Name which full behavior changed and which part remains open.
- [ ] Trace the real caller, route/command/tool registration, normal result, refusal/error result, and return path. A helper or snapshot alone does not make a feature reachable.
- [ ] Inspect affected state across restart, cancellation, concurrency and rollback where those matter. Check that a failed validation leaves no partial effect.
- [ ] Check adjacent callers and generated contracts: route/auth/OpenAPI parity, client typegen, shipped HUD bundle, mobile/desktop intent, and documented settings when touched.
- [ ] Inspect a meaningful regression for the changed behavior and run the focused command. Record pass/fail/skip and any platform, provider or full-suite limits. Do not turn a changed evidence hash into a regression claim without an impact review.

Report concrete findings with file/line, repro, impact and the missing assertion. If no defect was found, say what was actually inspected and what was not run.
