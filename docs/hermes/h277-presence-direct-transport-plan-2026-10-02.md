# H277 House presence explanation: direct local transport

Pinned Hermes reference: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Base Nerva revision: `5a721fcb`. The optional House explanation is local by
URL, but its shared LM Studio/Ollama HTTPX client may select a proxy mount.
The URL guard sees the loopback request URL, not the physical proxy hop.

## Contract and sequence

1. Add a failing real-LM-Studio test with an offline instrumented HTTPX proxy.
   An explicit proxy for a loopback endpoint must be refused before the proxy
   transport handles any request. Also cover a direct offline transport and a
   proxy mount inserted by an earlier request hook after the initial check.
2. For strict-local explanations, use the existing
   `require_direct_async_transport` proof both before generation and in the
   final physical-request hook. Preserve the selected shared client and all
   non-strict callers; do not change global LM Studio/Ollama proxy defaults.
3. Run the focused House/H513/route suites, relevant transport regressions,
   Ruff, Graft refresh, generated-report checks and the full backend suite.
   Record the exact results and leave H277 partial. No live provider call,
   publication, merge or deployment.

The proof is scoped to the production HTTPX-backed local adapters. An adapter
that bypasses the shared `llm_async_client` still needs its own binding audit.

## Focused verification checkpoint

The explicit-proxy test failed before the fix because the local URL reached the
offline proxy transport. A second test showed that an opaque generator could
run despite an already proxied selected client. Both pass with the preflight
and physical checks. The initial House/H513/direct-transport union passed 61
tests; scoped Ruff and Graft build/check passed after correction. Two runtime
mutants, one removing the preflight proof and one removing the physical proof,
were both killed by separate focused tests. The exact source/test fingerprints
and subprocess outcomes are in the adjacent evidence JSON. Full-suite and
generated-report results are pending this checkpoint.
