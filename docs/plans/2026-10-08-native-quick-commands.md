# Native quick commands (H078)

Goal: let the owner save a small set of slash aliases and fixed local shell commands. Generated 2026-10-08 17:26 Europe/Bucharest over merged main `9aef0b72834a4635296fea0882752204a1906d17` (native code #1243 and sessions #1244). Reviewed product/evidence head: `cdf787ba8035521205a7e200aaa9a70427652e76`; branch `codex/nerva-quick-commands-20261008`.

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

Integration: 165 combined quick/catalog/session/binding/Hermes regressions and full Ruff/status checks pass over the corrected session dependency; 20,971 backend tests collected. Changed paths are the quick-command helper, command/settings seams, focused tests and reviewed parity/status artifacts. Next: publish the independent PR and merge only after trusted-main classification and all reported checks pass. Actual approved-host execution and live providers were not activated.
