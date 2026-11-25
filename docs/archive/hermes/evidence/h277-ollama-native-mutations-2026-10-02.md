# H277 native Ollama image route: exact-commit mutation evidence

Frozen source: `ff079d5a637d9f037758f81c1d05030aa38fcd18`. The offline
runner archived that commit, resolved `agents` inside the archive, ran the five
selected Ollama HTTP cases with mocked transport, and verified all 4,400 tracked
regular files by SHA-256 before and after. The baseline passed 5/5 before the
mutations and 5/5 again after restoration. No live Ollama request was made.

| Mutation | Targeted behavioral assertion | Result |
| --- | --- | --- |
| Remove image bytes from native `/api/chat` body | Decoded image must match the reviewed PNG | KILLED |
| Send to chat-completions instead of native `/api/chat` | Selected native request must reach the exact Ollama URL | KILLED |
| Exclude Ollama from selected-main candidates | Active Ollama model must appear at preflight | KILLED |
| Skip remote destination acknowledgement | Remote Ollama request must be refused before egress | KILLED |
| Skip final request-body digest verification | Late image substitution must never reach transport, with zero or one retry | KILLED |

**Five valid mutants, five assertion kills, zero survivors or invalid cases.**
Each targeted run had only assertion failures and no JUnit errors. The final
baseline and source restoration both passed. Per-mutant diffs, command lines,
JUnit XML, source hashes and output are under
`/tmp/nerva-h277-selected-route-mutations-20261002-ff079d5a637d`.

Replay with
`/tmp/nerva-pr-python-20261001/bin/python docs/hermes/evidence/h277-ollama-native-mutations-2026-10-02.py --commit ff079d5a637d9f037758f81c1d05030aa38fcd18`
in this checkout. The runner requires a fresh output directory. This is
focused local evidence for the Ollama native wire and guards; it does not
establish live-provider acceptance, persisted multimodal chat, native mobile
controls or parity for other provider wires.
