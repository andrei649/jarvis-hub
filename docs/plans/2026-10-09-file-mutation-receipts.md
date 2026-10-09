# H396 file mutation receipts implementation plan

> Agentic execution: use subagent-driven development with disjoint owned test
> files, one production writer and root integration/review. TDD before source.

**Goal:** retain truthful per-attempt file mutation observations in the existing
approved-execution result, without inferring success from generic error text.

**Architecture:** add `mutation_receipt` to existing `FileTools._mutate` returned
dictionaries only after resolution to an allowed non-root target. Existing
ToolRPC approved execution already carries this dictionary into its result;
its gated model-loop path only requests approval and never invokes the handler.

**Tech stack:** existing Python 3.12/asyncio/pytest; no dependency change.
**Design:** the contract below, bounded to the existing FileTools result flow.
**Generated:** 2026-10-09 UTC.
**Base/head before changes:** `ca1b0d5e09c5439ee4211bc68d985fe05a78e89d`.
**Branch/worktree:** `codex/file-mutation-receipts-20261009`,
`/workspace/jarvis-hub-file-mutation-receipts`.
**State/next action:** implemented and independently reviewed; 498 distinct focused
and integration cases pass. Source is frozen; next run the full backend milestone
on committed source. Parent baseline: 21668 passed, 37 JUnit-skipped (36 guarded
+1 existing xfail). No passing new full run is claimed yet.

## Contract and global constraints

- Add only `mutation_receipt: {"path": str(target), "op": "write"|"delete",
  "outcome": "refused"|"applied"|"unknown"}`. The three receipt keys are exact;
  existing outer keys/values remain unchanged. Use a small pure result wrapper
  in `file_tools.py`; no new store, state, ContextVar or asynchronous observer.
- `refused` means this attempt never submitted `_apply`: existing snapshot
  failures, not-found/not-file returns, contract/kernel denials and instruction
  approval floor. It does not say no snapshot/audit happened or no other actor
  changed the target. Scope/root denials and write content/size validation omit
  the receipt; do not resolve more paths just to produce an identity.
- `applied` means the existing `_apply` returned normally. It does not prove
  read-back, durability, current contents or which concurrent attempt won.
- `unknown` means `_apply` was submitted and its existing OSError handler ran.
  Test errors both before and after a real target mutation; neither becomes a
  claim of no effect. Preserve `ok: false`, reason, detail and snapshot ref.
- Escaping exceptions and cancellation still propagate with no returned receipt.
  A filesystem worker can finish after cancellation. ToolRPC's existing error
  envelope or runtime timeout is not a synthetic refusal receipt.
- Path names the target selected by existing scope resolution for this attempt.
  It is owner-facing result data, not private telemetry. ToolRPC scrubs the
  result; a scrubbed path is not an authoritative future correlation key.
  Do not add fields to kernel Action payloads, approval cards, tool events or
  logs. Leave scope, authorization, snapshots, scheduling and rollback unchanged.
- No runtime/orchestrator/client/outcome change, same-turn footer, aggregation,
  ordering/supersession claim or task-success label. Later footer work must join
  approved task execution to its requesting turn, retain trustworthy identity,
  handle unreturned/unknown results and establish ordering. H396 stays partial.
- Local work only. Preserve existing published PR #1247 and other worktrees.

## Review focus

1. Allowed aliases resolve to one intended target; forbidden or secret paths
   never gain an identity receipt. Test success/refusal aliases and early denials.
2. Snapshot/contract/kernel/instruction refusals preserve target bytes and all
   legacy fields. Prove each real refusal path and existing Action payload shape.
3. An OSError after actual write/delete must be unknown despite changed bytes.
   Exercise the real mutation before injecting that exception.
4. Cancellation during a filesystem worker can leave a later effect. Use bounded
   event-controlled workers, release/join in finally, assert cancellation escapes.
5. Gated ToolRPC intake has no receipt/effect; trusted approved execute transports
   actual receipts and keeps failures failed. Exercise real registration/execute.

## Task 1 — direct receipts and production (auth_audit, gpt-6-sol/high)

Own `agents/core/file_tools.py` and new `tests/test_file_mutation_receipts.py`.

- [x] Add tests through real FileTools calls: existing/new writes, delete/restore,
  allowed symlink alias, snapshot failures, missing/non-file targets, contract
  denial, kernel DENY/QUEUE/error, instruction floor, OSError before/after apply.
  Assert legacy fields and filesystem observations before the missing receipt.
  Include unchanged early-denial controls for invalid content/size/scope/secret/
  root. Do not weaken existing tests or change existing fixtures to hide drift.
- [x] Run new tests against unchanged production; save RED XML/log under
  `/workspace/scratch/mutation-receipts-direct-red.*`. Root must inspect failures
  and baseline source hashes before releasing implementation.
- [x] Add the pure wrapper and apply it only at the specified existing return
  branches. Preserve old control flow and result fields; do not catch more errors.
- [x] Run new direct tests plus existing file tools, instruction floor/class and
  code-guidance modules; record green and source digest. Root owns commits.

## Task 2 — execution/cancellation boundary (mobile_session_transport, sol/high)

Own new `tests/test_file_mutation_receipt_execution.py`, tests only.

- [x] Use actual registered gated FileTools and ToolRPC: intake requests approval
  with unchanged file and no receipt; valid trusted execute gives applied receipt;
  actual kernel refusal and apply OSError produce failed envelopes retaining the
  returned receipt. Class mismatch/trusted-context denial omit receipt and effect.
- [x] Demonstrate task cancellation while real `_apply` worker waits, then release
  it to perform a real write; cancelled await has no normal result even when the
  file changes later. Test escaped handler exception is the old tool_error without
  receipt. No sleeps or leaked threads; bounded events/finally cleanup.
- [x] Save actual tests-only RED before source release, then focused green after
  Task 1. Independently review production against the complete contract.

## Task 3 — integrate evidence and verification (root)

- [x] Confirm all returned receipts are source-assigned, legacy result fields and
  control flow unchanged; inspect independent review and all meaningful RED.
- [x] Review ten base-fresh file_tools pins before refreshing; add narrow H396
  evidence/remaining, architecture/build queue/parity notes and generated counts.
  Keep all stored ledger statuses/identities and preexisting stale pins unchanged.
- [ ] Freeze source/tests, run combined focused regressions, Ruff/diff/status/
  Hermes and one serial full backend milestone. Compare exact skipped identities
  with `h396-backend-final.xml`; run actual executed-count guard. Client counts
  2039 frontend/native and 316 mobile are reused because clients do not change.
- [ ] Save proof, manifests and clean local commit; report limits truthfully.

Rollback: revert this additive result/test/docs unit; no migration or persisted
schema change. An absent receipt remains unknown to any future consumer.
