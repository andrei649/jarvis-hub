# Owner Test-Drive Guide — structured real-usage pass

> Written after the first B0 feedback ("full of bugs or confusing things", 2026-07-07).
> This is a **driving script**, not a checklist audit (that's [MANUAL_TESTING.md](MANUAL_TESTING.md)):
> ~2 hours in 6 short sessions, each says exactly what to do and **what should happen**,
> so every deviation you notice is a finding. Do sessions on different days if you like —
> Session 4 (memory) actually works better across days.

## How to capture findings (the whole point)

Keep a raw text file open. One block per observation, in the moment, no polishing:

```
DID:       (what you clicked/typed)
GOT:       (what happened — paste errors verbatim, screenshot if visual)
EXPECTED:  (what you thought would happen)
HURT:      blocker / annoying / cosmetic
```

Paste the raw file to the AI session when done — it becomes the triaged backlog.
Rule of thumb: **if you hesitated, that's a finding too** ("I didn't know what to click" is data).

---

## Session 0 — Preparation (10 min)

1. Update to the latest branch build (`claude/project-review-handoff-yq9za9` or the merged main) and restart.
2. **Turn the brain on** — the cognition/memory/learning stack is default-OFF and most
   "Jarvis feels dumb" impressions come from testing with it off:
   - Admin → Settings → `product.posture` → **`companion_wave1`** (or `PUT /api/admin/settings`).
   - Verify: `GET /api/security/posture` shows the posture; `GET /api/cognition` shows enabled.
3. Confirm your model is loaded in LM Studio (badge top-right of the HUD or the Model card).

**Should happen:** posture change takes effect ≤30s, no restart. If chat quality doesn't
noticeably change after this session vs. before — that's finding #1, write it down.

## Session 1 — First run, as a stranger (15 min)

1. Open the HUD in a **private/incognito window** (clean localStorage = first-run state).
2. **Should happen:** a "FIRST RUN" panel lands front-and-center (the Command Center):
   install ready ✓, your model named, wizard progress dots, first actions with honest
   ready/held states. *(New since your feedback — if you don't see it, blocker.)*
3. Click **run** on "Say hello". **Should happen:** a real reply appears in the panel and
   the wizard's test_chat step ticks.
4. "Continue to cockpit", then reload. **Should happen:** the gate does NOT reappear
   (dismiss persists).
5. Walk the remaining wizard steps from Console ▦ → Start.

## Session 2 — Conversation quality, the "hermes gap" measured (25 min)

This is where "nowhere near hermes-agent" becomes specific. Ask these 8, in Romanian
and English, and grade each reply 1–5 with a one-line "what a better agent would have done":

1. "What's on my plate today?" (should use calendar/tasks if configured, or say honestly it has none)
2. A multi-step ask: "Research X and give me 3 options with trade-offs" (does it act, or just talk?)
3. A domain route: a finance question, then a fitness question (do sensible agents answer?)
4. A follow-up referencing turn 1 ("and which of those is cheapest?") — context held?
5. Teach it: "Reține: prefer răspunsuri scurte, fără emoji." — then ask anything. Did style change?
6. A correction: tell it it was wrong about something. Does it acknowledge and adjust, or fold instantly?
7. Something it CAN'T do. **Should happen:** honest "can't", not confabulation.
8. "What model are you running?" **Should happen:** the real loaded model, not a guess.

**Capture per reply:** grade, latency feel, and specifically *what hermes/ChatGPT would have
done differently* — those notes decide whether the next big build is the agentic tool loop.

## Session 3 — Governed autonomy, the product's core (20 min)

1. Ask for a task with one irreversible step ("draft and send an email to myself about X").
2. **Should happen:** draft happens autonomously; the SEND blocks with a decision card
   (Decision Inbox / Telegram) showing a preview + irreversibility flag.
3. Approve → **should** execute (check your inbox). Trigger another → Reject → **should not**.
4. Open the audit log (Console → Trust). **Should happen:** every step recorded, chain verified.
5. Start another task, hit the kill-switch mid-run. **Should happen:** immediate halt, task
   held not lost; disengage releases it.
6. Check `GET /api/metrics/north-star` — your approve/reject just became data. Does it show?

## Session 4 — Memory, across days (15 min + tomorrow)

1. Tell it 3 real facts (a preference, an upcoming date, an open concern).
2. Tomorrow, new session: "Ce știi despre <fact>?" **Should happen:** recall without re-telling.
3. Check the morning brief mentions the upcoming date / open concern (caring follow-ups).
4. Forget-test: delete one fact (Memory panel / forget). Ask again. **Should happen:** it's gone —
   and stays gone after a restart.

## Session 5 — Proactive day (10 min, passive)

Leave it running a full day with heartbeats on. **Should happen:** morning brief arrives once,
interrupts stay ≤4/day, nothing spams you. Capture: was ANY proactive output actually useful?
(Brutal honesty here — "technically worked, practically noise" is the most valuable finding type.)

## Session 6 — Optional surfaces (only what you use)

- **Telegram:** message it from your phone; reply lands; an inbound task from Telegram should
  require approval (inbound = untrusted).
- **Voice:** one push-to-talk turn; one TTS reply.
- **Mobile app:** Status tab shows the First-run card + Trust card; Approvals tab decides a real task.
- **WorldView:** only if you started it with `JARVIS_WORLDVIEW=1` — it has NO live feeds by
  design; `npm run db:seed` gives badged demo data. Judge only: is the *empty state honest*?

---

## When done

Paste the raw findings file to the AI session. It will: triage into
blocker/annoying/cosmetic, open the fix loop top-down, and re-rank the backlog from
YOUR data — real usage now outranks every planned item. That's the operating model
from here to 1.0.
