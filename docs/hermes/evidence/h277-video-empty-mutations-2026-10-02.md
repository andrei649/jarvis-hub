# H277 valid-empty retry: bounded exact-source mutation evidence

Frozen source: `45d76bbef62cb347b19d8a89ee68988db74476bc`, extracted with `git archive` to `/private/tmp/nerva-h277-video-empty-mutations-1dsjwbd0`. The interpreter was `/tmp/nerva-pr-python-20261001/bin/python`. `agents.__file__` resolved inside this archive. `source_manifest.json` records the exact baseline command, selected files, imported path, and SHA256 values for all **4,306 tracked regular files**. The live integration checkout was never a mutation target; its HEAD advanced independently while this archive ran.

The full baseline and final selection followed `/tmp/nerva-video-empty-evidence-review-20261002.md`: `test_h277_video_empty_retry.py`, `test_h277_video_analysis.py`, `test_h277_video_fallback.py`, `test_h277_video_routes.py`, `test_h277_video_candidate_consent.py`, `test_h277_video_provider_chain.py`, `test_h277_video_failures.py`, `test_h277_video_boundaries.py`, `test_h277_video_native.py`, `test_h277_video_gemini.py`, `test_h277_video_retry.py`, and `test_h513_data_handling.py`. **Baseline 500 passed; final baseline 500 passed; zero failures or errors in either.** Each mutation ran the targeted test nodes recorded in `cases.json`. Pytest used repository 30-second timeout and loopback-only socket guards, `PYTHONDONTWRITEBYTECODE=1`, and disabled cache provider. No archive bytecode was present after execution.

| Case | Mutated behavior | Result | Direct evidence |
| --- | --- | --- | --- |
| 01 | Remove enabled empty policy from signed class material | KILLED | Both setting-drift assertions fail, including approval stale before send and drift on cleanup |
| 02 | Remove full-chain restart wording from approval notice | KILLED | Approval-notice assertion fails |
| 03 | Accept empty retry budget `2` | KILLED | Sanitized invalid-budget parameter case fails |
| 04 | Increase consumer loop cap alone | SURVIVED | Two no-third-call tests pass; the second-empty terminal guard still stops the call |
| 05 | Relax second-empty terminal guard alone | SURVIVED | Two no-third-call tests pass; the loop remains capped at two calls |
| 06 | **COMPOUND: relax BOTH call-cap guards** | KILLED | Both `test_second_empty_is_terminal_and_never_starts_third_call` and `test_five_route_chain_never_exceeds_two_full_calls` fail |
| 07 | Disable a full-chain restart after valid empty | KILLED | Both primary-empty and fallback-empty restart wire tests fail |
| 08 | Remove primary transient retry from consumer call two | KILLED | Fresh-per-call transient budget wire test fails |
| 09 | Remove successful `chosen_call` | KILLED | First-call and recovered-call result assertions fail; provenance only |
| 10 | Treat compatible `finish_reason=length` as valid empty | KILLED | Malformed/truncated compatible wire test fails by allowing an extra send |
| 11 | Treat meaningful compatible reasoning-only output as valid empty | KILLED | Three invalid compatible wire parameters fail by allowing an extra send |
| 12 | Treat Gemini `MAX_TOKENS` as valid empty | KILLED | Pure codec subtype assertion fails; this case alone is not wire-send proof |

**12 valid cases: 10 killed, 2 survived, 0 invalid.** Every exact source anchor appeared once (the compound case had two unique anchors), every mutated file parsed as Python, and original bytes and SHA256 were restored after every case. Final SHA256 check verified **4,306/4,306 tracked regular archive files unchanged**. Assertion failures were counted as kills; no case had a setup, collection, or runtime error. The two single-guard survivors demonstrate redundant bounds only for these targeted observations. The compound kill directly exercises the no-third-call behavior. These results do not establish full H277 parity, historical-source coverage, live provider behavior, or the full backend suite.

Replay and review artifacts in this directory: `run_mutations.py`, `plan.md`, `cases.json`, `results.json`, `summary.json`, `source_manifest.json`, `baseline.json`/`.log`/`.xml`, `final_baseline.log`/`.xml`, and one `.diff`/`.log`/`.xml` set per case. The runner requires the full frozen SHA via `--commit`, creates an exact archive, checks archive-local imports, and restores source after each candidate. No production code or test repair, integration write, stage, commit, push, network provider call, dependency install, or delegation was performed by this campaign.
