# Bounded review: PRs #1361–#1363

Generated 2026-11-14 UTC. Goal: establish concrete blockers and whether #1363 carries #1359–#1362 code. Base `1338833d5a344d277c43828a9d9314e10af792f1`; heads #1361 `91aa3bd7e70bdd78c6796dadd8c1b7a423a0398e`, #1362 `0856c504c0a46279df632cbe3cbc1612f6fed6b5`, #1363 `702845ae45765583f996fdb5b2b08de9db6664bc`. Read-only source review; exact #1363 archive extracted into `review-history-1363/` for tests. No source checkout edits, publication, merge, deployment, service install, or blocked-operation retry.

## Findings / recommendation

No concrete code merge blocker found in the requested session organization, retained-transcript, pagination/history integration boundaries. Prefer integrating #1363 once its exact head satisfies trusted policy and every reported CI check completes success/neutral/skipped. The coordinator reports cancelled Windows full-tests for #1362/#1363; this review did not inspect remote CI, so it does not clear that eligibility blocker. Re-check live head and CI before any merge. Do not independently replay #1359–#1362 changes after #1363 integration; their code is already represented.

## Subsumption proof

`git diff --name-only 1338833d refs/review/NNNN`, then `git diff refs/review/NNNN refs/review/1363 -- PATH` compared all earlier changed production/test code. `git cherry -v refs/review/1363 refs/review/NNNN` reports earlier commits as `+`: #1363 reconciles the final content, rather than preserving those commit identities or individual patch IDs. This is code subsumption, not ancestry subsumption, and not a claim that every status/document byte is identical.

- #1359 `686fcbf4`: service installer, boot guards/refusal, channel configuration, outbound safety, all channel transports except base wrapper, orchestrator wiring, commands, web/serve, systemd/Windows service files, and all corresponding tests except outbound-safety tests are byte-identical. Shared `agents/cli/nerva.py` retains service registration/dispatch and adds session features. Base wrapper additionally consumes private `_literal_job_output` before silence suppression; sanitization remains applied. `agents/core/autonomy/jobs.py:2155` passes this marker only for wrapped adapters. Added outbound-safety integration test proves literal script `[SILENT]` survives Telegram transport while secrets still redact. This is an integration fix beyond #1359, not a dropped #1359 hunk.
- #1360 `d97f48c7`: `scripts/bootstrap.py`, `tests/test_bootstrap_script.py`, and `tests/test_bootstrap_smoke_contract.py` are byte-identical.
- #1361 `91aa3bd7`: `agents/cli/session_organization.py` and its complete regression file are byte-identical. Diff of shared `nerva.py` adds history/transcript/service functionality without removing organization parser/dispatch/receipt logic.
- #1362 `0856c504`: core/CLI transcript helpers, both transcript Python regression files, HUD source/test/native test, all mobile transcript source/test files, web asset entrypoint, and clock-independent skill-binding test are byte-identical. Sessions router diff adds pagination imports/helpers/route only; transcript route remains. Generated schema diff adds pagination only. Shared `nerva.py` retains transcript behavior while adding organization/history/service integration.
- #1363 additionally contains parent `33b8d57b` owner pagination/history commit. It is not merely a duplicate of the prior four PRs.

## Boundary review evidence (line numbers at #1363)

- `agents/core/session_transcript.py:31`: real per-session turn lease, checkpoint identity captured before loading, existing rewind recovery/prepare-session protocol used, identity rechecked after loading and before response. `session_continuation.py:414` existing loader binds instance/import lineage and validates durable rewind snapshot/head; it does not switch the current session. Deleted/recreated identities cannot silently export cached history under the old identity.
- `agents/core/session_transcript.py:62`: only user/assistant text copied; system rows excluded; tool/media fields omitted. Bounds enforced before and after secret redaction. No retention-policy or archive-store change is introduced. Missing/corrupt/replaced/cold history and rewound current retained history covered by regressions; imported history remains explicitly addressed and is not copied to disk by preview.
- `agents/core/routers/sessions.py:135` and `:394`: pagination and transcript require admin guard; legacy bounded user list remains separate. Both responses use no-store; transcript exception messages/partial redaction do not escape.
- `agents/core/checkpoint.py:1181`: stable `(started_at DESC,id DESC)` keyset with NULL timestamps after dated rows; archive and existing continuation visibility predicates run before limit. Boundary need not reference a still-existing row. Page failure raises instead of claiming exhaustion.
- `agents/cli/session_history.py:112`: strict bounded metadata projection, deduplication, cursor-cycle refusal, shrinking requested count means no matching row is dropped at result cap. CLI buffers result until scan completes; late failure produces no partial stdout. Current CLI explicitly states bounded scan rather than fixed snapshot/completeness, requires repeated filters on resume, and explains advancing age anchor. It does not inspect raw history/metadata for filters.
- `agents/cli/session_transcript.py:64`: create-only 0600 atomic hard-link publication; existing paths are not overwritten and there is no unsafe fallback.
- HUD generation/mounted fences and mobile connection/visibility/request fences discard stale async previews. Text rendered as text, not HTML. Owner-only backend remains authoritative.

## Validation

Exact #1363 isolated archive, Python `/workspace/jarvis-hub/.venv/bin/python`:

```text
python -m pytest tests/test_cli_session_organization.py tests/test_cli_session_transcript.py tests/test_session_transcript.py tests/test_session_pagination.py tests/test_cli_session_history.py -q
exit 0; 361 selected cases passed (count confirmed by collection)
```

Deprecation warnings only (pytest-asyncio loop-scope default, audioop, Starlette testclient/httpx). No full suite, frontend/native/mobile suite or new remote CI run claimed. #1361/#1362 identity of retained source/tests plus exact combined-head tests support integration; this does not claim separate executions of every earlier head.

Next action: coordinator reconcile this bounded review with gateway/bootstrap reviews, live CI and combined main integration checks; preserve cancelled-check gate.
