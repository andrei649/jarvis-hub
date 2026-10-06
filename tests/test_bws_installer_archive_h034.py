"""The pinned helper installer rejects unsafe ZIP entries before replacing a binary."""

import hashlib
import io
import platform
import sys
import zipfile

import pytest

from agents.core.security.secret_sources import install


def test_pinned_installer_rejects_unsafe_extra_member_without_replacing_binary(tmp_path, monkeypatch):
    target = (sys.platform, platform.machine().lower())
    if target not in install._PINNED:
        pytest.skip("no pinned helper for this platform")
    destination = tmp_path / ("bws.exe" if sys.platform == "win32" else "bws")
    destination.write_bytes(b"previous helper")
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as zipped:
        zipped.writestr("../escaped.txt", b"unsafe")
        zipped.writestr("release/" + destination.name, b"replacement helper")
    payload = archive_buffer.getvalue()
    filename = install._PINNED[target][0]
    monkeypatch.setitem(install._PINNED, target, (filename, hashlib.sha256(payload).hexdigest()))
    monkeypatch.setattr(install.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))

    with pytest.raises(RuntimeError, match="invalid"):
        install.install_bws(destination=destination)

    assert destination.read_bytes() == b"previous helper"
    assert not (tmp_path / "escaped.txt").exists()
