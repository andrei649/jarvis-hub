# H277 composer review and auxiliary scope: exact-commit mutation evidence

Frozen commit: `12ed820300ae529e10bfff8ad6ccb5475887b71f` (`h277: bind composer image reviews and isolate auxiliary recovery`). The runner extracted that commit with `git archive` to `/private/tmp/nerva-h277-composer-review-4boz39qg`, then confirmed `agents.__file__` resolved inside the archive. It used `/tmp/nerva-pr-python-20261001/bin/python` with `PYTHONDONTWRITEBYTECODE=1`, the repository's loopback-only socket and 30-second timeout pytest guards, and the cache provider disabled. No live provider was called.

The six-module focused baseline covered the review store, prepared auto-vision consumer, auxiliary parameter recovery, existing composer behavior, and H513 auxiliary/composer guards. **Baseline: 120 passed. Final restored baseline: 120 passed.** Every candidate altered one exact anchor, parsed as Python, and ran only the recorded targeted test nodes. Test and source selections, commands, individual diffs, JUnit results, and full source hashes are in the `/tmp/nerva-composer-review-mutations-20261002` replay directory.

| Case | Behavior changed | Result | Assertion evidence |
| --- | --- | --- | --- |
| 01 | Reuse a consumed handle | KILLED | Direct one-use and prepared-route replay assertions fail |
| 02 | Omit prompt from the review fingerprint | KILLED | Direct and prepared-route changed-prompt assertions fail |
| 03 | Omit session from the review fingerprint | KILLED | Cross-session assertion fails |
| 04 | Omit agent from the review fingerprint | **SURVIVED** | Both selected tests pass; neither varies the agent |
| 05 | Omit endpoint/credential binding from the fingerprint | KILLED | Direct rotated-credential assertion fails; prepared route also has a public revision check |
| 06 | Omit selected route from the fingerprint | KILLED | Changed-route assertion fails |
| 07 | Accept an expired handle | KILLED | Expiration assertion fails |
| 08 | Skip review consumption in the prepared route | KILLED | Prepared-route replay and changed-prompt assertions fail |
| 09 | Let a child task inherit auxiliary retry permission | KILLED | Real-review child-task isolation assertion fails |
| 10 | Reuse a closed auxiliary scope | KILLED | Inherited-context lifetime assertion fails |
| 11 | Omit backend identity from auxiliary scope | KILLED | Direct scope and backend retry assertions fail |
| 12 | Omit model identity from auxiliary scope | KILLED | Direct scope and backend retry assertions fail |

**12 valid candidates: 11 killed, 1 survived, 0 invalid.** Every kill was an assertion failure, with zero JUnit errors; the survivor had two passing targeted tests. The missing regression is a direct store test that issues a token for `agent_id="jarvis"`, tries to consume it with `agent_id="athena"` while keeping session, prompt, model, route and binding identical, asserts `vlm_destination_changed`, then verifies the refused claim burned the token. A prepared-route variant should also verify no image egress. The existing helper in `test_h277_vision_review.py` hardcodes `jarvis` for both issue and consume, so the selected suite cannot detect the agent-binding removal. No product or test file was changed in this campaign.

Each mutated file was restored byte-for-byte after its case. The final manifest check confirmed **4,387/4,387 tracked regular archive files** matched their starting SHA256 values; the final 120-test baseline also passed. This is focused offline mutation evidence, not full-suite, frontend, live-provider, or complete H277 parity proof.

Replay: `python docs/hermes/evidence/h277-composer-review-mutations-2026-10-02.py baseline --commit 12ed820300ae529e10bfff8ad6ccb5475887b71f`, followed by the same command with `mutations` as the phase. The runner writes no worktree files; archive, logs, XML, JSON, and diffs remain under `/tmp/nerva-composer-review-mutations-20261002`.
