# R2 Taint Propagation Teeth Design

## Goal

Close the residual provenance gap where inbound content can enter the approval queue or vector memory without a durable taint marker, then later be treated as ordinary generated/local data.

## Non-Goals

- Do not enable the Action Kernel by default.
- Do not build a full LLM data-flow taint system.
- Do not change approval UI behavior beyond existing task payload/card metadata.
- Do not retag trusted web/voice/operator turns as untrusted.

## Design

`AutonomyWorker` becomes the queue-intake choke point for kernel-independent taint teeth. Both `govern_enqueue()` and `submit()` derive an effective origin from the explicit `origin` argument plus the current `action_origin` context, preserving an inbound parent context even when a caller accidentally passes the legacy default `"generated"`. If the effective origin is untrusted, the task payload is copied through `taint.mark_if_untrusted()`, persisted with the task, and forced to `ASK` even when policy would otherwise `ACT` or `NOTIFY`. Human edit decisions re-run the same marking before policy evaluation so an edit cannot launder an inbound task into auto-approval.

`Task.origin` remains a string for database compatibility, but the taxonomy is documented as `manual | generated | inbound`. This avoids a migration while making `inbound` a first-class queryable origin.

For memory, `MemoryManager.add_turn()` gains an optional `channel` argument. Existing callers remain compatible. Orchestrator user-turn writes pass the channel; only inbound user turns get vector metadata marked as tainted with a source like `inbound:telegram`. Assistant turns remain generated for this slice. `rag_guard.provenance_from_hit()` then prefers `metadata.taint_source` when `metadata.tainted` is true, so a vector hit from inbound content stays visibly untrusted when rendered and scanned.

## Data Flow

1. Inbound turn binds `current_action_origin() == "inbound"`.
2. A broker or worker enqueue reaches `AutonomyWorker`.
3. Worker marks the payload and forces `ASK`.
4. Task persists with `origin="inbound"` and `payload.tainted=true`.
5. If the owner edits the task, the edited payload is re-marked before policy decides.
6. User-turn vector embeds carry `tainted` and `taint_source`.
7. Recall provenance uses that taint source instead of generic `vector`.

## Risk

The intended behavior change is that inbound-origin tasks cannot auto-approve even without the Action Kernel. Trusted generated/manual tasks keep their existing policy behavior. The memory change is metadata-only and opt-in on existing `MEMORY_EMBED_TURNS`; conversation snapshots remain unchanged.

## Tests

- Worker red/green proves inbound `govern_enqueue()` forces `ASK`, persists taint, and blocks a policy-`ACT` task.
- Worker red/green proves inbound `submit()` does the same.
- Edit red/green proves an edited inbound task remains blocked and the edited payload is tainted.
- Memory red/green proves inbound user-turn embeddings carry taint metadata.
- Recall red/green proves tainted vector metadata becomes the rendered snippet source.
