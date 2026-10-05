# H067 pending input groundwork — partial local checkpoint

Goal: all697 pinned Hermes capabilities. Generated2026-10-05, head
a7ffad6676cfb28e7ac374d495b4a5889e5f4646, preserved dirty local worktree.
Reference: Hermes59b2aeef6c7a, MIT attribution in the H067 license file.

502 affected tests passed, with zero failures/errors/skips and zero drift across
2036 frozen Python/contract inputs. The XML is sanitized; report.json records
the raw hash and prior RED attempts. Ruff and scoped Bandit passed. The latest
full backend/frontend evidence belongs to the earlier H063 snapshot; no new full
suite, live provider/channel or GitHub-CI claim is made here.

Implemented: pending parser/state, exact prompt cleanup, governed ledger surface,
opt-in ToolRPC clarify producer and pre-lease direct Gateway interception, strict
Telegram temporary-notice send/delete, and a durable conversation-only undo utility.
Default-off preview is deliberately not an activation or complete H067 claim.

Next action: integrate Telegram polling/lane and saturated-rate pending reply
ingress, keeping pairing/origin before resolution; then native cards, destructive
commands and their governed permanent opt-out. The undo helper still needs the
owner/generation/lease/preappend command gate. Workspace output still needs real
governed delivery receipts before credit. See report.json for the complete original
remaining contract, including batch/Other behavior, memory bypass and full suites.

Shutdown is bounded best effort: admission closes before the transport, but an
already-started cancellation-resistant delete can finish remotely later. An
unfinished drain is reported and its late result is abandoned, not counted as a
successful shutdown-time deletion. No forced remote-IO-stop claim is made.

Rollback: localized reverse diffs against /tmp/nerva-h067-baseline-20261005;
never restore entire files over inherited work. No staging/commit/publication.

## Paths changed in this checkpoint

| Path | Purpose |
| --- | --- |
| agents/core/channels/pending_input.py | Identity-bound parsing, FIFO state and exact-prompt cleanup |
| agents/core/channels/pending_input_runtime.py | Opt-in clarify producer and delivered Gateway response binding |
| agents/core/channels/ephemeral.py | Text-compatible notices and bounded deletion ownership |
| agents/core/memory/session_undo.py | Conversation-only durable rewind utility |
| agents/core/permission_ledger.py | Governed always scope for session_command, required consent check |
| agents/core/channels/telegram.py | Strict sent-message acknowledgements, topic/voice-safe temporary notices |
| agents/core/orchestrator.py | Request lifetime, pre-lease interception and shutdown cleanup |
| agents/core/autonomy_coordinator.py | Conditional clarify ToolRPC registration |
| agents/core/orchestrator_bindings.py | Coordinate-only writer inventory adjustment |
| agents/core/settings_db.py | Default-off clarification preview and zero-default notice TTL |
| tests/test_pending_input.py | Pure parser/state regressions |
| tests/test_pending_input_runtime.py | Gateway/ToolRPC wait, identity, credit and cleanup regressions |
| tests/test_ephemeral_reply.py | Acknowledgement, topic, deletion and resistant shutdown regressions |
| tests/test_session_command_permission.py | New governed permission-surface regressions |
| tests/test_permission_ledger.py | Exact surface manifest includes session_command |
| tests/test_session_undo.py | Real durable undo and failure/cancellation cleanup |
| docs/hermes/pending-input-plan-2026-10-05.md | Original full contract and integration interfaces |
| docs/hermes/licenses/hermes-pending-input-MIT.txt | Full donor attribution and license |
| docs/hermes/assessment.json | H067 partial and bounded collateral review of current preimages |
| HERMES_STATUS.md, docs/HERMES_CAPABILITIES.md | Generated truthful697-row status |
| This evidence directory | Sanitized results, frozen input hashes and remaining integration work |
