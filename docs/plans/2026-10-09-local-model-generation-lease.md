# Local model protection before residency work

- Generated: 2026-10-09 UTC.
- Goal: close the software eviction window between residency confirmation and
  in-flight protection in both Agent.process and Agent.synthesize.
- Base / HEAD before edits: ef56dd389976a2acc3ebaab3f594a2ff80eaa90e.
- Branch/worktree: codex/local-model-generation-lease-20261009,
  /workspace/jarvis-hub-model-generation-lease.
- Scope: owner-authorized autonomous LOCAL development. No push/merge/deploy,
  live model, controller activation or physical-device claim.
- Next action: meaningful production-path regression RED, minimal reorder, GREEN.

## Contract and choice

The current Agent paths await the route-aware _ensure_resident hook before
entering ModelManager.using. A concurrent local request can evict the first model
in that interval. using already records active references even for unconfirmed
models, and a confirmed load transfers them into its resident entry. Its lock
and cleanup already implement the needed primitive.

Enter the existing local-only using context before calling the existing
route-aware _ensure_resident hook, then keep the context through generation.
Apply this to BOTH process and synthesize. Preserve prepared-route validation
and generation/data-handling guards after the residency await. Keep _NullCtx,
default-off, absent-manager, cloud route and refused-controller behavior.
No new manager API is needed. Keep the manager's existing best-effort overcommit
policy; no admission control, load waiting, physical VRAM reservation, canonical
provider reconciliation or ComfyUI participation is added. Exact controller
acknowledgment still does not prove measured hardware residency.

Update ModelManager usage documentation to show protection before ensure; the
standalone ensure API remains compatible and is not itself an atomic lease.
Avoid unrelated routing, checkpoint, response, failure-count or latency changes;
if moving the await affects the existing latency boundary, review it explicitly.
All tests use injected controllers/backends, no real model or network.

## Ownership and checks

- auth_audit (gpt-6-sol/high): agents/core/agent.py,
  agents/core/llm/model_manager.py (documentation only unless a demonstrated
  defect requires coordinated expansion), NEW tests/test_agent_model_lease.py.
  Write a deterministic RED for each real Agent call path. A route hook should
  pause AFTER manager.ensure_resident returns; competing B under a one-model
  budget used to unload A before A's context entered. Assert actual unload
  history/residency at generation, not only call order or mocked using calls.
  Then minimally reorder. Cover cancellation during load, refusal/no-controller
  continuation and release, concurrent same-model reference ownership, generation
  error/guard refusal cleanup, cloud/no-manager/default-off compatibility.
- mobile_session_transport (gpt-6-sol/high): independent read-only contract and
  regression review once frozen; no overlapping edits. Bounded named collateral
  claim review can be assigned after pin inventory.
- wall_contracts (gpt-6-luna/medium): read-only affected evidence-pin and current
  source-coordinate inventory against exact base; no refresh or status mutation.
- Root: plan, source/control-flow review, integration, metadata/ledger/documents,
  bounded named claim review, git. At most four active including root; no nested
  delegation. Focused tests during implementation; one serial full backend
  milestone after frozen integration. Reuse unchanged JS/native evidence.

Run model-manager/controller, both Agent integration paths, local-only synthesis,
prepared-route and agent runtime/guard regressions. Preserve route/schema parity.
Record RED/GREEN and full executed counts; generated status must match actual
collection. Refresh only pins that were current at base after named claim review;
leave unrelated preexisting stale pins stale. H515 stays partial for its larger
resource-coordination and physical residency gaps. Narrow its remaining lease
wording only to the demonstrated two Agent local text paths.

Rollback source ordering, new tests, usage documentation and scoped evidence as
one reversible local unit. No stored-data migration or public interface change.

## Implemented and focused evidence

Both production-path eviction regressions were RED before the two source reorders.
Review then found generation parameters had moved ahead of the residency await;
separate RED cases reproduced that drift, and selection is again after the await.
The writer's eight-file union is 330/330; root's disjoint 16-file compatibility
union is 336/336, all without failures/errors/skips. The new module has 22 cases.
Source is frozen with no Critical/Important issue from independent review.

The process clock resets after residency/parameters: loading stays outside latency,
reference acquisition wait is now also outside it, and a parameter exception is
accounted by the existing failure handler while the context releases protection.
ModelManager executable AST is unchanged; all other 27 Agent methods and the rest
of the module are unchanged. No public route/schema, client or authority change.

Canonical collection is 21,274 backend cases, routes 555; unchanged frontend/native
2,009 and mobile 306 inventories retain their earlier evidence. Ruff, whitespace,
Hermes and status checks pass. Named collateral review supports ten current pin
refreshes plus two new direct H515 evidence pins; eight preexisting stale Agent
pins remain stale. H515 summary/remaining now distinguish these two protected
local text paths from broader unresolved generation/resource leases. Its partial
status and all other claim/status text remain unchanged. The full backend
milestone follows the source checkpoint and is recorded in the integration proof.
