"""Owner quick commands adapted from Hermes gateway/run_inbound.py (MIT).

Reference 59b2aeef6c7a, NousResearch 2025. Retain alias expansion and built-in
precedence; replace direct subprocess execution with Nerva's terminal ToolRPC.
Configuration lives in agents.yaml general.quick_commands. Runtime input is
never interpolated into the configured exec command.
"""

from __future__ import annotations

import re

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_MAX_COMMANDS = 128
_MAX_TEXT = 2000
_MAX_ALIASES = 8


def configured_commands(orch):
    general = getattr(getattr(orch, "config", None), "general", {})
    mapping = general.get("quick_commands", {}) if isinstance(general, dict) else {}
    if type(mapping) is not dict or len(mapping) > _MAX_COMMANDS:
        return {}
    return {name.lower(): spec for name, spec in mapping.items()
            if type(name) is str and _NAME.fullmatch(name)}


async def dispatch_quick(registry, text, *, orch, principal, seen):
    from .commands import CommandOutcome

    parsed = registry.parse(text)
    if parsed is None:
        return None
    name, args = parsed
    mapping = configured_commands(orch)
    if name not in mapping:
        return None

    def refuse(reason):
        return CommandOutcome(name, "refused", reason)

    if not principal.admin:
        return refuse(f"/{name} is an owner command.")
    if len(text.strip()) > _MAX_TEXT or name in seen or len(seen) >= _MAX_ALIASES:
        return refuse("Quick command is too long or contains an alias cycle; nothing changed.")
    spec = mapping[name]
    if type(spec) is not dict:
        return refuse("Invalid quick-command configuration.")
    kind = spec.get("type")
    if kind == "alias":
        target = spec.get("target")
        if type(target) is not str or not target.strip():
            return refuse("Quick-command alias has no target.")
        target = target.strip()
        target = target if target.startswith("/") else f"/{target}"
        expanded = f"{target} {args}".strip()
        if len(expanded) > _MAX_TEXT or registry.parse(expanded) is None:
            return refuse("Invalid or oversized quick-command alias target.")
        return await registry.dispatch(expanded, orch=orch, principal=principal,
                                       _quick_seen=seen | {name})
    if kind != "exec":
        return refuse("Quick commands support type alias or exec.")
    command = spec.get("command")
    target = spec.get("target", "local-host")
    timeout = spec.get("timeout", 30)
    if (type(command) is not str or not command.strip() or len(command) > 4000
            or type(target) is not str or not 1 <= len(target) <= 64
            or type(timeout) is not int or not 1 <= timeout <= 600):
        return refuse("Invalid quick-command execution configuration.")
    server = getattr(orch, "tool_rpc", None)
    if not callable(getattr(server, "handle", None)):
        return refuse("Governed terminal execution is unavailable.")
    tool_args = {"target": target, "command": command, "timeout": timeout}
    if "cwd" in spec:
        if type(spec["cwd"]) is not str or len(spec["cwd"]) > 1024:
            return refuse("Invalid quick-command working directory.")
        tool_args["cwd"] = spec["cwd"]
    try:
        result = await server.handle({"tool": "terminal_run", "args": tool_args}, actor="jarvis")
    except Exception:
        return CommandOutcome(name, "failed", "Governed quick-command execution failed.")
    if type(result) is not dict:
        return CommandOutcome(name, "failed", "Invalid governed terminal response.")
    if result.get("reason") == "approval_required" and type(result.get("task_id")) is int:
        return CommandOutcome(name, "queued", f"Quick command queued for approval: {result['task_id']}.")
    if result.get("ok") is not True:
        return refuse(f"Quick command refused: {result.get('reason', 'execution_unavailable')}.")
    value = result.get("result")
    if type(value) is dict:
        output = str(value.get("stdout") or value.get("stderr") or "Command returned no output.")
        status = "answered" if value.get("ok", True) is True and value.get("exit_code", 0) == 0 else "failed"
    else:
        output, status = str(value or "Command returned no output."), "answered"
    redact = getattr(getattr(orch, "secret_broker", None), "redact", None)
    if callable(redact):
        output = redact(output)
    from .security.log_redaction import SecretRedactionFilter

    output = SecretRedactionFilter().redact_text(output)
    return CommandOutcome(name, status, output[:20_000])


def help_lines(orch, registry):
    return [f"/{name} — quick {spec.get('type', 'command')} (owner)"
            for name, spec in sorted(configured_commands(orch).items())
            if type(spec) is dict and registry.get(name) is None]
