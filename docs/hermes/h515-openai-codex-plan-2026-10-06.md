# H515 OpenAI, Codex OAuth and HUD implementation plan

Goal: finish the full697 objective locally. Base/head:
`a7ffad6676cfb28e7ac374d495b4a5889e5f4646`. Generated:2026-10-06.
Preserve all dirty files; no stage/commit/publication, live paid call, credential
import, dependency install or provider activation. Python3.12 project environment:
`/Users/andrei649/Projects/nerva-hub/.venv/bin/python`.

Pinned donor: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`:
`plugins/image_gen/_common.py` three GPT Image2 tiers;
`plugins/image_gen/openai/__init__.py` generation/edit request construction;
`plugins/image_gen/openai-codex/__init__.py` paired credential/base resolution,
`_build_image_request` and native `images/generations` / `images/edits` HTTP.
Do not substitute hosted image generation through Responses: the pinned donor
explicitly uses native image endpoints. Reuse payload and header rules.

## Shared interfaces and ownership

Backend implementer exclusively owns media_backends/openai_image.py,
new codex_image.py and optional image_provider_catalog.py, cloud_image_runtime.py,
image_tool_dispatcher.py, plugin_gate.py, routers/multimodal.py and focused new
backend tests. Root owns evidence/docs/builds/shared test baselines and the HUD: frontend/src/api/images.ts,
panels/images.tsx, bounded image-proposal display in gap.tsx and focused/new frontend
tests. The attempted separate HUD delegation hit the lifetime thread ceiling;
root implements this independent frontend scope while the backend agent works.

Status preserves old OpenAI fields and adds providers keyed `openai`,
`openai-codex`, `fal`: configured:boolean, enabled:boolean, default_model:string,
models:string[], reachable:null, reason:string. Add per-model edit capability
metadata if required; do not silently infer availability from model inventory.
Existing FAL status fields remain compatible. Selected API/tool backend values
are `openai`, `openai-codex`, `fal` with cloud=true. Legacy OpenAI1.5 default calls
keep their current behavior. Quality-tier model IDs derive wire quality; no
unsupported contradictory quality field is silently discarded. Cloud references
are provider-specific; local artifact IDs keep their existing local limits.

## Steps and acceptance

1. Backend RED actual registered-tool/API proposal for GPT Image2 tier and Codex
   OAuth, then compose into the signed single-attempt worker/artifact pipeline.
   Preserve unknown-no-replay, actor/origin and live configuration validation.
   Credentials resolve as a paired token/base from an explicit owner-configured
   OAuth source. No automatic secret-file import during development. Binding and
   transport must reject untrusted origins; no token can go to model-supplied URLs.
   Generation and edits reuse donor format; artifact inputs must be immutable,
   bounded and owner-admitted, with provider metadata sanitized locally.
2. HUD RED rendered provider/model selection and actual request payload; then
   expose usable configured providers without enabling any. Preserve local
   default, existing OpenAI controls, approvals, unknown-state handling and image
   gallery flow. Show catalog/model-based capabilities and setup gaps truthfully.
3. Both run focused tests after implementation. Root reviews interfaces, runs
   affected backend union, frontend tests/typecheck/build once after source
   freeze, scans exact contents, refreshes only reviewed preimage pins and
   rebuilds/checks Graft. No full H515 credit until all eight routes, Clarity,
   picker/setup and existing lifecycle requirements are actually satisfied.

Rollback: reverse only saved batch diffs against preimages; preserve all inherited
work. Remaining backend/header/auth ambiguity must be reported with concrete
source evidence; implemented refusal is not a claim of working OAuth integration.
