# Nerva in your editor (Agent Client Protocol)

`nerva acp` makes Nerva the coding agent of an editor that speaks the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP): Zed, JetBrains IDEs, and
any other ACP client. The editor launches the command and talks JSON-RPC to it over
stdin/stdout. Rows: G11 / H542, H543, H544, H545, H056.

## What it is (and is not)

- **The same Nerva.** Every prompt runs as an ordinary hub turn (`POST /chat/stream`): the
  same router, agents, Action Kernel, tool loop, memory and signed audit as the HUD. The
  `nerva acp` process has no agent loop of its own.
- **One conversation per editor thread.** Each `session/new` opens a hub conversation of its
  own (`acp_…`). The HUD's current conversation is never switched.
- **Bound to the editor's folder.** The thread's file tools and project files
  (`AGENTS.md`, `CLAUDE.md`, …) resolve inside the folder the editor opened, exactly like a
  `/worktree new` session. The folder must lie inside the hub's file roots
  (`JARVIS_FILE_ROOTS`); otherwise the session is refused (`cwd_outside_file_roots`). The
  editor can narrow what the tools reach, never widen it.
- **Live rendering.** Answers stream as message chunks; each tool call appears as a card with
  its kind (read, edit, execute, search, fetch…) and status. The tool's arguments and
  results are not shown on these cards, which is the same rule the HUD's tool trail follows.
  Nerva's `todo` checklist appears in the editor's plan panel. The hub's slash commands
  (`/plan`, `/review`, `/context`, `/compress`, `/goal`, `/verify`, …) are advertised for
  completion and dispatched by the hub as in the HUD. `/new`, `/reset` and `/undo` are not
  offered; start a new editor thread instead.
- **Cancel** stops the turn: the stream is closed and the hub cancels a turn whose client
  went away.

## Permissions: the editor is one more approval surface

When a turn needs your decision (a file write, a command, anything the kernel queues), Nerva
does what it always does: it queues an **approval card** and the turn stops. For each card
**this turn** queued, the editor shows a permission request:

- a file write or delete is drawn as the **real diff**: the current text (the editor's own
  buffer when it offers `fs/read_text_file`, otherwise the file on disk) against the exact
  bytes the write would leave;
- a command shows the **exact command**; anything else shows its payload;
- the card says its tier and whether it is **irreversible**.

Your answer is posted to the same route the HUD's card and `nerva approvals` use
(`POST /autonomy/tasks/{id}/decision`). It is one decision with two surfaces: a card already
decided in the HUD is not asked, and an answer to a card decided meanwhile elsewhere is
refused by the hub and reported. The rules:

| Editor answer | What Nerva does |
|---|---|
| Accept | `accept` on the card; the hub runs it and the card follows the result |
| Allow matching requests (session / always) | only offered when the hub itself offers a reusable consent for that card, and never for an irreversible card; posted to the hub's consent route |
| Reject | `reject` on the card |
| no answer within the timeout, Cancel, editor closed | **reject** (deny by default) |

Nerva never writes files through the editor (`fs/write_text_file` is not used): an accepted
write goes through the hub's governed file tool, with its snapshot and rollback, and the
editor sees the file change on disk.

Deciding needs the owner's credential: set `JARVIS_ADMIN_TOKEN` (or `NERVA_ADMIN_TOKEN`) in the
agent's environment. Without it, turns still run, the cards stay queued, and the editor tells
you to decide them in the HUD or with `nerva approvals`.

Timeout: `--permission-timeout SECONDS`, or `NERVA_ACP_PERMISSION_TIMEOUT` (default 300).

## MCP servers the editor hands over

An editor can pass MCP servers with a session (`session/new` → `mcpServers`). Nerva treats
each one as a **new MCP server**, which needs your consent:

- nothing starts when the session opens. At the session's first prompt the editor asks you,
  per server, showing the command, its arguments and the **names** of the environment variables
  it sets (never their values);
- an accepted server is registered on the hub **for that conversation only**. Its tools are
  offered to that conversation's turns and to no other, through the hub's MCP client:
  trust tier, tool filters, approval cards for mutating tools, egress rules and the
  stdio environment allowlist all apply. Its trust tier is `read-only` unless
  `NERVA_ACP_MCP_TRUST=full`;
- it is **never saved** to the MCP server list. It is removed when the editor closes the
  session or the `nerva acp` process ends. If that process was killed, the session is
  reaped the next time an editor opens or closes a session after 12 idle hours, and a hub
  restart drops it too;
- only stdio servers are accepted; HTTP/SSE servers are refused. Safe mode and a managed pin on
  `mcp.servers` refuse it as they refuse any added server.

## Setup

1. Start the hub (`python serve.py`) and check from a terminal:

   ```bash
   NERVA_ADMIN_TOKEN=… python scripts/nerva.py acp --check
   ```

2. Configure the editor. Use the virtualenv's Python and the absolute path of your checkout.
   `NERVA_HUB_URL` is only needed when the hub is not on `http://127.0.0.1:8080`.

**Zed** (`~/.config/zed/settings.json`):

```json
{
  "agent_servers": {
    "Nerva": {
      "command": "/home/you/jarvis-hub/.venv/bin/python",
      "args": ["/home/you/jarvis-hub/scripts/nerva.py", "acp"],
      "env": {
        "NERVA_ADMIN_TOKEN": "<your admin token>",
        "NERVA_HUB_URL": "http://127.0.0.1:8080"
      }
    }
  }
}
```

Then open the Agent panel and start a new **Nerva** thread.

**JetBrains IDEs** (AI Assistant → Agents; the file is `~/.jetbrains/acp.json`):

```json
{
  "agent_servers": {
    "Nerva": {
      "command": "/home/you/jarvis-hub/.venv/bin/python",
      "args": ["/home/you/jarvis-hub/scripts/nerva.py", "acp"],
      "env": { "NERVA_ADMIN_TOKEN": "<your admin token>" }
    }
  }
}
```

**Any other ACP client:** launch `python <checkout>/scripts/nerva.py acp` with the same
environment. stdout carries only protocol messages; diagnostics go to stderr.

## Limits

- One message is at most 4 MiB on the wire; a prompt is at most 4,096 characters, the
  hub's chat limit. Attach files as references (they become `@file:` references, read by the
  hub under its own file scope) instead of pasting them. A reference outside the editor's
  folder is left out.
- Images and audio in prompts are not accepted. `session/load`, session modes and model
  switching are not offered: the editor's thread is the conversation, and the model is the
  hub's routing.
- A clarify question that offers choices is put to you as a choice. A question that needs
  typed text is shown and skipped, because a permission dialog cannot take free text.
- Tool-call cards carry the tool, its status and kind only; the HUD's tool trail has the same
  bound.

Code: `agents/core/acp/` (protocol, rendering, path confinement, the agent),
`agents/cli/acp_hub.py` (the hub backend and stdio), `agents/core/routers/acp.py` (session and
MCP routes). Tests: `tests/test_g11_acp.py`.
