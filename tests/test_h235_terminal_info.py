"""H235 — the terminal chat's own helpers: directory and git branch, battery, OSC 52 copy.

All local: nothing here talks to the hub or runs a shell, and every string drawn is
card-safe (a branch name or directory with an escape or bidi character cannot repaint
the terminal). The OSC 52 payload is base64, so an answer cannot smuggle a sequence.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest

from agents.cli import repl as R
from agents.cli import term_info as T
from tests.test_h224_terminal_interaction import _repl

# ── git branch and directory ──────────────────────────────────────────────────


def test_git_branch_from_a_checkout_and_its_subfolders(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/feature/x\n")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert T.git_branch(deep) == "feature/x"


def test_git_branch_detached_worktree_and_none(tmp_path):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "w").mkdir(parents=True)
    (main / ".git" / "worktrees" / "w" / "HEAD").write_text("a" * 40 + "\n")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'w'}\n")
    assert T.git_branch(tree) == "@" + "a" * 12
    (tree / ".git").write_text("not a pointer")
    assert T.git_branch(tree) is None


def test_a_hostile_branch_name_is_drawn_safe(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/x\x1b]0;owned\x07‮y" + "z" * 200)
    branch = T.git_branch(tmp_path)
    assert "\x1b" not in branch and "\x07" not in branch and "‮" not in branch and len(branch) <= 60


def test_cwd_label_uses_tilde_and_keeps_the_tail(tmp_path):
    home = tmp_path / "home"
    assert T.cwd_label(home / "proj", home) == "~/proj"
    assert T.cwd_label(home, home) == "~"
    long = tmp_path / ("d" * 100) / "end"
    label = T.cwd_label(long, home)
    assert label.startswith("…") and label.endswith("/end") and len(label) == 60


# ── battery ───────────────────────────────────────────────────────────────────

def _supply(root: Path, name: str, kind: str, capacity: str | None = None, status: str | None = None):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "type").write_text(kind + "\n")
    if capacity is not None:
        (folder / "capacity").write_text(capacity + "\n")
    if status is not None:
        (folder / "status").write_text(status + "\n")


def test_linux_battery_from_sysfs(tmp_path):
    _supply(tmp_path, "AC", "Mains")
    _supply(tmp_path, "BAT0", "Battery", "42", "Discharging")
    assert T.battery(platform="linux", sysfs=tmp_path) == T.Battery(42, False)
    assert T.Battery(42, False).label() == "battery 42%"
    assert T.battery(platform="linux", sysfs=tmp_path / "missing") is None


def test_linux_without_a_battery(tmp_path):
    _supply(tmp_path, "AC", "Mains")
    assert T.battery(platform="linux", sysfs=tmp_path) is None


@pytest.mark.parametrize("text,expected", [
    ("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t54%; discharging; 3:12 remaining",
     T.Battery(54, False)),
    ("Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%; charged; 0:00 remaining", T.Battery(100, True)),
    ("Now drawing from 'AC Power'", None),
])
def test_mac_battery_parses_pmset(text, expected):
    seen = []

    def run(argv):
        seen.append(argv)
        return text

    assert T.battery(platform="darwin", run=run) == expected
    assert seen == [["/usr/bin/pmset", "-g", "batt"]]       # fixed absolute argv, no shell


def test_mac_battery_survives_a_missing_pmset():
    def run(argv):
        raise FileNotFoundError(argv[0])

    assert T.battery(platform="darwin", run=run) is None
    assert T.battery(platform="sunos5") is None


def test_battery_polling_warns_once_per_five_points(tmp_path, monkeypatch):
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch)
    readings = iter([T.Battery(14, False), T.Battery(13, False), T.Battery(9, False), T.Battery(30, False),
                     T.Battery(10, True)])
    monkeypatch.setattr(T, "battery", lambda: next(readings))
    for minute in range(5):
        repl.check_battery(now=1000.0 + minute * R.BATTERY_POLL_SECONDS)
    repl.check_battery(now=1000.0 + 4 * R.BATTERY_POLL_SECONDS + 1)   # within the minute: not polled
    warnings = [line for line in err.getvalue().splitlines() if line.startswith("battery")]
    assert warnings == ["battery 14% and discharging", "battery 9% and discharging"]


# ── /where and /copy in the chat ──────────────────────────────────────────────

def test_where_names_directory_branch_and_battery(tmp_path, monkeypatch):
    (tmp_path / "proj" / ".git").mkdir(parents=True)
    (tmp_path / "proj" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.chdir(tmp_path / "proj")
    monkeypatch.setattr(T, "battery", lambda: T.Battery(80, True))
    repl, _hub, _out, err = _repl(tmp_path, monkeypatch, environ={"HOME": str(tmp_path)})
    repl.local("/where")
    assert "~/proj · git main · battery 80% (charging)" in err.getvalue()


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_copy_sends_the_last_answer_as_base64_osc52(tmp_path, monkeypatch):
    repl, _hub, out, err = _repl(tmp_path, monkeypatch)
    repl.local("/copy")
    assert "no answer to copy yet" in err.getvalue() and out.getvalue() == ""
    repl.show_reply({"reply": "line one\nrm -rf /\x1b]52;c;ZXZpbA==\x07 done"})
    out.truncate(0)
    out.seek(0)
    repl.local("/copy")
    sequence = out.getvalue()
    assert sequence.startswith("\x1b]52;c;") and sequence.endswith("\x07")
    payload = sequence[len("\x1b]52;c;"):-1]
    assert set(payload) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    copied = base64.b64decode(payload).decode()
    assert copied.startswith("line one\nrm -rf /") and "\x1b" not in copied and "\x07" not in copied
    assert "copied" in err.getvalue()


def test_osc52_wraps_for_tmux_and_refuses_oversize():
    plain = T.osc52("hi", {})
    assert plain == "\x1b]52;c;aGk=\x07"
    wrapped = T.osc52("hi", {"TMUX": "/tmp/tmux-1/default,1,0"})
    assert wrapped == "\x1bPtmux;\x1b\x1b]52;c;aGk=\x07\x1b\\"
    assert T.osc52("x" * 60_000, {}) is None


def test_the_client_commands_are_listed():
    assert "/copy" in R.LOCAL_COMMANDS and "/where" in R.LOCAL_COMMANDS
    assert any(line.startswith("/copy") for line in R.KEY_HELP)
    assert R.route_line("/where") == ("local", "/where")


# ── H225: a queued message can be edited before it is sent ─────────────────────

def test_queue_edit_takes_a_message_back_into_the_draft(tmp_path, monkeypatch):
    repl, *_ = _repl(tmp_path, monkeypatch)
    repl.running = True
    repl.submit("first")
    repl.submit("secnod")
    repl._rl = object()          # a readline is present: the draft is prefilled
    repl.local("/queue edit 2")
    assert [item.message for item in repl.queue] == ["first"] and repl._prefill == "secnod"
    repl.local("/queue edit 9")
    assert [item.message for item in repl.queue] == ["first"]
    assert "/queue edit N" in R.LOCAL_COMMANDS["/queue"]


@pytest.mark.parametrize("flag,percent,line,expected", [
    (0, 37, 0, T.Battery(37, False)),
    (8, 90, 1, T.Battery(90, True)),
    (0x80, 255, 1, None),            # no system battery
    (0, 255, 0, None),               # unknown
])
def test_windows_battery_from_get_system_power_status(monkeypatch, flag, percent, line, expected):
    import ctypes
    from types import SimpleNamespace

    def status(ref):
        struct = ref._obj
        struct.BatteryFlag, struct.BatteryLifePercent, struct.ACLineStatus = flag, percent, line
        return 1

    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GetSystemPowerStatus=status)),
                        raising=False)
    assert T.battery(platform="win32") == expected


# ── review fixes (M2, m1) ─────────────────────────────────────────────────────

def _repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path / ".git" / "HEAD"


def test_a_fifo_head_is_not_waited_on(tmp_path):
    import os
    import threading

    os.mkfifo(_repo(tmp_path))
    box = {}
    worker = threading.Thread(target=lambda: box.setdefault("v", T.git_branch(tmp_path)), daemon=True)
    worker.start()
    worker.join(3)
    assert not worker.is_alive() and box["v"] is None


def test_a_symlinked_head_or_git_folder_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("ref: refs/heads/stolen\n")
    _repo(tmp_path).symlink_to(target)
    assert T.git_branch(tmp_path) is None
    other = tmp_path / "other"
    (other / "sub").mkdir(parents=True)
    (other / "sub" / ".git").symlink_to(tmp_path / ".git")
    assert T.git_branch(other / "sub", other) is None


def test_a_git_folder_owned_by_someone_else_is_not_read(tmp_path, monkeypatch):
    _repo(tmp_path).write_text("ref: refs/heads/theirs\n")
    assert T.git_branch(tmp_path) == "theirs"
    monkeypatch.setattr(T, "_trusted_owner", lambda info: False)
    assert T.git_branch(tmp_path) is None
    # the owner rule itself: this user or root only
    import os
    import types

    monkeypatch.undo()
    monkeypatch.setattr(os, "geteuid", lambda: 4242, raising=False)
    assert T._trusted_owner(types.SimpleNamespace(st_uid=4242)) and T._trusted_owner(types.SimpleNamespace(st_uid=0))
    assert not T._trusted_owner(types.SimpleNamespace(st_uid=1000))


def test_the_walk_stops_at_home(tmp_path):
    _repo(tmp_path).write_text("ref: refs/heads/above-home\n")
    home = tmp_path / "home"
    (home / "proj").mkdir(parents=True)
    assert T.git_branch(home / "proj") == "above-home"
    assert T.git_branch(home / "proj", home) is None


def test_the_walk_stops_at_a_filesystem_boundary(tmp_path, monkeypatch):
    import os

    _repo(tmp_path).write_text("ref: refs/heads/other-fs\n")
    (tmp_path / "mnt").mkdir()
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if str(path) == str(tmp_path):
            values = list(info)
            values[2] = info.st_dev + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(T.os, "stat", fake_stat)
    assert T.git_branch(tmp_path / "mnt") is None


def test_battery_is_polled_on_a_timer_while_the_chat_runs(tmp_path, monkeypatch):
    import time as _time

    repl, *_ = _repl(tmp_path, monkeypatch)
    readings = []

    def reading():
        readings.append(1)

    monkeypatch.setattr(T, "battery", reading)
    monkeypatch.setattr(R, "BATTERY_POLL_SECONDS", 0.05)
    monkeypatch.setattr(repl, "step", lambda: (_time.sleep(0.5), False)[1])
    assert repl.run() == 0
    assert len(readings) >= 3                # polled while the prompt waited, not per Enter
