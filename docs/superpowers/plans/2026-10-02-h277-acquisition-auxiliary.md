# Acquisition auxiliary model implementation brief

Goal: allow capability generation and grounded draft planning to choose independent
local models without changing JSON retry, output-validation or privacy behavior.
Spec: [acquisition design](../../hermes/h277-acquisition-auxiliary-design-2026-10-02.md). Base a5b74939d4632c61e007ad64e4df937c44c47bc5.
PR1226 is merged. Execute on codex/acquisition-auxiliary-models-20261002. Rollback: revert this bounded slice; no deployment or provider calls.

Ownership: `agents/core/llm/auxiliary_text.py`,
`agents/core/acquisition/llm_synth.py`, new
`tests/test_h277_acquisition_auxiliary.py`. No other tracked edits, staging,
commits, publishing or subdelegation. Parent owns docs, counts and evidence.

Implement `prepare_local_auxiliary(router, task)` returning an async callable
accepting the existing generation keywords, including compression's optional
`summary_idle`. Keep `generate_local_auxiliary` as a compatible one-shot wrapper.
Capture model and local backend once at preparation; each invocation opens a fresh
H513 scope. No API parameter accepts arbitrary backend/model/pin bypass.

Add fixed tasks `acquisition_capability` and `acquisition_draft`, flags
`JARVIS_AUX_ACQUISITION_CAPABILITY_MODEL` and
`JARVIS_AUX_ACQUISITION_DRAFT_MODEL`, fallback active model then `local`.
Use the existing printable Unicode, raw length <=256, ASCII-space trim validation.
Unknown task/configuration errors remain sanitized. Existing four tasks retain
job-pin exclusion (also when invoking a prepared operation), defaults, Qwen suffix,
compression streaming and cancellation. Acquisition retains its existing job-pin
behavior, explicitly tested: the strict-local accessor bypasses job selection.
Do not silently introduce a new policy restriction with this refactor.

Prepare once before each acquisition JSON loop. Keep two attempts, temperature
0.2 then 0, max_tokens2048/1024, prompts, object/array parsing and validators.
Policy/provider/config errors never become JSON retries or cloud fallback.

Red first through both real producers: configured models must reach backend,
independent of active model. Then test invalid/no backend/no fallback, exact
fallback, Unicode, new-invocation setting changes and preserved pins behavior.
Force malformed first reply and mutate env, router active model and current
backend: operation must retain original backend/model, while a new operation can
see the new values. Each attempt has fresh authorization. Test actual HTTPX hook
revocation between attempts and swallowed physical denial; retain real drive
blocked/409 behavior. Do not weaken the existing guard to satisfy a freeze test.

Run new tests plus all `tests/test_h32*.py`, `tests/test_h513*.py`,
`tests/test_h277_local_auxiliary.py`, `tests/test_h413_session_titles.py`,
`tests/test_query_rewrite.py`, `tests/test_background_review.py`,
`tests/test_h674_compaction_hold.py`, `tests/test_context_compression*.py`,
`tests/test_h277_model_roles.py`, `tests/test_h277_role_routes.py`.
Use `/tmp/nerva-pr-python-20261001/bin/python` with existing socket/time guards.
Save red/green JUnit and concise report under `/tmp/nerva-acquisition-*`.
Run scoped Ruff and diff check. Full suite is the parent's serial milestone.

## Completion checklist

- [x] Red-first producer tests, shared prepared helper and two real consumers.
- [x] Focused guards, retry freeze and full existing consumer regressions.
- [x] Parent review, configuration docs and unchanged mobile/HUD boundary.
- [ ] Full backend on frozen source; refresh only reviewed affected evidence.
- [ ] Exact publication scan, PR and checked integration.

Ruling: retain acquisition's current job-pin behavior explicitly; changing it is
a separate policy decision. The four existing producers still reject pins.
Owner-authorized autonomy/delegation replaces repeated interactive design gates.
