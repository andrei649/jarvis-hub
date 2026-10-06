# H515 collateral source review

Date: 2026-10-06. Base: c6a855183b26a8b45200d47834565d69aa6dcb0f.
Goal: retain the existing partial image assessment after the typed environment
reader repair; importing Hermes earns no native-equivalence credit.

The reviewed change in `agents/core/media_backends/codex_image.py` replaces raw
environment reads with the shared `env_flag`/`env_str` readers. Default-off and
explicit owner configuration remain. The credential resolver still requires the
official Codex origin, current expiry and account identity. No existing credential
file is discovered or imported. The existing runtime still binds the provider,
configuration and source bytes into canonical approval before a request.

Re-read the current Codex resolver and request shape, its actual mediated HTTP
producer/worker tests, and Krea Enhance source/host revalidation. The dedicated
review run passed all 77 cases in `test_cloud_image_codex`,
`test_openai_codex_image`, `test_cloud_image_krea_enhance`,
`test_cloud_image_krea_enhance_guards`, `test_cloud_image_openrouter_krea`,
`test_image_options_extended` and `test_media_library`. HTTP providers were
injected; this is no entitlement, paid-provider or live-device acceptance.

The regenerated OpenAPI types add Hermes administration paths without changing
image contracts. The mobile/HUD documentation additions describe Hermes owner
administration; image limitations remain. Removed hashed Vite bundles are replaced
by the build, so this assessment keeps the registered UI source and its tests as
stable evidence, rather than pinning obsolete bundle filenames.

H515 remains **partial**. Preserve all recorded open managed Nous, credentials,
catalog/storage/output, local memory/lease coordination, mobile and live
acceptance requirements. This review refreshes evidence for the existing claim;
it neither closes the inventory row nor credits the runtime catalog.
