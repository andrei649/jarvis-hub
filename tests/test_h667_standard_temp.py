"""Standard temp locations are owner choices, never implicitly owned cache."""

from pathlib import Path

import pytest

from agents.core import exec_cache
from agents.core.sandbox import Sandbox


def _settings(root=""):
    return lambda category, key, default=None: root if (category, key) == exec_cache.SETTING else default


@pytest.mark.parametrize("index", range(3))
def test_standard_temp_choices_have_order_before_managed_cache(tmp_path, index):
    keys = ("TMPDIR", "TMP", "TEMP")
    env = {key: str(tmp_path / key.lower()) for key in keys[index:]}
    assert exec_cache.resolve_root(env, _settings()) == (Path(env[keys[index]]), False)


def test_explicit_execution_choices_win_over_standard_temp(tmp_path):
    env = {key: str(tmp_path / key.lower()) for key in ("TMPDIR", "TMP", "TEMP")}
    owner = tmp_path / "owner"
    explicit = tmp_path / "explicit"
    assert exec_cache.resolve_root(env, _settings(str(owner))) == (owner, False)
    env[exec_cache.ENV_KEY] = str(explicit)
    assert exec_cache.resolve_root(env, _settings(str(owner))) == (explicit, False)


@pytest.mark.parametrize("bad", ["relative/root", "/nul\x00root", "/line\nroot", "~no_such_h667_user/root"])
def test_invalid_standard_temp_skips_to_next_choice(tmp_path, caplog, bad):
    target = tmp_path / "temp"
    env = {"TMPDIR": bad, "TMP": "  ", "TEMP": f"  {target}  "}
    assert exec_cache.resolve_root(env, _settings()) == (target, False)
    assert "TMPDIR" in caplog.text and "skipped" in caplog.text


def test_empty_or_invalid_standard_choices_end_at_managed_cache(tmp_path, monkeypatch):
    managed = tmp_path / "managed"
    monkeypatch.setattr(exec_cache, "managed_root", lambda: managed)
    assert exec_cache.resolve_root({"TMPDIR": "", "TMP": "relative", "TEMP": " "}, _settings()) == (managed, True)
    assert exec_cache.resolve_root({"TMP": str(managed)}, _settings()) == (managed, True)


def test_sandbox_uses_process_temp_choice_without_pruning_it(tmp_path, monkeypatch):
    from agents.core import settings_db

    managed = tmp_path / "managed"
    chosen = tmp_path / "durable-temp"
    monkeypatch.setattr(exec_cache, "managed_root", lambda: managed)
    monkeypatch.setattr(settings_db, "get_value", _settings())
    monkeypatch.delenv(exec_cache.ENV_KEY, raising=False)
    monkeypatch.setenv("TMPDIR", str(chosen))
    sandbox = Sandbox()
    assert sandbox.work_dir.parent == chosen
    assert sandbox.work_dir_managed is False
    assert sandbox._work_lock is None
    payload = sandbox.work_dir / "script.py"
    payload.write_text("print('synthetic')")
    report = exec_cache.prune(chosen, managed=sandbox.work_dir_managed)
    assert report["deleted"] == [] and payload.read_text() == "print('synthetic')"
