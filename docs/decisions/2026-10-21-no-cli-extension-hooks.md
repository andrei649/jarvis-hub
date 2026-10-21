# Decision: no CLI extension hooks in `nerva` (H652)

**Date:** 2026-10-21 · **Status:** decided — not offered · **Revisit when:** the CLI
gains an interactive full-screen interface, or a second first-party client needs to
wrap it.

## What Hermes offers

Hermes' developer guide ("Extending the CLI") documents protected methods on its
`HermesCLI` class that a wrapper program overrides to inject prompt_toolkit widgets,
keybindings, layout order, styles and slash commands into the interactive TUI, without
overriding `run()`. A wrapper is a Python program that subclasses the CLI and runs in
the same process as the agent.

## What Nerva does instead

`nerva` (`agents/cli/nerva.py`) is a different kind of program: a one-shot verb CLI
over the hub's HTTP API. Every online verb calls the same routes the HUD calls; it holds
no agent, no model and no tool runtime of its own, and it has no full-screen TUI to put
widgets in. Dispatch is a static table, `agents/cli/nerva.py::_VERBS`, of functions
defined in that module; nothing is discovered or imported at run time.

We do **not** add wrapper hooks, entry-point discovery or a plugin directory to it:

1. **There is nothing to hook.** The Hermes hooks exist to customise a long-running
   TUI. Nerva's interactive surfaces are the HUD (`frontend/`) and the chat channels;
   the CLI prints and exits.
2. **The API is already the extension point.** A wrapper that wants a new view calls
   the hub's routes, exactly as `nerva` does (`agents/cli/client.py`), and is checked by
   the same route guards (`tests/_snapshots/route_auth.json`). It needs no hook in our
   code, and it cannot reach anything the routes do not expose.
3. **Code-loading hooks would bypass the extension model.** The hub never imports
   third-party code: an extension is a declared, consented, sandbox-proved package
   (`docs/EXTENSIONS.md`). A CLI that imported Python from a plugin folder or an entry
   point would be an unreviewed second door into the owner's machine, with the owner's
   admin token in its environment.
4. **Each customisation Hermes users reach for has a governed home already:**

   | want | where it lives |
   |---|---|
   | a custom chat command | owner `quick_commands` (alias or fixed tool command, `agents/core/quick_commands.py`), or a skill command (`skills/<name>/main.py`) |
   | a new capability for the model | a tool (`docs/developer/adding-a-tool.md`), a skill, an MCP server, or an extension |
   | a new verb in `nerva` | a function in `agents/cli/nerva.py` plus its route, reviewed like any other change |
   | a different look | the HUD's appearance preferences (`agents/core/appearance.py`: look, accent, font, density, motion) |
   | a script over the CLI | `--json` on the read verbs, stable exit codes (`EXIT_OK`, `EXIT_FAILED`, `EXIT_USAGE`, `EXIT_NO_HUB`, `EXIT_AUTH`) |

## Consequences

- `tests/test_h652_developer_docs.py` pins the decision: `nerva` dispatches only to
  functions defined in `agents/cli/nerva.py`, and nothing under `agents/cli/` loads
  code dynamically (`importlib`, `entry_points`, `__import__`, `exec`). Adding a hook
  means changing that test, which means revisiting this page first.
- A Hermes user moving over loses TUI wrapper hooks and keeps everything else; the
  parity row (H652) records this as a deliberate difference, not a gap.
