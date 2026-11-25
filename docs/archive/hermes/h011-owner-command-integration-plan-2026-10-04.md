# H011 owner command integration

Generated 2026-10-04; base/head `2757922d4d0ee48376a538ec529add9125976c5f`.
Goal remains complete parity with all 697 pinned Hermes capabilities. The prior
turn made progress: terminal storage/provenance integration committed locally,
645 affected and 56 binding/reference cases passed. No publication is authorized.

Owned query paths: new `agents/core/checkpoint_inventory.py`,
`agents/core/checkpoint_commands.py`, new inventory/owner command tests;
`agents/core/commands.py`, existing preappend orchestrator/web hooks and tests;
CLI package `agents/cli/nerva.py`, its new test and the exact verb-tree assertion
in `tests/test_nerva_cli.py`. Root alone writes this checkout. The independent
manual local/SSH kernel implementer works only in an external snapshot on
environment runner/transport paths; shared coordinator/kernel/queue remain root.

1. Apply hash-verified inventory plus active-group correction. Run actual group
   lifecycle tests on the integrated, corrected storage source.
2. Demonstrate ADMIN registry lacks usable checkpoint queries before wiring.
   Add owner handlers for status/list and exact maintenance previews; raw
   commands remain outside chat history, notes and attached context. Check owner
   before constructing scope/store or accessing paths. Both handler and registry
   reject malformed/oversized commands rather than truncate an intended action.
3. Use existing SnapshotStore and configured file/local-terminal roots. Stored
   roots outside configured scope remain visible as unconfigured, never probed.
   Report bounded rows, unknown sizes and incomplete/truncated inventories honestly.
4. Emit exactly one checkpoint notice. Only a complete query/preview produces
   complete/preview; invalid, ambiguous or unavailable effects are not success.
   `--execute`/`--force` must never delete directly or fabricate an approval.
5. Integrate reviewed CLI wrapper through existing /chat and admin credentials;
   verify a real owner handler result is consumed by the CLI, with refusal and
   pending approvals overriding any success prose.
6. Run affected query/slash/CLI/web/session/lease/source gates. Freeze and record
   the batch with current source hashes; do not award H011 equivalence yet.

Required remaining H011 work, not dropped from scope: list/diff/select checkpoint
including ordinal and per-file selection; safe and explicit overwrite restore;
classified reversible/irreversible/instruction authority; exact maintenance
candidate/generation approval; at-most-once effect journal and restart handling;
original session/tail/clock binding across approval waits; filesystem success then
current-last-user rewind, separate partial outcomes and prompt cache invalidation.
Preview metadata grants no authority. No unrelated legacy archive is deleted.

Rollback removes registrations/CLI/query wiring while preserving checkpoint
rows, pre-undo refs, chat persistence and append-only audit. No live filesystem
operation outside synthetic tests, provider, push, merge or deploy is planned.
