# Reasoning effort no-escalation repair

**Goal:** An explicit effort below a known wire's minimum cannot silently become stronger or fall through to provider defaults.
**Integration base:** 33165622e61009901f8092025543bb42b985c5ff. **Reviewed source:** 2ca400ccf049c11d2db64ac051a459ce918e440b. **Assessment time:** 2026-09-15T17:29:30.649419Z. **Original repair base:** a94e0bfa434d7e7e05838334ca78e5103658cd39. **State:** integrated contract and guarded full-suite verification complete; metadata handoff ready.
**Architecture:** Pure canonical resolution returns `(None, 'below-minimum')` when no weaker rung exists. A typed `ReasoningEffortRefused(ValueError)` enforces that decision before HTTP in compatible, Gemini and Anthropic adapters. Gemini public retry wrappers propagate this local refusal, without credential/cache retry or usage publication.

## Accepted contract

Known nonempty vocabulary: select strongest rung <= request; never floor upward. Explicit `none` on generic declared vocabularies refuses unless an adapter has an existing reviewed disabling mechanism. Anthropic true disable branches remain; a default-on family with no disable mode refuses. A disable branch whose companion effort cannot be expressed also refuses. Declared empty and undeclared vocabularies retain existing distinct omission/default semantics; budget-only Anthropic families retain their separate thinking-budget contract. Gemini2.5 explicit effort with insufficient output room for its existing minimum budget refuses rather than omitting the block. No speculative model tables or provider parameters change.

All actual provider builders construct fresh payloads; no production reused-payload seam was found. Prepopulated helper payload stripping is explicitly outside this repair, as blanket removal would break intentional budget-only thinking.

## Implementation and tests

Files: reasoning_effort.py canonical helper/typed refusal; provider_request.py compatible wiring; gemini.py wire and retry boundary; focused new tests plus existing reasoning ladder/vocabulary assertions. Anthropic adapter behavior is exercised through its existing apply call before HTTP. No protected files, dependencies, global metadata, assets, live providers or publication.

- [x] RED pure minimal→high and default-on no-disable behavior, replacing old escalation assertions.
- [x] RED actual text/stream/structured provider calls across OpenRouter/compatible/Gemini/Anthropic: below-floor and explicit none, zero HTTP/callbacks/usage, no auth/cache fallback; Gemini insufficient output budget.
- [x] Implement typed refusal before payload mutation/send; preserve exact/down-clamped, unset, unknown, empty and true-disable/budget-only positive controls.
- [x] Run focused provider/usage/reasoning tests; whole Ruff and baseline Bandit, scoped graph freshness; commit owned paths only and send exact source/count evidence for review.

Token budget mappings remain product mappings, not claims about billed thinking. No whole H679 equivalence or broader catalog claim follows from this unit.

## Verification

New `tests/test_reasoning_no_escalation.py`: **37 collected cases**. Existing three test modules replace prior upward-floor/default-omission expectations without reducing cases. RED evidence `/tmp/nerva-effort-red.log` records canonical and actual compatible/Anthropic failures; initial Gemini cases also exposed a test cleanup mismatch (`close` versus `aclose`), corrected to close the injected HTTP client. Existing Gemini budget test previously asserted silent omission and now asserts local refusal. Final no-network mocks cover every actual text/stream/structured adapter entrypoint, callbacks/usage, auth/cache retry isolation and payload immutability.

**296 focused tests pass**, `/tmp/nerva-effort-final.log`:

```sh
/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_reasoning_no_escalation.py tests/test_reasoning_effort_ladder.py tests/test_reasoning_vocabulary_registry.py tests/test_provider_request_profiles.py tests/test_gemini_request_context.py tests/test_openrouter_h20_2.py tests/test_gemini_stream_usage.py tests/test_text_usage_propagation.py tests/test_stream_token_usage.py tests/test_cloud_token_usage.py
```

Whole Ruff and Bandit1.9.4 baseline pass (`/tmp/nerva-effort-ruff.log`, `/tmp/nerva-effort-bandit.log`); scoped `agents/core/llm` Graft wiring graph/check passes (`/tmp/nerva-effort-graft-check.log`), no deep/network pass or instruction/ignore edits. Local graph excluded. Independent reviewer ran117 focused cases against the stable diff before commit, with no blocker; exact SHA clearance follows. No full backend, paid/live call or publication performed.

## Amendment: frozen empty vocabulary contract (2026-09-15)

Independent frozen-source audit (`scripts/hermes_status.py show H679`, original37-delta-27-31.md) establishes `()` means **NO reasoning parameters**, not merely no effort field. Earlier budget-only preservation analysis above is superseded here: actual Claude override/registry empty emitted adaptive thinking, and built-in budget families advertised empty while emitting budgets. Reviewer repro: `/tmp/nerva-h679-empty-audit.py`.

Accepted design, coordinated with root and H129 reviewer before code:

- Add separate product budget rungs to `WireCapability`; retain `efforts` as actual wire effort-field vocabulary. Built-in budget families advertise existing `_BUDGETS` rungs through the profile, while emitting only `thinking.budget_tokens`.
- Explicit registry/admin empty has precedence before adaptive/disabled/budget shaping, for every requested setting. Strip known Anthropic reasoning controls (`thinking`, `output_config.effort`) including pre-existing helper fields, preserving unrelated output configuration and sampling restrictions. This omits request controls; it does not promise mandatory model reasoning is disabled.
- Nonempty budget declaration clamps its product rung; below-minimum refuses; no `output_config.effort` is invented. Undeclared unknown models keep their old wire behavior. Existing true-disable and no-escalation contracts stay in force when vocabulary is nonempty.
- RED actual generate/stream/tool adapters with override and registry empty across adaptive/default-on/budget families, plus prepopulated helper/unchanged output-format regression; verify built-in product vocabulary and budget-only exact fields. Update old tests that encoded the contrary empty-field-only assumption.
- Run original independent repro and focused reasoning/provider/usage suites, Ruff/Bandit and reviewer exact-head clearance. No tables of speculative models, dependencies, protected files, global metadata or assets.

Amendment verification: **35 new cases**, 341 focused tests passed in `/tmp/nerva-effort-empty-final.log` (previous command plus `test_reasoning_empty_contract.py`, `test_llm_provider_profiles.py`, `test_provider_context_limits.py`). Combined unit adds72 backend cases. RED23 `/tmp/nerva-effort-empty-red.log` covers the actual wire/omission/budget distinction; RED2 `/tmp/nerva-effort-empty-precedence-red.log` proves a nonempty catalog previously widened an explicit empty constructor declaration. Either explicit empty now wins; nonempty catalog priority otherwise stays unchanged. Original auditor script now records override `{}`, registry `{}`, and built-in budget-only `thinking` (`/tmp/nerva-h679-empty-audit-green.log`).

Whole Ruff/Bandit1.9.4 baseline and scoped Graft freshness pass (`/tmp/nerva-effort-empty-{ruff,bandit,graft-check}.log`). No live provider verification. Source review requested from the auditor who identified the frozen-contract gap; this amendment remains subject to their exact-head clearance.

## Integrated contract reassessment — 2026-09-15

Independent auditor cleared exact a096c148 after 162 guarded tests and the original real-adapter mocked-wire counterexample passed. Root rebased the two source commits without behavior changes onto grid33165622, producing integrated2ca400cc. The full frozen H679 tri-state/no-escalation contract is supported; optional live discovery and a Nebius-specific adapter are not prerequisites. H364 remains partial for its broader vendor coverage. The isolated guarded full integration suite collected 11,559 backend cases: 11,535 passed, 23 skipped and one expected failure, with zero errors or unexpected failures (262.370 seconds, JUnit evidence). No live provider or billing proof is claimed.

Full integration command used `/tmp/nerva-run-isolated.py` with the existing fish4.9.3 binary on PATH and `/usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest -q --junitxml=/tmp/nerva-h679-integrated-full.xml`. Original pytest.ini timeout/thread and loopback-only socket guards were preserved; no addopts override. Logs: `/tmp/nerva-h679-integrated-full.log` and XML. Tracked counts: backend11,559, frontend1,326, mobile140, routes501; frontend/mobile counts retain independently verified unchanged integration baselines.

Standard81 metadata tests pass; Hermes report/status/count checks pass. Release machine checks pass while existing owner/market gates remain unfulfilled: live-model eval, B0 manual signoff and partner feedback, with the missing soak-evidence warning. The release helper's full-suite-skipped warning refers to its separate `--skip-tests` invocation, not the independently completed guarded run above. No live provider or billing claim follows.
