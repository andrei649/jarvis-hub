# H277 selected-main local vision capability producer

Pinned Hermes reference: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Base Nerva revision: `c8607264`. The selected-main composer already reads an
exact per-model `model_vision_capabilities` snapshot, but no production code
populates that snapshot. Tests currently inject it by hand. Consequently a
known text-only local model can still be offered a reviewed image turn.

## Contract

Only an explicitly selected image turn may query model capability metadata.
Read LM Studio's native `GET /api/v1/models` `models[].key` and strict boolean
`capabilities.vision` for the exact selected model. Read Ollama's `POST
/api/show` `capabilities` array for that model. A well-formed explicit false
verdict skips the main image route; true keeps it. Missing, malformed,
unreachable or unsupported metadata means unknown, preserving the existing
main-first behavior. No model-name guesses, provider-wide claims, image bytes,
prompt text, cloud fallback discovery or paid requests enter the probe.

The metadata request uses the selected local backend's endpoint and owned
HTTPX client. It must be loopback, direct, non-redirecting, time-bounded and
response-size-bounded. A proxy or changed final URL refuses the probe and
leaves the verdict unknown. The physical request guard also binds the Ollama
`/api/show` body to the exact selected model, including after HTTP hooks.
Refresh the exact model at both review issuance
and review consumption so a changed verdict changes the reviewed destination
before image dispatch. The synchronous final request guard reads only the
frozen in-memory verdict; it does not perform hidden I/O.

Official wire references: [LM Studio native model list](https://lmstudio.ai/docs/developer/rest/list)
and [Ollama `/api/show` schema](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml).
Older LM Studio releases may not expose the v1 field; their result remains
unknown rather than inferred from a model name.

## Design choice

Probe the selected model during the existing async composer preparation.
Probing all models at router startup would add unbounded requests and go stale
before a later image turn. Filename/name heuristics cannot establish a negative
capability verdict. This unit changes `agents/core/llm/vision_capability.py` and
the existing selected-turn consumer in `agents/core/routers/composer_vision.py`;
the existing provider adapters and general chat routing stay unchanged.

## TDD and verification

1. Add parser and offline transport tests for exact model identity, true,
   false, unknown/malformed metadata, URL/proxy/redirect refusal, response
   bound and cancellation. Observe the intended failures before coding.
2. Add selected composer tests for text-only fallback, capable main, unknown
   main, changed capability after review, and no metadata probe on ordinary
   status/text paths. Then wire the producer into the selected turn.
3. Run focused H277/H513/composer tests after each step, mutation probes for
   the negative verdict and approval-time refresh, full backend/frontend
   suites, Graft, source scan and generated-status checks. Keep H277 partial
   until all its other accepted requirements are implemented and verified.

No live provider call, push, merge or deployment is part of this unit.

## Local verification

The 178 focused H277/H513 tests pass. Three isolated runtime mutation
baselines pass, and all three mutants are killed (negative verdict, stale
review, and direct transport). The Ollama request-body substitution test was
observed red before its guard was added, then passed. Ruff lint and Graft
freshness pass. The complete backend suite exited 0 with 21,242 passed,
34 skipped and one expected xfail out of 21,277 collected tests. The complete
frontend suite exited 0 with 1,874 passed. The staged index scan found zero
secrets. No live LM Studio or Ollama instance has been used.
