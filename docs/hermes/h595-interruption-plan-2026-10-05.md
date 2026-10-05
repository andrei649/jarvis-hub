# H595 product interruption

Goal: all 697 Hermes capabilities, local only. Base/head:
`a7ffad6676cfb28e7ac374d495b4a5889e5f4646`. Generated: 2026-10-05.

Reuse the pinned Hermes contract: an admitted new user message in the same
conversation stops active code and returns `status=interrupted` with the named
user-message marker. Preserve partial output, tool-call count and duration where
the current backend exposes them. Ordinary transport cancellation must propagate.

1. Track only an active code task and its trusted session identity; never cancel
   the whole model turn or derive authority from model-supplied arguments.
2. Signal before HTTP turn leases and channel lanes, after admission and pending
   reply interception. Unrelated sessions, jobs, rejected and observation-only
   traffic cannot interrupt the worker.
3. Await existing backend teardown and clear resident state before returning the
   interruption result. The old turn finishes normally; the queued turn follows.
4. Demonstrate missing behavior with a failing ingress regression, implement the
   narrow wiring, then verify real worker teardown and negative routing cases.

Implementer (`gpt-6-sol`, high, no children) owns code tools, the interruption
registry, orchestrator/HTTP/Telegram ingress and focused interruption tests.
Coordinator owns sandbox/runtime review and all documentation/evidence/assessment.
Preimages: `/tmp/nerva-h595-interrupt-baseline-20261005`.
Rollback: restore only this batch's owned diffs from those preimages; preserve all
inherited changes. Dependencies: existing code authorization, session routing,
pending-input interception and cancellation teardown. No remote provisioning,
publication, provider activation or unrelated refactor. Next action: RED ingress
test, then implementation and relevant integration tests.
