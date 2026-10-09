# Ollama parsed-response counter availability

- Generated: 2026-10-09 UTC.
- Base: de70661489cd5c69b245de23186d77ece040629f.
- Tested source: 8363102c85a78e584aae9cce520def9e70c80607.
- Branch/worktree: codex/ollama-counter-availability-20261009,
  /workspace/jarvis-hub-ollama-counter-availability.
- Delivery: local. PR #1247 remains the separate earlier publication.
- [Plan and rollback](plans/2026-10-09-ollama-counter-availability.md).

## Behavior

Ollama normalized each prompt/eval counter independently but did not retain
whether both were supplied. A positive input count with missing output could
therefore become a provider measurement of that input and zero output. A later
tool response with neither count was silent and could leave an earlier observed
aggregate looking complete.

Only ollama_usage changes production behavior. counts_complete is True when
prompt_eval_count and eval_count are both exact nonnegative integers, including
a valid zero pair. Missing or malformed fields make it False; valid siblings
survive. Booleans, numeric strings, floats, nonfinite values, negatives and
containers are not accepted as counters. TokenUsage.reported retains its legacy
nonzero predicate, and as_dict retains its four numeric fields. Cache/total
metadata does not introduce a discount or inflate prompt occupancy.

The existing text observer and tool runtime now receive explicit incomplete and
valid-zero Ollama observations. Accounting labels incomplete observations as
estimated and preserves known token lower bounds. A later unavailable tool
response marks the observed aggregate incomplete. Positive prompt counts remain
useful anchors independently of output availability; output-only or zero input
does not replace or erase an existing anchor.

Actual mocked non-stream /api/generate and /api/chat regressions intentionally
omit done and preserve accepted HTTP/JSON behavior. Streaming still requires
literal done is True and retains its existing error, malformed-frame, transport
and cancellation gates. Answers, tool calls, request shapes and other providers
are unchanged. The other 28 functions and all other module AST are identical.

## Verification

Root checked the unchanged production hash for the builder RED: 26 cases,
22 failures and 4 passing controls, 2.381 seconds, zero errors/skips. Initial
consumer RED: 87 cases, 17 failures and 70 passes, 3.512 seconds. Thirteen of
those failures exercised the production gap; four were an empty tool-registry
fixture refusing before HTTP. Those four are not claimed as production RED.
After registering a benign offered tool, root restored only the parser to the
exact base and confirmed all four actual runtime cases failed for missing
availability flags or missing zero events: 1.169 seconds, zero errors/skips.
The candidate was then restored and frozen.

- Final ten-module focused union: **292/292**, 5.389 seconds. Covers both new
  modules, existing local/compatible accounting and anchors, actual text/stream
  publication, and cloud tool dialects.
- Root's disjoint thirteen-module integration: **344/344**, 8.004 seconds.
  Covers tool protocol/runtime, other provider usage, scoped observers, cost
  metering, compaction, provider context limits and route/OpenAPI guards.

Combined: **636 distinct passing cases**, zero failures/errors/skips. Ruff and
diff checks pass. Canonical collection records **21,450 backend cases** (+41),
unchanged frontend/native 2,009 and mobile 306, 555 routes and 18 agents.
Hermes/status checks pass. Client counts are reused; no client run is claimed.

No new full backend run was needed for this one-function parser change after
the preceding milestone. The latest full result remains **21,372 passed and
37 skipped**, 312.491 seconds, at **42013de7435c08f7bee91257d7c7f7fd2091366c**.
That historical full result is not relabeled as this source's validation.

## Review and limits

auth_audit (gpt-6-sol/high) owns the parser and direct regressions;
mobile_session_transport (gpt-6-sol/high) owns actual propagation regressions
and independently reviews the frozen parser. wall_contracts (gpt-6-luna/medium)
inventories exact-base pins. Root owns scope, critical review, integration,
documentation and git. No Critical or Important finding remains.

All 12 affected evidence pins were current at base and are refreshed after
bounded claim review; two new test pins are added to H673. All 226 capability
statuses remain unchanged, as do unrelated stale pins. H363/H673 availability
wording and the architecture inventory now include Ollama. H557's same-target
Gemini dialect coordinates move by six lines; its schema behavior is unchanged.
H670 identity behavior and H686's missing live status readout are unchanged.

Availability describes only the counters of an observed parsed response. It
does not prove complete physical attempts, retries, silent failures, auxiliary
calls or a whole-turn bill. Other unflagged providers retain legacy availability
behavior. No live provider, model server, billing service, device or GPU was
used. There are no new routes, settings, client contracts or persistent changes.

## Frozen evidence

- Production SHA-256: 898fa6e43eafe2dd8b59b5d204a0a15199ca63d69f5f0f6d9e4cf2072743d62e.
- New parser tests: 7cdb54e30b7ceabf71ec59f24f366d2cb1360935cdf5ca6b22972991163e235c.
- New propagation tests: e41f404fc697b87fc212ef74f744e4e639d3f4614536d5c053803d0e4f024403.

Scratch artifacts under /workspace/scratch use the ollama-counter-availability
prefix: builder-red, consumer-red, runtime-red, focused and integration XML/log
pairs; source-manifest.json, base-hashes.json, ast-review.json,
pin-inventory.json/md, pin-refresh.json, consumer-review.md, claim-review.md,
and status-sync.log. The source manifest includes both adjusted existing tests.
