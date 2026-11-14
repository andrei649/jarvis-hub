# V70 final cumulative integration verdict

Verified 13 November 2026. The cumulative delivery is mechanically integrable on the pinned current main and has a green complete Linux backend run in a suitable test environment. It is uncommitted/unpublished; there is no candidate GitHub SHA or PR CI receipt. Windows checkout contents remain unobserved.

## Git and scope

Remote main1338833d5a344d277c43828a9d9314e10af792f1 and gateway branch686fcbf4f25ebfbb416b3a35dff29045163cffbd were rechecked at completion. Main is the local HEAD merge base; six gateway commits are above main. PR1359 remains draft/open/unmerged on that head. Local branch codex/hermes-continuation-20261112 has181modified tracked files,8deletions,250untracked files:439dirty paths, zero staged. Complete main delta463paths includes gateway prerequisites and all new runtime/test/asset files.

The only repository repair in this assessment is regenerated docs/test-manual/14-api-surface-sweep.md (44insertions/42deletions). No runtime/security-source change, source reset/rebase/staging/commit, security-control weakening, system-permission change, Windows write, publication, merge/deploy or service activation was performed. Prior cumulative kernel/security changes remain in the candidate and need deliberate review; this large candidate is not a security-neutral CLI-only PR.

## Resolved obstacles and exact evidence

- Direct main integration ambiguity resolved: main-to-v70.patch applies to a complete isolated main tree. FINAL-MAIN-APPLY-RECEIPT.json confirms all7,302tracked/new paths match the source candidate after application, with463changed paths and patchSHA256fa5282c490a55fddda600489486d14adf9d254ee7d96417735b4e9635aab25ab. final-main-source-manifest.json pins changed bytes/deletions.
- Required untracked files/assets included. Isolated HUD+Workspace build succeeded using existing dependencies;27generated files were byte-identical before/after and to the source checkout. No installs.
- Initial full test run truthfully preserved:36,217passed/212failed/141errors/108skipped of36,678.346provider/action-auth cases traced to `/tmp`UID65534mode01777, correctly rejected by existing guards for UID1000;3terminated fixture processes remained zombies under non-reaping PID1;4API chapter tests caught stale generated route documentation.
- Remedies are test plumbing plus generated documentation: fresh owned TMPDIR/basetemp, private outer Linux subreaper (only own descendant wait/reap, no signals), and the normal API-doc generator. Existing unsafe ancestor permissions and guards unchanged. Independent review matched every original353bad node to the501-case controlled rerun: all353passed, none missing or skipped. Whole rerun466passed/35skipped/zero failures/errors.
- A second complete run was then performed rather than combining partial results: FINAL-BACKEND-RECEIPT.json exit0, full source snapshot7,302paths unchanged before/after. `/tmp/nerva-v70-final-backend.xml`:36,570passed,108skipped,zero failures/errors,36,678total. Exact-JUnit backend-count guard passed and all23Hermes area suites passed. No keyword filter or disabled safety assertions.
- Fresh full mobile Jest420/420 passed. Frontend, E2E and mobile TypeScript exit0. FINAL-POSTCHECKS.json verifies the source snapshot remains unchanged after these checks.
- Whole-repository Ruff passed with0findings; canonical Bandit0newfindings/errors; lockfile check, selfdev policy validate/selftest, API chapter check, Hermes metadata check, generated status and whitespace checks all passed. Logs/receipts included.
- Frontend Vitest3,178 (2,883browser+295native) is reused V66 evidence, not a fresh V70 execution. Its32changed frontend paths match current bytes; current mobile source matches V66, and isolated fresh build/typechecks strengthen linkage. This is source-level/fixture acceptance, not live browser/device proof.

108skips remain explicit in FINAL-SKIP-REASONS.json:35require isolated Playwright+installed Chrome,9fish,8bubblewrap namespaces,7liveNeo4j,7dedicated Docker containment,6rustc, Windows-native lanes and other opt-in/host checks. They were not silently converted into passes or enabled by activating services. Metadata inventory697 remains171equivalent/482partial/8missing/36excluded; passing area suites is not a claim that the partial backlog is complete.

## Windows and external limits

No actual Windows checkout/HEAD/dirty hashes was available in this executor. Dot's historical11:29UTC note found no lost code in3untracked files but cannot clear current conflicts. compare-checkout.py and windows-comparison-input-final.json supply a read-only463path comparison against candidate/main/gateway, including line-ending distinctions. Linux selftest matches463candidate paths; static repository names have0casecollisions/Windows-invalid names. Windows script execution is unclaimed. See PR-PATH.md; never overwrite unknown Windows work.

Gitleaks, semgrep and pip-audit are unavailable locally and were not installed/run. Their future triggered GitHub checks remain required evidence on the eventual published candidate SHA. Branch-protection settings were not queried. Linux full tests/typechecks/builds do not establish Windows E2E, physical devices, live channels, containment or provider-account acceptance. No legacy unsafe history was reconstructed; V66 archive provenance findings remain valid.

## Minimum remaining path

1. Obtain the read-only comparison from the actual Windows checkout, or explicitly scope the initial review to the verified Linux candidate while retaining the Windows gap.
2. Coordinate overlap with draft#1359. The cumulative candidate includes its six gateway commits; choose the documented main-based or stacked continuation lane when publication is explicitly requested. Do not take over/reset Claude's branch or the dirty original checkout.
3. On the chosen isolated target branch, apply exactly ONE correct-base patch: main-to-v70.patch on main1338833d, or continuation.patch on gateway686fcbf4. Include all new files and generated asset replacements. A narrower feature PR needs its own dependency-complete extraction/test evidence.
4. Only after publication authorization, create branch/commits/PR and obtain all triggered CI/security checks on that actualSHA. This assessment stages/commits/pushes nothing and performs no merge/deploy.

See independent DELTA-AUDIT.md, EVIDENCE-AUDIT.md, PROVIDER-ENV-RCA.md, PROCESS-RCA.md and REMEDIATION-REVIEW.md for dated findings and limitations. Earlier reports intentionally preserve their then-pending/red state; this final verdict and exact final receipts provide the current result. MissionControl handoff r06 is included; Drive upload/scheduling unconfirmed.
