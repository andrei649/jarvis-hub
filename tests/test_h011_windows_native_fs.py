"""Unit 1 read-only Windows H011 primitives; native tests use disposable NTFS files."""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys

import pytest

import agents.core.checkpoint_windows_fs as windows_fs
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


def test_fake_mount_remap_during_rewalk_refuses_at_final_fence():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with fs.open_root(r"C:\project") as root:
        original_open_child = api.open_child

        def remap_during_walk(parent, name, directory):
            child = original_open_child(parent, name, directory)
            api.guid = "\\\\?\\Volume{22222222-2222-2222-2222-222222222222}\\"
            return child

        api.open_child = remap_during_walk
        with pytest.raises(WindowsFsRefusal, match="mount_changed"):
            fs.verify_mount(root)


def test_fake_parent_close_failure_also_closes_new_child():
    api = FakeApi()
    original_close = api.close
    failures = 0

    def fail_parent_once(handle):
        nonlocal failures
        if handle == 1 and failures == 0:
            failures += 1
            raise WindowsFsRefusal("close_failed:synthetic")
        original_close(handle)

    api.close = fail_parent_once
    with pytest.raises(WindowsFsRefusal, match="close_failed:synthetic"):
        WindowsHistoryFs(api).open_root(r"C:\project")
    assert failures == 1
    assert api.closed.count(1) == 1
    assert api.closed.count(2) == 1


def test_fake_stamp_failure_and_child_close_failure_exposes_unverified_owner():
    api = FakeApi()

    def fail_child_stamp(handle):
        if handle == 2:
            raise WindowsFsRefusal("stamp_failed:synthetic")
        return api.stamps[handle]

    def fail_child_close(handle):
        if handle == 2:
            raise WindowsFsRefusal("close_failed:synthetic")
        api.closed.append(handle)

    api.stamp = fail_child_stamp
    api.close = fail_child_close
    with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
        WindowsHistoryFs(api).open_root(r"C:\project")
    assert api.closed.count(1) == 1
    assert len(caught.value.unverified_handles) == 1
    assert caught.value.unverified_handles[0].raw == 2
    api.close = FakeApi.close.__get__(api)
    caught.value.unverified_handles[0].close()
    assert api.closed.count(2) == 1


def test_fake_parent_and_child_close_failures_keep_both_unverified():
    api = FakeApi()

    def fail_both_closes(handle):
        raise WindowsFsRefusal(f"close_failed:{handle}")

    api.close = fail_both_closes
    with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
        WindowsHistoryFs(api).open_root(r"C:\project")
    assert {handle.raw for handle in caught.value.unverified_handles} == {1, 2}
    api.close = FakeApi.close.__get__(api)
    for handle in caught.value.unverified_handles:
        handle.close()
    assert sorted(api.closed) == [1, 2]


def test_fake_open_root_mount_refusal_and_close_failure_retains_root():
    api = FakeApi()
    original_guid = api.volume_guid
    lookups = 0

    def remap_before_mount_check(drive):
        nonlocal lookups
        lookups += 1
        if lookups == 2:
            api.guid = "\\\\?\\Volume{22222222-2222-2222-2222-222222222222}\\"
        return original_guid(drive)

    def fail_root_close(handle):
        if handle == 2:
            raise WindowsFsRefusal("close_failed:synthetic")
        api.closed.append(handle)

    api.volume_guid = remap_before_mount_check
    api.close = fail_root_close
    with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
        WindowsHistoryFs(api).open_root(r"C:\project")
    assert isinstance(caught.value.__cause__, WindowsFsRefusal)
    assert caught.value.__cause__.reason == "mount_changed"
    assert len(caught.value.unverified_handles) == 1
    root = caught.value.unverified_handles[0]
    assert root.raw == 2
    api.close = FakeApi.close.__get__(api)
    root.close()
    assert root.raw is None and api.closed.count(2) == 1


def test_fake_open_root_preserves_both_owners_when_rewalk_and_root_closes_fail():
    api = FakeApi()
    original_close = api.close

    def fail_project_close(handle):
        if handle == 2:
            raise WindowsFsRefusal("close_failed:synthetic")
        original_close(handle)

    api.close = fail_project_close
    with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
        WindowsHistoryFs(api).open_root(r"C:\project")
    assert len(caught.value.unverified_handles) == 2
    assert all(handle.raw == 2 for handle in caught.value.unverified_handles)
    assert caught.value.unverified_handles[0] is not caught.value.unverified_handles[1]
    api.close = original_close
    for handle in caught.value.unverified_handles:
        handle.close()
    assert api.closed.count(2) == 2


def test_fake_internal_mount_rewalk_close_failure_retains_temporary_handle():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with fs.open_root(r"C:\project") as root:
        original_close = api.close

        def fail_rewalk_close(handle):
            if handle == 2:
                raise WindowsFsRefusal("close_failed:synthetic")
            original_close(handle)

        api.close = fail_rewalk_close
        with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
            fs.verify_mount(root)
        assert caught.value.unverified_handles[0] is not root
        assert caught.value.unverified_handles[0].raw == 2
        api.close = original_close
        caught.value.unverified_handles[0].close()


def test_fake_open_child_stamp_and_close_failure_retains_child():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with fs.open_root(r"C:\project") as root:
        original_stamp, original_close = api.stamp, api.close

        def fail_stamp(handle):
            if handle == 3:
                raise WindowsFsRefusal("stamp_failed:synthetic")
            return original_stamp(handle)

        def fail_child_close(handle):
            if handle == 3:
                raise WindowsFsRefusal("close_failed:synthetic")
            original_close(handle)

        api.stamp, api.close = fail_stamp, fail_child_close
        with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
            fs.open_child(root, "note.txt", directory=False)
        assert caught.value.__cause__.reason == "stamp_failed:synthetic"
        assert caught.value.unverified_handles[0].raw == 3
        api.close = original_close
        caught.value.unverified_handles[0].close()


def test_fake_verify_name_and_context_close_failures_retain_owner_and_cause():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with (fs.open_root(r"C:\project") as root,
          fs.open_child(root, "note.txt", directory=False) as note):
        original_close = api.close

        def fail_note_close(handle):
            if handle == 3:
                raise WindowsFsRefusal("close_failed:synthetic")
            original_close(handle)

        api.close = fail_note_close
        with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
            fs.verify_name(root, "note.txt", note)
        assert caught.value.unverified_handles[0] is not note
        assert caught.value.unverified_handles[0].raw == 3
        api.close = original_close
        caught.value.unverified_handles[0].close()

        api.stamps[3] = _stamp(3, file=True, size=4)
        api.close = fail_note_close
        with pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught:
            fs.verify_name(root, "note.txt", note)
        assert caught.value.__cause__.reason == "name_changed"
        api.close = original_close
        caught.value.unverified_handles[0].close()
        api.stamps[3] = _stamp(3, file=True)

        api.close = fail_note_close
        with (pytest.raises(WindowsFsRefusal, match="handle_close_uncertain") as caught,
              fs.open_child(root, "note.txt", directory=False) as temporary):
            raise WindowsFsRefusal("body_failed:synthetic")
        assert caught.value.__cause__.reason == "body_failed:synthetic"
        assert caught.value.unverified_handles == (temporary,)
        api.close = original_close
        temporary.close()


@pytest.mark.parametrize("name,expected_bytes", [("plain", 10), ("é", 2),
                                                   ("😀", 4), ("A😀B", 8)])
def test_fake_counted_unicode_name_uses_full_utf16_bytes(name, expected_bytes):
    encoded, length, maximum = windows_fs._counted_name(name)
    assert encoded == name.encode("utf-16-le")
    assert (length, maximum) == (expected_bytes, expected_bytes + 2)
    if name == "A😀B":
        assert encoded[:len(name) * 2].decode("utf-16-le") == "A😀"


def test_fake_marshalled_unicode_structure_counts_exact_buffer_bytes():
    class Unicode(ctypes.Structure):
        _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort),
                    ("Buffer", ctypes.c_void_p)]

    name_fields = windows_fs._counted_name("A😀B")
    encoded, length, maximum = name_fields
    buffer = (ctypes.c_ubyte * maximum).from_buffer_copy(encoded + b"\0\0")
    counted = windows_fs._marshal_counted_name(name_fields, buffer, Unicode,
                                               ctypes.addressof(buffer))
    assert (counted.Length, counted.MaximumLength) == (8, 10)
    assert ctypes.string_at(counted.Buffer, counted.Length) == encoded
    assert counted.Length > len("A😀B") * 2
    wrong = (ctypes.c_ubyte * maximum).from_buffer_copy(b"x" * maximum)
    with pytest.raises(WindowsFsRefusal, match="name_encoding_unavailable"):
        windows_fs._marshal_counted_name(name_fields, wrong, Unicode,
                                         ctypes.addressof(wrong))


def test_fake_component_and_path_limits_use_utf16_units_and_refuse_surrogates():
    assert windows_fs._component("a" * 253 + "😀") == "a" * 253 + "😀"
    with pytest.raises(WindowsFsRefusal, match="invalid_name"):
        windows_fs._component("a" * 254 + "😀")
    with pytest.raises(WindowsFsRefusal, match="invalid_name"):
        windows_fs._component("😀" * 128)
    for name in ("\ud800", "\udc00", "x\ud800y"):
        with pytest.raises(WindowsFsRefusal, match="invalid_name"):
            windows_fs._component(name)
    overlong = "C:\\" + "\\".join(["😀" * 100] * 164)
    assert len(overlong) < 32760
    assert len(overlong.encode("utf-16-le")) // 2 > 32760
    with pytest.raises(WindowsFsRefusal, match="invalid_path"):
        windows_fs._path(overlong)
    with pytest.raises(WindowsFsRefusal, match="invalid_path"):
        windows_fs._path("C:\\\ud800")


def test_fake_invalid_unicode_refuses_before_any_native_api_call():
    api = FakeApi()
    fs = WindowsHistoryFs(api)
    with pytest.raises(WindowsFsRefusal, match="invalid_path"):
        fs.open_root("C:\\\ud800")
    assert api.calls == []
    with fs.open_root(r"C:\project") as root:
        before = len(api.calls)
        with pytest.raises(WindowsFsRefusal, match="invalid_name"):
            fs.open_child(root, "\ud800", directory=False)
        assert len(api.calls) == before


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows only")
def test_native_non_bmp_parent_and_distinct_prefix_siblings(tmp_path):
    parent = tmp_path / "P😀"
    parent.mkdir()
    (parent / "A😀").write_bytes(b"prefix")
    (parent / "A😀B").write_bytes(b"full")
    fs = WindowsHistoryFs()
    with fs.open_root(str(parent)) as root:
        with fs.open_child(root, "A😀", directory=False) as prefix:
            prefix_id = prefix.stamp.identity
            assert fs.read_exact_bounded(prefix, 6) == b"prefix"
        with fs.open_child(root, "A😀B", directory=False) as full:
            assert full.stamp.identity != prefix_id
            assert fs.read_exact_bounded(full, 4) == b"full"
            assert fs.verify_name(root, "A😀B", full).identity == full.stamp.identity
        fs.verify_mount(root)


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
