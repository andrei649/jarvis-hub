# Hermes: governed local image generation

Generated: 2026-09-09. Goal: let a configured local ComfyUI instance produce one
image through the existing approved ToolRPC path. Base/head before changes:
`d0a729f846e08c7fb3d35180a31050316c8439c1`. Branch: `codex/hermes-local-image`.
Lease: none. Dependency: existing trusted ToolRPC executor and media manager.

The backend is off unless the owner enables it and supplies a checkpoint name.
Only a literal loopback HTTP endpoint is accepted; there are no cloud providers,
proxy settings, redirects, model downloads, services, arbitrary workflow nodes,
or caller-supplied paths. A fixed standard ComfyUI workflow submits one prompt,
polls that exact prompt's history, validates one PNG output and writes it under
Nerva's media data root. Submission is never retried after an ambiguous failure.

The model and HTTP entrypoint both propose `image_generate` through ToolRPC.
The trusted executor verifies the durable human-approved row. Its backend
fingerprint is minted server-side at proposal and must still match at execution.
The local guard rechecks the same immutable payload, current configured backend,
heavy-feature posture, actual persisted risk tier and original provenance, then
requires an enabled/bound Action Kernel plus durable pre-effect audit. DENY,
absent/invalid verdict and errors refuse execution. FileTools semantics apply:
QUEUE is satisfied only by that exact durable human approval, without rewriting
the verdict, origin or risk tier. An exclusive durable execution claim prevents
concurrent/replayed submissions for one approval, including after restart.
No new Action Kernel kind, protected path or default policy is introduced.

Non-goals: GPU/LLM swapping, image editing, video, cloud generation, activating
the feature, dependency installation and proof on a real ComfyUI/model host.

Likely paths: new `agents/core/media_backends/comfyui.py` and
`agents/core/image_generation_runtime.py`; narrow ToolRPC/executor registration
in `autonomy_coordinator.py`; existing media routes in `routers/multimodal.py`;
focused tests, setup instructions and scope-specific delivery/parity ledgers.

Tests: baseline media/idle image suites (25 passed); backend protocol fixtures
for exact workflow, output bytes, hostile paths/redirects/oversize data, terminal
errors, timeout and cancellation; real queue/coordinator tests for disabled
configuration, accepted execution, changed configuration/payload, duplicate
execution, absent kernel/audit, DENY/QUEUE and inbound taint. Existing route and
ToolRPC tests remain relevant. Mock only the external HTTP transport; never
contact a real generation endpoint.

Rollback: remove the enable flag or revert this single PR. Generated files stay
under the media data root; existing catalog recording remains opt-in. No data
migration or shared-main mutation.

Verification at handoff: 62 focused image tests passed, including real
queue/worker/kernel and authenticated HTTP behavior with mocked ComfyUI HTTP.
The relevant broader set passed 249 tests (media, tool profiles/runtime,
orchestrator bindings, route/OpenAPI/typegen guards, user guard and lifespan).
After the final import organization and explicit API response annotations,
69 focused image/route/OpenAPI/typegen tests passed again, including a final
regression preserving inbound provenance before the worker is bound. Ruff and
diff checks passed. Reviewer independently confirmed the earlier 61 image tests and found no
remaining actionable issue. OpenAPI types were generated using the already
cached 7.13.0 CLI without starting a server or installing dependencies.

Next action: root integration, clean-branch rebase if needed, then PR validation.
No push from the implementation agent. Real ComfyUI/model proof and canonical
mapping for strict mediated queue deployments remain separate requirements.
