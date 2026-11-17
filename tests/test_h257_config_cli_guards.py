"""H257 — `nerva config` on a box with no running hub: the rest of Hermes's guards.

* ``set`` refuses to replace a whole section (an object) with a value that is not one
  unless ``--force`` (Hermes ``config set``'s mapping guard);
* an unknown name gets a difflib "did you mean" (Hermes prints the same);
* a CLI write is on the audit log in the route's own words (AUD-8), never with a secret
  value, and runs under the same settings-write lock (one mediation, two surfaces).
"""

from __future__ import annotations

import io

import pytest

from agents.cli import nerva
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main
from agents.core import settings_audit, settings_db


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    return tmp_path


class _Audit:
    def __init__(self):
        self.rows: list[tuple[str, str]] = []

    def log(self, event):
        self.rows.append((event.action_taken, event.content_preview))


@pytest.fixture
def audit(monkeypatch):
    log = _Audit()
    monkeypatch.setattr(nerva, "_audit_log", lambda: log)
    return log


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


# ── --force: a section is not replaced by a scalar by accident ───────────────


def test_set_refuses_to_replace_a_whole_section_with_a_scalar_without_force(temp_settings, audit):
    settings_db.put_category("appearance", {"preferences": {"panel": {"w": 3, "h": 4}, "accent": "cyan"}})

    code, _, err = _run(["config", "set", "appearance.preferences.panel", "7"])
    assert code == EXIT_FAILED and "--force" in err and "2 key(s)" in err
    assert settings_db.get_value("appearance", "preferences")["panel"] == {"w": 3, "h": 4}

    code, _, err = _run(["config", "set", "appearance.preferences", '"flat"'])
    assert code == EXIT_FAILED and "--force" in err

    code, _, err = _run(["config", "set", "appearance.preferences.panel", "7", "--force"])
    assert code == EXIT_OK, err
    assert settings_db.get_value("appearance", "preferences")["panel"] == 7


def test_set_without_force_still_replaces_a_section_with_an_object_or_a_leaf(temp_settings, audit):
    settings_db.put_category("appearance", {"preferences": {"panel": {"w": 3}, "accent": "cyan"}})
    code, _, err = _run(["config", "set", "appearance.preferences.panel", '{"w": 5}'])
    assert code == EXIT_OK, err
    code, _, err = _run(["config", "set", "appearance.preferences.accent", "amber"])
    assert code == EXIT_OK, err
    # a new key replaces no section
    code, _, err = _run(["config", "set", "appearance.preferences.font", "mono"])
    assert code == EXIT_OK, err
    # an empty object is no section to lose
    settings_db.put_category("appearance", {"preferences": {"panel": {}}})
    code, _, err = _run(["config", "set", "appearance.preferences.panel", "1"])
    assert code == EXIT_OK, err


def test_unset_needs_no_force(temp_settings, audit):
    settings_db.put_category("appearance", {"preferences": {"panel": {"w": 3}}})
    code, _, err = _run(["config", "unset", "appearance.preferences.panel"])
    assert code == EXIT_OK, err


# ── did you mean ─────────────────────────────────────────────────────────────


def test_an_unknown_name_gets_a_did_you_mean(temp_settings, audit):
    code, _, err = _run(["config", "set", "llm.tool_loop_max_iteration", "9"])
    assert code == EXIT_FAILED and "did you mean llm.tool_loop_max_iterations" in err
    code, _, err = _run(["config", "get", "llm.tool_loop_max_iteration"])
    assert code == EXIT_FAILED and "did you mean llm.tool_loop_max_iterations" in err
    code, _, err = _run(["config", "unset", "apperance.preferences"])
    assert code == EXIT_FAILED and "did you mean appearance.preferences" in err
    # nothing close: no suggestion, the old wording
    code, _, err = _run(["config", "set", "zzzz.qqqq", "1"])
    assert code == EXIT_FAILED and "did you mean" not in err and "not a declared setting" in err


def test_did_you_mean_is_bounded_on_a_huge_name(temp_settings, audit):
    import time

    start = time.monotonic()
    code, _, err = _run(["config", "get", "llm." + "x" * 100_000])
    assert code == EXIT_FAILED and "did you mean" not in err
    assert time.monotonic() - start < 10      # difflib sees a bounded prefix only


# ── one mediation: the audit row and the lock ────────────────────────────────


def test_a_cli_write_is_audited_in_the_routes_words(temp_settings, audit):
    code, _, err = _run(["config", "set", "llm.tool_loop_max_iterations", "9"])
    assert code == EXIT_OK, err
    previews = [p for action, p in audit.rows if action == settings_audit.ACTION]
    assert previews == [settings_audit.change_preview("llm", ["tool_loop_max_iterations"],
                                                      {"tool_loop_max_iterations": 9}, surface="cli")]
    assert "tool_loop_max_iterations=9" in previews[0] and "via cli" in previews[0]


def test_a_cli_secret_write_never_reaches_the_audit_row(temp_settings, audit):
    secret_key = next(iter(sorted(settings_db.SECRET_KEYS)))
    category = next(c for (c, k) in settings_db._SPEC if k == secret_key)
    code, _, err = _run(["config", "set", f"{category}.{secret_key}", "sk-live-very-secret-123456"])
    assert code == EXIT_OK, err
    joined = " ".join(p for _a, p in audit.rows)
    assert secret_key in joined and "sk-live-very-secret-123456" not in joined


def test_a_free_text_value_is_named_not_shown(temp_settings, audit):
    spec = next(s for s in settings_db.DEFAULTS if s["kind"] == "text" and s["key"] not in settings_db.SECRET_KEYS
                and (s["category"], s["key"]) not in settings_db.ROUTE_ONLY)
    name = f"{spec['category']}.{spec['key']}"
    code, _, _ = _run(["config", "set", name, "https://user:pw@example.invalid"])
    if code == EXIT_OK:
        joined = " ".join(p for _a, p in audit.rows)
        assert spec["key"] in joined and "pw@" not in joined


def test_the_cli_write_runs_under_the_settings_write_lock(temp_settings, audit, monkeypatch):
    from agents.core.autonomy import mode

    seen = []
    real = mode.locked_settings_write

    def spy(orch, fn, *args, **kwargs):
        seen.append((orch, getattr(fn, "__name__", "")))
        return real(orch, fn, *args, **kwargs)

    monkeypatch.setattr(mode, "locked_settings_write", spy)
    code, _, err = _run(["config", "set", "llm.tool_loop_max_iterations", "8"])
    assert code == EXIT_OK, err
    assert seen == [(None, "put_category")]


def test_the_route_and_the_cli_share_one_wording():
    from agents.core.routers import admin

    values = {"tool_loop_max_iterations": 3}
    assert admin._audited_values("llm", values) == settings_audit.audited_values("llm", values)


# ── review of 1bb285d0: M1 (a cross-process lock), M2 (credential leaves), m5 ─────────────

_PROBE = ("import sys\nfrom pathlib import Path\nfrom agents.core import settings_db\n"
          "settings_db.DB_PATH = Path(sys.argv[1])\nfrom agents.core.autonomy import mode\n"
          "sys.exit(0 if mode._write_lock.acquire(blocking=False) else 3)")


def test_another_process_cannot_take_the_settings_write_lock_during_a_cli_write(temp_settings, monkeypatch):
    # review r5: the lock the CLI holds over its read-check-write is held across processes
    import subprocess
    import sys

    monkeypatch.setattr(nerva, "_audit_log", lambda: None)
    seen: list[int] = []
    real = settings_db.put_category

    def put_and_probe(*args, **kwargs):
        # what a hub process would do at this instant: take the settings-write lock
        seen.append(subprocess.run([sys.executable, "-c", _PROBE, str(settings_db.DB_PATH)],
                                   timeout=60).returncode)
        return real(*args, **kwargs)

    monkeypatch.setattr(settings_db, "put_category", put_and_probe)
    code, _, err = _run(["config", "set", "llm.tool_loop_max_iterations", "12"])
    assert code == EXIT_OK, err
    assert seen == [3], "another process took the settings-write lock while the CLI held it"


def test_the_checks_run_inside_the_lock(temp_settings, audit, monkeypatch):
    from agents.core import retention
    from agents.core.autonomy import mode

    held = []
    real = retention.needs_approval

    def spy(*args, **kwargs):
        held.append(getattr(mode._write_lock._local, "depth", 0))
        return real(*args, **kwargs)

    monkeypatch.setattr(retention, "needs_approval", spy)
    code, _, err = _run(["config", "set", "llm.tool_loop_max_iterations", "7"])
    assert code == EXIT_OK, err
    assert held and held[0] >= 1


def test_a_busy_lock_writes_nothing_and_says_so(temp_settings, audit, monkeypatch):
    from agents.core import settings_lock

    def busy(*args, **kwargs):
        raise settings_lock.SettingsLockBusy("another process holds the settings-write lock")

    monkeypatch.setattr(settings_lock, "_flock", busy)
    code, _, err = _run(["config", "set", "llm.tool_loop_max_iterations", "6"])
    assert code == EXIT_FAILED and "not changed" in err
    assert settings_db.get_value("llm", "tool_loop_max_iterations") != 6


TOKEN = "sk-live-abcdefghijklmnopqrstuvwxyz0123456789"


def test_config_set_masks_a_credential_leaf_in_its_echo(temp_settings, audit):
    # review r3
    settings_db.put_category("mcp", {"servers": [{"name": "remote", "url": "https://mcp.example/sse",
                                                  "headers": {"Authorization": "Bearer x"}}]})
    code, out, err = _run(["config", "set", "mcp.servers.0.headers.Authorization", f"Bearer {TOKEN}"])
    assert code == EXIT_OK, err
    assert TOKEN not in out + err
    assert all(TOKEN not in row for _a, row in audit.rows)
    code, out, _ = _run(["config", "get", "mcp.servers"])
    assert code == EXIT_OK and TOKEN not in out and "remote" in out
    code, out, _ = _run(["config", "get", "mcp.servers", "--reveal"])
    assert TOKEN in out                                  # the owner asked for it


def test_masked_leaves_masks_by_name_container_and_shape():
    value = {"name": "x", "env": {"PLAIN": "1"}, "api_key": "abc", "nested": [{"token": "t"}],
             "note": f"key {TOKEN}", "count": 3, "on": True}
    shown = settings_db.masked_leaves(value)
    assert shown["name"] == "x" and shown["count"] == 3 and shown["on"] is True
    assert shown["env"]["PLAIN"] == settings_db.MASK and shown["api_key"] == settings_db.MASK
    assert shown["nested"][0]["token"] == settings_db.MASK and shown["note"] == settings_db.MASK
    assert value["api_key"] == "abc"                     # a copy


def test_config_migrate_writes_are_audited(temp_settings, audit):
    # review m5
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE category='llm' AND key='tool_loop_max_iterations'")
        conn.commit()
    finally:
        conn.close()
    code, _, err = _run(["config", "migrate"])
    assert code == EXIT_OK, err
    rows = [p for action, p in audit.rows if action == "settings_migrate"]
    assert rows and "llm.tool_loop_max_iterations" in rows[0] and "via cli" in rows[0]
