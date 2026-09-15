# Approved cloud image completion implementation plan

Goal: one exact human-approved OpenAI image POST produces a validated local artifact and idempotent opt-in catalog record. Base: 669919ff1c6475d3ff5decb9ad1dd75a54736d39. Generated: 2026-09-15. Head: working branch codex/backlog-cloud-image. Next action: independent source review, followed by parent integration. Parent owns integration, global evidence, bundle and publication.

## Contract and scope

A real `cloud-image` plugin manifest/adapter, not the cloud-llm text method, owns the fixed HTTPS OpenAI generations endpoint. Existing OPENAI_API_KEY configuration is read through env_config only; no credential is inspected, printed or persisted in task payloads. Fixed gpt-image-1.5, n=1, PNG, finite quality and size. Reject unsupported image edits/upscale/seed/steps rather than silently reinterpret them. Official reference: https://developers.openai.com/api/reference/resources/images/methods/generate (GPT image responses are base64; PNG and standard sizes supported). No provider SDK/dependency, arbitrary endpoint, artifact URL fetch, redirect, automatic network retry, or live/billable test.

A strict plugin.egress discriminator binds method, endpoint, exact normalized body, credential configuration generation, adapter version and artifact persistence intent. One human approval and one signed worker execution claim; QUEUE alone never grants execution. Compose URL/cloud discriminator routing before the existing worker consumes its permit once. URL monitor's guard and semantics remain intact; unknown plugin.egress payloads refuse. Fail closed if enforced mediation, signing, kernel, configuration or required redact boundary is unavailable. Recheck after DNS immediately before dial. Persist an exclusive attempt marker before the only POST; cancellation/crash/timeout after possible submission is unknown and never automatically replays.

Bound response transfer/JSON/base64/raster bytes and dimensions. Require exactly one fully decoded static PNG matching approved dimensions; no remote path/URL controls local writes. Strip untrusted metadata through validated raster re-encoding. Atomically create an opaque artifact in existing generated root. Persist a bounded completion receipt before optional catalog finalization; catalog failure remains visible, and local finalization may retry without provider execution. Use a stable per-task catalog identity with serialization so retry cannot duplicate or lose concurrent records. Respect JARVIS_MEDIA_CATALOG opt-in: no prompt catalog when off. Public response exposes opaque artifact and semantic status only, never raw provider response/path/credential. Uncertain attempts never become success from queue DONE alone.

## Files and steps

1. RED/GREEN bounded OpenAI request/result schema and honest plugin manifest: new media_backends/openai_image.py, plugin_gate.py, tests/test_cloud_image.py.
2. RED/GREEN signed approval/execution and durable no-replay/artifact completion: new cloud_image_runtime.py, narrow coordinator dispatcher composition, tests using actual TaskQueue/worker and mock transport.
3. RED/GREEN stable serialized catalog add + restart/local-finalization tests: media_catalog.py, cloud runtime tests; preserve existing local add interface.
4. RED/GREEN actual guarded media route/status/result projection into gallery/export: routers/multimodal.py plus existing image result view only if necessary, no frontend/bundle until runtime works. Cloud options get an explicit finite schema, local bounds unchanged. Existing unsupported cloud video/thumbnail do not enter this image executor.
5. Focused regression suites for URL monitor, local image, media catalog/gallery/export/routes, worker permits and plugin manifest; Ruff/type/schema checks appropriate to actual changes. No protected path edits, no global status/count edits.

## Acceptance and rollback

Tests must cover no transport before approval; forged/wrong-kind/wrong-discriminator/mutated/config-stale approval; after-DNS DENY/e-stop; one permit consumption; fresh no-cookie transport; redirect/error/oversized/invalid base64/truncated/animated/decompression refusal; successful route→actual signed worker→mock response→artifact→catalog→gallery/export; duplicate/restart/concurrent calls; cancellation and ambiguous POST no replay; filesystem/catalog failure and local-only recovery; opt-out and redacted errors. All network is mocked, all files under isolated temporary roots. Roll back this coherent source/test/module-plan unit; existing task/artifact records remain inert and unknown tasks cannot auto-replay. H515 remains a bounded increment rather than all Hermes providers/controls.

## Implementation evidence (2026-09-15)

- Steps 1–4 implemented with observed failing schema, runtime, recovery, route, profile and strict-type regressions before their fixes. The API increment does not change the Images HUD's local-only authoring.
- 33 new cases in `tests/test_cloud_image.py`; 417 focused integration cases passed, zero failures/errors/skips in `/tmp/nerva-cloud-final.xml`. Coverage includes actual signed worker and guarded routes, canonical artifact/gallery ZIP bytes, URL-monitor one-permit composition, DNS-time stop, provider failures/cancellation, restart recovery, opt-out, catalog deletion and concurrent catalog writers.
- Whole-repository Ruff passes. Existing baseline Bandit (`agents scripts`) passes with inherited comment-parser warnings. No protected files or dependencies changed.
- Both frontend TypeScript checks and existing OpenAPI/route guard tests pass. Existing shared node_modules is linked locally; no dependency changes. Final 33-case cloud suite also passes after strengthening the PNG metadata fixture.
- Pinned cached openapi-typescript 7.13.0 regenerated exactly four schema lines for finite optional size/quality fields; no route additions. Parent owns final frontend bundle/global evidence.
- Scoped Graft wiring build/check for `agents/core/media_backends` passes (3 Python files, 21 nodes); cache `/tmp/nerva-cloud-graft` is outside the repository, no deep/semantic indexing.
- Standard test launcher: `TMPDIR=/private/tmp /usr/bin/python3 /tmp/nerva-run-isolated.py WORKTREE /usr/bin/env NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest ...`; launcher supplies isolated canonical JARVIS_HOME, JARVIS_TESTING and disabled dotenv. Network/provider transport is mocked throughout.
- Operator contract and known limits: `docs/cloud-image-generation.md`. Live provider billing and end-user cloud HUD authoring have not been exercised or claimed.

## Independent review correction

The reviewer found the required redactor was not invoked. Five fake-only actual queue regressions failed before the fix: known secret, broker exception, non-string screening, newly known secret after approval, and newly known secret during DNS. Validation now requires exact unchanged string output from the broker before persistence and at the existing pre-dial validation, with generic refusal and no approved-body rewrite. This adds five cases (38 new total), with no protected edits or live calls.

## Root integration evidence

Independent review repeated 135 cloud/local-image/catalog/export tests after the
secret-screening repair. Integrated with per-job model selection, the first full
11,380-test collection found four expected registry-inventory differences from the
new cloud-image manifest. The readiness snapshot adds exactly that wired plugin;
all 104 previous entries remain unchanged. Three fixed-count reality checks now
include the new real policy case. All 95 registry/cloud/Hermes checks pass after
the repair; the complete backend suite is rerunning before merge. No live or
billed provider request was made and no capability was promoted to VERIFIED.
