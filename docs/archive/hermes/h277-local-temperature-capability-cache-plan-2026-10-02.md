# H277 local auxiliary temperature capability memory

Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Base Nerva: `e3cc4249`. Hermes remembers a route/model that explicitly rejected
`temperature` and omits that field on later auxiliary calls. Nerva already
repairs one selected LM Studio auxiliary call, but its next call repeats the
same HTTP 400. This step closes that repeated-call gap without changing the
general chat, tool-turn or streaming contracts.

## Contract and design

The first of the five non-streaming local auxiliary producers still sends its
configured temperature. Only a typed bounded 400 naming that parameter, followed
by a successful repaired response, teaches the long-lived LM Studio backend to
omit it for the exact model on later auxiliary operations. Store a bounded
backend-owned cache tied to its current client, base URL and selected transport.
A changed model, client, endpoint, transport or backend starts without this
knowledge. Failed repair,
cancelled calls, ordinary chat, tool turns and streams do not learn or use it.

The existing operation scope and H513 physical-request guard still authorize
each call, including a cache hit. No credential/provider fallback, new remote
route, payload mutation or user-data persistence is introduced. A model server
whose behavior changes without a backend/client/endpoint change may retain the
omission until that backend is replaced; this is the same process-lifetime
assumption as the pinned route cache and is an explicit runtime limit.

## Verification sequence

1. Red-first tests through all five real producers: second operation should
   send once without `temperature`, preserving model, prompt and token cap.
2. Prove no learning from a failed repair, no omission on ordinary chat, no
   cross-model/client/endpoint reuse, and fresh H513 refusal before a cached
   send. Keep the three-send limit for a single operation.
3. Implement in the existing `auxiliary_recovery.py` and LM Studio `_post_chat`
   only; run focused suites after each step, then full backend and status checks.
   Rebuild/check Graft and refresh only the Hermes rows whose source evidence
   changed. H277 remains partial because its other recovery/provider work is
   still open.

No live provider call, push, merge or deployment is part of this step.

## Focused result

The repeated-call test failed before the cache was added. A second red test
found that replacing a client's selected transport could reuse a stale verdict;
the cache now binds that transport as well. The 246-case H277/H513/LM Studio/
compaction regression union passes, scoped Ruff passes, and three isolated
runtime mutants are killed after their baselines pass. Graft freshness and the
staged secret scan pass. The complete backend suite exited 0 with 21,253 passed,
34 skipped and one expected xfail of 21,288 collected tests. The complete
frontend suite exited 0 with 1,874 passed. These are offline checks; no live
LM Studio model has been queried.
