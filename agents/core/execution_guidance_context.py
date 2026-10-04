"""Passive, per-agent execution facts for H388 system-prompt guidance.

The target runner chooses one named backend per call. Prompt construction has no
selected target, so only declared, currently eligible rows are described here.
No audit, authorization, remote probe, or transport initialization occurs.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from .env_config import env_flag, env_json_object, env_str
from .environment_probe import _build_probe_line
from .environments.targets import default_targets

_toolchain_cache: dict[tuple[str, str, str], str | None] = {}
_toolchain_lock = threading.Lock()
_MAX_CACHE = 32
_MAX_FACT = 4096


def _targets_for(coordinator) -> list:
    registry = getattr(coordinator, '_targets', None)
    if registry is None:
        return list(default_targets())
    return [registry.snapshot(name) for name in registry.names()]


def _local_roots() -> tuple[str, ...]:
    from .environments.local_transport import default_roots

    try:
        return tuple(str(Path(root).expanduser().resolve()) for root in default_roots())
    except (OSError, RuntimeError, ValueError):
        return ()


def _ssh_roots() -> dict[str, tuple[str, ...]]:
    from .environments.ssh_transport import parse_hosts

    try:
        pinned = Path(env_str('JARVIS_TERMINAL_SSH_KNOWN_HOSTS')).expanduser()
        if not pinned.is_absolute() or not env_str('JARVIS_TERMINAL_SSH_KNOWN_HOSTS').strip():
            return {}
        return {name: host.roots for name, host in parse_hosts(
            env_json_object('JARVIS_TERMINAL_SSH_HOSTS')).items()}
    except (ValueError, TypeError, OSError):
        return {}


def _local_toolchain_line(agent_id: str, roots: tuple[str, ...]) -> str | None:
    from .operating_prompt import is_guidance_preview

    key = (agent_id, os.environ.get('PATH', ''), '\0'.join(roots))
    with _toolchain_lock:
        if is_guidance_preview():
            return _toolchain_cache.get(key)
        if key in _toolchain_cache:
            return _toolchain_cache[key]
        try:
            line = _build_probe_line()
        except Exception:
            line = None
        if line is not None and (len(line) > 1024 or any(ord(char) < 32 or ord(char) == 127 for char in line)):
            line = None
        if len(_toolchain_cache) >= _MAX_CACHE:
            _toolchain_cache.pop(next(iter(_toolchain_cache)))
        _toolchain_cache[key] = line
        return line


def _root_label(root: str) -> str:
    """Preserve ordinary paths, omit those unsafe or too long for one prompt fact."""
    if len(root) > 256:
        return '[configured path omitted: too long]'
    if any(ord(char) < 32 or ord(char) == 127 for char in root):
        return '[configured path omitted: control characters]'
    return root


def _roots_label(roots: tuple[str, ...]) -> str:
    visible = ', '.join(_root_label(root) for root in roots[:3])
    extra = len(roots) - 3
    return f'{visible} ({extra} more roots omitted)' if extra > 0 else visible


def _bounded_targets(lines: list[str]) -> str:
    if not lines:
        return 'No named terminal target is enabled for this agent.'
    # Reserve room for an exact omission count; never cut a target summary in half.
    budget = _MAX_FACT - 100
    kept: list[str] = []
    for line in lines:
        candidate = '; '.join((*kept, line))
        if len(candidate) > budget:
            break
        kept.append(line)
    omitted = len(lines) - len(kept)
    if omitted:
        kept.append(f'{omitted} eligible targets omitted from this bounded prompt.')
    return '; '.join(kept)


def execution_guidance_context(coordinator, agent_id: str) -> dict:
    """Return configured agent ID and environment Mapping[str, str] for prompt rendering."""
    agent = str(agent_id or '').strip()
    environment: dict[str, str] = {}
    if not agent or not env_flag('JARVIS_TERMINAL_TARGETS'):
        environment['targets'] = 'No named terminal target is enabled for this agent.'
        return {'profile': agent, 'environment': environment}

    try:
        declared = _targets_for(coordinator)
    except (AttributeError, ValueError):
        declared = []
    sandbox = getattr(getattr(coordinator, '_orch', None), 'sandbox', None)
    try:
        docker_active = sandbox is not None and sandbox.active_backend() == 'docker'
    except (AttributeError, OSError, RuntimeError):
        docker_active = False
    local_roots = _local_roots() if env_flag('JARVIS_TERMINAL_LOCAL_HOST') else ()
    remote_roots = _ssh_roots() if env_flag('JARVIS_TERMINAL_SSH_HOST') else {}
    lines: list[str] = []
    local_available = False
    for target in sorted((row for row in declared if row is not None), key=lambda row: row.name):
        if (not target.enabled or 'terminal.exec' not in target.capabilities
                or ('*' not in target.allowed_agents and agent not in target.allowed_agents)):
            continue
        if target.backend == 'docker' and docker_active:
            lines.append(f'{target.name} (docker): shell commands in container; cwd /workspace; '
                         'container OS/user unknown until selected. Other tools may use different machines.')
        elif target.backend == 'local' and local_roots:
            local_available = True
            lines.append(f'{target.name} (local): one argv command, no shell operators; '
                         f'default cwd {_root_label(local_roots[0])}; '
                         f'allowed cwd roots: {_roots_label(local_roots)}. '
                         'Runs on the Nerva host; other tools may use different machines.')
        elif target.backend == 'ssh' and target.name in remote_roots:
            roots = remote_roots[target.name]
            lines.append(f'{target.name} (ssh): one argv command, no shell operators; '
                         f'default remote cwd {_root_label(roots[0])}; '
                         f'allowed remote cwd roots: {_roots_label(roots)}; '
                         'remote OS unknown until selected. Other tools may use different machines.')
    environment['targets'] = _bounded_targets(lines)
    if local_available:
        line = _local_toolchain_line(agent, local_roots)
        if line is None:
            environment['toolchain'] = 'Local target only: Python toolchain probe unavailable; verify on the local target.'
        else:
            environment['toolchain'] = (f'Local target only: {line}' if line else
                                        'Local target only: no Python toolchain issue detected.')
    return {'profile': agent, 'environment': environment}
