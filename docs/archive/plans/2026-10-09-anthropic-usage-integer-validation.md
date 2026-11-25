# Strict Anthropic token count types

- Generated: 2026-10-09 UTC.
- Goal: prevent malformed Anthropic metadata from being coerced into observed
  token counts while preserving a valid answer and valid sibling fields.
- Base / HEAD before edits: 5d4f81c3b1d9cbe8f83a454abb373b32d775bf1c.
- Branch/worktree: codex/anthropic-usage-integer-validation-20261009,
  /workspace/jarvis-hub-anthropic-usage-validation.
- Scope: autonomous local provider-parser bug fix; no live requests/publication.
- Next action: this bounded local fix is verified; retain the separate usage
  presence/completeness and whole-turn attribution gaps.

## Contract

anthropic_usage currently calls int on provider values. True becomes one token,
fractions are truncated, and numeric strings become counts. Require exact
nonnegative Python ints, matching the existing neighboring usage parsers and
the provider's integer wire fields. Reuse _local_count per field. Invalid,
negative, missing and null fields stay zero; retain other valid field values.
Do not infer cache detail counts, replace valid siblings, discard an answer,
or fall back to an earlier cumulative stream snapshot after a malformed delta.

Official SDK type evidence, reviewed 2026-10-09: anthropics/anthropic-sdk-python
commit 50b78d17a8a73bef97c3884102310344ac00f056, src/anthropic/types/usage.py.
input_tokens and output_tokens are int; cache_read_input_tokens and
cache_creation_input_tokens are Optional[int]. This is wire type evidence,
not a claim about SDK runtime strictness or proof of token/accounting completeness.

Change only anthropic_usage in production. Preserve the numeric TokenUsage
shape, its existing nonzero-based reported predicate, observer behavior,
stream terminal gates, tool execution, prompts, retries and other parsers.
Explicit zero versus missing metadata, partial measurement completeness,
physical-attempt coverage, synthesis and complete per-turn cost remain separate
gaps. No new CLI receipt numbers or claim that a turn was free.

## Ownership and verification

- auth_audit (gpt-6-sol/high): agents/core/llm/tool_dialects.py and new
  tests/test_anthropic_usage_validation.py. Capture meaningful RED for booleans,
  numeric strings and fractions; include negative/nonfinite/malformed controls,
  zero and valid integer/sibling preservation. Exercise actual mocked text,
  structured/tool and streaming responses, including late malformed cumulative
  input/cache replacement with valid final output. No provider network.
- mobile_session_transport (gpt-6-sol/high): independent frozen code/claim review,
  no overlapping writes. Confirm consumers and stream gates retain their scope.
- wall_contracts (gpt-6-luna/medium): affected evidence-pin inventory, read-only.
- Root: plan/proof, architecture/backlog and generated status, integration/git.
  At most four active agents, no nested delegation.

Run focused parser/adapter suites, then disjoint usage observers, runtime billing
and prompt-anchor consumers. Ruff, exact source-scope check, relevant route/
schema checks and canonical collection follow. Broaden only for a concrete
failure or unresolved concern; the preceding full backend at source30e0e53
remains earlier evidence until another full run is warranted. Keep original
scope on reused client results and preserve already-stale evidence pins.

## Rollback

Revert this parser change, regressions and supporting evidence as one local
unit. No data migration, public schema or deployment requires rollback.

## Completed verification

New module: RED 15 failures and 7 passes before the fix, 22 cases total.
Frozen writer union: 462/462 in 11.843 seconds. Root's disjoint downstream union:
191/191 in 6.557 seconds. Combined 653 distinct passing cases, no failures,
errors or skips. Ruff and exact AST scope checks pass. Independent review has
no Critical/Important finding. Only anthropic_usage changes in production.

Canonical collection is 21,336 backend (+22), frontend/native 2,009 and mobile
306; routes remain 555. Hermes/status/whitespace checks pass. Nine named fresh
pins are refreshed, H363 gains its new test evidence and explicit limits, and
H557 coordinates point to the same source statements after the eight-line shift.
Every status and other semantic claim is retained. The preceding full backend
result at 30e0e53 remains earlier evidence; this narrow parser change is covered
by the focused adapters and integration consumers. No live provider/device test
or new frontend run is claimed. Details: docs/project-anthropic-usage-validation-20261009.md.
