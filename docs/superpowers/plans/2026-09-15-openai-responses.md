# Bounded API-key Responses provider

Goal: explicitly selected public OpenAI Responses transport for non-reasoning GPT-4.1, including text, streaming and local function-tool turns.
Base: 6fba226b63fbb19c0324ee05f1154cb82cdc892e. Generated: 2026-09-15 18:29:38 UTC. Head: this source commit. Next: independent review and parent integration.

## Accepted scope

Distinct openai-responses profile using existing OPENAI_API_KEY configuration, fixed https://api.openai.com/v1/responses. Only gpt-4.1 and gpt-4.1-2025-04-14; reject other models before HTTP. No credentials are inspected during development. Existing cloud routing, local-only policy, approved models and guardrail wrappers remain. No protected edits, new dependencies, provider-hosted tools, image inputs, OAuth, live calls or silent migration from chat/completions.

Stateless requests use store:false, complete caller-supplied text transcript, explicit strict:false function schemas and call_id-linked function outputs. No previous_response_id or backend transcript cache. Model reasoning vocabulary is explicitly empty. Unknown reasoning-model support is not inferred. Request-scoped hashed cache key; retention is finite in_memory (default) or24h, only for the fixed supported models. Streaming has bounded bytes/events/output and a total deadline; only validated terminal completion publishes usage, once. Cancellation/errors/incomplete streams do not resubmit. Inclusive input totals split cached input once into Nerva's disjoint usage fields; output reasoning detail never added to total.

Official docs inspected 2026-09-15: https://developers.openai.com/api/docs/models/gpt-4.1 lists both exact IDs and Responses/function/stream support; https://developers.openai.com/api/docs/guides/prompt-caching explicitly lists GPT-4.1 extended24h support and in_memory for earlier models; https://developers.openai.com/api/docs/guides/migrate-to-responses defines function_call/function_call_output and strict:false; https://developers.openai.com/api/docs/guides/streaming-responses defines terminal events. This API-key path is not Codex OAuth/subscription access. H363/H364 remain partial for Codex OAuth and reasoning replay.

## Steps

- [x] RED actual configured router selects Responses and respects local-only/model policy; actual request cache and two-turn function mapping.
- [x] Pure bounded dialect and adapter; minimal profile/settings/router wiring.
- [x] RED/green streaming splits, terminal usage, unsupported models, failures/cancel/limits/session isolation; actual agent tool loop and guardrail tests.
- [x] Focused suites, whole Ruff, baseline Bandit1.9.4 and scoped Graft; clean source commit for independent review.

Files: llm/responses.py and responses_dialect.py, providers/__init__.py, hybrid_router.py, settings_db.py, focused tests and this guide. Rollback: revert this unit; existing provider defaults remain. No full backend, global metadata or generated assets in source delivery.


## Operator contract and limits

In admin LLM settings choose `compatible_provider=openai-responses`, `compatible_model=gpt-4.1` or `gpt-4.1-2025-04-14`, and an existing configured `OPENAI_API_KEY`; reconnect through the existing lifecycle. This does not change which agents may use cloud models or their approved-model lists. Unsupported model IDs refuse before HTTP. The fixed endpoint ignores custom OpenAI base URLs. No API key or auth file was read during development; all requests below use fixture-only credentials and MockTransport.

`responses_cache_retention` defaults to `in_memory`; `24h` is an explicit option documented for GPT-4.1. `store:false` disables Responses object storage; it does not disable prompt caching or promise zero provider data retention. Cache keys derive from the existing hashed provider/session scope; no raw session identifier is sent in that field. There is no local response/transcript cache and no `previous_response_id`. Function results replay the caller's transcript using `call_id`, never the different provider output-item ID.

The adapter accepts text and local function tools only. Function schemas explicitly use `strict:false`; malformed arguments retain the existing nonexecutable ToolCall parse error. Successful top-level completion cannot override an explicitly incomplete output item. Hosted tools, images and encrypted reasoning replay are unsupported. A stream needs a validated terminal response, matching emitted text/refusal, bounded EOF and successful close; duplicate completion, contradictory/truncated trailers, errors, timeout and cancellation do not publish usage or retry. Tokens already emitted before a late failure cannot be retracted. Limits: 2 MiB request/nonstream response, 512 KiB text, 32 calls, 1 MiB SSE event, 8 MiB stream, 10,000 events, 120-second total async deadline. No automatic resubmission or key rotation is introduced.

API-key public billing is distinct from Codex subscription/OAuth. H363/H364 remain partial for that auth/transport contract and reasoning replay. Invocation integration calls `request_context.ensure_reasoning_active()` immediately before both Responses HTTP dispatch paths. Expired explicit scopes and nested null scopes retain revocation; ordinary no-override requests preserve their defaults. The declared-empty GPT-4.1 vocabulary emits no reasoning fields.

## Verification

- Initial router/transport RED: `/tmp/nerva-responses-red.log`; boundary RED: `/tmp/nerva-responses-boundaries-red.log` (typed invalid model/retention and streamed refusal).
- Reviewer RED: `/tmp/nerva-responses-close-red.log`, seven failures covering late close/error/delta and incomplete message/function items. Corrected focused result: 363 passed, zero failures/errors/skips, including 73 new Responses cases; `/tmp/nerva-responses-final-focused.log` and `/tmp/nerva-responses-focused.xml`.
- Command (existing socket/timeouts/addopts retained):

```sh
TMPDIR=/private/tmp /usr/bin/python3 /tmp/nerva-run-isolated.py /Users/andrei649/Projects/nerva-worktrees/openai-responses /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_openai_responses.py tests/test_llm_provider_profiles.py tests/test_provider_request_profiles.py tests/test_hybrid_router.py tests/test_settings_db.py tests/test_reasoning_empty_contract.py tests/test_text_usage_propagation.py tests/test_agent_runtime_v2.py tests/test_route_preserving_guardrails.py tests/test_tool_loop_guardrails.py tests/test_guardrails_generate_kwargs.py --junitxml=/tmp/nerva-responses-focused.xml -q
```

- Whole Ruff passes: `/tmp/nerva-responses-ruff.log`. Bandit 1.9.4 `-r agents scripts -q -b .bandit-baseline.json` exits 0: `/tmp/nerva-responses-bandit.log`. Existing baseline comment-parser warnings remain. One existing Gemini network-error test reports the expected pytest-socket refusal of a non-loopback connection; no allowed live provider call occurred.
- Graft parsed exactly the five owned runtime files (91 nodes, 223 edges), cache `/tmp/nerva-responses-graft`; `graft --dir /tmp/nerva-responses-graft check .` is fresh. No semantic/paid indexing, hooks or generated cache committed.
- No full backend, live API, OAuth, frontend build, protected path or global status change in this unit.

## Invocation lifetime integration plan

Integration base: 2c504203ef297c06d8f3d47adf31e17511f7e4b4 (reviewed invocation
source on merged compaction-clock). Only the single original Responses source
commit was rebased from6fba226b; resulting source cad9b7e5.

Add the public ensure_reasoning_active() check immediately before both actual
Responses dispatch paths, including the shared nonstream path accepting a prebuilt
payload. Keep GPT-4.1's explicit empty vocabulary; no reasoning parameters are added.
RED actual prebuilt request blocked until its explicit/null-child ancestor expires;
then ensure neither network nor usage occurs. Also verify all public text/stream/tool
entrypoints reject expired scopes and ordinary no-override requests still work.
No config/authority/global metadata changes. Run guarded Responses+invocation/provider
integration tests, update this plan and commit only source/test/plan delta.

Integration verification: two prebuilt-request RED failures and six public-path passes before the fix (`/tmp/nerva-responses-invocation-red.log`). After the dispatch checks, 426 guarded focused tests pass, plus 35 HTTP invocation tests (461 total). Eight new integration regressions bring this source unit to 81 added Responses cases. Existing ordinary no-override text/stream/tool and two-turn runtime tests remain green. No live provider calls, full backend or generated assets are claimed.

Final integration quality checks: whole Ruff passes; baseline Bandit over relative `agents scripts` exits 0 (existing comment-parser warnings only). Scoped manual Graft build/check covers the two changed Python files and reports fresh wiring; no cache committed. Logs: `/tmp/nerva-responses-invocation-{ruff,bandit}.log`, `/tmp/nerva-responses-integration-graft.log`.

## Reviewed final integration

Independent H129 review cleared the original corrected Responses source with363
focused cases. Root reviewed the invocation lifetime integration and independently
ran171 guarded integration cases, /tmp/nerva-responses-root-integration.xml. Two
owned commits were rebased onto final invocation1c099a8399d7da858caa80ef1ae011bdb2fbb90e,
producing source8aedbe527e9c0b3d82960e04b6926e540249761b. Assessment base/UTC identify
that exact source. The fixed public API-key/non-reasoning model contract is unchanged.

Evidence refresh requires every prior evidence hash in the row to match the invocation
base. H257/H269/H284 remain stale verbatim; the exact manifest is
/tmp/nerva-responses-evidence-refresh.json. H363/H364/H673 remain partial, distinguishing
public API-key Responses from Codex OAuth/subscription, named Grok capabilities and
reasoning-model opaque replay. No live cache, pricing, billing or vendor acceptance
proof is claimed. Full-suite evidence is owned by the integrator and will be recorded
from completed /tmp/nerva-responses-full.log and .xml only.

The first integration full run began before metadata was stable and reported one
Hermes generated-report freshness failure (expected118 equivalents from the old
assessment versus inherited121 in HERMES_STATUS.md). Current regenerated reports
match the reviewed assessment at121/327/94/107/48. No source repair follows from
that failure. The integrator preserves the first full logs/XML and will run a fresh
full suite only after the metadata checks pass and all tracked files are frozen.
Final full outcome remains pending; no full-green result is claimed here yet.

Fresh final full suite on frozen metadata: **11,831 collected, 11,807 passed,
23 skipped, one expected failure, zero errors/failures**, 246.434 seconds;
/tmp/nerva-responses-full.log and /tmp/nerva-responses-full.xml. The first run is
preserved at /tmp/nerva-responses-full-first.log and .xml: 11,806 passed, 23 skipped,
one expected failure, one generated-report freshness failure, 262.308 seconds.
No runtime repair was needed between runs; the second run used stable metadata.

The integrator used product Python3.12 through /tmp/nerva-run-isolated.py with
/usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 and complete fish/Node PATH:
/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin.
Repository pytest.ini/socket/timeout guards were retained. Integrated whole Ruff and
Bandit1.9.4 baseline passed, /tmp/nerva-responses-integrated-ruff.log and
/tmp/nerva-responses-integrated-bandit.log. Root source review confirmed the bounded
public-model contract and all three previously-stale rows remained unchanged.

Final81 metadata cases (test_hermes_sprint_status, test_status_sync, test_release_gate)
pass, /tmp/nerva-responses-metadata.log and .xml. status_sync --verify-test-count
backend --test-result /tmp/nerva-responses-full.xml confirms11831. Generated counts
retain frontend1326/mobile140/routes501, with no new frontend/native run for this
backend unit. Hermes totals remain121 equivalent/327 partial/94 missing/107 excluded/
48 needing review; H363/H364/H673 remain partial. No live API, subscription, cache
hit-rate or billing evidence is inferred from these mocked and guarded tests.
