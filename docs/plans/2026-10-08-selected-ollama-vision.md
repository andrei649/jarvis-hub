# Selected Ollama image turns

- Generated: 2026-10-08 16:10 Europe/Bucharest. Base: `8a02ff345bf81f4a2f162714567a59c185245099`. Branch: `codex/nerva-vision-20261008`; implementation head pending commit.
- Goal: send a reviewed image to the exact selected native Ollama model for the current turn and retain bounded image context only after success, with fresh owner review before reuse.
- Non-goals: Hermes runtime, cloud provider/SDK expansion, Krea, video, broad image generation, unrelated routing changes.
- Likely paths: `agents/core/llm/vision_ollama_wire.py`, narrow selected-backend adapter, image-history helper, `agents/core/routers/composer_vision.py`, `frontend/src/vision-turn.ts` and `frontend/src/composer-images.tsx`, focused tests. `frontend/src/app.tsx` is reserved for the parent after its other writer completes.
- Tests: red H277 regressions on base, focused Python 3.12 selected image/normalization/history/composer tests, relevant frontend tests/build and Ruff. Preserve decode/body bounds, consent, destination, provenance, and late review gates.
- Rollback: revert one local implementation commit. Source recovery reference `fc47ce039dc1d3279b38eac9d7fce6ce86983b74`; parent owns global ledgers, schema/assets and remote integration.
- Current paths: selected Ollama helpers under `agents/core/llm/`, memory and continuation seams, `agents/core/orchestrator.py`, `agents/core/routers/composer_vision.py`, `frontend/src/cockpit.tsx`, `frontend/src/composer-images.tsx`, `frontend/src/vision-turn.ts`, and focused tests.
- Next action: integrate the reactive selected session ID and agent into both App InputBar callers after the session work lands; selected drafts with no session ID remain disabled. Parent then updates generated OpenAPI/schema/assets, status/parity ledgers, and runs integration gates.
- Verified locally before commit: selected/history/legacy Composer/session/empty-retry and non-video normalization Python tests, three Composer frontend test files, frontend typecheck/build, and Ruff. The video normalization fixture uses a Windows local path and returns `bad_video_url` before its assertions; no video code changed.
