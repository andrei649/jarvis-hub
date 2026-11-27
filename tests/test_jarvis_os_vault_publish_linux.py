"""Linux-only atomic vault publication regressions over a synthetic vault."""

import errno
import os
import sys

import pytest

from tests.test_jarvis_os_vault_fs import tree, vault_fs  # noqa: F401

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux renameat2 publication")


def test_publish_is_exclusive_without_a_hard_link_reader_window(tree, monkeypatch):
    """Observe the exact old link step, when a normal read rejected nlink=2."""
    vault, _outside = tree
    with vault_fs.VaultFs(vault) as fs:
        inbox = fs.open_dir(("08 Inbox",), create=True)
        try:
            original_link = os.link
            observed = []

            def observe_link(source, destination, **kwargs):
                result = original_link(source, destination, **kwargs)
                try:
                    fs.read_in(inbox, "Published.md", 4096)
                except vault_fs.UnsafePath as exc:
                    observed.append(str(exc))
                return result

            monkeypatch.setattr(os, "link", observe_link)
            fs.publish_in(inbox, "Published.md", b"complete synthetic note")
            entry, data = fs.read_in(inbox, "Published.md", 4096)
            assert entry.links == 1 and data == b"complete synthetic note"
            assert observed == []  # no publication step ever exposes nlink=2
            with pytest.raises(FileExistsError):
                fs.publish_in(inbox, "Published.md", b"replacement forbidden")
            assert fs.read_in(inbox, "Published.md", 4096)[1] == data
        finally:
            fs.close_dir(inbox)


@pytest.mark.parametrize("unsupported", ["missing", errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL])
def test_publish_unsupported_rename_falls_back_exclusively(tree, monkeypatch, unsupported):
    import ctypes

    vault, _outside = tree

    def unavailable(*_args):
        ctypes.set_errno(unsupported)
        return -1

    class NoSymbol:
        pass

    class Unsupported:
        renameat2 = staticmethod(unavailable)

    monkeypatch.setattr(ctypes, "CDLL", lambda *_args, **_kwargs: (
        NoSymbol() if unsupported == "missing" else Unsupported()))
    with vault_fs.VaultFs(vault) as fs:
        inbox = fs.open_dir(("08 Inbox",), create=True)
        try:
            fs.publish_in(inbox, "Published.md", b"first")
            with pytest.raises(FileExistsError):
                fs.publish_in(inbox, "Published.md", b"second")
            assert fs.read_in(inbox, "Published.md", 100)[1] == b"first"
            assert fs._api.list_names(inbox) == ["Published.md"]
        finally:
            fs.close_dir(inbox)


@pytest.mark.parametrize("error", [errno.EEXIST, errno.EACCES])
def test_publish_does_not_mask_rename_collision_or_permission(tree, monkeypatch, error):
    import ctypes

    vault, _outside = tree

    def refused(*_args):
        ctypes.set_errno(error)
        return -1

    class Refused:
        renameat2 = staticmethod(refused)

    monkeypatch.setattr(ctypes, "CDLL", lambda *_args, **_kwargs: Refused())
    with vault_fs.VaultFs(vault) as fs:
        inbox = fs.open_dir(("08 Inbox",), create=True)
        try:
            with pytest.raises(OSError) as exc:
                fs.publish_in(inbox, "Published.md", b"first")
            assert exc.value.errno == error
            assert fs._api.list_names(inbox) == []
        finally:
            fs.close_dir(inbox)
