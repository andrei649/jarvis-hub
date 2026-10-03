"""Trusted, passive descriptor resolution for the real terminal producer.

Only private signed source consumers call this resolver. It reads declared
configuration without constructing a transport or accessing key contents.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

from .consent_ledger import ConsentContext
from .consent_registration import trusted_registration_key
from .consent_types import ConsentDescriptor
from .mediation import canonical_json
from .policy import AutonomyPolicy
from .terminal_consent_categories import terminal_consent_categories

_POLICY_FIELDS = (
    'mode', 'agent_modes', 'cap_per_action', 'daily_ceiling',
    'earned_autonomy_enabled', 'tier_outcomes',
)


def _policy_snapshot(policy):
    if type(policy) is not AutonomyPolicy:
        return None
    values = {key: getattr(policy, key) for key in _POLICY_FIELDS}
    values['tier_outcomes'] = {str(int(tier)): outcome for tier, outcome
                             in policy.tier_outcomes.items()}
    return values


def _hash(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _file_identity(path: str) -> dict:
    """Detect identity/pin replacement using metadata, never reading credentials."""
    resolved = Path(path).expanduser().resolve(strict=True)
    stat = resolved.stat()
    if not resolved.is_file():
        raise ValueError('configured identity is not a file')
    return {'path': str(resolved), 'device': stat.st_dev, 'inode': stat.st_ino,
            'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def _transport_identity(target, sandbox):
    from agents.core.env_config import env_flag, env_json_object, env_str

    if target.backend == 'local':
        from agents.core.environments.local_transport import default_roots, default_timeout

        if not env_flag('JARVIS_TERMINAL_LOCAL_HOST'):
            return None
        return {'roots': [str(Path(root).expanduser().resolve()) for root in default_roots()],
                'default_timeout': default_timeout()}
    if target.backend == 'ssh':
        from agents.core.environments.ssh_transport import (
            default_connect_timeout,
            default_timeout,
            parse_hosts,
        )

        if not env_flag('JARVIS_TERMINAL_SSH_HOST'):
            return None
        host = parse_hosts(env_json_object('JARVIS_TERMINAL_SSH_HOSTS')).get(target.name)
        if host is None:
            return None
        return {'host': {**asdict(host), 'roots': list(host.roots)},
                'known_hosts': _file_identity(env_str('JARVIS_TERMINAL_SSH_KNOWN_HOSTS')),
                'identity': _file_identity(host.identity_file) if host.identity_file else None,
                'default_timeout': default_timeout(), 'connect_timeout': default_connect_timeout()}
    if target.backend == 'docker':
        from agents.core.sandbox import Sandbox

        if type(sandbox) is not Sandbox:
            return None
        return {'image': sandbox.docker_image, 'timeout': sandbox.timeout,
                'max_memory_mb': sandbox.max_memory_mb, 'work_dir': str(sandbox.work_dir.resolve()),
                'allow_subprocess': sandbox.allow_subprocess,
                'max_output_bytes': sandbox.max_output_bytes}
    return None


def build_terminal_consent_resolver(orch, registry, server, spec):
    """Bind one registered producer to its current worker, policy and target scope."""
    worker = getattr(orch, 'autonomy', None)
    queue = getattr(orch, 'autonomy_queue', None)

    def resolve(task, source):
        from agents.core.env_config import env_flag
        from agents.core.kernel import kernel_enabled

        try:
            if (worker is None or queue is None or getattr(orch, 'autonomy', None) is not worker
                    or getattr(orch, 'autonomy_queue', None) is not queue
                    or server._tools.get('terminal_run') is not spec
                    or not env_flag('JARVIS_TERMINAL_TARGETS') or not kernel_enabled()
                    or task.kind != 'toolrpc.terminal_run' or type(source) is not dict):
                return None
            producer = source.get('producer')
            policy = _policy_snapshot(worker.policy)
            captured_policy = source.get('policy')
            if (type(producer) is not dict or policy is None or type(captured_policy) is not dict
                    or {key: captured_policy.get(key) for key in _POLICY_FIELDS} != policy):
                return None
            key = trusted_registration_key('terminal_run', spec)
            if (not key or key != spec.get('_consent_registration_key')
                    or producer.get('registration_key') != key
                    or producer.get('registration_epoch') != spec.get('_grouping_epoch')):
                return None
            args = task.payload.get('args')
            if (task.payload.get('tool') != 'terminal_run'
                    or task.payload.get('target') != 'terminal_run' or type(args) is not dict
                    or producer.get('request') != {'tool': 'terminal_run', 'args': args}):
                return None
            current_registry = registry() if callable(registry) else registry
            target = current_registry.snapshot(args.get('target'))
            if (target is None or not target.enabled
                    or ('*' not in target.allowed_agents and task.agent not in target.allowed_agents)
                    or 'terminal.exec' not in target.capabilities):
                return None
            transport = _transport_identity(target, getattr(orch, 'sandbox', None))
            if transport is None:
                return None
            categories = terminal_consent_categories(
                args.get('command'),
                resolved_user_home=str(Path.home()) if target.backend == 'local' else None,
                resolved_hermes_home=None, trusted_gateway_lifecycle=None,
            )
            if not categories:
                return None
            target_config = {'name': target.name, 'backend': target.backend, 'enabled': target.enabled,
                             'allowed_agents': sorted(target.allowed_agents),
                             'capabilities': sorted(target.capabilities),
                             'approval_required': sorted(target.approval_required),
                             'transport': transport}
            context = ConsentContext(
                principal=producer['principal'], surface=producer['surface'],
                session_id=producer['session_id'], session_instance=producer['session_instance'],
                registration_key=key, policy_revision=_hash(policy), target_scope=_hash(target_config),
            )
            return ConsentDescriptor(context, categories, spec['_grouping_epoch'])
        except Exception:
            return None

    return resolve
