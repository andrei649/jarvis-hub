# H277 same-provider retry investigation

Read-only investigation, 2026-10-02. Pinned Hermes
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`; no implementation or live call.
This is the next design input after native Gemini video integration, not an
acceptance claim or a change to the current single-send contract.

## Observed reference behavior

- `tools/vision_tools.py:_call_vision_llm` uses `async_call_llm`, then calls it
  once more if extracted analysis is empty. This is an additional consumer-level
  attempt, distinct from auxiliary transport recovery.
- `agent/auxiliary_client.py:async_call_llm` retries the primary once on a
  classified transient transport failure before entering the recovery ladder.
- `_is_transient_transport_error` recognizes connection/stream failures and
  HTTP 408/5xx; `_should_retry_same_provider` also checks critical-path timeout
  exclusions. The broader reference classifier uses exception names/text as well
  as status. Copying it verbatim would weaken Nerva's typed guard isolation.
- The synchronous `call_llm` has a separate configurable 0–6 retry count (default
  two) with exponential backoff. That count does not describe the inspected
  asynchronous video call path, which performs one immediate transient retry.

Reference file SHA256:

- `agent/auxiliary_client.py`:
  `736dc25cab3ee014c88d156449ed16596bf214a0f70966e78582e71f86bb2c68`
- `tools/vision_tools.py`:
  `baf2ec9e09422ca2437dc603b3fe3b7b7c170dbc9d884ce9ff0e2d67aca7f288`

## Design work still required

Nerva currently permits one physical model send per approved candidate. A retry
must be an explicit bounded authority change, with its policy bound into the
approval and rechecked before every send and after cleanup. Retain the total
execution deadline, source reuse, independently scoped credentials and consent,
fresh per-attempt bodies and refusal of hook/policy/cancellation failures.

Keep transient retries separate from authentication/payment/provider fallback
and from an empty-output retry. Native blocked or malformed successful responses
must not become retry permission merely because they contain no visible answer.
The existing no-chain HMAC compatibility contract needs an explicit migration or
opt-in design before increasing the send budget. No retry implementation is
authorized by this investigation alone; the standing project goal supplies scope,
and the next written design must resolve these contracts before code changes.
