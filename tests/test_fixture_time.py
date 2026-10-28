"""Portable fixture timestamps never follow links or mutate a rejected tree."""
import ctypes
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import fixture_time


def test_owned_tree_ages_when_no_follow_utime_is_unavailable(tmp_path, monkeypatch):
    nested = tmp_path / "nested"
    nested.mkdir()
    leaf = nested / "data"
    leaf.write_bytes(b"fixture")
    real_utime = fixture_time.os.utime
    stamped = []

    def native_utime(path, times, **kwargs):
        if "follow_symlinks" in kwargs:
            raise NotImplementedError("utime: follow_symlinks unavailable")
        stamped.append(Path(path))
        return real_utime(path, times)

    monkeypatch.setattr(fixture_time.os, "utime", native_utime)
    monkeypatch.setattr(fixture_time.time, "time", lambda: 1_700_000_000)
    fixture_time.age_tree(tmp_path, 2)

    assert set(stamped) == {tmp_path, nested, leaf}
    assert all(p.stat().st_mtime == pytest.approx(1_700_000_000 - 7200) for p in stamped)
    assert leaf.read_bytes() == b"fixture"


@pytest.mark.parametrize("at_root,reparse", [(True, False), (True, True), (False, False), (False, True)])
def test_link_or_reparse_fixture_entries_are_never_stamped_or_traversed(tmp_path, monkeypatch, at_root, reparse):
    (tmp_path / "owned").write_bytes(b"owned")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    outside = blocked / "target"
    outside.write_bytes(b"unchanged")
    original_mtime = outside.stat().st_mtime
    target = tmp_path if at_root else blocked
    real_lstat = Path.lstat

    def lstat(path):
        if path == target:
            return SimpleNamespace(st_mode=stat.S_IFDIR if reparse else stat.S_IFLNK,
                                   st_file_attributes=0x400 if reparse else 0)
        return real_lstat(path)

    stamp = Mock(wraps=fixture_time.os.utime)
    link_stamp = Mock()
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(fixture_time.os, "utime", stamp)
    monkeypatch.setattr(fixture_time, "_stamp_link", link_stamp)

    if at_root:
        with pytest.raises(ValueError, match="link or reparse point"):
            fixture_time.age_tree(tmp_path, 2)
        stamp.assert_not_called()
        link_stamp.assert_not_called()
    else:
        fixture_time.age_tree(tmp_path, 2)
        assert {Path(c.args[0]) for c in stamp.call_args_list} == {tmp_path, tmp_path / "owned"}
        assert link_stamp.call_count == 1 and link_stamp.call_args.args[0] == blocked
    assert outside.stat().st_mtime == original_mtime
    assert outside.read_bytes() == b"unchanged"


def test_unavailable_link_timestamp_primitive_never_falls_back_to_following(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"unchanged")
    real_lstat = Path.lstat
    monkeypatch.setattr(Path, "lstat", lambda p: SimpleNamespace(st_mode=stat.S_IFLNK) if p == blocked else real_lstat(p))
    monkeypatch.setattr(fixture_time, "_stamp_link", Mock(side_effect=NotImplementedError("no link primitive")))
    stamp = Mock()
    monkeypatch.setattr(fixture_time.os, "utime", stamp)

    with pytest.raises(NotImplementedError, match="no link primitive"):
        fixture_time.age_tree(tmp_path, 2)
    stamp.assert_not_called()


@pytest.mark.parametrize("failure", [None, "open", "stamp", "close"])
def test_windows_link_timestamp_uses_a_nofollow_handle_and_closes_it(tmp_path, monkeypatch, failure):
    opened, stamped, closed = [], [], []

    def create(*args):
        opened.append(args)
        return ctypes.c_void_p(-1).value if failure == "open" else 17

    def set_time(handle, created, accessed, modified):
        assert created is None
        a, m = accessed._obj, modified._obj
        stamped.append((handle, a.dwLowDateTime | (a.dwHighDateTime << 32),
                        m.dwLowDateTime | (m.dwHighDateTime << 32)))
        return failure != "stamp"

    def close(handle):
        closed.append(handle)
        return failure != "close"

    kernel = SimpleNamespace(CreateFileW=create, SetFileTime=set_time, CloseHandle=close)
    monkeypatch.setattr(fixture_time, "_windows_kernel", lambda: kernel)
    monkeypatch.setattr(fixture_time, "_windows_error", lambda: OSError("native timestamp error"))
    path = tmp_path / "link"
    if failure:
        with pytest.raises(OSError, match="native timestamp error"):
            fixture_time._stamp_windows_link(path, 1_700_000_000)
    else:
        fixture_time._stamp_windows_link(path, 1_700_000_000)

    assert opened == [(str(path), 0x100, 7, None, 3, 0x02200000, None)]
    assert closed == ([] if failure == "open" else [17])
    expected = 1_700_000_000 * 10_000_000 + 116444736000000000
    assert stamped == ([] if failure == "open" else [(17, expected, expected)])
