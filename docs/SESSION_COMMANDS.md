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

Plan mode stays on for this conversation, also after a restart, until you send `/plan off`
(Hermes's plan mode lasts one turn; Nerva keeps it until you leave it). It follows the
conversation when it gets a new session id (`/undo`, `/new`, `/reset`, a chat's idle or daily
rollover). Only you can turn it on or off. If the plan-mode state file is ever unreadable,
every conversation is held in plan mode until you send `/plan off`.

**What plan mode covers, exactly:**

- every tool call the model makes in this conversation: only tools declared `read_only`
  run (`file_read`, `web_search`, `skills_list`, …). Tools that declare a state change are
  refused even when they look like reads: `skill_view` records the skill as loaded for the
  session, `todo` writes the list, `kanban_list` declares a reversible effect. Plan mode
  trusts what a tool declares, never its name;
- every action the Action Kernel mediates while a turn of this conversation runs: only
  `research` and a `plugin.egress` GET or HEAD pass. Every other kind is refused, whatever
  its name says (`checkpoint.restore` starts with "check" and restores files).

**What it does not cover:**

- your own slash and skill commands (`/remind`, `/memory approve`, a `/kanban` edit, a
  skill command): they are yours, and they run;
- writes the hub makes on its own after a turn, such as the background memory review
  (governed by its own approval setting) and the plan file itself;
- tasks queued for approval before you sent `/plan`, and sub-agents already running;
- reading the web: a GET can carry data in its address. That is true outside plan mode
  too; plan mode does not add or remove that channel.

**Where the plan is saved:** in Nerva's data folder, not in your project, because the model
cannot write in plan mode and the hub writes the file for it. The model's file tools are
limited to the folders you shared with it, so it does not read the plan file back on its
own; the plan is also in the conversation as its reply. Two plans on the same topic in
the same second get `-2`, `-3` … at the end of the name.

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
  the loop **pauses**; `/loop resume` continues it with another 100. A `--times` above 100
  raises the limit to that number. A loop whose prompt is a slash command (`/loop 10m
  /recap`) is not judged on the command's output; it runs until `--times`, the limit or
  `/loop stop`.
- **Safety:** every wakeup is an ordinary turn. Before it runs it is checked like any
  action: the kill switch, plan mode, approval mode `off` and the loop's budget (24 hours
  and its run limit, both counted from when you set it or last resumed it) can each stop
  it. When that happens the loop pauses and says why; `/loop resume` gives it a fresh
  24 hours. The emergency stop (`/pause`) pauses every loop. A wakeup never starts while a
  turn is running in the same conversation or chat. (A company-mode goal run takes no turn
  in a conversation, so it does not hold a loop back.)
- **Whose authority:** a wakeup runs as you. On a chat channel such as Telegram, whether
  the chat is still yours is checked again before every wakeup, exactly as for a message
  you type (the owner ids, the pairing, a running adapter); if it is not, the loop pauses
  and nothing is sent there, not even the pause notice (it is in the conversation and the
  audit log). `/loop` is refused in a group.
- The loop is saved with the conversation, so it continues after a restart, and it moves
  with the conversation to a new session id (`/undo`, `/new`, `/reset`, a chat's rollover;
  a chat's rollover moves only a loop set from that chat). A wakeup holds the conversation
  for its whole run, so a change waits for it, and a wakeup counts as activity in its chat,
  so a chat a loop is still talking in does not roll over for being idle.
- Wakeup answers appear in the conversation (the HUD chat, `/recap`). On Telegram, ntfy
  and other chat channels each answer is also sent to the chat the loop was set from.
  Slack, Discord and email answers stay on their reviewed reply path and are not sent by
  a loop.

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
