"""H084 read-only chat identity commands use the serving process's real identity."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import paths
from agents.core.channels import outbound_safety
from agents.core.commands import CommandContext, Principal
from agents.core.identity_commands import profile_command, version_command


def _ctx(name: str, *, owner: bool = True, args: str = "") -> CommandContext:
    return CommandContext(SimpleNamespace(), Principal(channel="web", admin=owner), name, args)


def test_version_uses_canonical_running_version_without_args(monkeypatch):
    import agents

    monkeypatch.setattr(agents, "__version__", "9.8.7")
    assert version_command(_ctx("version")) == "Nerva 9.8.7"
    assert version_command(_ctx("v", owner=False)) == "Nerva 9.8.7"
    assert "Usage: /version" in version_command(_ctx("version", args="extra"))


def test_version_sanitizes_entire_banner_before_clipping(monkeypatch):
    import agents

    secret = "private-" + "x" * 300
    monkeypatch.setattr(agents, "__version__", secret)
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda text: text.replace(secret, "[REDACTED:known]"))
    reply = version_command(_ctx("version"))
    assert "[REDACTED:known]" in reply
    assert "private-" not in reply and "x" * 100 not in reply


def test_profile_default_reports_canonical_id_label_and_actual_home(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.delenv("NERVA_PROFILE", raising=False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "state"))
    reply = profile_command(_ctx("profile"))
    assert "Profile ID: default" in reply
    assert "Display label: default (canonical ID; no separate label configured)" in reply
    assert f"Home: {tmp_path / 'state'}" in reply
    assert not (tmp_path / "state").exists()


def test_profile_named_uses_active_profile_context_and_keeps_label_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    monkeypatch.delenv("NERVA_PROFILE", raising=False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "state"))
    reply = profile_command(_ctx("profile"))
    assert "Profile ID: work" in reply
    assert "Display label: work (canonical ID; no separate label configured)" in reply
    assert f"Home: {tmp_path / 'state-profiles' / 'work'}" in reply
    assert "JARVIS_PROFILE" not in reply


def test_profile_guest_and_arguments_refuse_before_private_path_lookup(monkeypatch):
    def private_path():
        pytest.fail("guest or malformed command read private home")

    monkeypatch.setattr(paths, "profile_name", private_path)
    monkeypatch.setattr(paths, "data_root", private_path)
    assert "owner" in profile_command(_ctx("profile", owner=False)).lower()
    assert "Usage: /profile" in profile_command(_ctx("profile", args="other"))


def test_profile_home_redacts_whole_value_before_clipping(tmp_path, monkeypatch):
    secret = "private-" + "x" * 300
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda text: text.replace(secret, "[REDACTED:known]"))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / secret))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.delenv("NERVA_PROFILE", raising=False)
    reply = profile_command(_ctx("profile"))
    assert "[REDACTED:known]" in reply
    assert "private-" not in reply and "x" * 100 not in reply


def test_profile_withholds_overlong_home_and_invalid_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / ("private-" + "x" * 5000)))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    reply = profile_command(_ctx("profile"))
    assert "Home: (path withheld)" in reply and "private-" not in reply
    monkeypatch.setenv("JARVIS_PROFILE", "Invalid Profile")
    reply = profile_command(_ctx("profile"))
    assert "unavailable" in reply.lower() and "Invalid Profile" not in reply
