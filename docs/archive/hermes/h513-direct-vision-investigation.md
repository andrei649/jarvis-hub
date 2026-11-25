# H513 remaining direct vision callers

Read-only investigation, 2026-09-27. Base/head:
`bd2bb70ead1b493043a335e77713fc42c47d4013` plus local sprint changes.
Goal: prepare the next bounded direct-vision policy slice after the verified
composer/embedding milestone. Investigator: gpt-6-luna, medium; no source edits,
provider calls or acceptance tests. These findings are not delivered functionality.
Next action: coordinator design with explicit camera-policy and provider identity
decisions before delegating implementation. Changed paths in this investigation:
this document only.

## Actual dispatch owners

- `agents/core/channels/media_reader.py`: inbound Telegram photos use the resolved
  vision-role configuration and require loopback before download and inference.
  `InboundImageReader` constructs `VLMBackend`, checks `is_local`, calls vision
  generation, and converts its failure sentinel to `vlm_failed`. No cloud fallback;
  captions are excluded from the inference prompt. Telegram sender allowlisting is
  conditional on configuration, so an inbound image must not inherit owner
  authority merely because it arrived through Telegram.
- `agents/core/screen_locator.py`: `LocalVLMLocator` supplies a visual fallback
  after accessibility misses, only for configured loopback VLMs. The locator is
  potentially model-directed. No production call of `build_local_vlm_locator` was
  found; the desktop runtime builds its driver without a locator. Verify this
  wiring gap before claiming usable visual fallback. Kernel authority for later
  desktop actions remains a separate boundary from screenshot inference.
- `agents/core/routers/multimodal.py`: user-authenticated `/api/vlm/describe` and
  `/api/screen/reflex` require a loopback vision configuration, then construct a
  native backend directly. Describe additionally evaluates model-selection guards
  and supports a request model override. It currently returns `ok: true` even if
  the native backend returns its error sentinel; screen reflex instead reports
  `generated: false`. Preserve route authentication and honest failure semantics.
- `agents/core/cameras/runtime.py` and `agents/core/cameras/vlm.py`: unattended,
  default-off camera ingestion requires configured household consent, camera VLM
  enablement and per-event description enablement. Its separately configured
  endpoint/model must be loopback; only bounded masked PNG frames reach the model.
  The native backend uses empty API-key configuration. Errors or unsafe descriptions
  become no description, never remote fallback.
- `agents/core/screen_reflex.py` is a protocol/core with an injected generator,
  not a configuration or dispatch owner. Gates belong at the verified native
  adapter/caller boundary; do not describe arbitrary injected generators as local.

## Shared boundary and decisions still required

Vision-role configuration resolves role settings before legacy VLM environment
settings. Native `VLMBackend` uses `llm_async_client('vlm')`; that hook only enforces
H513 when a physical request scope exists. These independent callers currently
have no such scope. A plain `VLMBackend` also lacks the provider profile required
by generic data-handling authorization. Introduce a truthful explicit provider/
model/destination identity; do not infer authorization from mutable `is_local`.

The candidate shared adapter must bind the configured and prepared POST URL,
effective model/Authorization, actual direct transport and request lifetime, with
fresh policy/configuration checks. Local-only owned clients should ignore
environment proxies. Generic factories retain their existing contract. Composer
and judge proxy behavior remains a separately recorded gap; the embedding fix did
not change those clients.

Camera VLM has a custom compatibility endpoint rather than a declared LM Studio
profile. Its training policy is therefore unknown under the existing registry,
even on loopback. Household camera consent is not a provider-data acknowledgment.
Choose and document a usable, configuration-bound owner acknowledgment/warning
surface or another truthful explicit policy contract before implementing unattended
authorization. Do not silently label a custom endpoint no-training or borrow the
primary provider/judge consent. Strict-local callers must never gain remote use.

The next implementation must test actual consumers, fresh wire/configuration races,
ordinary error fallbacks, pre-inference refusal and the desktop wiring claim. No
project-wide direct-VLM coverage or live provider acceptance is established here.
