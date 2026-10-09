# Strict Anthropic token count types

- Generated: 2026-10-09 UTC.
- Base: 5d4f81c3b1d9cbe8f83a454abb373b32d775bf1c.
- Branch/worktree: codex/anthropic-usage-integer-validation-20261009,
  /workspace/jarvis-hub-anthropic-usage-validation.
- Goal: stop malformed metadata becoming observed token counts by coercion.
- Delivery: local; PR #1247 is the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-anthropic-usage-integer-validation.md).

## Behavior and limits

anthropic_usage used int conversion: True became one token, fractions were
truncated, and numeric strings became counts. It now uses the existing strict
count helper for input, output, cache-read and cache-write fields. Only exact
nonnegative integers are retained. Invalid, negative, missing and null fields
normalize to zero while valid sibling fields and the answer remain intact.
Zero remains the existing representation for an unavailable field, not proof
that no tokens were used. A later malformed cumulative stream field replaces
the earlier count; it cannot resurrect a prior snapshot as the final count.

The official Anthropic SDK [Usage type at commit
50b78d17a8a73bef97c3884102310344ac00f056](https://github.com/anthropics/anthropic-sdk-python/blob/50b78d17a8a73bef97c3884102310344ac00f056/src/anthropic/types/usage.py)
declares input/output as int and the two cache counts as Optional[int]. This
supports the wire-type contract, not a claim about SDK runtime enforcement.

Only anthropic_usage changes in production. Other parsers, request bodies,
tool-call parsing, TokenUsage, observers, retry rules and stream terminal gates
are unchanged. Root AST comparison confirms every other module statement and
function is identical. Existing valid cache categories remain disjoint.

Usage presence and completeness remain unresolved: an explicit all-zero report
and absent metadata still collapse to the same value; partial-positive metadata
can still be treated as provider totals by existing consumers. This fix does not
establish a complete turn bill, count physical retries or synthesis, fill CLI
receipt costs, or repair the cache-write pricing approximation. H363 stays partial.

## Verification

The new 22-case module ran before the production change: **15 failures, 7 passes**,
zero errors/skips, 2.204 seconds. Twelve failures cover three malformed types
across all four fields; the remaining failures exercise actual mocked text,
structured-tool and completed-stream responses. Controls retain valid integers,
zero, negative/nonfinite/malformed refusal and valid siblings.

After the fix, the writer's 11-module union passed **462/462**, zero failures,
errors or skips, 11.843 seconds. It includes all new cases, actual runtime sink
delivery, local/cloud/Responses adapters, text/stream observers and context anchors.
Root's disjoint nine-module union passed **191/191**, zero failures, errors or
skips, 6.557 seconds: complete prompt anchors, route compaction, tool runtime,
Claude prefix caching, cost consumers and route/OpenAPI guards. Combined:
**653 distinct passing cases**. No live provider/model or device was used.

Ruff passes both changed Python files. Canonical collection records **21,336
backend cases** (+22), unchanged frontend/native 2,009 and mobile 306, 555 routes
and 18 agents. Hermes, generated-status and whitespace checks pass. The prior
full backend at source 30e0e53d4c65a435317048f0ee61fb05acf2d5a1 passed 21,277
with 37 skipped; it is earlier evidence, not a new full run for this parser fix.
Focused adapters and downstream consumers cover this bounded change; no new
concern required repeating that full suite. Client source and wire schemas are
unchanged; prior client evidence retains its original scope.

## Review and freshness

auth_audit (gpt-6-sol/high) owns parser/tests; mobile_session_transport
(gpt-6-sol/high) independently reviewed the frozen source and nine named evidence
claims; wall_contracts (gpt-6-luna/medium) checked exact base pins. Root owns
integration, documentation and git. No Critical/Important finding remains.

Nine previously current pins are refreshed: tool_dialects in H362/H363/H386/H391/
H392/H557/H673/H678 and architecture in H670. H363 gains the focused test pin and
the bounded fix/remaining-limit wording. H557's affected source coordinates move
back eight lines and point to identical original statements. Every status and
all other semantic claims remain unchanged; no unrelated stale pin is refreshed.

Frozen SHA-256 values:
- agents/core/llm/tool_dialects.py: 4e7ac593d7dfde1a73df0dbf9f3103eb3c58cb4fd6e45c5508d66e501b4c3cf6
- tests/test_anthropic_usage_validation.py: 88981c7d11bae121fc202ec3d763853c105de7d1a735eee7df3618a460a26a9d

Scratch evidence: anthropic-usage-validation-{red,focused,integration}.{xml,log},
anthropic-usage-validation-review.md, anthropic-usage-validation-pin-inventory.{json,md},
anthropic-usage-validation-ast-review.json, anthropic-usage-validation-status-sync.log
and anthropic-usage-upstream.txt.
