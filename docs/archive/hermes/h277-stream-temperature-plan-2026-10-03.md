# H277 streaming auxiliary temperature recovery

Goal: extend the pinned Hermes auxiliary temperature repair and learned route
capability to Nerva's actual local compression stream. Generated 2026-10-03;
base/head `4668be6c`, branch `codex/h277-provider-discovery-20261002`.
Reference: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`agent/auxiliary_client.py:_fixed_temperature_for_model` and
`_parameter_rungs` (temperature removal and remembered route rejection).

Existing LM Studio nonstreaming auxiliary calls may repair one bounded structured
HTTP 400 temperature rejection and remember success on the exact client,
destination, transport and model. Compression streams currently bypass that
scope. Add a task-local call context inside `stream_summary`'s owned worker and
enter the existing recovery scope there for LM Studio compression only. Parent
and unrelated child tasks receive no retry permission; cancellation closes the
scope even if a backend suppresses cancellation. The scope also snapshots the
physical cache identity at entry, preventing a client/destination/transport
changed during cleanup from learning a rejection on the previous route.

The native LM Studio stream retains ordinary behavior. In the scoped auxiliary
path, omit a proven rejected temperature up front or retry its first explicit
400 once after response cleanup. Preserve the unload retry as a separate one-use
allowance, at most three physical sends. No retry after received stream activity,
tokens, reasoning or cancellation; no generic failure or timeout grants repair.
Each physical send uses the existing fresh H513 guard. Remember rejection only
after a repaired, nonempty successful completion, never on incomplete/error or
refused streams.

Owned paths: `agents/core/llm/base.py`, `agents/core/llm/auxiliary_text.py`,
`agents/core/llm/auxiliary_recovery.py`,
`agents/core/compaction_hold.py`, new focused tests, this plan and inspected Hermes
assessment/generated reports. Red-first tests cover actual compression egress,
response cleanup, both repair orders, refusal/revocation, cache reuse/isolation,
activity, parent/child authority and cancellation. Run focused H277/H513/H674
and backend regressions, Graft freshness, status derivation and staged secret
scan. Rollback this scoped streaming increment; preserve earlier nonstreaming
repair and all unchanged consumer contracts. No new cloud route, owner grant,
paid service, publication, live-provider proof or full H277 completion claim.

Verification checkpoint: the red-first real compression regression passed after
implementation. The focused stream/compression baseline passed 31 tests; the
broader affected-row regression passed 3,433 tests across 117 modules. The full
backend suite passed 21,372 tests, with 34 skips and one expected xfail (67
warnings, 1,110.71 seconds). Eight behavior-bearing isolated mutants were killed;
the restored baseline passed 31/31 and all six source/test hashes matched. One
prior single-guard mutant was structurally equivalent and is documented outside
the killed-mutant count. Ruff, diff checks, derived Hermes status, Graft tier-0
freshness and the exact staged gitleaks scan passed. No live model or frontend
acceptance was performed for this backend-only change.

Delivery: one Sol High implementer owned only `base.py` and its backend tests;
the coordinator owned shared scope/integration and evidence. Source-based H277
review remains partial. Next action: continue the separate opt-in smart terminal
approval plan after committing this local checkpoint.
