# Cloud standalone generated-image digest binding

- Generated: 2026-10-09 UTC. Base/head before edits: `7fe1f27` on `codex/cloud-generated-digest-20261009`.
- Goal: new signed cloud image completions publish through the existing shared generated-PNG helper so their standalone 32-hex IDs receive expected-digest sidecars, while preserving cloud task completion, recovery, catalog, and no-replay behavior.
- Paths: `agents/core/cloud_image_runtime.py`, dedicated `tests/test_cloud_generated_artifact_digest.py`, minimal existing cloud test adjustment only if needed, and this plan.
- Design: retain `_safe` generated-root checks before publication and inside the final live guard. Preserve the pre-publication post-answer governance check; set publication phase before sidecar/storage work, then classify a final live governance decline as `withheld_after_generation` and final machinery failure as `cloud_image_recheck_failed`. Use shared `save_artifact` output for ID, size, dimensions, and completion SHA; keep the completion record shape and independently compare bytes to its SHA during recovery. Bind cloud config generation to the actually imported shared helper implementation and check it has not changed on disk.
- Non-goals: no provider/approval policy or attempt-marker change, no replay, no backfill of existing cloud PNGs, no catalog or cloud completion schema migration, and no change to the shared publisher source. Old sidecar-free IDs remain raw-reader unbound, while completion recovery still checks its durable SHA.
- Tests: red/green signed-cloud one request success and sidecar/digest, tamper raw reader and recovery refusal, restart/no replay, final guard governance/machinery mapping, publication failures, generated-root safety, helper source binding, and occupied-ID collision; focused cloud/local provider and API regressions, Ruff, and diff check.
- Dependencies/limits: depends on committed `comfyui.save_artifact` per-ID reservation and sidecar reader. Helper source rotation can fail closed for old pending cloud approvals. Shared directory sync is best effort; authority-critical attempt marker fsync is unchanged. Local filesystem tamper that removes a sidecar can make raw legacy reading available, but recovery retains its independent completion SHA.
- Rollback: revert this cloud runtime and tests/documentation together. Existing published sidecars remain harmless; completion records and attempt markers are untouched.
- Proof: the dedicated signed-cloud tests first failed in seven expected cases before the source change; they now pass all 11. The final six-file focused JUnit `/workspace/scratch/cloud-generated-artifact-digest-focused.xml` passed 171 tests with zero failures/errors/skips, including old cloud completion/catalog/restart/HTTP behavior and shared local publication regressions. Ruff on the changed Python files and `git diff --check` passed. No full backend suite or live provider call was run here.
- Delivered details: the new final guard runs after the helper links its digest sidecar and just before its PNG link. Governance decline remains `withheld_after_generation`; mediation-store failure and other machinery errors keep their existing failure reasons; unsafe storage and link failures remain publication `unknown`. The completion SHA is still independently compared with recovered bytes even if an old sidecar is absent. Existing cloud record `_write` still handles attempt/proposal/completion records; no test or production changes to that authority path were needed.

Coordinator checkpoint (2026-10-09): frozen runtime SHA-256
`2919f85246f9bb3ec40f60cac5567998adffa3bbb5c0fe0f393d0b3732ca18eb`.
The focused six-file union passed 171 cases; five disjoint integration suites
(local runtime, typed view, signed mediation and local/catalog digests) passed 163.
The independent gpt-6-sol/high reviewer ran the new 11-case module and found no
Important/Critical finding; builder used the same model/effort, inventory used
gpt-6-luna/medium. Reports: `/workspace/scratch/cloud-generated-artifact-digest-{focused,integration}.xml`.
Existing cloud test files are unchanged. Full collection reports 21,106 backend
cases (+11); frontend 1,962/mobile 284/routes 554 are unchanged. Ruff, diff and
generated project/Hermes freshness checks pass. A combined full-backend milestone
for both standalone digest units follows this source checkpoint; its result is
not yet claimed here. No live/paid provider or device execution was performed.

Only previously current cloud-runtime evidence pins H285/H477/H515/H518 were
refreshed after scoped review; H285's `_available` citation moves from line 183 to
188. Existing test pins, unrelated evidence and all verdicts remain unchanged.
H477 narrows only the new built-in cloud standalone gap; legacy and broader
contracts remain partial. This unit remains local and is not in PR #1247.

Combined milestone (2026-10-09), verified source `5c0985c`: full backend **21,069 passed, 37 skipped, zero failures/errors** out of 21,106 cases in 266.284 seconds. Exact-count and generated freshness gates pass. This later run covers both local and cloud standalone digest units; earlier notes keep their checkpoint scope. [Integrated proof](../project-generated-image-integrity-integration-20261009.md).
