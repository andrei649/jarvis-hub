# H277 selected-image review: exact-commit mutation evidence

Frozen source: `d19cf4fae06834b9a78afdcedbb0c00da41be196`. The offline
runner archived that commit and resolved `agents` inside the archive. It
verified SHA-256 for all 4,402 tracked regular files before and after the run.
The selected-composer baseline passed 15/15 before the mutations and 15/15
again after restoration. No provider call was made.

| Mutation | Behavioral assertion | Result |
| --- | --- | --- |
| Remove image data from the one-use review binding | A different image must be refused before transport; the token cannot be replayed | KILLED |
| Accept a selected preflight without image digests | Missing digests must return 422 before a token is issued | KILLED |
| Sort image digests in the review binding | Reversing two images must be refused before transport | KILLED |

**Three valid mutants, three assertion kills, zero survivors or invalid cases.**
Each targeted run had one assertion failure and zero JUnit errors. The final
baseline and complete source restoration passed. Per-mutant diffs, commands,
JUnit XML, source hashes and logs are under
`/tmp/nerva-h277-selected-route-mutations-20261002-d19cf4fae068`.

Replay with
`/tmp/nerva-pr-python-20261001/bin/python docs/hermes/evidence/h277-exact-image-review-mutations-2026-10-02.py --commit d19cf4fae06834b9a78afdcedbb0c00da41be196`
in a checkout containing this runner, using a fresh output directory. This
proves the selected-image binding against these three faults; it does not
establish live-provider acceptance or persistent multimodal chat.
