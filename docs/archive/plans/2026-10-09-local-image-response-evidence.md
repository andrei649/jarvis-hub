# Local image provider-response evidence

- Generated: 2026-10-09 UTC.
- Goal: let the existing web/native image state distinguish a narrowly proven
  invalid local OpenAI-compatible provider response from an unknown outcome.
- Base / HEAD before edits: `662cd4c3d522f6e508a5300aeee56fdf85d508e5`.
- Branch: `codex/local-image-response-evidence-20261009`.
- Worktree: `/workspace/jarvis-hub-local-image-response`.
- Delivery: autonomous local development under the owner directive; no push,
  merge, deployment, live provider or changed approval authority.
- Next action: failing producer/integration and strict projection regressions,
  then implementation in separately owned files.

## Bounded design and alternatives

The existing local runtime catches an ImageGenerationError, preserves its reason,
and lets MediaGenManager wrap it as a generic failed result. A bare reason does
not identify the backend or producing phase. Inferring failure from current
configuration or broad existing reasons would misclassify old/ambiguous tasks.
Adding a separate signed attestation system is outside this bounded readback
change. Instead preserve a fixed typed discriminator minted at reviewed branches
of the existing local OpenAI image adapter. The current public `failed` state and
its limited copy already serve this meaning; no client/schema change is needed.

`media_backends/local_openai_image.py` owns these private names:

- `_RESPONSE_FAILURE_REASONS`: the five exact strings `backend_http_error`,
  `invalid_response`, `response_too_large`, `invalid_image`,
  `image_dimensions_mismatch`.
- `_RESPONSE_FAILURE_MARKER = "local_openai_images_v1"`.
- `_ProviderResponseFailure`, an ImageGenerationError subtype, minted only at
  observed negative response branches after the one fixed POST yields a response.

Nonredirect non-200 HTTP, invalid JSON headers/length/body/schema/base64, excessive
response size, invalid decoded PNG and wrong dimensions are included. Catch only
the shared PNG validator's exact invalid_image outcome for conversion. Generic
exceptions and guard failures do not acquire this subtype. Redirect/encoding
policy refusals, HTTPError/timeouts, submission unknown, withheld generation,
guard/config/source/approval failures and publication failures remain uncertain.
ComfyUI's ambiguous generation_failed remains unchanged. There is no retry.

LocalImageRuntime captures this subtype before the manager's generic catch and
adds `provider_response_failed: "local_openai_images_v1"` only to that failed
result. The existing reason is preserved. The resulting queue DONE envelope is:

```json
{"status":"failed","reason":"<allowlisted>","tool":"image_generate",
 "result":{"ok":false,"reason":"<same>",
           "provider_response_failed":"local_openai_images_v1"}}
```

Projection requires exact ordinary dict/key/type shapes shown above, matching
allowlisted reasons, exact marker, DONE, canonical `tool.rpc`, plain payload with
tool and target both image_generate. Other/legacy/malformed/extra-key results
remain uncertain. The existing route's positive non-bool equal-ID check and admin
guard remain intact. Valid local ready parsing and cloud verified recovery remain
unchanged. Public output contains only task_id, failed and null artifact; no raw
reason, prompt, URL, path or provider content. This is typed evidence inside the
queue's trust domain, not independent protection against complete DB forgery,
proof of no work/charge, or permission to retry.

Changing the existing adapter/runtime sources changes their existing approved
source fingerprints. Old approvals fail closed; old persisted results without
the marker remain uncertain. No migration or ToolRPC/manager change is needed.

## Ownership, checks and rollback

- auth_audit (gpt-6-sol/high): local_openai_image.py,
  image_generation_runtime.py, tests/test_h517_provider_integration.py and
  tests/test_h517_local_provider.py. Producer subtype, propagation, real signed
  queue/worker/HTTP response regressions, one POST/no replay/no PNG or catalog,
  timeout/guard/publication exclusions. Run RED before changes, then focused tests.
- mobile_session_transport (gpt-6-sol/high): image_generation_view.py and
  tests/test_image_generation_view.py. Strict local projection with literal test
  envelopes, exclusions, auth/no-store/redaction and existing cloud/ready behavior.
  Coordinate imports against the fixed names above; no other file edits.
- Root: plan, cross-review, integration, collateral freshness, BACKLOG/parity/HUD
  evidence, generated status, git. Optional read-only inventory agent: pins only.
- No nested delegation or overlapping writers. Existing dependency environments
  are reused. The base has a complete green backend milestone; no duplicate
  baseline suite is needed. Run meaningful focused RED/GREEN, combined provider/
  runtime/projection/mediation tests, Ruff and route/metadata guards, then one full
  backend milestone. No frontend/mobile rebuild is needed unless their contract
  or source changes. Compare skipped IDs and refresh only previously current pins
  after named claim review; preserve already-stale pins and unrelated verdicts.
- Rollback: revert this typed producer marker, runtime propagation, strict local
  projection, regressions and associated evidence as one local unit. Old/new rows
  then use the prior uncertain projection; no stored approval or artifact changes.
- H18.27 stays partial for remaining ComfyUI/ambiguous evidence and physical-device/
  live-generator acceptance. This is not a claim that all image outcomes are known.

## Implementation and focused results

Producer RED exposed 15 missing typed/durable evidence failures; projection RED
exposed five allowed outcomes still uncertain. Frozen source now uses the exact
private type plus allowlisted reason, preserving the marker through the existing
manager/ToolRPC envelope. The projector checks all planned shape/type/identity
constraints. Six real signed-worker negative-response cases also verify public
admin readback, one POST, no artifacts/catalog, direct replay refusal and no later
dispatch. Timeout/policy/publication and matching-reason guard outcomes stay
unmarked and publicly uncertain. No authority/client/schema changes occurred.

Producer focused union 233/233 and independent projection 87/87 pass. Root's
broader 13-file provider/runtime/API/ComfyUI/cloud/artifact/route union passes
474/474, zero failures/errors/skips. Ruff passes on all six changed Python files.
Canonical collection yields 21,199 backend cases (+45), 555 routes; client counts
remain 2,009 frontend/native and 306 mobile with their prior milestone evidence.
Cross-review found no Critical/Important issue. Named bounded claim review
supports 11 formerly current pin replacements; H312's stale runtime pin and all
claim/verdict/remaining strings are preserved. Public model ASTs and the runtime's
seven other methods/nested authority guard are unchanged.

The complete backend milestone at source
`b5fc19c55553923a2c463c84d5d5d916fcfa17a4` passes: 21,162 passed,37 skipped,
zero failures/errors,21,199 total in 264.508 seconds. The skipped IDs match the
previous image failure milestone exactly, and executed count verification agrees
with collection/tracked inventory. The source tree was frozen for the run; only
these final evidence notes follow it. No frontend/client/schema/build rerun or
remote/live-provider acceptance is implied. Full evidence:
[local response integration](../project-local-image-response-20261009.md).
