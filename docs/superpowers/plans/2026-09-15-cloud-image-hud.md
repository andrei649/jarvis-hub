# Cloud Images owner workflow

Base d3a0c09ee772f3d1b1ac17f29869e75900f2ef66. Generated 2026-09-15. Parent owns integration, generated bundle and global evidence; this worktree owns only cloud status, Images client/panel, narrow inbox rendering/navigation, tests and this guide. Accepted design from prior read-only review; implement inline with TDD, no subagents or live provider calls.

## Contract

Expose optional cloud_image capability through existing user-guarded media status: fixed OpenAI gpt-image-1.5, finite standard sizes/qualities, approval required, reachable unknown. Status checks local availability only and never creates config records, signs/proposes work or calls a provider. Missing capability on an older hub leaves local generation intact; malformed cloud data cannot enable cloud. No public credential/digest/generation or network health claim.

Images defaults to local. Cloud mode creates only a new image and sends exact prompt, cloud:true, finite size and quality; local model/checkpoint/edit/references/upscale cannot leak into that body. Request remains one-attempt, with ambiguous response never automatically retried. Configure/status/auth failures are distinct from successful202 queued approval.

Decision Inbox recognizes the exact cloud-image plugin.egress payload, displays immutable exact prompt/provider/model/size/quality and paid operation notice, and reuses accept/reject/defer. Changes require a new proposal; no generic edit/preview for cloud image. Use existing prefix-aware console navigation and an Images task query return link; strict positive safe integer only, no implicit submission. Existing bounded polling, guarded artifact reader and object URL lifetime remain. Watching stops only observation, not server work. Gallery is the existing catalog/reader/export; catalog-off is accurately explained.

## Steps and verification

1. RED/GREEN read-only cloud capability method and router tests: configured/unavailable, no calls/no records/no secrets, local status preserved. Files cloud_image_runtime.py, routers/multimodal.py, test_cloud_image.py.
2. RED/GREEN strict frontend capability parsing and explicit proposeCloudImage serializer, local compatibility and one-attempt ambiguous responses. Files api/images.ts and test/images-api.test.ts.
3. RED/GREEN Images provider controls, no local-option leakage, provider-neutral task status, prefix-aware inbox/task return and immutable cloud inbox. Files panels/images.tsx, gap.tsx, focused React tests. Keep original approval/action guardrails.
4. Actual browser under a nonempty prefix using temporary isolated app, actual authenticated routes/signed worker and HTTP mock provider: cloud proposal, inbox approval, task return/read, artifact/gallery/export. No production lifespan/channels or paid provider; build only temporary fixture assets, parent owns shipped bundle. Test cancellation/task switching and object URL cleanup through existing +focused regressions. One Vitest worker.
5. Focused backend/frontend, both TypeScript checks, scoped/full Ruff and baseline Bandit as appropriate. Independent review before source handoff. Graft scoped cache freshness; no secrets/generated trees/deep paid indexing.

No new authority, provider URL/model selection, API credentials UI, secret policy or protected files. Capability alone does not promise service reachability; unknown task outcomes remain unknown. Broader H515 provider/control catalog remains outside this unit.

## Evidence and remaining verification

Implemented steps 1–4 after observed RED status/serializer/UI/navigation/inbox tests. Three new backend status cases and nine new frontend cases cover the added surface; existing local generation tests remain green. Focused backend 93 pass (cloud runtime/status, localimageflow/view and route/OpenAPI guards). Browser workflow passed both 1440×900 desktop and Pixel7 with a nonempty `/nerva` prefix, actual route/worker/approval/artifact/catalog/export, providerHTTPMockTransport only. Fixture uses one canonical temporary root and temporary Vite output under `/tmp/nerva-cloud-hud-assets`, never shipped assets. A generic1280 desktop gallery width assertion failed before using the established1440 fixture size; this unit does not certify all existing gallery breakpoints.

Navigation uses ordinary canonical prefix-aware links, so an inbox roundtrip reloads the route. Its `image_task` query only selects a strictly validated existing task for guarded reads; it grants no authority and cannot submit a proposal. Dedicated Playwright tests live outside the generic e2e directory and are explicitly included in the e2e TypeScript program.

Final verification: 93 focused backend tests, 84 focused frontend tests, two prefix browser cases, both TypeScript programs, whole Ruff and baseline Bandit1.9.4 passed. Scoped API TypeScript Graft wiring build/check is fresh in /tmp/nerva-cloud-hud-graft (no deep indexing). Pinned cached openapi-typescript7.13.0 regenerated only the existing202 response description, removing the local-only wording. Independent source review and parent integration remain pending. No provider was contacted, no new dependency installed, no protected files edited and no full backend suite claimed.

## Review correction

Independent review found the initial browser test saved the inbox link before approval, hiding that the accepted row disappears. Two observed RED regressions now require a surviving visible decided-task return link and task-ID URL state. Inbox retains that link after a successful decision; Images records task ID on202/manual watch while preserving unrelated history/query/hash, and clears it on New proposal. The browser now clicks the visible post-decision link (no cached-href navigation). Added one frontend case; ten new frontend cases total. Final corrected focused frontend85 and both TypeScript checks pass; browser is rerun against rebuilt temporary assets.

## Root integration

Independent review cleared ef2f7b57 with93 backend,85 frontend and two actual click-only prefix browser cases after the navigation repair. Root integrated the same source with scheduled media, effective tool windows and script workdir; all1,326 frontend tests and all three TypeScript programs pass, and the production bundle is regenerated. Full backend verification follows the metadata update. H515 remains partial for model-callable cloud selection, real VRAM orchestration and explicit frozen action-kind mapping; the accepted adaptation does not require eight cloud providers. A separate root repair addresses the independently reproduced1280px background cockpit overflow, with its own failing browser regression.

Final root full backend:11,487 collected,11,463 passed,23 skipped and one expected failure; no unexpected failures (`/tmp/nerva-cloud-hud-integrated-full.xml`,258.622 seconds). All1,326 frontend tests, all three TypeScript programs, Vite bundle, whole Ruff and Bandit1.9.4 baseline pass. Independent source and browser review remains attributed to the exact repaired source rather than claimed as a live provider run.
