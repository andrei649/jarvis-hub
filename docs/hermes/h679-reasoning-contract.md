# H679 reasoning vocabulary contract

The frozen H679 row requires a cached per-model hook with three distinct answers: `None` preserves transport defaults, `()` omits all reasoning parameters, and a nonempty vocabulary uses one monotonic nearest-weaker clamp without escalation. Its Nebius example motivates the shared clamp; it does not require a new Nebius adapter or live discovery service.

## Verified implementation

- `agents/core/llm/providers/__init__.py` exposes the hook. Immutable constructor-owned declarations normalize into read-only mappings; unknown entries return `None` without network or filesystem discovery. `provider_request.py`, `gemini.py` and `hybrid_router.py` bind reviewed built-ins and operator declarations to actual compatible/Gemini adapters. Reconnects and concurrent adapters cannot mutate each other's snapshots.
- `reasoning_effort.py` supplies canonical normalization/clamping. A known request below the supported minimum refuses locally through `ReasoningEffortRefused`, rather than increasing effort or silently restoring a potentially stronger provider default. Compatible, Gemini and Anthropic text/stream/tool entrypoints preserve this refusal before HTTP, retry or usage publication.
- Explicit empty Anthropic declarations remove `thinking` and `output_config.effort`, preserve unrelated output formatting and independent sampling restrictions, and take precedence over nonempty registry/constructor declarations. Actual generate/stream/tool tests cover adaptive, default-on and budget-only families.
- Budget-only families advertise their existing product budget rungs separately from the native effort-field vocabulary. Canonical clamping controls the budget mapping without inventing an `output_config.effort` field. Undeclared models keep their existing request behavior. Empty declarations omit controls; they do not promise that a model's mandatory internal reasoning is disabled.

## Scope and evidence

The original lower-bound and explicit-empty counterexamples were reproduced before repair. Independent review cleared exact source `a096c14881576583d98894ff6219702c58144024` with 162 guarded tests, plus the original actual-Claude mocked request repro: override `{}`, registry `{}`, built-in budget-only `thinking.budget_tokens`. Author verification passed 341 focused reasoning/provider/context/usage tests; the combined unit adds 72 backend cases. The source was rebased without changing the reviewed implementation onto grid base `33165622e61009901f8092025543bb42b985c5ff`, integrated source head `2ca400ccf049c11d2db64ac051a459ce918e440b`.

Operator declarations must match the configured provider's actual capabilities. Existing local transports that do not expose reasoning controls keep their defaults; this contract does not add new native wire schemas. No live provider acceptance, model billing or automatic catalog discovery is claimed. Those limitations do not leave an unimplemented obligation in this frozen request-shaping row. H364's wider vendor coverage remains partial.

Regression files: `tests/test_reasoning_no_escalation.py`, `tests/test_reasoning_empty_contract.py`, `tests/test_reasoning_effort_ladder.py`, `tests/test_reasoning_vocabulary_registry.py`, `tests/test_provider_request_profiles.py`, `tests/test_models_review_regressions.py`. Full integration verification is recorded in [the implementation plan](../superpowers/plans/2026-09-15-reasoning-no-escalation.md).

Integrated full verification: 11,559 collected cases, 11,535 passed, 23 skipped and one expected failure, zero unexpected failures, using the isolated product Python3.12 with unchanged pytest guards. Standard81 metadata checks pass. The separate release machine checks pass; existing live-evaluation, manual-signoff, feedback and soak-evidence gaps remain.
