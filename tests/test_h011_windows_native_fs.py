"""Unit 1 read-only Windows H011 primitives; native tests use disposable NTFS files."""

from __future__ import annotations

import os
import platform
import subprocess
import sys

import pytest

from agents.core.checkpoint_windows_fs import (
    WindowsFsRefusal,
    WindowsHistoryFs,
    WinFileId,
    WinStamp,
)


def _stamp(number: int, *, file: bool = False, reparse: bool = False,
           size: int = 3, high: int = 0) -> WinStamp:
    return WinStamp(WinFileId((1).to_bytes(8, "little"),
                              number.to_bytes(8, "little") + high.to_bytes(8, "little")),
                    size if file else 0, 1, not file, False, 10, 11,
                    0x400 if reparse else (0x20 if file else 0x10),
                    0xA000000C if reparse else 0)


class FakeApi:
    def __init__(self):
        self.guid = "\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\"
        self.calls = []
        self.closed = []
        self.stamps = {1: _stamp(1), 2: _stamp(2), 3: _stamp(3, file=True)}
        self.children = {(1, "project", True): 2, (2, "note.txt", False): 3}
        self.data = b"abc"
        self.denied = set()
        self.acl = ("owner", "owner", True, (("owner", "allow"),
                                             ("S-1-5-18", "allow")))

    def volume_guid(self, drive):
        self.calls.append(("guid", drive))
        return self.guid

    def open_volume_root(self, guid):
        self.calls.append(("root", guid))
        return 1

    def volume_info(self, handle):
        self.calls.append(("volume", handle))
        return "NTFS", 0x8

    def open_child(self, parent, name, directory):
        self.calls.append(("child", parent, name, directory))
        if name in self.denied:
            raise WindowsFsRefusal("open_failed:5")
        return self.children.get((parent, name, directory))

    def stamp(self, handle):
        return self.stamps[handle]

    def read(self, handle, limit):
        self.calls.append(("read", handle, limit))
        return self.data[:limit]

    def acl_info(self, handle):
        self.calls.append(("acl", handle))
        return self.acl

    def close(self, handle):
        self.closed.append(handle)


def test_fake_root_walk_and_exact_read_use_held_parents():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with fs.open_root(r"C:\project") as root:
        assert root.stamp.identity == _stamp(2).identity
        with fs.open_child(root, "note.txt", directory=False) as note:
            assert fs.read_exact_bounded(note, 3) == b"abc"
            assert fs.verify_name(root, "note.txt", note).identity == note.stamp.identity
            fs.verify_private_acl(note)
        fs.verify_mount(root)
    assert api.closed.count(1) == 3 and api.closed.count(2) == 3
    assert api.closed.count(3) == 2  # held target and verify-name open
    assert ("child", 1, "project", True) in api.calls
    assert ("child", 2, "note.txt", False) in api.calls


@pytest.mark.parametrize("path", [r"C:relative", r"\\server\share\a", r"\\?\C:\a",
                                  r"C:\a\..\b", r"C:\a.\b", r"C:\a:ads",
                                  r"C:\a\\b", r"C:\CON", r"C:\a ",
                                  r"C:\PROGRA~1", r"C:\COM¹", r"C:\CONIN$"])
def test_fake_root_refuses_alias_and_device_paths_before_api(path):
    api = FakeApi()
    with pytest.raises(WindowsFsRefusal):
        WindowsHistoryFs(api).open_root(path)
    assert api.calls == []


def test_fake_missing_is_distinct_from_denied_and_reparse():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with fs.open_root(r"C:\project") as root:
        assert fs.open_child(root, "missing.txt", directory=False) is None
        api.denied.add("denied.txt")
        with pytest.raises(WindowsFsRefusal, match="open_failed:5"):
            fs.open_child(root, "denied.txt", directory=False)
        api.children[(2, "bad.txt", False)] = 3
        api.stamps[3] = _stamp(3, file=True, reparse=True)
        with pytest.raises(WindowsFsRefusal, match="reparse"):
            fs.open_child(root, "bad.txt", directory=False)
        assert api.closed.count(3) == 1


def test_fake_cross_volume_and_unsupported_volume_refuse_without_leaked_handle():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with fs.open_root(r"C:\project") as root:
        api.stamps[3] = WinStamp(WinFileId((2).to_bytes(8, "little"),
                                           (3).to_bytes(16, "little")),
                                 3, 1, False, False, 10, 11, 0x20, 0)
        with pytest.raises(WindowsFsRefusal, match="different_volume"):
            fs.open_child(root, "note.txt", directory=False)
        assert api.closed.count(3) == 1
    other = FakeApi()
    other.volume_info = lambda _handle: ("ReFS", 0)
    with pytest.raises(WindowsFsRefusal, match="unsupported_volume"):
        WindowsHistoryFs(other).open_root(r"C:\project")
    assert other.closed == [1]


def test_fake_drive_remap_high_id_collision_read_change_and_acl_refuse():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with fs.open_root(r"C:\project") as root:
        api.guid = "\\\\?\\Volume{22222222-2222-2222-2222-222222222222}\\"
        with pytest.raises(WindowsFsRefusal, match="mount_changed"):
            fs.verify_mount(root)
        api.guid = "\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\"
        with fs.open_child(root, "note.txt", directory=False) as note:
            api.stamps[3] = _stamp(3, file=True, high=1)
            with pytest.raises(WindowsFsRefusal, match="name_changed"):
                fs.verify_name(root, "note.txt", note)
            api.stamps[3] = _stamp(3, file=True, size=4)
            with pytest.raises(WindowsFsRefusal, match="name_changed"):
                fs.verify_name(root, "note.txt", note)
            api.stamps[3] = _stamp(3, file=True)
            api.data = b"abcd"
            with pytest.raises(WindowsFsRefusal, match="read_changed"):
                fs.read_exact_bounded(note, 3)
            api.data = b"abc"
            api.acl = ("owner", "owner", False, (("owner", "allow"),))
            with pytest.raises(WindowsFsRefusal, match="acl_invalid"):
                fs.verify_private_acl(note)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_local_ntfs_root_and_child_exact_read(tmp_path):
    note = tmp_path / "note.txt"
    note.write_bytes(b"native bytes")
    fs = WindowsHistoryFs()
    with fs.open_root(str(tmp_path)) as root:
        print(f"native OS={platform.platform()} Python={platform.python_version()} "
              f"volume={fs.api.volume_info(root.raw)}")
        assert root.stamp.is_directory
        with fs.open_child(root, note.name, directory=False) as child:
            assert child.stamp.identity.file_id != b"\0" * 16
            assert fs.read_exact_bounded(child, 12) == b"native bytes"
            assert fs.verify_name(root, note.name, child).identity == child.stamp.identity
        fs.verify_mount(root)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_name_replacement_and_bounded_read_refuse(tmp_path):
    note = tmp_path / "note.txt"
    note.write_bytes(b"abc")
    fs = WindowsHistoryFs()
    with fs.open_root(str(tmp_path)) as root, fs.open_child(
            root, note.name, directory=False) as held:
        with pytest.raises(WindowsFsRefusal, match="read_too_large"):
            fs.read_exact_bounded(held, 2)
        moved = tmp_path / "moved.txt"
        os.replace(note, moved)
        note.write_bytes(b"other")
        with pytest.raises(WindowsFsRefusal, match="name_changed"):
            fs.verify_name(root, note.name, held)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_reparse_and_acl_refusal_use_synthetic_tree(tmp_path):
    fs = WindowsHistoryFs()
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
    with fs.open_root(str(tmp_path)) as root, pytest.raises(
            WindowsFsRefusal, match="reparse"):
        fs.open_child(root, "link", directory=True)
    (target / "nested").mkdir()
    with pytest.raises(WindowsFsRefusal, match="reparse"):
        fs.open_root(str(link / "nested"))


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_private_owner_acl_accepts_only_protected_allowed_aces(tmp_path):
    note = tmp_path / "private.txt"
    note.write_bytes(b"private")
    fs = WindowsHistoryFs()
    sid = fs.api._current_sid()
    private = subprocess.run(["icacls", str(note), "/inheritance:r", "/grant:r",
                              f"*{sid}:F"], capture_output=True, text=True, check=False)
    assert private.returncode == 0, private.stderr
    with fs.open_root(str(tmp_path)) as root, fs.open_child(
            root, note.name, directory=False) as held:
        fs.verify_private_acl(held)
        hostile = subprocess.run(["icacls", str(note), "/grant", "*S-1-1-0:R"],
                                 capture_output=True, text=True, check=False)
        assert hostile.returncode == 0, hostile.stderr
        with pytest.raises(WindowsFsRefusal, match="acl_invalid"):
            fs.verify_private_acl(held)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_handles_close_after_repeated_root_and_child_probes(tmp_path):
    import ctypes
    from ctypes import wintypes as w

    note = tmp_path / "note.txt"
    note.write_bytes(b"abc")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetProcessHandleCount.argtypes = (w.HANDLE, ctypes.POINTER(w.DWORD))
    kernel.GetProcessHandleCount.restype = w.BOOL

    def handle_count():
        count = w.DWORD()
        assert kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(count))
        return count.value

    before = handle_count()
    fs = WindowsHistoryFs()
    for _ in range(10):
        with fs.open_root(str(tmp_path)) as root, fs.open_child(
                root, note.name, directory=False) as held:
            assert fs.read_exact_bounded(held, 3) == b"abc"
            fs.verify_name(root, note.name, held)
            fs.verify_mount(root)
    assert handle_count() <= before + 2
