# H277 selected-conversation image route: exact-commit mutation evidence

Frozen local commit: `ffa6b5a672d85502db20c07359c76de5a77c49db`. The runner used `git archive` to extract that commit into `/private/tmp/nerva-h277-selected-route-bqvp7hx4` and confirmed `agents.__file__` resolved inside the archive. It ran with `/tmp/nerva-pr-python-20261001/bin/python`, `PYTHONDONTWRITEBYTECODE=1`, the repository's 30-second pytest timeout and loopback-only socket guard, and the pytest cache provider disabled. The image transport was mocked; no live provider call was made.

The focused `tests/test_h277_selected_composer.py` baseline passed **12/12** before mutation and **12/12** after restoration. The new session and route regressions switch state inside `VLMBackend.generate_vision_checked`, after the review handle has been consumed but before the physical request. They assert HTTP 409 and zero captured image requests. The cross-agent regression fixes session, prompt, model, route and binding to identical values, so only the agent fingerprint can deny the claim; it also checks the refused claim burns the handle. Each of these tests passed on the frozen baseline and failed against its corresponding mutant.

| Mutant | Changed behavior | Targeted result |
| --- | --- | --- |
| 01 | Omit agent from the review fingerprint, repeating the prior campaign's survivor | KILLED: cross-agent claim assertion failed |
| 02 | Omit shared-session identity from the final selected-route resolver | KILLED: session switched after consumption reached the mocked transport |
| 03 | Omit selected route comparison from the final resolver | KILLED: changed route reached the mocked transport |
| 04 | Offer a known text-only selected main model as vision-capable | KILLED: expected allowed fallback was replaced by `auto:main` |
| 05 | Remove both strict-local checks around remote fallback | KILLED: remote fallback was offered to `frigga` |
| 06 | Read an ambient OpenRouter key instead of the selected backend's key | KILLED: physical request used the wrong authorization |

**Six valid mutants: six killed by assertion failures, zero survived, zero invalid.** Every targeted run contained one test, one assertion failure, and zero JUnit errors. Each mutant used a unique source anchor, parsed as Python, and restored its changed files byte-for-byte. The final inventory matched **4,396/4,396 tracked regular files** to their starting SHA256 hashes; the final focused baseline had zero failures, errors or skips. Per-mutant diffs, test commands, logs, JUnit XML, source hashes and results are under `/tmp/nerva-h277-selected-route-mutations-20261002-ffa6b5a672d8`.

Replay command: `/tmp/nerva-pr-python-20261001/bin/python docs/hermes/evidence/h277-selected-route-mutations-2026-10-02.py --commit ffa6b5a672d85502db20c07359c76de5a77c49db`. The runner requires a fresh output directory for its exact commit. This is focused offline evidence for the selected LM Studio and compatible/OpenRouter path; it does not establish native provider wire, frontend, full-suite or live-provider acceptance.
