# Native quick commands (H078)

Goal: let the owner save a small set of slash aliases and fixed local shell commands. This slice starts from `16c79633d4ee14ed95f6a88dd1c19920ed65b269`; the integration owner will record the final main/head SHA.

Set `commands.quick_commands` in Admin → Settings as JSON. The default `{}` enables nothing:

```json
{
  "today": {"type": "alias", "target": "/status"},
  "check_disk": {"type": "exec", "command": "df -h"}
}
```

Aliases append the caller's text to their target, so `/today extra` becomes `/status extra`. Built-in commands win on name collisions. Aliases are owner-only, have a depth and length bound, and cyclic or malformed maps are rejected on write. Alias targets `/new`, `/reset`, and `/undo` are refused so their pre-append conversation contract remains intact. A fixed `exec` command ignores all caller text. It targets `local-host` through the existing gated `terminal_run` ToolRPC path; each invocation must enter the signed ask-tier approval queue before execution. The command requires the existing terminal target and local-host gates to be enabled. A queued reply gives the task ID; output is available through the existing task result after approval. Any immediate ToolRPC output is bounded and redacted before chat display.

No new command editor, argument template, shell interpolation, execution target option, or standing approval is included. Rollback: remove the `commands.quick_commands` setting or revert this slice; pending approval tasks still require their own owner decision.

Checks: `tests/test_quick_commands.py`, `tests/test_slash_commands.py`, and `tests/test_commands_catalog.py`, plus Ruff on touched Python files. Mobile/HUD surface: the existing Admin settings JSON editor is used; no new route or HUD component.
