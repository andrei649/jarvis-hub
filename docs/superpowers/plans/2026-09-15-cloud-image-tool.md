# Governed cloud image tool dispatch

Goal: let model-callable image_generate explicitly propose the existing single cloud image provider, with local generation/edit as the default.
Base: dcb0b00be4d2990848a8e1beb10bd68ec5db3ab9. Generated: 2026-09-15. Head: delivery commit containing this plan (resolve with git rev-parse HEAD). Next: independent review and parent integration.

## Contract and architecture

A server-owned dispatcher routes preflight/intake by an exact boolean cloud selector. Local arguments delegate to LocalImageRuntime unchanged after removing the public selector. Cloud accepts only prompt/backend=openai/fixed model/finite size/quality; all local edit parameters and private binding fields refuse. Cloud intake resolves the runtime at call time and calls submit once with the trusted actor and current origin. The existing signed plugin.egress task is the only approval and execution. The ToolRPC execution handler remains local-only; a forged cloud tool.rpc cannot execute or enqueue. Missing runtime refuses without fallback. No new authority, protected policy, provider, endpoint, credential or live call.

The existing worker owns exact approval, taint, one-use claims, cancellation/ambiguous no-replay and artifact/catalog completion. The existing agent loop stops on approval_required. This unit does not implement VRAM swapping or claim whole H515 equivalence.

Paths: new image tool dispatcher, coordinator registration, cloud runtime submit actor parameter, focused tests and this module guide. No assets/global reports/schema routes. Rollback: revert this one unit; local tool and existing cloud API remain available.

## Steps and verification

- [x] RED actual ToolRPC cloud proposal and trusted actor propagation.
- [x] Minimal dispatcher and runtime actor binding; strict invalid option and forged execution tests.
- [x] Actual signed approval/worker/mock HTTP/PNG/catalog, agent loop approval stop, restart/cancellation and unchanged local edit checks.
- [x] Focused tests, Ruff/Bandit, scoped graph freshness, clean owned-path commit and independent review.

No provider calls or GPU required: transports are injected. Existing pytest socket/timeout guards and isolated JARVIS_HOME remain enabled.

## Model-facing usage

`image_generate({"prompt":"blue square"})` preserves local generation. `image_generate({"prompt":"blue square","cloud":true,"backend":"openai","quality":"low","size":"1024x1024"})` proposes one paid cloud image. The only cloud model is gpt-image-1.5; omitted size/quality retain the existing square/low defaults. Cloud edits/upscale and local options are rejected, never silently discarded. Local reference-based editing remains unchanged. The owner accepts/rejects/defers the same task in Decision Inbox and follows its image task/artifact in Images or Gallery.

Each explicit tool request is a new proposal. No automatic resubmission occurs after an ambiguous enqueue acknowledgment: the owner may inspect Inbox for the persisted proposal. Tool calls do not wait for or pretend to complete an approved provider request. A restart or cancellation after possible provider effects does not authorize replay.

## Evidence

Initial RED: /tmp/nerva-cloud-tool-red.log, actual cloud ToolRPC returned local_image_disabled instead of approval_required.
Final isolated pytest: tests/test_cloud_image_tool.py tests/test_cloud_image.py tests/test_local_image_runtime.py tests/test_image_mediation_composition.py tests/test_orchestrator_bindings.py tests/test_agent_runtime_v2.py; 284 passed, zero skips/failures/errors, /tmp/nerva-cloud-tool-final.xml and .log. New test module adds 26 cases. Existing test changes update the local-runtime inspection seam and intentional public tool schema/description, preserving assertions. Fourteen existing binding call coordinates shift +5; AST call nodes are identical to base excluding locations.
Whole Ruff passes. Baseline Bandit 1.9.4 scans agents/scripts with the existing .bandit-baseline.json. Scoped Graft /tmp/nerva-cloud-tool-graft indexes only the three runtime files and media_backends (six files); check confirms fresh wiring, no semantic/provider calls or hooks. Logs /tmp/nerva-cloud-tool-{ruff,bandit,graft}.log. Existing Starlette TestClient/httpx deprecation warning remains; no live provider or GPU verification claimed.

Rollback remains this single dispatcher unit. No generated assets, global assessments or route schemas changed. H515 VRAM orchestration and frozen governance mapping remain separate obligations.

## Integrated validation

Reviewed source rebased onto H679 at 76f68944cbd5133c8454f267d8e4c6685bec5b9c. Full guarded backend: 11,585 collected, 11,561 passed, 23 skipped, one expected failure, zero unexpected failures, 256.66 seconds. Logs /tmp/nerva-cloud-tool-full.log and .xml; status_sync backend count verification passes. Existing socket restrictions blocked Telegram test connection attempts; no guard was disabled. 81 metadata tests pass at /tmp/nerva-cloud-tool-metadata.xml. Whole Ruff and baseline Bandit 1.9.4 pass again after rebase.

Command: PATH=/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin TMPDIR=/private/tmp /usr/bin/python3 /tmp/nerva-run-isolated.py /Users/andrei649/Projects/nerva-worktrees/cloud-image-tool /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest --junitxml=/tmp/nerva-cloud-tool-full.xml. Existing addopts/socket/timeouts were preserved. Frontend1326/mobile140/routes501 are retained integration counts, not rerun by this backend-only unit. Hermes totals remain121 equivalent/327 partial/94 missing/107 excluded/48 needing review.
