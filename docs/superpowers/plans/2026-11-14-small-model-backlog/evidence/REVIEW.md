# Specification package validation — 2026-11-14

Goal: make the remaining Nerva/Hermes work assignable in bounded units to smaller
models, with a coordinator retaining design and integration decisions.

Base inspected: `587977b623cf2d1099733d57037e1c056babe1e5`; base tree:
`d509686d6cfbdb0052600ddcba27764b4186ed3b`. Application source corresponds to
lot4 `ffbfce81`; the additional base commit records the lot5 pause.
Changed paths: this package and its sibling index Markdown file only.
The package's delivery SHA is the containing planning commit/PR head; it is not
an application implementation or a new Hermes acceptance checkpoint.

## Coverage and readiness

- 697 exact, unique contract IDs in 23 area files; recorded ledger counts remain
  187 equivalent / 474 partial / 0 missing / 36 excluded.
- 510 recorded non-equivalent contracts remain in scope. Nine additional review
  overlays flag concerns without rewriting canonical verdicts.
- 39 open checkbox records and 54 open table records are preserved separately.
  Five repeated table IDs and an unclassified six-row table remain explicit.
- 26 detailed packets: 21 ready specifications, four requiring design, one
  requiring an external platform. Ready means ready for implementation assignment,
  subject to dependencies and source freshness; it does not mean implemented.
- The rest of the contract catalog preserves exact requirements, evidence paths,
  previous specifications and domain acceptance guidance. Those cards still need
  bounded design before small-worker implementation. No claim of 510 ready tasks.

## Checks actually run

From the repository root:

```sh
python docs/superpowers/plans/2026-11-14-small-model-backlog/taskpack.py validate --check-source
python docs/superpowers/plans/2026-11-14-small-model-backlog/verify_taskpack.py -v
```

Validation passed: 26 packets, 697 contracts, 93 backlog records, zero validation
errors. Eight offline helper checks passed: exact coverage/fingerprints; unknown
dependency refusal; dependency-cycle refusal; missing-contract refusal; changed
production-file refusal before selection; dependencies/file ownership during
selection; lossless pagination; unknown IDs/conflicting assignments refusal.

Regenerated the catalog with the project's Python and compared SHA-256 of all
27 generated JSON files before and after: identical. Checked test paths named in
packet commands: each exists or is explicitly owned as a new file. No application
test suite was run for this specification-only change.

## Independent review and corrections

Two implementers used `gpt-6.1-sol` with medium reasoning to draft separate core
and product packets. The coordinator reviewed both, and a separate read-only pass
reviewed the core packets, helper and delegation instructions. No token savings
were measured or claimed.

Corrections include actual Agent callback regressions rather than a hypothetical
MoA callback issue; design holds for sync atomicity/conflict policy; actual HUD
and CLI callers for room acknowledgement; concrete mobile response types; exact
existing status/MoA symbol names; production fingerprints; and a defined staged
skill response with backward-compatible receipt handling. Incoming skill staging
does not claim installation, authority propagation or executable discovery.

## Limits and next action

The accompanying review reports describe a historical GitHub snapshot, not the
CI result of this planning commit. Known application CI failures remain unresolved
here. No Windows/macOS/device/provider acceptance, deployment, paused-service
restart or previously blocked update/restart adversarial check was performed.

Next action: run `taskpack.py next`, assign independent ready packets with the
worker prompt and exact base, then review actual changes/tests. Refresh source
fingerprints only after reviewing an accepted new baseline; never refresh merely
to hide drift. Resolve the four design packets with concrete interfaces before
delegation. Main and existing implementation branches are not modified by this PR.
