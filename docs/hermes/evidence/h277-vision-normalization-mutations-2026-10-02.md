# H277 native vision normalization: bounded exact-source mutation evidence

Frozen source: `74cc7130dee0408cddf026bfb7a004726f0c9c93`, extracted with `git archive` to `/private/tmp/nerva-h277-vision-normalization-6m3xshp3`. The interpreter was `/tmp/nerva-pr-python-20261001/bin/python`; `agents.__file__` resolved inside the archive. `source_manifest.json` records the exact focused test command, SHA256 for the four changed runtime files (`native_response.py`, `video_native.py`, `vlm.py`, `video_analysis.py`), and SHA256 for all **4,329 tracked regular files**.

The 13-module focused baseline/final selection covered the new compatible and Gemini normalization modules, prior image/video retry and native regressions, and H513 interactive/composer/media/camera/data-handling guards. **Baseline 504 passed; final baseline 504 passed**, with no failures or errors. Each mutation ran only its targeted test nodes as recorded in `cases.json`. Pytest retained the repository's 30-second timeout and loopback-only socket guard, used `PYTHONDONTWRITEBYTECODE=1`, and disabled the cache provider.

| Case | Mutated behavior | Outcome | Assertion evidence |
| --- | --- | --- | --- |
| 01 | Let structured reasoning displace visible text | KILLED | Both image settings and signed compatible video visible-precedence tests fail (3) |
| 02 | Accept top-level compatible error envelope with visible text | KILLED | Governed image and signed video invalid-output tests fail (2) |
| 03 | Prefer lower-priority reasoning-detail fields over summary | KILLED | Image detail-priority output assertion fails (1) |
| 04 | Publish duplicate normalized reasoning pieces | KILLED | Image and video deduplication output assertions fail (2) |
| 05 | Bypass normalizer in governed image dispatch | KILLED | Six structured-reasoning image cases fail |
| 06 | Bypass normalizer in signed compatible video dispatch | KILLED | Four structured-reasoning video cases fail |
| 07 | Insert spaces between raw Gemini thought fragments | KILLED | Both raw-fragment/partial-tag codec assertions fail |
| 08 | Classify inline-thought-only Gemini output as retryable empty | KILLED | Pure terminal classification and signed one-send/no-fallback assertions fail (2) |

**8 valid candidates: 8 killed, 0 survived, 0 invalid.** Every original anchor appeared exactly once; every mutant parsed as Python; all kills were assertion failures with zero JUnit errors. Each source file was restored to exact original bytes after its case. The final SHA256 check confirmed **4,329/4,329 tracked regular archive files unchanged**. No test was modified during the campaign.

The top-level error-envelope probe is one specific invalid envelope, not a claim that every malformed shape was mutated. Cases 03 and 04 establish output-shape checks; cases 05, 06 and the signed part of 08 establish actual governed consumer behavior under offline HTTPX tests. This focused run does not establish full H277 parity, full-suite/frontend acceptance, historical-source behavior, or live-provider results.

Replay and review artifacts in this directory: `run_mutations.py`, `plan.md`, `cases.json`, `results.json`, `summary.json`, `source_manifest.json`, `baseline.json`/`.log`/`.xml`, `final_baseline.log`/`.xml`, and one `.diff`/`.log`/`.xml` set per case. The runner requires the frozen full SHA, archives that commit, checks import origin, validates unique anchors and Python syntax, restores each source, and verifies all tracked regular-file hashes. It made no integration worktree edit, stage, commit, push, provider call, install, or delegation.
