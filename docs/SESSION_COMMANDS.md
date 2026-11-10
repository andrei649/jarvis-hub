# Session commands: /plan, /loop, /btw, /context, /compress

These commands work in any chat that reaches Nerva: the HUD, `nerva chat`, Telegram and the
other channels. `/plan`, `/loop`, `/proactive`, `/context` and `/compress` are owner
commands. `/btw` follows the channel's access list (`commands.user_allowed_commands`).

## /plan — plan first, change nothing

```
/plan add a dark mode toggle to the settings page
/plan                 plan what we have been talking about
/plan status          is plan mode on here, and which plans were saved
/plan off             leave plan mode (also: exit, done)
```

`/plan <task>` does three things:

1. It puts this conversation in **plan mode**. In plan mode only reads run. Any tool that
   writes, sends or runs something is refused before it can even ask for approval, and
   so is any action the Action Kernel sees that is not a read. Searching the web (a GET)
   and reading files still work.
2. It asks the model for a written plan, using Hermes's own plan prompt: goal, context,
   step-by-step tasks with exact file paths and commands, tests, risks. If the request is
   unclear, the model asks you a question instead of guessing.
3. When the model answers, Nerva saves the plan as a markdown file in
   `<data>/plans/YYYY-MM-DD_HHMMSS-<topic>.md` and tells you where.

Plan mode stays on for this conversation, also after a restart, until you send `/plan off`.
Only you can turn it on or off. If the plan-mode state file is ever unreadable, every
conversation is held in plan mode until you send `/plan off`.

## /loop — repeat a prompt in this conversation

```
/loop 5m check the deploy status          first run now, then every 5 minutes
/loop every 10m /recap                    repeat a slash command
/loop keep an eye on the queue            self-paced (see below)
/loop 2m poll CI --times 30               stop after 30 runs
/loop 5m watch the queue --until the queue is empty
/loop status · /loop pause · /loop resume · /loop stop
```

`/proactive` is the same command.

- **Fixed cadence:** `30s`, `5m`, `2h`, `1h30m`. The shortest interval is 30 seconds.
- **Self-paced** (no interval): the first check is after 1 minute. While the answer stays
  the same (times and durations are ignored when comparing), the wait doubles, up to 15
  minutes. As soon as the answer changes, it goes back to 1 minute.
- **Stopping:** the loop stops when the model ends an answer with `LOOP_COMPLETE` on its
  own line, when the `--until` condition is met (a local model judges the answer; if it
  cannot, the loop goes on), or after `--times N` runs. After 100 runs without a limit
  the loop **pauses**; `/loop resume` continues it.
- **Safety:** every wakeup is an ordinary turn. Before it runs it is checked like any
  action: the kill switch, plan mode, approval mode `off` and the loop's budget (24 hours
  from when you set it, and its run limit) can each stop it. When that happens the loop
  pauses and says why. The emergency stop (`/pause`) pauses every loop. A wakeup never
  starts while a turn is running in the same conversation, or while a goal run is active.
- The loop is saved with the conversation, so it continues after a restart.
- Wakeup answers appear in the conversation (the HUD chat, `/recap`). On chat channels
  such as Telegram they are not pushed to you yet.

## /btw — a side question about this conversation

```
/btw what did I ask first?
```

Nerva reads the whole conversation (as much as the local model can hold), with secrets and
personal data removed, and answers once on the local model, beside the conversation.
Neither the question nor the answer becomes part of the conversation, and the side
answer cannot use any tool. What it used is counted against this conversation
(`GET /api/analytics/session-usage?session_id=…`, purpose `btw`).

## /context — what fills the model's window

```
/context          the meter
/context all      also every tool and skill, one per line
```

Shows a 10×10 grid and a table: how many tokens the system prompt, the tools, the skills,
your memory, the conversation history and attachments (images and `@file` blocks) take,
against the model's window, and where compaction starts. The same numbers are in the HUD
(Console → **Context Meter**) and at `GET /sessions/{session_id}/context`. All figures are
estimates; when the model provider measured the last request, that number is shown too.

## /compress — what compaction will do

Nerva compacts a long conversation on each turn, inside the request it sends, and never
edits the saved conversation. `/compress` tells you which of the three things the next
turn will do: nothing (below 60% of the window), drop older images (above 60%), or also
summarise the older text (above 85%, keeping the first and the latest turns). It changes
nothing itself.
