# H515 managed Nous image contracts

Read-only next-batch map, not an implemented provider or entitlement claim. Source is the pinned Hermes archive `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`: `tools/image_generation_managed.py`, `tools/managed_tool_gateway.py`, `tools/fal_common.py`, `tools/image_generation_tool.py` and the Krea/OpenRouter plugins. No credentials were imported, no gateway was activated and no provider request was made.

The [official Nous Tool Gateway guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway) documents explicit per-tool Nous selection, OAuth coverage, a combined image picker and separate paid/free-pool eligibility. Native Krea and Portal models require a paid subscription; an available free pool funds FAL models only. Catalog membership and an existing OAuth token do not establish entitlement. A direct-provider key never silently reroutes an explicitly selected managed provider.

## Reuse and integration

| Donor contract | Nerva adaptation |
| --- | --- |
| Managed catalog combines FAL, native Krea IDs and Portal models; model ID chooses the gateway. | Preserve explicit managed selection and backend labels. Bind the admitted catalog and selected backend/model into approval. Do not treat catalog discovery as an entitlement proof. |
| Gateway bearer uses Nous OAuth access token. | Existing `NousAuthService.peek_credentials` is inference-specific; `usable_inference_token` may prefer an agent key. Add a narrow managed-access-token reader over the existing encrypted store, retaining issuer/client/profile/quarantine/expiry checks. Never use an inference agent/API key as gateway Bearer or import Hermes credentials. |
| FAL managed submission returns request ID and response/status/cancel URLs, with an idempotency key. | Separate approved submission from bounded GET continuation; bind returned origins/IDs. The donor's generic 429 POST retry cannot bypass Nerva's one-attempt payment rule. |
| Native Krea uses `https://krea-gateway.nousresearch.com`, then same-origin authenticated `/jobs/{id}` GET. | Reuse the native image/Enhance bodies and polling adapter. Bind managed principal and transport independently from direct `KREA_API_KEY`. |
| Portal images use `https://inference-api.nousresearch.com/v1/chat/completions`, text/image modalities and model discovery. | Reuse result parsing/pixel admission. Manifest the fixed origin, bounded catalogs and exact wire contract separately; preserve explicit model selection and no fallback. |
| Managed uploads may involve presign POST plus an R2 PUT. | Treat upload as its own authorized workflow. Do not hide extra POST/PUT requests inside image approval. |

## Unfinished contracts

Before activation, verify the OAuth scope/audience accepted by each current gateway and the catalog/result/CDN contracts from authoritative sources or injected contract fixtures. The inspected inference-only helper does not prove those contracts. Gateway 401/403/402 remains the entitlement/refusal boundary; no paid entitlement probe is part of local development. Keep adapters and credentials separate from chat inference routing. The existing local-only sprint and all 697 capability requirements remain in force.
