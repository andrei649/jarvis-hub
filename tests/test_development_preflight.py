"""Developer preflight fails closed without exposing runtime configuration."""

import json
import subprocess
from pathlib import Path

from scripts import development_preflight as preflight


def test_wrong_interpreter_blocks_product_commands(tmp_path):
    calls = []
    result = preflight.run_preflight(
        tmp_path, version=(3, 11), runner=lambda *args, **kwargs: calls.append(args)
    )
    assert result["ok"] is False
    assert result["checks"][0]["name"] == "python"
    assert result["checks"][0]["status"] == "fail"
    assert calls == []
    assert "install_smoke" in result["unexecuted"]


def test_timeout_and_secret_output_are_bounded(tmp_path):
    secret = "PRIVATE-TOKEN-MUST-NOT-APPEAR"

    def runner(argv, **kwargs):
        assert kwargs["timeout"] <= 45
        if "--version" in argv:
            return subprocess.CompletedProcess(argv, 0, "v22.23.4", "")
        if "--help" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=secret)
        return subprocess.CompletedProcess(argv, 0, secret, secret)

    result = preflight.run_preflight(
        tmp_path, version=(3, 12), runner=runner,
        environ={"JARVIS_USER_TOKEN": secret}, check_files=False,
    )
    assert result["ok"] is False
    assert any(row["reason"] == "timeout" for row in result["checks"])
    assert secret not in json.dumps(result)
    assert "live_provider" in result["unexecuted"]
    assert "native_device" in result["unexecuted"]


def test_front_door_configuration_refuses_invalid_flag_without_value(tmp_path):
    secret = "DO-NOT-PRINT-THIS-FLAG-VALUE"
    result = preflight.run_preflight(
        tmp_path, version=(3, 12), environ={"NERVA_PUBLIC_PROFILE": secret},
        check_files=False, runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    config = next(row for row in result["checks"] if row["name"] == "configuration")
    assert config["status"] == "fail"
    assert secret not in json.dumps(result)


def test_real_cli_and_smoke_are_selected_with_isolated_state(tmp_path):
    commands = []

    def runner(argv, **kwargs):
        commands.append((argv, kwargs))
        if "install_smoke.py" in " ".join(argv):
            state = Path(kwargs["env"]["JARVIS_HOME"])
            assert state.is_relative_to(tmp_path)
            assert kwargs["env"]["JARVIS_TESTING"] == "1"
            assert "JARVIS_ADMIN_TOKEN" not in kwargs["env"]
        output = ('WEBSITE_POLICY_READY' if 'website_refusal' in ' '.join(argv)
                  else '{"ok": true}' if "install_smoke.py" in " ".join(argv) else "usage: nerva")
        return subprocess.CompletedProcess(argv, 0, output, "")

    result = preflight.run_preflight(
        tmp_path, version=(3, 12), runner=runner, smoke=True,
        environ={"PATH": "/bin", "JARVIS_ADMIN_TOKEN": "private"}, check_files=False,
    )
    assert result["ok"] is True
    assert any("agents.cli.nerva" in argv and "--help" in argv for argv, _ in commands)
    assert any("install_smoke.py" in " ".join(argv) for argv, _ in commands)
    assert "install_smoke" not in result["unexecuted"]
    assert result["acceptance"]["live_provider"] == "not_run"
    assert result["acceptance"]["upstream_hermes_runtime"] == "not_run"


def test_owner_policy_preflight_is_bounded_and_never_discloses_private_error_output(tmp_path):
    private = "PRIVATE-POLICY-PATH-AND-VALUE"

    def runner(argv, **kwargs):
        assert kwargs["timeout"] == 45
        output = 'WEBSITE_POLICY_UNAVAILABLE' if 'website_refusal' in ' '.join(argv) else 'usage: nerva'
        return subprocess.CompletedProcess(argv, 0, output, private)

    result = preflight.run_preflight(tmp_path, version=(3, 12), runner=runner, check_files=False)
    row = next(row for row in result['checks'] if row['name'] == 'website_policy')
    assert row['status'] == 'fail' and row['reason'] == 'website_policy_unavailable'
    assert 'security.website_blocklist' in row['action']
    assert private not in json.dumps(result)


def test_readonly_policy_probe_uses_selected_profile_while_product_smoke_remains_isolated(tmp_path):
    profile = tmp_path / 'selected-profile'
    seen = []

    def runner(argv, **kwargs):
        if 'website_refusal' in ' '.join(argv):
            assert kwargs['env']['JARVIS_HOME'] == str(profile)
            assert 'PYTHONPATH' not in kwargs['env']
            seen.append('policy')
            return subprocess.CompletedProcess(argv, 0, 'WEBSITE_POLICY_READY', '')
        assert kwargs['env']['JARVIS_HOME'] != str(profile) if 'env' in kwargs else True
        return subprocess.CompletedProcess(argv, 0, 'usage: nerva', '')

    result = preflight.run_preflight(
        tmp_path, version=(3, 12), runner=runner, check_files=False,
        environ={'JARVIS_HOME': str(profile), 'PYTHONPATH': '/unrelated/import/path'},
    )
    assert seen == ['policy']
    assert next(row for row in result['checks'] if row['name'] == 'website_policy')['status'] == 'pass'
    assert not profile.exists()


def test_zero_exit_without_real_entrypoint_output_is_not_a_pass(tmp_path):
    result = preflight.run_preflight(
        tmp_path, version=(3, 12), smoke=True, check_files=False,
        runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    assert result["ok"] is False
    assert any(row["name"] == "cli" and row["status"] == "fail" for row in result["checks"])
    assert any(row["name"] == "install_smoke" and row["status"] == "fail" for row in result["checks"])


def test_frontend_node_and_dependencies_are_required_when_selected(tmp_path):
    result = preflight.run_preflight(
        tmp_path, version=(3, 12), frontend=True,
        runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "v24.0.0", ""),
    )
    assert result["ok"] is False
    assert any(row["name"] == "node" and row["status"] == "fail" for row in result["checks"])
    assert any(row["name"] == "frontend_dependencies" and row["status"] == "fail" for row in result["checks"])


def test_existing_venv_does_not_validate_another_active_interpreter(tmp_path):
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("placeholder")
    result = preflight.run_preflight(
        tmp_path, version=(3, 12),
        runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "usage: nerva", ""),
    )
    assert next(row for row in result["checks"] if row["name"] == "venv")["status"] == "fail"


def test_hardened_configuration_requires_the_audit_key(tmp_path):
    result = preflight.run_preflight(
        tmp_path, version=(3, 12), check_files=False,
        environ={"JARVIS_HARDENED": "1"},
        runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "usage: nerva", ""),
    )
    assert next(row for row in result["checks"] if row["name"] == "configuration")["status"] == "fail"


def test_explicit_insecure_bind_matches_the_boot_guard(tmp_path):
    result = preflight.run_preflight(
        tmp_path, version=(3, 12), check_files=False,
        environ={"JARVIS_HOST": "0.0.0.0", "JARVIS_ALLOW_INSECURE_BIND": "1"},
        runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "usage: nerva", ""),
    )
    assert next(row for row in result["checks"] if row["name"] == "configuration")["status"] == "pass"


def test_configuration_notices_cannot_pollute_json_output(tmp_path, capsys):
    from agents.core import boot_guards

    # This is a real boot-guard branch which prints a security notice.
    environment = {"JARVIS_CHANNEL_OPEN": "1", "JARVIS_CHANNEL_PAIRING": "0",
                   "TELEGRAM_BOT_TOKEN": "private"}
    boot_guards.assert_front_door(environment)
    assert "[SECURITY]" in capsys.readouterr().out
    preflight.run_preflight(
        tmp_path, version=(3, 12), environ=environment, check_files=False,
        runner=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "usage: nerva", ""),
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert not captured.err


def test_installed_versions_must_match_applicable_pins(tmp_path):
    for name in ("requirements-beta.lock", "requirements-dev.lock"):
        (tmp_path / name).write_text(
            '# generated\nexample==2.0 \\\n    --hash=sha256:abc\n'
            'old-platform-only==1.0; python_version < "3.0"\n'
        )
    assert preflight.locked_versions_match(tmp_path, lookup=lambda name: "1.0") is False
    assert preflight.locked_versions_match(tmp_path, lookup=lambda name: "2.0") is True
