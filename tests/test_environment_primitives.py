"""Hermes-style execution environment primitives for Jarvis.

These tests cover pure contracts only: backend metadata, CWD marker parsing,
and child-process environment scrubbing. Real Docker/SSH execution is a later
integration layer.
"""

from agents.core.environments import (
    WINDOWS_ESSENTIAL_ENV_VARS,
    backend_profiles,
    build_cwd_marker,
    extract_cwd_marker,
    prepare_python_child_env,
    scrub_child_env,
)


def test_backend_profiles_describe_local_docker_and_ssh_contracts():
    profiles = {profile.name: profile for profile in backend_profiles()}

    assert set(profiles) == {"local", "docker", "ssh"}
    assert profiles["local"].isolated is False
    assert profiles["local"].remote is False
    assert profiles["local"].supports_file_rpc is False

    assert profiles["docker"].isolated is True
    assert profiles["docker"].remote is False
    assert profiles["docker"].supports_file_rpc is True

    assert profiles["ssh"].isolated is False
    assert profiles["ssh"].remote is True
    assert profiles["ssh"].supports_file_rpc is True


def test_cwd_marker_round_trips_and_extracts_last_complete_marker():
    marker = build_cwd_marker("session_abc")
    output = (
        "first line\n"
        f"{marker}/work/old{marker}\n"
        "middle line\n"
        f"{marker}/work/new{marker}\n"
        "tail"
    )

    result = extract_cwd_marker(output, "session_abc")

    assert result.cwd == "/work/new"
    assert result.output == "first line\nmiddle line\ntail"


def test_cwd_marker_ignores_malformed_or_wrong_session_markers():
    marker = build_cwd_marker("session_abc")
    other = build_cwd_marker("session_other")
    output = f"keep\n{marker}/missing-close\n{other}/tmp{other}\n"

    result = extract_cwd_marker(output, "session_abc")

    assert result.cwd is None
    assert result.output == output


def test_scrub_child_env_blocks_secret_names_and_keeps_safe_values():
    source = {
        "PATH": "/bin",
        "HOME": "/home/andrei",
        "JARVIS_HOME": "/srv/jarvis",
        "JARVIS_BASE_URL": "http://localhost:8080",
        "OPENAI_API_KEY": "sk-secret",
        "MY_PASSWORD": "secret",
        "RANDOM_VALUE": "drop",
        "TENOR_API_KEY": "allowed-by-skill",
    }

    scrubbed = scrub_child_env(
        source,
        passthrough=lambda key: key == "TENOR_API_KEY",
        is_windows=False,
    )

    assert scrubbed["PATH"] == "/bin"
    assert scrubbed["HOME"] == "/home/andrei"
    assert scrubbed["JARVIS_HOME"] == "/srv/jarvis"
    assert scrubbed["TENOR_API_KEY"] == "allowed-by-skill"
    assert "JARVIS_BASE_URL" not in scrubbed
    assert "OPENAI_API_KEY" not in scrubbed
    assert "MY_PASSWORD" not in scrubbed
    assert "RANDOM_VALUE" not in scrubbed


def test_scrub_child_env_allows_windows_essentials_only_in_windows_mode():
    source = {
        "SystemRoot": r"C:\Windows",
        "ComSpec": r"C:\Windows\System32\cmd.exe",
        "APPDATA": r"C:\Users\andrei\AppData\Roaming",
        "PATH": r"C:\Windows\System32",
        "GITHUB_TOKEN": "ghp-secret",
    }

    posix = scrub_child_env(source, is_windows=False)
    windows = scrub_child_env(source, is_windows=True)

    assert "SystemRoot" not in posix
    assert "ComSpec" not in posix
    assert "APPDATA" not in posix
    assert "PATH" in posix

    assert "SystemRoot" in windows
    assert "ComSpec" in windows
    assert "APPDATA" in windows
    assert "PATH" in windows
    assert "GITHUB_TOKEN" not in windows
    assert all(name == name.upper() for name in WINDOWS_ESSENTIAL_ENV_VARS)


def test_prepare_python_child_env_forces_utf8_stdio():
    env = prepare_python_child_env({"PATH": "/bin", "OPENAI_API_KEY": "sk-secret"})

    assert env["PATH"] == "/bin"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert "OPENAI_API_KEY" not in env
