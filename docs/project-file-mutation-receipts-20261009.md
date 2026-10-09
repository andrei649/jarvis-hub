# File mutation receipts — local H396 prerequisite

Generated 2026-10-09 UTC. Base `ca1b0d5e09c5439ee4211bc68d985fe05a78e89d`;
branch `codex/file-mutation-receipts-20261009`. Local only; PR #1247 contains
only the earlier published mobile-session work.

Returned FileTools mutation handlers now add `mutation_receipt` with exactly
`path`, `op` and `outcome`. Seven existing returns after allowed non-root path
resolution receive this field; all legacy result fields are preserved.

- `refused`: this attempt never submitted `_apply`. Snapshot, contract, kernel
  and instruction-floor refusals retain their existing reasons and snapshot refs.
  This does not say snapshots/audits were absent or another actor made no change.
- `applied`: `_apply` returned normally. This does not prove read-back, directory
  durability, current contents or which concurrent attempt won.
- `unknown`: the existing apply OSError handler ran. Tests exercise errors both
  before and after real writes/deletes; a changed target remains possible.

Content/size validation, invalid/forbidden/secret/root paths and pre-handler
refusals have no receipt. Escaping errors and cancellation still propagate;
cancellation can leave a filesystem worker running with no returned receipt.
An absent receipt is unavailable evidence, never proof of refusal or no effect.

The execution boundary matters: registered file mutations are gated and trusted.
The model-loop `handle` path only queues approval. The actual handler runs later
through approved `ToolRPCServer.execute`, which carries the receipt in its
existing result envelope and keeps failed handler results failed. This is not a
same-turn footer or an addition to the H686 HTTP/SSE chat outcome.

The path describes the execute-time resolved target selected by existing scope
logic, not a stable inode or race-free identity. The outward result passes through
ToolRPC scrubbing, so its path cannot be a trusted future correlation key. A
future footer needs requesting-turn/task/attempt attribution, trustworthy target
identity, unknown/lost/cancelled-result handling and established ordering. Task
DONE or task ID alone does not prove successful unique execution. No such
aggregation or supersession logic is added here.

Scope, snapshots/restore, kernel Action payloads, approval cards, instruction
classification, scheduling, audit calls and code guidance remain unchanged. No
runtime, ToolRPC, worker, executor, client, setting, route, dependency or stored
schema changes. The new observation is result data, not a new log/tool event.

## Verification

- Corrected direct tests-only RED: **20 cases, 18 missing-receipt failures and
  two controls**, zero errors/skips, 1.278 s. Each failure follows real legacy
  branch/filesystem assertions. Root separated successful delete, instruction
  floor and canonical-alias denial into independently reached cases before
  source release. Initial bundled 17-case artifacts remain preserved.
- Approved-execution RED: **8 cases, five missing-receipt failures and three
  controls**, zero errors/skips, 2.189 s. Tests use real registration, gated
  intake, trusted execute, failed envelopes, changed bytes before OSError and
  cancellation followed by an event-controlled late filesystem effect.
- Root verified all three baseline source digests before implementation.
  Final direct/file-tool/instruction/code-guidance suite: **264/264**, 4.209 s.
  A subsequent helper-docstring precision edit changes no execution; final-hash
  approved-execution suite: **8/8**, 1.168 s.
- Root integration: **226/226**, 10.390 s across 12 disjoint modules covering
  document reads, search, spill paging, project context, identity, ToolRPC/kernel/
  sandbox behavior and route/OpenAPI parity. Combined focused evidence is
  **498 distinct cases**, with no failures/errors/skips.
- AST comparison proves the entire file-tools module equals the base after
  removing the pure helper and unwrapping seven result calls. Independent source
  and ten-row collateral reviews found no Critical/Important issue.
- Collection: **21733 backend** (28 added), **2039 frontend/native**, **316 mobile**,
  555 routes, 18 agents. Client counts are reused from the prior verified unit;
  no client code changed. Full backend verification is pending; collection is
  not a passing full run. No live provider/device test was run.

Eleven base-fresh evidence pins refresh after named review: ten file-tools claims
and H670's architecture identity-band claim. Moved H507/H661 citations retain
their statements; H670's instruction-name line is unchanged. Four narrow H396
pins are added. All 226 stored review statuses/identities and the inventory hash
remain unchanged; older unrelated stale evidence stays stale. H396 stays partial.

Artifacts `/workspace/scratch/mutation-receipts-*` retain RED/green/integration,
source/AST/line maps, pin inventory and reviews. Two gpt-6-sol/high agents owned
direct source/tests and execution tests/review; gpt-6-luna/medium performed the
read-only inventory. Root owned scope, RED release, integration, metadata and git;
maximum four active, no nested delegation.

Rollback is this additive result/test/docs unit; no migration is needed.
