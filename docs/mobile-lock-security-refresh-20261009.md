# Mobile lockfile security refresh

Generated: 2026-10-09 05:19 UTC. Base at implementation: `da7c8a222c2cd0cb658b192c967194bc9c88efa3`; branch `codex/mobile-lock-refresh-20261009`. Next action: preserve this reviewed local candidate for integration; remaining dependency advisories and physical-device acceptance stay open.

Goal: resolve currently reported npm advisories where a compatible transitive version can be selected by the existing direct Expo 58 / React Native 0.87 / Jest 30 dependency ranges, with special attention to `shell-quote` command injection.

Non-goals: changing any direct SDK/runtime/test version, adding blanket overrides, npm `--force`, broad Expo or React Native downgrade, application behavior, or claiming an audit-clean tree while upstream pinned ranges remain vulnerable.

Paths changed: `mobile/package-lock.json`, this evidence file, the A3 backlog status and generated `project-status.json`. `mobile/package.json`, application code, and tests are unchanged.

Baseline: `/workspace/scratch/h1824-mobile-audit-base.json` at 05:15 UTC reports 45 findings: 1 critical, 17 high, 27 moderate. The critical `shell-quote` advisory is GHSA-pqg4-j6r4-53mv, installed 1.10.0, fixed by 1.11.0 within parent `react-devtools-core` range `^1.6.1`. The vulnerable nested `brace-expansion` 2.1.4 can move to 2.1.7 within parent range `^2.0.2`. `@expo/metro-file-map` 58.0.4 exists within Expo CLI `^58.0.3`; current is 58.0.3. npm's suggested Expo 44 / RN 0.72 fixes are outside this rollback unit.

Final lock delta:

| Package | Before | After | Why |
| --- | --- | --- | --- |
| `shell-quote` | 1.10.0 | 1.12.0 | Clears critical GHSA-pqg4-j6r4-53mv / audit ID 1241332; parent `react-devtools-core` accepts `^1.6.1`. |
| nested `test-exclude/node_modules/brace-expansion` | 2.1.4 | 2.1.7 | Clears one moderate and two high advisories: IDs 1240101, 1240105, 1240109 within parent `^2.0.2`. |
| `@expo/metro-file-map` | 58.0.3 | 58.0.4 | Clears its inherited high finding by removing the `micromatch` dependency; Expo CLI accepts `^58.0.3`. |

`npm audit fix --package-lock-only` produced the same remaining advisory count but also advanced directly locked `expo` 58.0.3 to 58.0.6 and reshaped 101 package entries. That broader lock was discarded. The final targeted `npm update ... --package-lock-only` changes only the three package entries above (19-line lock diff). Direct Expo 58.0.3, React Native 0.87.1, and other declared SDK/runtime/test versions remain exactly as in the base lock. Incidental npm removal of existing `libc` metadata was restored.

Audit after the targeted refresh: **42 findings: 0 critical, 15 high, 27 moderate**. Four leaf advisory IDs remain, amplified through 42 affected package/meta rows. There are no new advisory IDs:

| Leaf advisory | Installed / constraint | Why not resolved in this compatible refresh |
| --- | --- | --- |
| `braces` GHSA-vfj7-8cjw-p6xm / 1240992 (high) | 3.0.3 via `micromatch` `^3.0.3` | 3.0.3 is the registry's latest `braces` release and still matches the vulnerable range `<=3.0.3`; current `micromatch` 4.0.8 is also its latest. |
| `node-forge` GHSA-86w9-cpqp-85rv / 1240912 (high) | 1.4.0 via Expo CLI/code-signing `^1.3.3` | 1.4.0 is the latest release and still matches `<=1.4.0`. |
| `uuid` GHSA-w5hq-g745-h8pq / 1119441 (moderate) | 7.0.3 via `xcode` `^7.0.3` | Fixed versions begin at 11.1.1, outside the parent's major-7 range. |
| `sprintf-js` GHSA-hp3w-g68c-fv3c / 1241202 (moderate) | 1.0.3 via nested `argparse` `~1.0.2` | The registry's latest `sprintf-js` is 1.1.3, still in the advisory's `<=1.1.3` range. |

Many remaining rows are inherited Expo/Metro/React Native/Jest advisory chains. npm's automatic all-fix guidance suggests incompatible Expo 44 or React Native 0.72 downgrades; neither is a valid security refresh of this SDK 58 app. No `--force`, blanket override, or direct version change was used in the final lock.

Validation: baseline and final `npm ci --no-audit --no-fund` passed (1,299 packages). Final `npx tsc --noEmit` passed; `npm test -- --runInBand --silent` passed 39 suites / 173 tests. Android and iOS `expo export` each completed with a Hermes bundle; output is under `/workspace/scratch/mobile-lock-export-{android,ios}`. `git diff --check` passed. `npm audit --json` exits 1 because the 42 findings above remain; before/after reports are `/workspace/scratch/h1824-mobile-audit-base.json` and `/workspace/scratch/mobile-lock-after-audit.json`.

Coordinator validation: status-sync Python tests passed **38/38**; generated status, Hermes freshness and final diff checks passed. Implementation and independent lock/registry-metadata review used `gpt-6-sol` with high reasoning; no Important/Critical issue was found within this three-package refresh. Offline exports verify compilation, not device runtime acceptance. No push or deployment was performed.

Rollback: revert the lockfile and its evidence/ledger updates; direct package declarations stay intact. No product or server state changes.

Dependencies: npm registry advisory/metadata service and the existing pinned mobile package manifest. No credentials or paid provider calls.
