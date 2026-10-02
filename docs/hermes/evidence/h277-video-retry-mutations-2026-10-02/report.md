# Exact-source video retry mutation verification

Frozen source: `5da06db66c837993a644f330f67da385ed7bf835`, extracted with `git archive` to `/private/tmp/nerva-h277-video-mutations-b8svo6q7`. The interpreter was `/tmp/nerva-pr-python-20261001/bin/python`; `agents.__file__` resolved inside this archive. SHA256 values for all 4,234 tracked regular files, the exact test command, and the final restoration result are in `source_manifest.json`. No production tests or integration source files were mutated.

The focused selection was exactly `tests/test_h277_video*.py`, `tests/test_h277_model_roles.py`, `tests/test_h277_role_routes.py`, `tests/test_h513_data_handling.py`, `tests/test_task_mediation_evidence.py`, `tests/test_image_mediation_composition.py`, and `tests/test_cloud_image_tool.py`. The runner expanded the video glob to ten archive-local files. Every pytest invocation used `PYTHONDONTWRITEBYTECODE=1`, the repository's 30-second pytest timeout and loopback-only socket guard, and a disabled pytest cache provider. There was no bytecode in the archive at setup or after execution.

Baseline: **755 passed, 0 failures, 0 errors**. Final baseline after restoring all mutations: **755 passed, 0 failures, 0 errors**. Final SHA256 verification: **4,234/4,234 exact tracked regular files restored**. The initial baseline setup attempt failed before test collection because `PYTEST_DISABLE_PLUGIN_AUTOLOAD=0` disables plugin loading; `baseline_setup_attempt.log` preserves that infrastructure error. The runner removed that setting and obtained the green baseline before any mutation. It is not counted as a mutant or kill.

| Case | Source change | Outcome | Direct focused evidence |
| --- | --- | --- | --- |
| 01 | Omit enabled retry policy marker from signed class material | KILLED | 2 assertions, including pending-task invalidation on policy change |
| 02 | Increase primary attempt budget by one | KILLED | 7 assertions, including primary retry count and fallback behavior |
| 03 | Remove primary-only condition from attempt cap alone | SURVIVED | 755 passed; the retry decision still requires `route_index == 0` |
| 04 | Remove primary-only condition from retry decision alone | SURVIVED | 755 passed; fallback `max_attempts` remains one |
| 05 | **COMPOUND: remove BOTH primary-only gates** | KILLED | `test_fallback_connection_never_gets_second_send` fails |
| 06 | Treat owned timeout as transient | KILLED | `test_owned_attempt_timeout_goes_directly_to_fallback` fails |
| 07 | Let exhausted transient HTTP proceed to fallback | KILLED | 3 assertions, including 503 refusal without provider fallback |
| 08 | Remove physical-send latch for auth flow | KILLED | 2 one-send assertions, including the enabled auth-flow test |
| 09 | Strip tab/newline controls in retry parser | KILLED | Both ambiguous-value parameter cases fail |
| 10 | Accept retry budget `2` | KILLED | Parser refusal and proposal-before-send assertions fail |
| 11 | Remove `chosen_attempt` | KILLED | 3 result-provenance assertions fail; this is not egress proof |

Total: **11 valid mutations: 9 killed, 2 survived, 0 invalid**. Every edit had exactly one source anchor, parsed as valid Python, and produced a recorded diff. The original bytes and SHA256 were restored after each case before the next. Each case ran the same 755-test selection; valid assertion failures were distinguished from setup/collection errors. The two surviving single-gate mutations are observationally equivalent under this focused suite because the other gate remains. The compound failure demonstrates the fallback behavior when both are absent; it does not establish a broader H277 guarantee.

Artifacts: `run_mutations.py`, `cases.json`, `results.json`, each `NN_*.diff`/`.log`/`.xml`, `baseline.json`/`.log`/`.xml`, `final_baseline.log`/`.xml`, `source_manifest.json`, and `summary.json`. The runner is resumable after interrupted cases and verifies archive hashes before continuation. No full backend suite, external provider call, historical-source comparison, or integration commit was part of this verification.
