# H277 acquisition auxiliary models — implementation evidence

Source freeze: branch `codex/acquisition-auxiliary-models-20261002`, base `origin/main` at `a5b74939` (PR 1226 merged). Owned edits only: `agents/core/llm/auxiliary_text.py`, `agents/core/acquisition/llm_synth.py`, and new `tests/test_h277_acquisition_auxiliary.py`. Implementation-stage report; publication and full-backend integration are recorded separately. No live provider call or paid route was used.

The fixed auxiliary task table now includes `acquisition_capability` and `acquisition_draft` with independent model flags. A prepared async callable captures the selected model and strict-local backend once per producer operation; each awaited JSON attempt opens a new H513 scope and uses the captured pair. The one-shot helper for the four earlier consumers delegates to it. All four retain job-pin exclusion, including when a prepared callable is invoked later under a pin. Acquisition explicitly retains its prior compatibility: a job pin is ignored by the local accessor, not used to select a model or provider. The two acquisition loops retain prompts, 2048/1024 token limits, temperatures 0.2 then 0, two attempts, JSON object/array parsing, and existing downstream validation. An optional `active_model` attribute keeps the previous `"local"` fallback.

Red-first evidence: `/tmp/nerva-acquisition-red-20261002.xml` has two actual real-producer assertion failures (`active-local` instead of configured capability/draft model). A separate compatibility regression was captured in `/tmp/nerva-acquisition-red-optional-model-20261002.xml`: both producers failed with `AttributeError` when a local router omitted the optional `active_model`; this was fixed with an optional lookup.

Final required focused regression: **1026 passed, 2 skipped, 2 existing warnings** in 16.71 s, with repository timeout/socket guards and `/tmp/nerva-pr-python-20261001/bin/python`; JUnit `/tmp/nerva-acquisition-regression-20261002.xml`. After Ruff import ordering, the changed new/four-consumer tests reran: **86 passed**, JUnit `/tmp/nerva-acquisition-final-focused-20261002.xml`. Scoped Ruff and `git diff --check` passed.

New tests exercise independent overrides, exact default and Unicode behavior, sanitized refusal, frozen model/backend through a JSON retry despite environment/router changes, fresh H513 authorization for each attempt, acquisition pin compatibility on real `LLMRouter` and `HybridRouter` accessors, late pins on prepared earlier tasks, cloud-only refusal, and actual HTTPX hook revocation including swallowed physical denial. No known contract blocker. The two warnings are the existing FastAPI/Starlette deprecation and the session-title no-running-loop coroutine warning.

## Integration boundary

H277 remains partial. Six existing auxiliary consumers now share operation-bound
local invocation; this does not add provider discovery, remote auxiliary routing,
SDK recovery, model installation, a settings editor or a production presence
explanation consumer. The acquisition job-pin compatibility is intentionally
preserved; a different pin policy requires a separate change. Existing H32 code
and grounding validators remain authoritative over generated output.

The parent reviews only six affected, previously-current Hermes evidence rows;
three already-stale FLAGS rows and the original207 stale rows remain untouched.
Full-backend integration, exact source hashes and GitHub acceptance are recorded
separately, not inferred from the focused selection above.

Bounded independent source/spec review found no blocking issue in route capture,
fresh scopes, pin compatibility, optional-model fallback or compression lifecycle.
The reviewer did not rerun tests. Parent full Ruff, diff and92 record checks passed
before freezing the full-backend source.
