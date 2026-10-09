# H515 provider reuse batch

Goal: all 697 capabilities, local-only. Base/head:
`a7ffad6676cfb28e7ac374d495b4a5889e5f4646`. Generated: 2026-10-05.

Current cloud runtime is OpenAI-specific; the local registry supplies ComfyUI and
OpenAI Images. The asset gallery catalog is not a provider model catalog. Preserve
existing generation attempts, governance, output publication and no-blind-retry
behavior while extending the provider seam.

Pinned donor: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Verified reuse sources:

- `tools/image_generation_catalog.py`: `FAL_MODELS`, default model and Clarity model.
- `tools/image_generation_tool.py`: `_resolve_fal_model` and catalog-filtered payloads.
- `plugins/image_gen/fal/__init__.py`: provider adapter and capabilities.
- `plugins/image_gen/openai-codex/__init__.py`: OAuth image request construction.
- `agent/image_gen_registry.py`: provider discovery/selection.

Next coherent implementation: port the FAL catalog and generation/edit payload
normalization into a Nerva provider adapter, composed under the existing cloud
attempt/artifact lifecycle. Use synthetic transport fixtures for all catalog
payload families, malformed responses, absent credentials and no-submit failures.
No provider activation, API spend or credential import is authorized by this batch.

Then adapt Codex OAuth and the remaining frozen routes (OpenAI tiers, Krea,
OpenRouter, xAI, DeepInfra and managed Nous), Clarity, and discovery/setup.
The existing ComfyUI unload/restore and native-image limitations remain open;
do not declare a catalog port to be complete image parity or a VRAM swap.

Likely owned paths: `agents/core/media_backends/` plus narrowly scoped provider
composition in `cloud_image_runtime.py` and corresponding tests. Before editing,
freeze that batch's interfaces/preimages and demonstrate missing dispatch in a
failing integration test. Rollback only that batch's diffs, preserving inherited
changes. This plan is the next batch, not evidence of implemented functionality.

Model-producer integration (coordinator, 2026-10-05): extend only
`agents/core/image_tool_dispatcher.py` plus new `tests/test_fal_image_tool.py` so
registered `image_generate(cloud=true, backend=fal)` reaches the same signed
cloud attempt. Demonstrate missing dispatch in RED; keep trusted actor/origin,
local artifact-reference limits and the single approval. The existing route and
cloud runtime remain the implementation agent's exclusive files. Preimage:
`/tmp/nerva-h515-model-tool-baseline-20261005`.
