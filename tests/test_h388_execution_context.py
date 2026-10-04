"""H388 named execution context stays inside each configured agent's tool scope."""

from types import SimpleNamespace

from agents.core.environments.targets import TargetRegistry, TerminalTarget
from agents.core.execution_guidance_context import execution_guidance_context


def _target(name, backend, *, agents=frozenset({'jarvis'}), enabled=True):
    return TerminalTarget(name, backend, enabled, agents, frozenset({'terminal.exec'}))


def _coordinator(targets, backend='docker'):
    class PassiveCoordinator:
        _targets = TargetRegistry(targets)
        _orch = SimpleNamespace(sandbox=SimpleNamespace(active_backend=lambda: backend))

        def _target_registry(self):
            raise AssertionError('prompt construction must not initialize registry/audit')

    return PassiveCoordinator()


def test_declared_targets_are_filtered_by_real_agent_and_global_switch(monkeypatch):
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    coordinator = _coordinator([
        _target('sandbox', 'docker', agents=frozenset({'*'})),
        _target('host', 'local', agents=frozenset({'jarvis'})),
        _target('disabled', 'docker', enabled=False),
        _target('other', 'docker', agents=frozenset({'ultron'})),
    ])
    result = execution_guidance_context(coordinator, 'frigga')
    assert result['profile'] == 'frigga'
    assert 'sandbox' in result['environment']['targets']
    assert all(x not in result['environment']['targets'] for x in ('host', 'disabled', 'other'))
    assert result['environment'].get('toolchain', '') == ''
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '0')
    assert 'sandbox' not in execution_guidance_context(coordinator, 'frigga')['environment']['targets']


def test_docker_offer_has_container_shell_cwd_and_no_host_facts(monkeypatch):
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', '/private/sensitive-host-root')
    result = execution_guidance_context(_coordinator([_target('sandbox', 'docker')]), 'jarvis')
    text = result['environment']['targets']
    assert 'sandbox' in text and 'docker' in text
    assert '/workspace' in text and 'shell' in text
    assert '/private/sensitive-host-root' not in text
    assert 'host OS' not in text
    assert 'toolchain' not in result['environment']


def test_local_and_ssh_descriptions_use_transport_cwd_rules(monkeypatch):
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_SSH_HOST', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', '/tmp/h388-test-root')
    monkeypatch.setenv('JARVIS_TERMINAL_SSH_HOSTS', '{"remote":{"user":"test","hostname":"remote.example","roots":["/srv/work"]}}')
    monkeypatch.setenv('JARVIS_TERMINAL_SSH_KNOWN_HOSTS', '/tmp/h388-known-hosts')
    coordinator = _coordinator([_target('host', 'local'), _target('remote', 'ssh')])
    result = execution_guidance_context(coordinator, 'jarvis')
    text = result['environment']['targets']
    assert 'host' in text and 'local' in text and '/tmp/h388-test-root' in text
    assert 'argv' in text and 'no shell' in text
    assert 'remote' in text and 'ssh' in text and '/srv/work' in text
    assert 'OS unknown' in text
    assert 'toolchain' in result['environment']


def test_python_probe_is_path_sensitive_and_never_runs_for_remote_only(monkeypatch):
    from agents.core import execution_guidance_context as module

    module._toolchain_cache.clear()
    observed = []
    monkeypatch.setattr(module, '_build_probe_line', lambda: observed.append('run') or 'Python toolchain: python3=missing.')
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '1')
    monkeypatch.setenv('PATH', '/first')
    local = _coordinator([_target('host', 'local')])
    assert execution_guidance_context(local, 'jarvis')['environment']['toolchain'].startswith('Local target only:')
    assert execution_guidance_context(local, 'jarvis')['environment']['toolchain'].startswith('Local target only:')
    assert observed == ['run']
    monkeypatch.setenv('PATH', '/second')
    execution_guidance_context(local, 'jarvis')
    assert observed == ['run', 'run']
    execution_guidance_context(_coordinator([_target('remote', 'ssh')]), 'jarvis')
    assert observed == ['run', 'run']


def test_upstream_python_probe_reports_mismatch_and_pep668(monkeypatch):
    from agents.core import environment_probe as probe

    monkeypatch.setattr(probe, '_python_version_of', lambda binary: '3.12.4' if binary == 'python3' else None)
    monkeypatch.setattr(probe, '_has_pip_module', lambda binary: False)
    monkeypatch.setattr(probe, '_pip_python_version', lambda: '3.11')
    monkeypatch.setattr(probe, '_detect_pep668', lambda binary: True)
    monkeypatch.setattr(probe.shutil, 'which', lambda binary: '/usr/bin/uv' if binary == 'uv' else None)
    line = probe._build_probe_line()
    assert 'python3=3.12.4 (no pip module)' in line
    assert 'pip→python3.11 (mismatch)' in line
    assert 'PEP 668=yes (use venv or uv)' in line
    assert 'uv=installed' in line


def test_docker_is_not_advertised_when_sandbox_backend_is_inactive(monkeypatch):
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    result = execution_guidance_context(_coordinator([_target('sandbox', 'docker')], backend='disabled'), 'jarvis')
    assert 'sandbox' not in result['environment']['targets']
    assert 'toolchain' not in result['environment']


def test_local_target_requires_armed_transport_and_probe_is_skipped(monkeypatch):
    from agents.core import execution_guidance_context as module

    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.delenv('JARVIS_TERMINAL_LOCAL_HOST', raising=False)
    monkeypatch.setattr(module, '_build_probe_line', lambda: (_ for _ in ()).throw(
        AssertionError('local probe must stay off')))
    result = execution_guidance_context(_coordinator([_target('host', 'local')]), 'jarvis')
    assert 'host' not in result['environment']['targets']
    assert 'toolchain' not in result['environment']


def test_probe_caps_child_output_and_wait(monkeypatch):
    import sys
    import time

    from agents.core import environment_probe as probe

    rc, out, _err = probe._run([sys.executable, '-c', "print('x' * 10000)"])
    assert rc == 0 and len(out) <= probe._MAX_PROBE_OUTPUT
    monkeypatch.setattr(probe, '_PROBE_TIMEOUT', 0.05)
    started = time.monotonic()
    rc, out, reason = probe._run([sys.executable, '-c', 'import time; time.sleep(30)'])
    assert (rc, out, reason) == (-1, '', 'timeout')
    assert time.monotonic() - started < 1.5


def test_multiple_target_context_survives_real_guidance_validation(monkeypatch):
    from agents.core.operating_guidance import build_operating_guidance

    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    context = execution_guidance_context(_coordinator([
        _target('sandbox-a', 'docker'), _target('sandbox-b', 'docker'),
    ]), 'jarvis')
    assert '\n' not in context['environment']['targets']
    guidance = build_operating_guidance(
        model='gpt-test', surface='cli', capabilities=frozenset({'tool:terminal_run'}),
        **context,
    )
    assert 'sandbox-a (docker)' in guidance
    assert 'sandbox-b (docker)' in guidance
    assert 'Operator-supplied profile: jarvis' in guidance


def test_many_targets_fit_builder_limit_with_honest_omission_count(monkeypatch):
    from agents.core.operating_guidance import build_operating_guidance

    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    targets = [_target(f'sandbox-{index:03d}', 'docker') for index in range(70)]
    context = execution_guidance_context(_coordinator(targets), 'jarvis')
    summary = context['environment']['targets']
    assert len(summary) <= 4096
    assert 'eligible targets omitted' in summary
    guidance = build_operating_guidance(
        model='gpt-test', surface='cli', capabilities=frozenset({'tool:terminal_run'}),
        **context,
    )
    assert '# Supplied execution environment' in guidance


def test_failed_local_probe_is_not_reported_clean(monkeypatch):
    from agents.core import execution_guidance_context as module

    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '1')
    monkeypatch.setenv('PATH', '/h388/probe/failure')
    module._toolchain_cache.clear()
    monkeypatch.setattr(module, '_build_probe_line', lambda: 1 / 0)
    context = execution_guidance_context(_coordinator([_target('host', 'local')]), 'jarvis')
    assert 'unavailable' in context['environment']['toolchain']
    assert 'no Python toolchain issue detected' not in context['environment']['toolchain']
