# H515 Krea Enhance and managed-provider follow-through

**Goal:** Port Hermes' optional native Krea Enhance pass into a separately approved, usable Nerva image workflow, then continue the managed Nous image contracts. All 697 capabilities remain the mission.

**Authoritative state:** Existing dirty consent worktree, branch `codex/h487-owner-consent-20261003`, head `a7ffad6676cfb28e7ac374d495b4a5889e5f4646`. The previous turn made progress: Krea continuation, xAI and dynamic DeepInfra were implemented and verified with 786 affected backend, 1965 full frontend and 120 record/route/schema tests. No files are staged.

**Donor:** The pinned archive at `/Users/andrei649/Projects/hermes-source-59b2aeef6c7a/hermes-agent-59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`, specifically `plugins/image_gen/krea/__init__.py:_enhance_image` and its provider tests. Its native request is one POST to `/generate/enhance/krea/enhance` with `image_url`, `image_scaling_factor=2` and the source prompt, followed by existing job polling. Enhance is opt-in, preserves the original generation on failure, and may change detail.

**Architecture:** Retain a validated Krea result URL privately in the original completion, alongside the existing artifact hash. An explicit `enhance_task_id` operation resolves an already completed original Krea generation to that exact source, prompt, model and 2x request. A new signed POST approval binds the source task, artifact and execution identity; it cannot alter the original result or implicitly run after generation. The existing bounded Krea job executor and fresh GET continuation handle enhancement output and interruptions. No arbitrary local path, provider fallback or credential-bearing result GET is accepted.

**Uncertainty/fallback:** Historical completions without a retained provider URL cannot be enhanced through this source operation. Provider URLs may expire; a refused enhancement preserves the original artifact. Enhance output must support 2K-to-4K through a scoped 4096px/16MiB decoder, a private completion-bound artifact proof and authenticated reader; default local generation/PNG/reference limits remain unchanged. Larger than 4K output remains an explicit separate gap. Managed Nous contracts are being inspected from pinned source before selecting a transport or credential seam.

**Ownership:** Root owns shared runtime, tool/API and final integration. One retained `gpt-6-sol` High agent owns only the pure Enhance adapter/tests; the other initially maps Nous read-only, then may own bounded frontend files after the shared interface is fixed. No child delegation.

**Paths:** `agents/core/media_backends/krea_enhance.py`, scoped optional bounds in `comfyui.py`/`fal_image.py`, `agents/core/cloud_image_runtime.py`, `agents/core/image_generation_view.py`, `agents/core/image_tool_dispatcher.py`, `agents/core/routers/multimodal.py`, image-provider HUD/API/card tests, generated schema/build, and relevant Hermes/mobile/HUD records. Preserve unrelated paths and pre-existing stale evidence.

**Integration amendment:** The gallery and portable export also use `media_library.read_catalog_blob`, whose normal PNG sniffer retains the 2K limit. Extend only completed generated Krea Enhance rows through the same private completion/proof/hash/pixel metadata, so the new result remains downloadable and exportable. Keep cache, attachment upload and edit-reference limits unchanged. Add real binary download/ZIP and invalid-proof regressions before closing this batch. `agents/core/media_library.py` is included in the saved preimages.

**Current provider contract:** The official [Krea Enhance reference](https://www.krea.ai/docs/api-reference/image-enhance/krea-enhance) confirms the pinned POST path, Bearer auth, async jobs, default factor 2 and an image URL maximum of 1024 characters. Its documented `gen.krea.ai/images/...` result origin is admitted explicitly by the default-off Krea manifest; no other response-derived CDN admission is added. This is documentation verification, not live/provider acceptance.

## Steps

- [x] Adapt the pure Enhance request/endpoint/wire contract and donor assertions; RED then GREEN.
- [x] Add behavior tests through the real signed worker for explicit source approval, exact one Enhance POST, canonical output, source preservation, failure/no replay and continuation after interruption.
- [x] Persist source result URLs privately; implement strict source descriptor and current authority/hash checks, reuse Krea polling and artifact completion.
- [x] Add exact `enhance_task_id` API/tool forms and owner-visible availability; integrate HUD action and immutable approval card without changing local bicubic upscale.
- [x] Finalize records and exact text scan after the completed focused review and milestone suites; verify source manifest and graph freshness.

**Boundaries:** Local only. No stage, commit, push, merge, deploy, credential import, provider activation, paid/live calls, dependency installation or global configuration changes. No kernel/queue authority redesign. No equivalence credit until the complete H515 requirements are met.

**Rollback:** Restore only this batch's exact preimages from `/tmp/nerva-h515-krea-enhance-baseline-20261006`; never reset the checkout.

**Wrap-up authorization:** On2026-10-06 the owner requested publication of all current work and a next-session prompt. The local-only development boundary above is superseded for this checkpoint push/draftPR; no merge into main or deployment is requested.
