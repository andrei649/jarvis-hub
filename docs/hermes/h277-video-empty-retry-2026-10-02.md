# H277 bounded video empty-result recovery

Generated 2026-10-02. Base `afcc652dcc0f5e0caa6ea8b826fb748848abac41`, branch
`codex/h277-video-empty-retry-20261002`. Reference Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`tools/vision_tools.py:_call_vision_llm`. See the
[design](h277-video-empty-retry-design-2026-10-02.md) for boundaries and rollback.

## Delivered behavior

`JARVIS_ROLE_VIDEO_EMPTY_RETRIES=1` permits one restart of the complete approved
video chain after a structurally valid successful response has no visible text.
An empty fallback restarts at the primary. A second empty response refuses;
exhausting a chain on failures alone does not permit another call. Default zero
preserves the existing approval class, notice and result shapes.

The signed class binds this extra budget. The approval notice explicitly discloses
the full-chain restart, including the independent primary transient budget when
enabled. One operation retains its prepared video, question, approved identities
and 180-second deadline. Every send gets a fresh client/body and current task,
kernel, consent, source and route checks, including after client cleanup. At most
two calls each consume `route_count + primary_transient_budget` sends. Enabled
provenance separates consumer-call and per-route attempt indexes without provider
bodies or credentials.

Compatible empty classification requires exactly one explicit `stop` choice with
present blank/null content and no error, tool, refusal or meaningful reasoning
output. Gemini requires one unblocked STOP candidate and valid text parts before
raising a typed empty result. Malformed, blocked, truncated and error-bearing
empty responses do not authorize extra sends. Existing nonempty acceptance stays
unchanged, including Gemini's inherited ignoring of malformed thought parts when
another part supplies visible text; broader output normalization remains open.

## Verification boundary

Four signed ToolRPC-to-worker tests failed before implementation. The final
14-module video/model-role/data-handling/protocol regression passed 647 cases,
including 61 new cases. Tests use native HTTPX clients with offline transports.
They cover both protocols, fallback restart, the 12-send worst case with five
routes, fresh transient budgets, one source download, cleanup revocation, signed
setting drift, deadline/cancellation and a bounded approval notice. Scoped Ruff
and whitespace checks pass. Full-suite and mutation results are recorded
separately against their frozen source; focused checks do not imply those results.

The coordinator and one Sol High writer implemented this bounded change, with a
separate read-only review. No live provider call, frontend change, device acceptance
or coverage-percentage measurement is claimed. H277 remains partial: image and
other-adapter empty recovery, broader output normalization, SDK credentials and
other parameters, provider discovery/cache, progress recovery, larger video uploads
and live/native-client acceptance remain unfinished. This batch remains local.
