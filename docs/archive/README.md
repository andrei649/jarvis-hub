# docs/archive — history, not instructions

Moved here on 2026-11-25 under `docs/decisions/2026-11-25-nerva-finish-line.md`: 426 plans,
handoffs and run notes that no code, test, script or workflow names, that no open branch touched,
and that had not changed on main for three weeks.

- Each file keeps its path under `docs/`: `docs/handoff/x.md` is now `docs/archive/handoff/x.md`,
  so links between archived files still work.
- Repo-path references in living Markdown were rewritten to the new location. Frozen evidence and
  manifest files (`docs/hermes/evidence/`, `docs/handoff/**/**.json`, `docs/hermes/assessment.json`)
  were deliberately left untouched, so some of them still name the old paths.
- Nothing here authorises work. A stale plan may inform an investigation; the current truth is
  `AGENTS.md`, `BACKLOG.md` (query it with `scripts/backlog.py`) and the decision above.

To bring a file back: `git mv docs/archive/<path> docs/<path>`.
