# Hermes parity: who works on which rows

Two Claude sessions work on the Hermes ledger at the same time. This page says which rows
each one owns, so that neither re-reads or rebuilds a row the other is changing. Both
sessions update it when a lane changes. The ledger itself stays the source of truth:
`python3 scripts/hermes_status.py summary`.

Opened 2026-10-11 at #1249 head `f9e130b5` (155/697 equivalent).

## Lanes

| Lane | Session | Branch and PR | Rows |
|---|---|---|---|
| Records and integration | CTO (`session_01FCWSJRUg9xJvyr2Cy1WHjF`) | `codex/hermes-progress-20261010`, #1249 | #1249's CI, `main` syncs and its merge condition (697/697); the 40 stale rows recorded `equivalent`; then the 112 stale rows recorded `partial`; then the 105 `scope_reopened` rows; H673 |
| Build | Developer (`session_01Kd5eTAYsUsx2NuKtYp8FB3`) | `claude/nerva-backlog-zero-0k83jc`, a draft PR stacked on #1249 | rows reviewed `partial` or `missing`, nearest to equivalent first (batches below) |
| Owner, last | owner | none | security rows (H481, H495, H502, H512) and anything under `selfdev-policy.json` → `protected_paths` |

The 40 stale rows recorded `equivalent`: H034 H078 H099 H117 H153 H156 H157 H165 H168 H200
H209 H242 H247 H259 H262 H273 H275 H285 H309 H313 H314 H318 H368 H378 H428 H433 H465 H490
H507 H513 H518 H523 H579 H586 H594 H670 H674 H677 H681 H687.

## Build batches

1. Small rows reviewed `partial`: H043 H182 H206 H222 H283 H296 H310 H445 H583 H676, and the
   small row reviewed `missing`, H545.
2. Medium rows reviewed `partial`: H115 H389 H417 H451 H452 H455 H529 H537 H554 H570 H571
   H605 H607 H622.
3. Rows still on the 2026-09-07 baseline (`partial`, then `missing`), by cluster.

## Rules both lanes follow

- **One writer per row.** Take a row only if this page gives it to your lane. To move a row,
  say so on #1249 and edit this page in the same change.
- **No pin drift (since 2026-11-10).** Evidence is no longer hash-pinned: a build change that
  moves or edits cited files re-opens nothing. What can re-open rows is a failing area
  acceptance suite (`docs/hermes/areas.json`, `python3 scripts/hermes_status.py verify`), and
  then only that area's `equivalent` rows. If a build change moves a test file that a suite
  names, update `areas.json` in the same PR. `hermes_restamp.py` is retired.
- **Re-read before you change a verdict.** A status change is a re-read of the row against the
  code, written into `assessment.json` with its summary, remaining work and evidence paths.
- **Shared files.** Both lanes write `docs/hermes/assessment.json` and the generated reports.
  Merge by review id, keep `scope_reopenings` byte-identical, and regenerate the reports with
  `python3 scripts/hermes_status.py write` and `python3.12 scripts/status_sync.py` rather than
  hand-merging them.
- **History.** Merge, never rebase or force-push a shared branch. The build lane merges
  `codex/hermes-progress-20261010` into its branch before every push and never pushes to it.
- **Messages.** Cloud sessions cannot message each other directly here. Use comments on #1249
  or on the build PR.
