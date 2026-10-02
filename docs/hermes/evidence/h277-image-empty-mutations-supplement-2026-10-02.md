# H277 governed image retry: two-test supplemental mutation evidence

This supplement is separate from the original ten-case campaign in the parent directory. Its exact source is `931b6626017146ffa31ece8f2bc9b5b7865d59a7`, extracted with `git archive` to `/private/tmp/nerva-h277-image-empty-supplement-lf7gameq`. The five runtime source SHA256 values match the original `a6a2388f037d130ec0a5bc06a5d9a3f49cf5a9ef` campaign exactly; this commit adds `tests/test_h277_image_retry_scope_edges.py` without changing those sources. `agents.__file__` resolved inside the archive.

The baseline and final selection was the new two-test edge module plus the original `tests/test_h277_image_empty_retry.py`: **42 passed before mutations and 42 passed after restoration**, with zero failures or errors. The two mutations each ran only their matching new regression:

| Case | Source mutation | Outcome | Direct observation |
| --- | --- | --- | --- |
| S01 | Remove final HTTP request-hook position check | KILLED | `test_hook_appended_after_scope_guard_cannot_reach_transport` fails when a hook appended after scope setup can alter the request before transport |
| S02 | Remove image-bearing gate inside a governed scope | KILLED | `test_text_only_call_in_governed_scope_never_retries` fails when a valid blank text-only response receives a second send |

**2 valid candidates: 2 killed, 0 survived, 0 invalid.** Each source anchor was unique and the mutated Python parsed. Each case restored its exact original bytes before the next; final SHA256 verification confirmed **4,318/4,318 tracked regular archive files unchanged**. The exact command, five focused source hashes, per-case diffs/logs/JUnit, `cases.json`, `results.json`, `summary.json`, and baseline/final JUnit are in this supplement directory.

These new regressions close the two specific observational gaps identified in the original campaign. They do not change the original five survivor classifications: the individual and compound cap mutations still have a third control-flow gate, and the inherited child still meets the separate H513 physical-scope guard. This supplement does not establish full H277 parity, full backend/frontend acceptance, or live-provider behavior. No production code, tests, or integration worktree were edited by this mutation run.
