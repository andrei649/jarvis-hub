# H277 video → vision route fallback plan (2026-10-02)

Status: implementation and focused tests complete; final full backend passed on
`78780b64` (20,108 passed, 34 skipped, one expected failure). See the
[milestone report](h277-video-analysis-2026-10-02.md) for exact scope and remaining work.
Base implementation: `732f34ac`. Coordinator decisions: use existing Nerva role/VLM
variables only; do not add Hermes environment aliases or config.yaml import. An
explicit video provider/base retains its own routing and requires its own model.
Without those route overrides, a valid vision route supplies the endpoint and model
unless VIDEO_MODEL names another model. Credential inheritance requires the exact
same provider and normalized complete native endpoint. No provider failure retries,
new paid services, publication, or deployment are authorized by this plan.

## Pinned behavior to match

Reference: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`, `tools/vision_tools.py` SHA256 `baf2ec9e09422ca2437dc603b3fe3b7b7c170dbc9d884ce9ff0e2d67aca7f288` (matches `docs/hermes/evidence/h277-current-2026-10-01/upstream_sources.json`). `tools/vision_tools.py:902-912,1070-1078` picks the first nonblank model from `auxiliary.video.model`, then `auxiliary.vision.model`, then `AUXILIARY_VIDEO_MODEL`, then `AUXILIARY_VISION_MODEL`. `"auto"` is normalized away by `agent/auxiliary_client.py:6072-6101`. The video tool builds `video_url` content, then `_aux_call_kwargs` sends `task="vision"` (`vision_tools.py:657-677,1018-1042`): provider/base URL/key, timeout/temperature and configured provider failure chain therefore come from `auxiliary.vision`, not `auxiliary.video` (except that video model preselection). `_resolve_task_provider_model` uses explicit call arguments before `auxiliary.vision.*`; vision `key_env` is resolved within its credential scope (`agent/auxiliary_client.py:6072-6140`). `resolve_vision_provider_client` uses a configured vision endpoint first, otherwise the main vision-capable provider, then `openrouter`, `nous`, `deepinfra` (`auxiliary_client.py:5498,5581-5708`). Its runtime failure ladder can try `auxiliary.vision.fallback_chain`; an unavailable explicit vision provider without base URL can also fall back to auto (`auxiliary_client.py:7240-7260,4371-4430,7665-7730`). The top-of-file prose names a different auto chain; use the current implementation order above.

## Smallest safe Nerva adaptation

This batch is **resolution fallback to one destination before approval**, not failure-driven provider switching. Nerva has no `auxiliary.*` YAML route in this path; map the model categories to env names while retaining existing H277 roles:

1. Model precedence for an inherited route: nonblank, non-`auto` `JARVIS_ROLE_VIDEO_MODEL`, then the model actually resolved by the configured vision adapter (`JARVIS_ROLE_VISION_MODEL`, legacy `JARVIS_VLM_MODEL`, or that adapter's valid default). No new `AUXILIARY_*` aliases are introduced here. Source provenance must identify the winner. An absent vision configuration preserves the existing explicit-video behavior; an invalid configured vision route must not silently select another destination.
2. Provider and endpoint: only when both `JARVIS_ROLE_VIDEO_PROVIDER` and `_BASE_URL` are absent may a valid vision role supply its actual provider and native request URL. An explicit video route remains explicit and needs its own model; it must never borrow a foreign endpoint, model or key. Existing fully configured video behavior stays unchanged. `auto` video-model selection is a Nerva adaptation; upstream's helper also has a truthy-whitespace early break before the vision section, which this contract does not reproduce.
3. Key: `JARVIS_ROLE_VIDEO_KEY` remains the video-specific credential. With no video key, borrow the *effective* key from `resolve_vlm_config` only if the video request URL is byte-for-byte the same normalized native Chat Completions URL as the vision adapter would use. This permits LM Studio's `http://localhost:1234` versus `.../v1` spelling when both send to `.../v1/chat/completions`; it refuses same-host/different-path, different scheme/port, or provider changes. Reuse the vision resolver's existing guarded `JARVIS_VLM_KEY` / `JARVIS_ROLE_VISION_KEY` selection; never read those keys independently or fall back to a global OpenAI key. If the vision route has userinfo/query or a wire mode the native video adapter cannot speak, fail closed as today. No key travels to a destination for which it was not resolved.
4. Put one pure effective-video-route resolver in `model_roles.py` (or a dedicated helper there) shared by `resolve("video")`/role listing and `video_policy.describe_video_data_target()`, with the key kept out of the public role row and `repr`. For an inherited vision endpoint, use the actual vision native request URL, including nonstandard configured path, rather than the video adapter's default `/v1` suffix guess. Preserve existing explicit-video behavior and unsupported Ollama refusal. `VideoIdentity.binding`, `role_target_scope`, and `class_binding` must cover final provider/model/base/request URL/authorization. Intake, signed execute, each source/model physical request, and final disclosure already re-resolve the identity: changing any inherited setting or key must stale the approval/role acknowledgment before bytes leave.
5. Existing remote controls still apply to an inherited route: explicit per-call `allow_remote`, `JARVIS_ROLE_VIDEO_ALLOW_REMOTE`, independent `role:video_analysis` consent, safe mode/strict-local/cloud_fallback/local-only-agent checks, selection guards, direct transport and exact physical request guard. No second physical destination can be tried under the first approval. A later provider-failure fallback needs an enumerated, owner-reviewed candidate set with a separate per-candidate consent and wire binding; do not add it here.

Decision examples: video model `clip-reader` with no video route override plus configured vision `openai-compatible` at `https://vision.example/v1` selects `clip-reader` on that exact endpoint; without a video model it selects the resolved vision model. An explicit video provider/base requires its own model. A video destination differing from the vision native endpoint never inherits its key, including a same-origin path change. No automatic provider retry is authorized.

## Owned implementation paths and tests

Implementation: `agents/core/llm/model_roles.py`, `agents/core/llm/video_policy.py`, and only if needed `agents/core/video_analysis.py` to consume the shared effective route. Tests: `tests/test_h277_model_roles.py` and `tests/test_h277_video_analysis.py` (or a focused `tests/test_h277_video_fallback.py`). Parent owns `.env.example`, `docs/FLAGS.md`, H277 evidence/ledger and generated artifacts after code settles. No frontend, router, or data-handling schema change should be necessary: the existing video consent target's scope derives from the effective identity.

Eight focused offline tests:

1. Video-specific model + configured vision provider/base/key sends the video model over the inherited *exact* vision request URL and auth, via MockTransport.
2. No video model selects the configured vision model; public role listing and physical request agree, without exposing the key.
3. Parameterized precedence matrix for video role model, vision role/legacy/default model, absent vision configuration, blank and `auto`, with source provenance.
4. Explicit video provider differing from vision refuses missing video model and never inherits vision base/key; with a video model it uses only its own endpoint.
5. Same-origin but different native request path drops the vision key; a dedicated video key works only under the newly approved configuration and rotates the class/consent scope.
6. Existing `JARVIS_VLM_KEY`/`JARVIS_ROLE_VISION_KEY` origin guard is preserved when the video route inherits vision; changing the vision role base drops or changes the inherited key.
7. After a signed approval, changing inherited vision model/provider/base/key or disabling vision blocks before source HTTP/model physical I/O (and revocation during cleanup withholds output). Recomputing the existing approval class may read the selected scoped local file to verify its hash; zero local reads are not part of this contract.
8. An inherited remote vision route still needs per-call remote approval and its own video role consent/privacy posture; a simulated model failure does not dispatch to another provider under that approval.

Run these with the repository's normal pytest addopts (socket/timeout guards retained) and existing focused H277/H513/image-mediation tests. No live or paid call. Baseline `9d5b3add` lacked `video_analysis.py`; static source comparison is baseline evidence, not an isolated baseline test result.
