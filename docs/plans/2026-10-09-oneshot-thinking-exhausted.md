# One-shot CLI recognizes exhausted thinking budgets

- Generated: 2026-10-09 UTC.
- Base / HEAD before edits: 23c435caaa63a14efb9d16a9a86bee56ad24b494.
- Branch/worktree: codex/oneshot-thinking-exhausted-20261009,
  /workspace/jarvis-hub-oneshot-thinking-exhausted.
- Goal: do not report the backend's exact no-visible-answer thinking-exhaustion
  message as a successful one-shot CLI answer.
- Scope: autonomous LOCAL fix; no remote publication, providers or devices.
- Next action: local unit verified; retain the remaining H002 outcome/attribution
  gaps and continue separately scoped backlog work.

The stdlib-only CLI refusal table has a comment for THINKING_EXHAUSTED_REPLY but
no entry. Add the exact backend constant's current text and a fixed machine
reason using the existing table/containment path. Do not import the LLM runtime
into CLI startup. Add the real constant to the existing drift guard.

For -z, direct, specialist-wrapped and sanitized/control-padded sentinel replies
must produce EXIT_FAILED, empty stdout, a specific stderr reason, and a receipt
with completed false/status refused. No extra request or retry/approval decision.
Interactive output/exit behavior remains compatible; its optional receipt may
truthfully report incomplete just as it already does for other refusal messages.
Ordinary successful answers and other exit codes keep their existing behavior.

This does not classify rephrased or mixed synthesis results. A prior raw responder
having exhausted its budget does not prove a later synthesis response failed; do
not add a notice based only on pre-synthesis outcomes. No generic failed/completed
API, orchestrator changes, provider retry, pricing or usage-attribution work.
H002 remains partial for its other concrete gaps; narrow only this exact sentinel.

Ownership: auth_audit (gpt-6-sol/high) writes agents/cli/nerva.py and
tests/test_nerva_oneshot.py only. mobile_session_transport (gpt-6-sol/high) does
independent frozen review and named collateral claims; wall_contracts
(gpt-6-luna/medium) may inventory pins read-only. Root owns plan/proof, metadata,
claim updates, integration and git. No nested delegation; max4active inclroot.

Run the full one-shot and CLI suites plus relevant receipt/import checks; source
freeze before integration. Record actual test counts and meaningful RED/GREEN.
The new regression tests must exercise cmd_chat and persisted receipt, not just
repeat table membership. Refresh only previously-current pins after named review;
keep preexisting stale pins. A serial full backend milestone follows if needed
for the final integrated backend checkpoint; do not rerun unchanged clients.
Rollback the single sentinel entry, regressions and scoped documents as one unit;
no public schema or persistent-data migration.

## Completed evidence

Six selected cases were RED before the table entry: four actual command/receipt
cases and two existing drift guards extended to the real constant. Final writer
CLI union: 274 passed, one existing live-import skip, 275 total in 5.398 seconds.
Root producer/approval/send/image union: 79/79 in 2.618 seconds, overlapping by
55 cases. Across both: 299 distinct cases, 298 passed and one skipped, zero
failures/errors. No live test was activated. All 55 one-shot cases pass; Ruff,
whitespace and a site-packages-disabled help launch pass.

Root AST review proves only one refusal-table entry changes; every function,
class, import and other module statement remains identical. Independent review
found no Critical/Important issue. This bounded delta needs no repeated full
backend/client execution after those CLI and adjacent integration checks; the
previous complete backend result is retained with its actual prior source SHA.
Collection records 21,278 backend, 2,009 frontend/native and 306 mobile cases,
with 555 routes; Hermes/status checks pass. No schema/client/provider change.

Nineteen previously current evidence pins are refreshed after named review; 35
preexisting stale pins stay stale, including H002 CLI. Eight H586 coordinates
shift by three with identical target lines. H002 remains partial; its missing
sentinel clause and test count are updated, and obsolete billing/session
explanations are narrowed
to verified remaining CLI receipt behavior. No other semantic claim/status change.
Full results and tested source hashes are in docs/project-oneshot-thinking-exhausted-20261009.md.
