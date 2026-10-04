# H277 N1–N7 focused mutation run — 2026-10-04

**Terminal result:** Python baseline passed; 10 Python mutants ran serially. Nine were killed by focused test assertions and one (`N7-import-guard`) by the intended `ImportError` raised from the mutated `request()` inside the targeted test body. That exception was initially mislabeled as setup by a broad automatic regex; the log shows pytest collection/setup succeeded and the failure arose at `tests/test_h277_approval_judge.py:1251`. The reviewed JSON result records it as `killed_by_runtime_exception`, not an assertion kill. There were zero setup/collection failures, timeouts, or selector survivors. The browser baseline passed (1 selected test), and the N2 browser mutant failed its focused assertion at `tests/frontend/tools.test.js:639`. Thus all **11 proposed mutants exposed a behavioral regression**, comprising **10 assertion kills and 1 runtime-exception kill**, not eleven assertion kills.

| Case | Actual observed failure |
|---|---|
| N1-post-slot | `skipped_revoked` stayed 0 instead of 2 after a live-policy revocation (`test_waiting_judgement_rechecks_live_policy[True-allow_remote]`). |
| N1-disk-state | Third backend call dispatched despite persisted rejection (expected 2 calls). |
| N2-finish-pending | Runtime `judge_pending` remained true after natural finish. |
| N3-premature-cap | Complete 1600-character value was cut before the 4000-character argument budget. |
| N4-depth-marker | `nesting_too_deep` was missing from refusal flags. |
| N5-nfkc | U+2033 double prime remained in rationale instead of normalizing to two apostrophes. |
| N6-bytes | Byte text lost its injection flags in the normalized snapshot. |
| N6-set | Set text lost its injection flags when its elements were omitted. |
| N7-import-guard | Intended `ImportError: judge unavailable` escaped `request()` inside the test body; no assertion line was reached. |
| N7-off-shape | `tainted` appeared in the unconfigured judge's public queue item. |
| N2-browser-budget | Expected an active poll at 6 s, but shortened deadline left 0 timers (`tools.test.js:639`). |

The Python runner used `/tmp/nerva-pr-python-20261001/bin/python -m pytest` with `JARVIS_TESTING=1`, the pytest socket allowlist `127.0.0.1,::1,localhost`, per-test `--timeout=30`, and a 150 s subprocess cap. Its baseline log is `/tmp/nerva-h277-mutation-20261004/baseline.log`; per-mutant logs are adjacent. Browser Vitest v5.0.2 came from the **already installed** `/Users/andrei649/Projects/nerva-pr-worktrees/integration/node_modules`, temporarily symlinked as `/tmp/nerva-h277-mutation-20261004/snapshot/node_modules`; no package was installed. Browser logs are `ui-baseline.log` and `ui-N2-browser-budget.log`. Raw and reviewed terminal results are in `results.json`; browser result is in `ui-results.json`.

The source fingerprint is the frozen current tracked working-tree overlay copied from HEAD `ce96e6aef3d26f64c3138c71c5f56cf9b61209f7` before the H487 milestone commit. `/tmp/nerva-h277-mutation-20261004/manifest.json` hashes all 4,589 copied paths (84,142,890 regular-file bytes). The six mutation/source-test files also have **identical live bytes** at later HEAD `cc4618a1615e9588e1f82800a57d36500329efe1`:

| File | SHA-256 |
|---|---|
| `agents/core/autonomy/advisory_judgements.py` | `ec90ed9ac95c64385d6a627f6793fc4f1864d73a43571447f655a82290514eb9` |
| `agents/core/autonomy/action_approvals.py` | `9ee9d1bbf42dd011b75b51e607750b187bd31ccf5f0a88e99bb5ce016067709b` |
| `agents/core/autonomy/approval_judge.py` | `63f493e46a4a71dfc03549a7b02e8d5ee5f898329c1fb3f0078c8868c23a7eea` |
| `agents/web/static/tools.js` | `45c4536ecd983d7871a3f313bd1f216062ea72f7cec50810b31c2ae9e7357ccb` |
| `tests/test_h277_approval_judge.py` | `e5f32cad56d50bf5f61ed8de43d21ef3397f078b6ecdef230ddbaaca90b51d5e` |
| `tests/frontend/tools.test.js` | `5fd583e9a2e9b2e2676fe75313f6a4ca5f2e5d10f704ec3584da893f07fddb1c` |

Every Python mutant was applied **only to the snapshot**, restored in `finally`, and SHA-256 checked against the original; the entire snapshot passed final manifest verification. The browser source was likewise restored, the temporary dependency symlink removed, and the entire snapshot verified again. No repository source/test file was edited by this campaign, and no provider, service, or real effect was invoked. These focused kills support the named N1–N7 regression tests on this exact source overlay; they do not establish complete H277 parity or live-provider acceptance.
