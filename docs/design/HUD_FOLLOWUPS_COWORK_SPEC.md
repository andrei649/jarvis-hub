# HUD follow-ups — Cowork implementation spec

> Written for a **Claude Cowork session on the owner's machine** (it can `npm install`, build the
> frontend, and drive the browser to verify — the remote sandbox cannot). Each item lists what to
> build, why, the exact backend endpoints/files that already exist, and an acceptance test. Sources:
> the 2026-07-24 QA run (`docs/qa-runs/2026-07-24-cowork-run.md`) and the owner's asks
> ("how do I manage projects on multiple subjects with no chat history?" / "how does it show me
> what it did, visually?").
>
> **Backend is mostly done** — these are HUD/frontend tasks. Verify each in the real browser at
> `http://127.0.0.1:8080/`, not just in vitest. Follow `docs/COWORK_QA_RUNBOOK.md` for setup.

---

## 1. Transcript rehydration on refresh  (started — verify + finish)

**Status:** a first pass shipped in `frontend/src/app.tsx` (a mount `useEffect` that fetches
`GET /memory` and maps `turns → messages`, guarded against demo mode and against clobbering an
in-flight conversation). **This was written in the remote sandbox and NOT built or run** — Cowork
must `npm install && npm run build`, then verify and fix anything that doesn't compile/behave.

- **Why:** the conversation persists server-side (`ConversationMemory` → disk) but the HUD started
  the pane empty and never re-fetched, so every refresh dropped the visible transcript.
- **Endpoint (exists):** `GET /memory` → `{session, turns:[{role, content, agent_id, timestamp, token_count}]}` (`agents/core/routers/memory_hud.py:28`, last 20 turns of `orch.session_id`).
- **Message shape** the pane renders: user `{role:'user', text, ts}` · agent `{role:'agent', who, role_label, text, ts}` (see `app.tsx` `setMessages` call sites).
- **Acceptance:** send a chat turn, get a reply, hit refresh → the turn + reply are still there.
  Demo mode still shows its seeded corpus. A fresh session shows an honest empty pane.
- **Nice-to-have (optional):** a session picker over `GET /sessions` + `POST /sessions/resume`
  (`agents/core/routers/sessions.py`) so the user can reopen an older session, not just the current one.

## 2. "Projects" surface — manage multiple subjects with persistent history

The owner wants to run several subjects in parallel with their own history. **Two backend primitives
already exist and are under-surfaced** — this is a HUD task to make them first-class.

- **Rooms = topic threads** (`agents/core/routers/rooms.py`): `GET /api/rooms`, `POST /api/rooms`
  (name/description/agent roster), `GET /api/rooms/{id}/history`, `POST /api/rooms/{id}/message`
  (`@mention` routes to a specific agent), `DELETE /api/rooms/{id}`. Each room is a persistent,
  topic-scoped conversation with its own agent roster — exactly "a project".
- **Missions = governed project workspaces** (`agents/core/routers/missions.py`, `orch.missions`):
  `GET /api/missions`, `POST /api/missions` (title/goal/plan/budget), state machine
  `start|pause|resume|complete|cancel`, `POST /api/missions/{id}/steps/{idx}/finish`, budget-bound
  (409 on overrun), audit trail on `GET /api/missions/{id}`. Use these for multi-step project *execution*.
- **Build:** a **Projects** surface (a new mode, or promote the existing `RoomsPanel`/`MissionsPanel`
  in the Console to a top-level view) with a left rail of Rooms/Missions and a main pane showing the
  selected one's persistent history + roster + composer (with `@mention`). A "New project" action
  creates a Room (lightweight) or a Mission (governed, with budget) as appropriate.
- **Existing HUD pieces to reuse:** `RoomsPanel` and `MissionsPanel` already exist in
  `frontend/src/gap.tsx` (Console) — they call these endpoints today; the work is elevating them
  into a real project workspace, not building the data layer.
- **Acceptance:** create two rooms on different subjects, hold a conversation in each, refresh →
  both histories persist and are switchable; `@mention` routes to the named agent; a Mission with a
  budget pauses/resumes and shows its audit trail.

## 3. Visual "what it did" — a per-project/session activity timeline

The owner wants to *see*, visually, what the system did. Pieces exist but are scattered.

- **Data sources (all exist):** `GET /api/admin/audit` (real, hash-chained action log — the record
  of everything done), `GET /api/traces` + `/api/cost` (per-request traces + cost), `GET /tasks`
  (autonomy queue), `GET /api/cognition/stream` (SSE live reasoning), and the new Mission Control
  page `/mission-control` + `GET /api/swarm/summary` (live swarm view).
- **Build:** a **timeline** view (per session/room/mission where possible) that merges audit events +
  task decisions + traces into one chronological "here's what happened" stream, with filters
  (agent, kind, reversible/irreversible) and a link from each entry to its audit/trace detail.
  Mission Control already visualizes the *live* swarm; this is the *historical* per-project record.
- **Acceptance:** run a governed task (approve one, reject one), open the timeline → both decisions
  appear with real timestamps, the approved one links to its audit entry, nothing is fabricated
  (honest empty state when there's no activity).

## 4. Kill-Switch panel shows a false "ENGAGED · all agents halted"  (bug fix)

- **Symptom (QA):** the v2 Console TRUST Kill-Switch card showed red "ENGAGED · all agents halted"
  while `GET /api/security/kill-switch` returned `{"global": false, "halted": {}}` and agents were
  plainly working — a false safety alarm that undermines the governance story.
- **Root cause pointer (from QA):** a correct implementation exists in `agents/web/static/tools.js`
  (`KillSwitchPanel`, deriving `halted = !!(s.data.global || Object.keys(s.data.halted||{}).length)`);
  the v2 bundle (`frontend/src/…`, compiled into `agents/web/v2/assets/index-*.js`) has its own copy
  that isn't reflecting live API state. **Diff the two and fix the v2 binding** so the card derives
  its state from `GET /api/security/kill-switch` exactly like `tools.js` does.
- **Acceptance:** with nothing halted, the card reads a normal/armed state (not "ENGAGED"); engage
  the kill-switch → it flips to ENGAGED; disengage → back to normal. It must never show "halted"
  when the API says `global:false, halted:{}`.

---

## Notes for the Cowork session
- Backend for 1–3 already exists — do **not** rebuild it; wire the HUD to it and verify in the browser.
- Keep the honesty rule from the runbook: honest empty/"not connected" states are correct; never
  render seed/mock data as if it were live. The QA run's whole point was catching fabricated-as-real.
- Land each item as its own small PR (draft), with a vitest test where a pure seam exists and a
  browser-verified screenshot in the PR. Update `docs/qa-runs/2026-07-24-cowork-run.md`'s §K if a
  fix closes one of its findings.
