# Consumer First-Run Outcomes — Design

**Goal:** Turn the existing first-run Command Center from an infrastructure checklist into a truthful consumer activation surface that answers “what can Nerva do for me now?”

**Non-goals:** No new runtime, endpoint, credential store, external integration, or autonomous authority. No raw secrets or credential values in the response. No claim that a wired plugin is live unless its existing runtime honesty verdict says so.

**Approach:** Extend `GET /api/onboarding/command-center` with a bounded `starter_outcomes` projection derived from existing live model truth, configured document folders, and the canonical capability registry/plugin honesty layer. Render three outcome-oriented cards in the existing `CommandCenterPanel`: plan my day, use my private documents, and research the web. Each card carries `live` or `needs_setup`, a plain-language next step, qualified data locality, and a read-only effect declaration. Credential-backed plugin classes expose explicit configuration truth so construction alone never means live.

**Files:**
- Create `tests/test_plugin_runtime_honesty.py` and modify `tests/test_first_run_command_center.py` first (RED).
- Modify `frontend/src/test/command-center-panel.test.tsx` first (RED).
- Modify `agents/core/plugins/{gmail_plugin,google_calendar,spotify_plugin,homebridge}.py` and `agents/core/routers/onboarding.py` (GREEN).
- Modify `frontend/src/gap.tsx` (GREEN).
- Update `BACKLOG.md` only after verified completion, recording this user-approved product slice without changing the active release gate.

**Risks:** Runtime plugin objects can be absent or have incomplete honesty metadata. The projection therefore fails closed to `needs_setup`, stays bounded to three curated outcomes, and uses existing registry truth rather than inspecting credentials directly.

**Verification:** Focused backend test, focused Vitest, onboarding regression suites, frontend typecheck/build, Ruff, status-sync check, and final diff inspection.

**Rollback:** Revert the source, test, generated HUD bundle, backlog, and generated status changes as one delivery unit; the endpoint remains backward compatible because the new field is additive.
