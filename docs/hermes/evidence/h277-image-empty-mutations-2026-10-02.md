# H277 governed image recovery: original bounded mutation campaign

Frozen source: `a6a2388f037d130ec0a5bc06a5d9a3f49cf5a9ef`, extracted with `git archive` to `/private/tmp/nerva-h277-image-empty-mutations-yfni5wgy`. The interpreter was `/tmp/nerva-pr-python-20261001/bin/python`. `agents.__file__` resolved inside the archive. `source_manifest.json` records the exact 13-module test selection, command, five scoped source SHA256 values (`vision_retry.py`, `native_response.py`, `vision_policy.py`, `vlm.py`, `video_analysis.py`), and SHA256 values for all **4,317 tracked regular files**. The live integration checkout was never mutated by this campaign; coordinator documentation edits were present there during final inspection.

The 13-module baseline/final selection followed `/tmp/nerva-image-empty-design-evidence-review-20261002.md`, excluding the CLI suites as directed. It included the new image tests, affected composer/local/screen/media/camera/VLM policy tests, video retry and shared-predicate regressions, and H513 data handling. **Baseline 421 passed; final baseline 421 passed; zero failures or errors in either.** Per-case targeted test nodes are recorded in `cases.json`. Pytest used repository 30-second timeout and loopback-only socket guards, `PYTHONDONTWRITEBYTECODE=1`, and disabled cache provider. No archive bytecode was present after execution.

| Case | Mutated behavior | Result | Direct evidence and surviving guard |
| --- | --- | --- | --- |
| 01 | Remove enabled marker from vision identity binding | KILLED | Media/camera stale-grant and composer acknowledgment-binding assertions fail (3) |
| 02 | Remove exact prepared-body digest check | KILLED | Existing late-hook body-mutation assertion fails (1) |
| 03 | Remove final HTTP hook position check | SURVIVED | Current test appends its mutator **before** the final policy hook; final digest still catches it. No after-final-hook regression in this frozen source |
| 04 | Raise retry-scope attempt cap alone | SURVIVED | VLM loop remains two; no-third-send test passes |
| 05 | Raise VLM send-loop cap alone | SURVIVED | Retry-scope cap remains two; no-third-send test passes |
| 06 | **COMPOUND: raise BOTH attempt caps** | SURVIVED | VLM continues only when `attempt == 0` is valid empty; after a second valid empty it returns the blank result. This third control-flow gate prevents a third send in the targeted test |
| 07 | Leave retry scope active after parent exit | SURVIVED | The independent H513 physical request scope still rejects the inherited child's late send |
| 08 | Treat nonblank raw thinking as eligible empty | KILLED | Stripped-blank wire test fails by allowing an extra send (1) |
| 09 | Accept owner retry budget `2` | KILLED | Strict invalid-budget parameter case fails (1) |
| 10 | Remove per-attempt physical-send latch | KILLED | Nested physical-send assertion fails (1) |

**10 valid candidates: 5 killed, 5 survived, 0 invalid.** Every source anchor was unique and each mutant parsed as Python. Case 06 changed two source files and restored both exact original bytes. All cases restored their source files before the next, and the final SHA256 check verified **4,317/4,317 tracked regular archive files unchanged**. Assertion failures alone were counted as kills; no case had a setup/collection/runtime error.

The absent governed text-only test named in the preparation plan was removed from the campaign before baseline; the frozen source has only a direct text-only test, which does not exercise an active governed scope. The frozen late-hook test appends its mutator before scope setup, so case 03 cannot establish rejection of a hook appended after the final policy hook. These are concrete test gaps for a separate supplement. The compound cap survivor is not a safety failure: another explicit control-flow gate remains. This focused campaign does not establish full H277 parity, the full backend/frontend suite, historical-source coverage, or live-provider behavior.

Original campaign artifacts in this directory: `run_mutations.py`, `plan.md`, `cases.json`, `results.json`, `summary.json`, `source_manifest.json`, `baseline.json`/`.log`/`.xml`, `final_baseline.log`/`.xml`, and one `.diff`/`.log`/`.xml` set per case. No production code or test repair, integration write, stage, commit, push, provider call, dependency install, or delegation was performed by this campaign.
