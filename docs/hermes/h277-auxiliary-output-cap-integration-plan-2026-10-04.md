# H277 auxiliary output-cap root integration

Generated 2026-10-04. Goal remains all697 pinned Hermes capabilities.
Base/head:`31a1d193`; prototype base:`4f265c6c`. Root is the sole real writer.

Apply the new33-case test module alone and verify behavioral RED. Re-read the
three-file patch against Hermes operation-only cap omission, then apply and run
new plus affected local-auxiliary, temperature, stream, SOUL and producer tests.
No queue/kernel or remote-provider changes; no new provider or live acceptance.
Exact task/backend/model/client/direct-local route and physical H513 checks must
remain current on each request; omission is never learned for the next call.
Existing temperature learning remains; per-field and unload retry budgets stay
bounded, and streams retry only before any activity and after cleanup.

Owned files: agents/core/llm/auxiliary_recovery.py, base.py, auxiliary_text.py,
tests/test_h277_auxiliary_output_cap_recovery.py. Final scoped evidence/status
records are coordinated after the source batch. Rollback: reverse these four
paths and regenerate counts/records. Next action: apply tests before source.

# H277 local auxiliary output-cap recovery prototype

1. Freeze a disposable source/test snapshot from the current selected agents, tests, scripts and configuration file keys. Verify each regular source byte at copy time; add only explicitly required HEAD-identical tracked supplements. Record HEAD separately from the path/hash fingerprint. Keep all writes under this directory.
2. Establish RED with a new test module exercising actual local auxiliary producers and offline HTTPX physical requests. Cover typed max_tokens rejection, both temperature/cap orders, unload plus both fields, one retry per field, no cross-operation cap memory, strict route/body authorization and refusal cases, and no-frame versus post-frame stream behavior.
3. Implement only auxiliary_recovery.py, base.py, and the proven soul_description guard adjustment in auxiliary_text.py. Restrict the new rung to the exact active auxiliary task/backend/model/client/route, a present cap, a bounded structured HTTP 400 naming max_tokens, and one omission per operation. Keep the existing temperature cache semantics and bounded stream deadlines.
4. Run GREEN focused tests, then affected auxiliary/temperature/stream/soul suites and Ruff. Verify final snapshot hash restoration relative to the captured input for all untouched files, inspect the exact four-path diff, and export implementation.patch, HANDOFF.md, RED/GREEN XML/logs and input manifest. The real checkout remains untouched.

Root terminal checkpoint: integrated source commits `48e911ed` and `c479790b`, verified head `e84f0922b230a2349933c67d8511cd3684c17e1a`. Frozen full backend: 22,465 total, 22,430 passed, 34 ordinary skips, 1 existing expected failure, zero failures/errors; all 3,020 input hashes unchanged. See [separate full receipt](evidence/h487-auxiliary-outcomes-full-2026-10-04.json). Implementation and root verification steps above are delivered; prototype checklist is retained as its pre-code historical plan. H277/H487 remain partial. Next action: reviewed next source units and remaining all697 work.
