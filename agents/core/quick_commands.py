"""Owner-configured slash aliases and fixed commands through governed ToolRPC."""

from __future__ import annotations

import re

from . import settings_db

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_MAX_COMMANDS = 128
_MAX_TEXT = 2000


def configuration_problem(value) -> str | None:
    """Keep bad settings out of the admin store and fail closed at dispatch."""
    if type(value) is not dict or len(value) > _MAX_COMMANDS:
        return "quick_commands: expected a map of at most 128 commands"
    names = set()
    for name, spec in value.items():
        if type(name) is not str or not _NAME.fullmatch(name) or name.lower() in names:
            return "quick_commands: names must be unique slash-command identifiers (max 64 characters)"
        names.add(name.lower())
        if type(spec) is not dict:
            return f"quick_commands: /{name} needs an alias or exec object"
        if spec.get("type") == "alias":
            target = spec.get("target")
            if set(spec) != {"type", "target"} or type(target) is not str or not 1 <= len(target) <= _MAX_TEXT:
                return f"quick_commands: /{name} needs a bounded alias target"
            from .commands import CommandRegistry

            parsed = CommandRegistry.parse(target if target.startswith("/") else f"/{target}")
            if parsed is None or parsed[0] in {"new", "reset", "undo"}:
                return f"quick_commands: /{name} has an invalid alias target"
        elif spec.get("type") == "exec":
            command = spec.get("command")
            if set(spec) != {"type", "command"} or type(command) is not str or not command.strip() or len(command) > 4000:
                return f"quick_commands: /{name} needs a fixed shell command of at most 4000 characters"
        else:
            return f"quick_commands: /{name} type must be alias or exec"
    for name in names:
        seen = set()
        current = name
        while current in names:
            if current in seen:
                return f"quick_commands: alias cycle involving /{current}"
            seen.add(current)
            spec = value[next(key for key in value if key.lower() == current)]
            if spec["type"] != "alias":
                break
            target = spec["target"]
            from .commands import CommandRegistry

            current = CommandRegistry.parse(target if target.startswith("/") else f"/{target}")[0]
    return None


def configured() -> dict:
    value = settings_db.get_value("commands", "quick_commands", {})
    return {name.lower(): spec for name, spec in value.items()} if configuration_problem(value) is None else {}


async def dispatch_quick(registry, name, args, *, text, orch, principal, seen):
    from .commands import CommandOutcome

    raw = settings_db.get_value("commands", "quick_commands", {})
    if configuration_problem(raw) is not None:
        if type(raw) is dict and any(type(key) is str and key.lower() == name for key in raw):
            return CommandOutcome(name, "refused", "Invalid quick-command configuration; nothing changed.")
        return None
    mapping = {key.lower(): spec for key, spec in raw.items()}
    if name not in mapping:
        return None
    if not principal.admin:
        return CommandOutcome(name, "refused", f"/{name} is an owner command.")
    if name in seen or len(seen) >= 8 or len(text.strip()) > _MAX_TEXT:
        return CommandOutcome(name, "refused", "Quick-command alias cycle or oversized input; nothing changed.")
    spec = mapping[name]
    if spec["type"] == "alias":
        target = spec["target"]
        expanded = f"{target if target.startswith('/') else '/' + target} {args}".strip()
        if len(expanded) > _MAX_TEXT:
            return CommandOutcome(name, "refused", "Quick-command alias is too long; nothing changed.")
        return await registry.dispatch(expanded, orch=orch, principal=principal, _quick_seen=seen | {name})

    server = getattr(orch, "tool_rpc", None)
    if not callable(getattr(server, "handle", None)):
        return CommandOutcome(name, "refused", "Governed terminal execution is unavailable.")
    try:
        result = await server.handle({"tool": "terminal_run", "args": {
            "target": "local-host", "command": spec["command"],
        }}, actor="jarvis")
    except Exception:
        return CommandOutcome(name, "failed", "Governed quick-command intake failed.")
    if type(result) is not dict:
        return CommandOutcome(name, "failed", "Invalid governed terminal response.")
    if result.get("reason") == "approval_required" and type(result.get("task_id")) is int:
        return CommandOutcome(name, "queued", f"Quick command queued for approval: {result['task_id']}.")
    if result.get("ok") is not True:
        return CommandOutcome(name, "refused", "Governed quick-command request refused; check the hub log.")
    value = result.get("result")
    output = str(value.get("stdout") or value.get("stderr") or "Command returned no output.") if type(value) is dict else str(value or "Command returned no output.")
    from .security.log_redaction import SecretRedactionFilter

    try:
        redact = getattr(getattr(orch, "secret_broker", None), "redact", None)
        output = redact(output) if callable(redact) else output
        output = SecretRedactionFilter().redact_text(output)
    except Exception:
        return CommandOutcome(name, "failed", "Command output could not be safely shown.")
    status = "failed" if type(value) is dict and (value.get("ok") is False or value.get("exit_code", 0) != 0) else "answered"
    return CommandOutcome(name, status, output[:20_000])


def help_lines(registry) -> list[str]:
    return [f"/{name} — quick {spec['type']}  (owner)" for name, spec in sorted(configured().items())
            if registry.get(name) is None]
