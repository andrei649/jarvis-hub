# Local integration path for cumulative V69 with V70 integration repair

Verified 2026-11-13. No publication, staging, commit, merge, deployment, Windows write or security-code change is authorized/performed by this assessment.

## Exact candidate

- Current remote main: `1338833d5a344d277c43828a9d9314e10af792f1`.
- Original working base: gateway head `686fcbf4f25ebfbb416b3a35dff29045163cffbd`, six commits above main.
- PR #1359 remains open, draft and unmerged on that exact head. Its mergeability is not approval and its prior CI cannot validate the dirty continuation.
- Source checkout: 181 modified tracked files, 8 tracked deletions, 250 new files, none staged; 439 changed paths against gateway head (V69 had 438; V70 repairs one generated API chapter).
- Main-based cumulative patch: `main-to-v70.patch`, 463 changed paths, with `final-main-source-manifest.json` and `FINAL-MAIN-APPLY-RECEIPT.json`.
- A complete isolated main tree was reconstructed and patched. All 7,302 checked tracked/new paths match the original candidate, including unchanged files and deletions.

Use one cumulative patch on its named base; never apply V1 through V69 sequentially. No rebase/reset is needed in the dirty source checkout. Ordinary `git diff` omits the 250 untracked files and is not a complete delivery.

## Resolved local assembly obstacles

1. The original checkpoint was gateway-head-relative, not main-relative. The new complete main-based patch directly resolves that prerequisite ambiguity.
2. New runtime/tests and eight replacement UI chunks were untracked. They are included in the patch and manifest; eight old chunks are removed consistently.
3. HUD/Workspace assets were rebuilt in the isolated full main candidate using the existing dependency tree, without installs. All 27 generated files are byte-identical before/after and match the original source checkout.
4. A read-only Windows comparison input and script are supplied. The script was verified on the Linux source against all 463 candidate paths, and static path checks found no case collisions or Windows-invalid names.

## Windows coordination

No Windows checkout was available to this executor. Dot's visible 2026-11-13 11:29 UTC report says no new lost code was found in three untracked Windows files; it supplies neither the checkout HEAD nor file hashes. Treat this as historical context, not a current conflict clearance.

On the authorized Windows host, a coordinator can run the following read-only command with the actual repository and transferred report folder paths:

```text
python compare-checkout.py <repository> windows-comparison-input-final.json
```

It writes JSON to stdout, reads Git metadata with optional locks disabled, compares candidate/main/gateway hashes, distinguishes probable UTF-8 CRLF-only differences, and skips symlinks. It neither checks out nor applies anything. A divergent hash is a review item, not automatically a conflict or proof of missing functionality. Review exact divergent paths before any future integration on that host. Windows execution itself is not claimed here.

## Before publication can be considered

1. Finish the fresh full Linux backend run, preserve its exact candidate identity, and run backend-count and Hermes-area guards on that same JUnit. Triage actual failures without relaxing security/parity controls; leave environment/platform and prohibited security changes explicit.
2. Use `EVIDENCE-AUDIT.md` for source-linked frontend/native/typecheck receipts and the exact PR CI commands. Do not convert collected backend counts, historical mobile Jest or a successful patch application into execution success.
3. Obtain the Windows metadata/hash comparison or explicitly limit the first integration to the verified Linux candidate. Do not overwrite unknown Windows work.
4. Coordinate overlap with draft #1359 before publishing another branch. A stacked continuation PR on the gateway branch avoids taking over Claude's draft, but a main-targeted cumulative PR must explicitly include/reference those six gateway commits. No option is executed here.
5. If a smaller feature PR is desired, extract a dependency-complete unit in a disposable checkout and test it separately. V69's three CLI files alone do not work on main: owner session pagination/checkpoint support and prior transcript validation are prerequisites. Directory-based splitting is insufficient where commands, channels and orchestrator overlap.
6. After explicit publication authorization, create the chosen branch/commits from the verified candidate, include all required new files/assets, and require the triggered CI checks on the resulting SHA. No permission for staging/commit/push/PR mutation is implied by this document.

The cumulative candidate includes prior kernel/security-sensitive work. This session makes no new security-code changes and does not relabel that cumulative scope as security-neutral.

## Verified remediation before the final complete run

Initial full run:36,678 cases;36,217passed,212failures,141errors,108skipped. All353affected cases were individually matched to a controlled501-case rerun and all353passed (none missing/skipped); that rerun total466passed/35skipped/zeroerrors.

346affected provider/action-auth cases traced to this container's `/tmp` owner65534mode01777 while processUID1000. Existing guards correctly reject that writable ancestor. Per-test TMPDIR and fresh basetemp under an owned private workspace avoid it without changing any guard/ancestorpermission. Three terminated-process cases saw zombies under PID1(`tail`); private outer Linux subreaper launcher reaps only its own descendants, never signals processes and preserves child exit. Four API sweep tests needed one generated documentation repair. No runtime/security-source change was made.

The original red JUnit/countPASS/HermesareaFAIL and controlled rerun are retained, not overwritten or combined into a synthetic full success. The fresh complete run with corrected test plumbing passed36,570/108skipped,zero failures/errors; both same-JUnit guards passed,23Hermes areas. See FINAL-VERDICT.md and FINAL-BACKEND-RECEIPT.json. Missing gitleaks/semgrep/pip-audit remain explicit future CI coverage, not local success.
