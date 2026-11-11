# Owner event hooks (G17)

An owner hook is a program you name that Nerva runs when something happens: before or after
a tool call, when a message arrives or a turn ends, when a session starts or ends, after a
slash command, and when an approval is asked for or decided. It is how you make Nerva fit
your machine without writing a plugin: log every command the agent runs, ping your phone
when a turn fails, or refuse a tool call your own script does not like.

Hermes rows: H163 (the HUD section), H514 (consent once, in writing), H021 (`hooks`
verbs), H408 (the lifecycle hooks and their wire protocol). Code: `agents/core/hooks/`,
`agents/core/routers/hooks.py`, `frontend/src/panels/hooks.tsx`, `nerva hooks`.

## Adding a hook

From the HUD (Console → Admin → **Hooks**), or:

```bash
nerva hooks add tool.before --guard --matcher 'terminal_*' -- /usr/bin/python3 /home/me/hooks/guard.py
```

Adding a hook **does not make it run**. It queues an approval card in the decision inbox at
the irreversible tier. The card shows the exact command, the event, the tool matcher,
whether the hook is a guard, its timeout, and every file that runs (the program and, for a
shell or an interpreter, its script) with its size and sha256. The hook runs only after a
person accepts that card as it is. A machine decision, an edited card, or a card whose
files changed since you asked is refused.

The hub refuses to define or run hooks until it has an **admin credential**
(`NERVA_ADMIN_TOKEN` or a minted admin token). A hub without one trusts every local program
as the owner, so a hook could decide approval cards for itself.

What a command may be:

- `argv[0]` is an absolute path to a regular file that only you (or the system) can write;
- a launcher that runs something else from its arguments (`env`, `sudo`, `xargs`, `find`,
  `npx`…) is refused; a shell (`/bin/bash`) or an interpreter (`python3`, `node`…) is
  allowed only with a script named by absolute path right after it (no `-c` / `-e`), and
  that script is bound by its hash like the program;
- the hardline denylist applies, and an argument that looks like a key is refused (a
  command line is visible to every process on the host);
- the arguments are fixed. **Nothing from an event is ever put on the command line**: there
  is no placeholder syntax and no shell.

Changing a script after approval stops the hook (`changed_since_approval` in its last run,
"files changed" in the HUD and `nerva hooks doctor`) until you approve it again. Switching a
hook off and removing it apply at once. Turning it back on is a new card. To change a hook,
add the new one with `--replaces <id>`: the old one keeps running until the new card is
accepted.

## Events

| Event | Hermes name | Blocking | What `extra` carries |
|---|---|---|---|
| `tool.before` | `pre_tool_call` | yes | `agent_id` (plus top-level `tool_name`, `tool_input`, `session_id`) |
| `tool.after` | `post_tool_call` | no | `status` (plus `tool_name`; never the arguments or the result) |
| `message.received` | `pre_llm_call` | no | `channel`, `chars` (never the text) |
| `turn.completed` | `post_llm_call` | no | `channel`, `status` (`ok`, `refused`, `error`), `duration_ms` |
| `session.started` / `session.ended` | `on_session_start` / `on_session_end` | no | — |
| `command.completed` | `pre_command` | no | `command`, `status` |
| `approval.requested` | `pre_approval_request` | no | `request_id`, `surface`, `command`, `description` (secrets masked) |
| `approval.decided` | `post_approval_response` | no | the same plus `choice`, `decided_by` |

`--matcher` (tool events only) is a tool name or a glob such as `terminal_*`.

## What a hook reads and may answer

stdin is one JSON object, the same shape Hermes uses, so scripts move between the two:

```json
{"hook_event_name": "pre_tool_call", "event": "tool.before", "tool_name": "terminal_run",
 "tool_input": {"command": "rm -rf build"}, "session_id": "…", "cwd": "<data>/hooks/run",
 "extra": {"agent_id": "jarvis"}, "nerva": {"hook_id": "hk-…", "occurred_at": 1762862400.0, "guard": true}}
```

A `tool.before` hook blocks the call with **exit code 2** (the first 400 characters of
stderr are the reason) or by printing `{"action": "block", "message": "…"}` or
`{"decision": "block", "reason": "…"}`. The model is told the call was blocked by an owner
hook, with that reason.

Nothing else is honoured. `allow`, `approve` and `modify` answers are recorded as ignored:
**a hook can never allow a call** that the approval queue or the Action Kernel would refuse
(it runs before them and they still decide everything they decided before), and it cannot
change a call's arguments. For every other event, nothing a hook prints is read.

**Guards.** If a hook fails (refused, timed out, crashed, exited with neither 0 nor 2, or
printed something that is not a JSON object), a hook you marked as a guard (`--guard`,
`tool.before` only) blocks the call: it fails closed. Any other hook lets the call through
and the failure is audited (it fails open).

## How a run is governed

Before each run: the hook is still active, its files still have the approved content,
`NERVA_HOOKS` is on (default on; `0` switches every hook off), safe mode is off (no hook
runs in safe mode; a guard does not block either), the emergency stop is off, the hub has an
admin credential, and, with `NERVA_ACTION_KERNEL` on, the Action Kernel grants the run as
`hook.exec` (risk tier 3) through the receipt of the task that activated that exact hook.
The kernel's mode `off` refuses it.

The run goes through the governed local host transport: the argv verbatim, no shell, the
private working directory `<data>/hooks/run`, an environment with every secret-looking
variable removed (no `*_TOKEN`, `*_KEY`, `*_SECRET`… and no `NERVA_*`/`JARVIS_*` except the
home and profile), the hook's timeout (default 10 s, at most `NERVA_HOOKS_MAX_TIMEOUT_S`,
30 s by default, ceiling 120 s; killed after it), and output capped at 8 KB. At most four
hooks run at once; observer runs never delay the turn and at most 32 wait.

What this does **not** do: a hook runs as the hub's operating-system user. It can read
whatever that user can read, and Nerva does not sandbox it further. Approve only programs
you trust.

Every run is audited: an intent-log row `hook.run` (actor `hook:<id>`) with the outcome,
reason, exit code and duration, and the last 200 runs in the HUD and `nerva hooks list`.

## Commands

| | |
|---|---|
| `nerva hooks list` | every hook, its state, guard, matcher, file drift and last run; whether hooks can run here |
| `nerva hooks add <event> [--guard] [--matcher G] [--timeout S] [--name N] [--replaces ID] -- <argv…>` | queue the card |
| `nerva hooks test <id> [--tool T] [--payload-file F]` | run one active hook once on a synthetic event, through the same gates and evaluation (audited as a test) |
| `nerva hooks disable <id>` / `enable <id>` / `remove <id>` | switch off now / ask to turn on (a card) / delete now |
| `nerva hooks doctor` | exits non-zero when a hook's files changed or hooks cannot run here |

HTTP: admin-only `GET /api/hooks`, `POST /api/hooks`, `POST /api/hooks/{id}/disable`,
`POST /api/hooks/{id}/enable`, `POST /api/hooks/{id}/test`, `DELETE /api/hooks/{id}`; writes
must come from this origin as JSON.

## Not built (yet)

- Hermes's other events (context injection before a model call, `transform_*`, stream,
  sub-agent, kanban, gateway platform events, `pre_command`, `pre_verify`).
- Rewriting a tool call's arguments (`modify`): refused by design for now.
- `--accept-hooks`: there is no way to skip the card.
- Python plugin hooks that veto or rewrite (H080): signed extensions still only observe.
