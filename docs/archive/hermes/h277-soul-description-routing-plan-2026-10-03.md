# H277: governed local route for SOUL description drafts

Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Base Nerva: `19bfdd80`. `soul_edit.draft_description` is a real admin
consumer of private persona text. It currently calls `router.local_backend`
and `backend.generate` directly, without the common task model selection or
the H513 physical-request scope. This unit adds a seventh local auxiliary
consumer while preserving the existing H156 draft behavior.

## Contract

`JARVIS_AUX_SOUL_DESCRIPTION_MODEL` selects an independent local model at the
actual draft request. Its unset/blank fallback is the active local model or the
existing default. A job-model pin does not become authority for this admin
draft. The 8,000-character SOUL input bound, 160-token cap, temperature 0.3,
Qwen `/no_think` suffix, one-paragraph/400-character normalization, 60-second
deadline and no-write proposal remain unchanged.

The selected backend must be an owned LM Studio or Ollama adapter on loopback
with a proven direct HTTPX transport. Before dispatch and at every physical
request, bind the selected router backend, client, endpoint, native LM Studio
`/v1/chat/completions` or Ollama `/api/generate` URL, and exact model/prompt/
token budget. An appended hook after the owned egress recorder, changed route
or proxy refuses before transport. H513's
internal-principal policy checks continue to run on every request and cannot
be swallowed into a successful draft. A refusal returns the existing generic
`no_local_model` error without echoing SOUL text or secret material. No cloud
fallback, paid provider, credential migration or persisted text is added.

## Red-first and verification

1. Use the real draft API with offline HTTPX adapters. Prove the independent
   model override reaches the wire, and the legacy Qwen/default behavior and
   response shape remain intact. Observe a failing assertion first.
2. Exercise a physical H513 revocation, proxy/late transport swap, endpoint
   drift, no local backend, timeout and empty/degraded answer. Each refusal
   must send no further persona bytes. Keep existing H156 tests passing.
3. Limit source edits to the common auxiliary helper, SOUL draft consumer and
   their tests. Run focused H277/H513/H156 suites, mutation probes, Graft,
   full backend/frontend suites and honest Hermes restamping. H277 remains
   partial until the other accepted integrations are complete.

No push, merge, deployment or live provider call is part of this unit.

## Focused result

Red-first regressions exposed the ignored model override, absent H513 scope,
Ollama URL mismatch, late model rewrite and an appended redirect hook. The
252-case H156/H277/H513/egress/LM Studio union now passes. Four isolated
runtime mutation baselines pass and all four mutants are killed. The complete
backend suite exited zero with 21,264 passed, 34 skipped and one expected
failure (21,299 collected); the frontend suite exited zero with 1,874 passed
across 207 files. Scoped Ruff, `git diff --check` and the rebuilt Graft graph
pass. These are local offline checks; no local model or cloud provider was
contacted.
