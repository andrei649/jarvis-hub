# Session commands: /plan, /loop, /btw, /context, /compress, /verify

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

## /verify — check that a project still builds and passes its tests

```
/verify [path]                 the project, its test/lint/build commands, its recipe and evidence
/verify detect [path]          what Nerva detects from the project's files (nothing is run)
/verify save [path]            save the recipe as <project>/.hermes/environment.json
/verify run [phases] [path]    run build and test (or: bootstrap, build, test, all)
/verify ledger                 the last checks and whether the evidence ledger is intact
/verify on-stop on|off         ask the model to verify before it says it is done (off by default)
/verify coding auto|on|off     the coding posture (brief + workspace snapshot)
```

The project is the one the path is in (a git repository, or a folder with `package.json`,
`pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, a Gradle file, a `Makefile` or a compose
file), else your default project folder (`llm.project_dir`), always inside your file roots.
Detection is Hermes's own recipe code: Node (npm, pnpm, yarn, bun; Next.js, Vite, SvelteKit,
Astro, Remix), Python (Django, FastAPI, Flask, pytest), Go, Rust, Maven, Gradle, Make and
docker compose. A saved `.hermes/environment.json` wins over detection; edit it to change what
`/verify run` runs.

**Running is never a shortcut.** Each command of `/verify run` is a normal `terminal_run`
call: it shows up as an approval card, follows your approval mode, the target policy and the
command denylist, and runs only on a terminal target you enabled. Nothing is queued while the
emergency stop is engaged or while the conversation is in plan mode (a test run executes the
project's code, so it is not a read). When a command waits for your approval the run stops;
approve it, then `/verify run` again continues with the next phase (a full run of the same
check that passed with the project's files unchanged since is not asked again; a run of one test
file never stands in for the suite). Nerva shows the app's start command but does not boot
the app or poll it.

**Evidence.** Every finished test, lint or build command of a project — yours or the model's —
is recorded with its result in an evidence ledger (`<data>/verify/evidence.db`). Each row is
hash-chained to the one before and anchored in the signed audit log, so a result cannot be
back-dated; `/verify ledger` checks both, and also says when a row is not anchored or when rows
were cut off the end. Any change to the project's files — an approved edit, a command, your own
editor, a `git pull` — makes earlier evidence stale (each result carries a fingerprint of the
files). A command that checks nothing (`--version`, `--collect-only`, `make -n`, `--listTests`)
is not evidence.

**Verify-on-stop.** With `/verify on-stop on`, when the model is about to finish a turn and this
conversation's edits to code (not prose) have no fresh passing check, Nerva hands the turn back
once with a note listing the project's commands (shown as data, and only commands that are plain
one-line strings). The model can only ask to run one, which again waits for you; a queued check
is never reported as a passing one, and the answer it first gave is kept.

**Coding posture.** When the model can edit or run code and the conversation's folder is a
project, its instructions carry a short coding brief and a snapshot taken once per conversation:
branch and upstream (ahead/behind), changed and untracked counts, the uncommitted diff size,
the last three commits and the project's commands. Git is run only for a repository whose own
config holds nothing but plain keys (remotes, branches, user name, line endings): a filter, an
include, a `config.worktree`, a partial clone, a signature program, `core.sshCommand` or any
other key means the snapshot says "Git: not read" and names the key, because such a config can
make git run a program. Commit messages and recipe names that look like instructions are
withheld. The project's AGENTS.md and similar files are presented to the model as untrusted
notes, never as rules. `/verify coding off` turns it off. The two `/verify` switches are your
configuration: in managed mode they cannot be changed here.

