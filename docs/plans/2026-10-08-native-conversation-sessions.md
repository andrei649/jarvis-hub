# Native conversation sessions (2026-10-08)

- Goal: adapt the recovered conversation-session behavior to current Nerva: owner-authorized `/new`, `/reset`, `/undo`; retained archived transcripts; generation-fenced channel routing; idle/daily rollover; progress-based stall feedback where an existing governed transport supports it.
- Base SHA: `8a02ff345bf81f4a2f162714567a59c185245099`.
- Head SHA at plan: `8a02ff345bf81f4a2f162714567a59c185245099`.
- Non-goals: Hermes runtime, Kanban, checkpoint/file capture or restore, terminal guardian, code context, vision, and bulk command imports.
- Paths: `agents/core/channels/session*.py`, narrow lifecycle callers in `agents/core/orchestrator.py`, `agents/core/commands.py`, `agents/core/scheduler_service.py`, `agents/core/settings_db.py`, `agents/core/memory/conversation.py`, `agents/web.py`, `frontend/src/app.tsx`, `frontend/src/desktop.tsx`, and `frontend/src/panels/sessions.tsx`; focused Python/API and frontend tests. Existing memory, owner/permission, Kernel, and delivery contracts remain authoritative.
- Web contract: `/chat` and the `/chat/stream` end event return the selected concrete `session_id`. The HUD sends this ID on subsequent turns and reopens an archived transcript through `/sessions/resume`. Old IDs remain exact historical IDs; they never alias a new generation. CLI receives the new ID in its command acknowledgement.
- Tests: recovered regression fails on base (missing `session_reset`), then focused session/channel/API integrations, admin settings persistence/validation, frontend transition/reopen/desktop tests, and Ruff after adaptation. `schedule_session_expiry` exercises idle rollover without inbound text.
- Dependencies: existing memory persistence, session leases, principal identity, permission ledger, and channel delivery checks. No added package.
- Rollback: revert this feature commit; saved conversation transcripts remain on disk. Generated route metadata must not be used as authority to delete transcripts.
- Rollback detail: remove the lifecycle scheduler job and UI ID tracking with the feature commit; route-index SQLite state can be retained or backed up without changing conversation snapshots.
- Generated: 2026-10-08.
