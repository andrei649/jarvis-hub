---
name: max
description: Use when the owner says "Max" — alone, as a codename, in any casing ("max", "MAX", "run max", "continue max", "/max") — to start or continue the Nerva finishing protocol immediately, without questions or explanations. Also triggers on "max status" (report the run ledger's last row, nothing more).
---

# Max — start or continue the finishing protocol

Read **`MAX.md`** (repo root) and execute it. That file is the entire briefing; do not
improvise a different workflow and do not ask what to work on.

Non-negotiable behaviors of this trigger:

1. **No explanations.** Open with the ignition line from `MAX.md` §0 and start working.
   No plan-approval requests, no summary of the protocol.
2. **Continuation over restart.** Read `docs/MAX_RUNS.md` first — if the last row names a
   "next" item, that is your primary slice unless `BACKLOG.md` says it shipped meanwhile.
3. **"max status"** is the one read-only variant: reply with the last ledger row and stop.

While `MAX.md` is fresh in context, skip the `jarvis-load-context` Tier-0 sweep — `MAX.md` §2
defines the (smaller) load for Max runs.
