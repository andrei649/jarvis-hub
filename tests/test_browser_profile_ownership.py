"""Fresh profile ownership never adopts a sibling or replacement."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agents.core import browser_profile
from agents.core.browser_profile import (
    create_owned_profile,
    guard_owned_profile,
    profile_absent,
    profile_identity,
    remove_owned_profile,
    validated_owned_profile,
)


def test_owned_profile_removed_only_with_its_identity():
    path, identity = create_owned_profile()
    try:
        assert identity == profile_identity(path)
        assert validated_owned_profile(path, identity) == path
        (path / "cookie.txt").write_text("fresh fixture", encoding="utf-8")
        nested = path / "Default" / "Storage"
        nested.mkdir(parents=True)
        (nested / "state.txt").write_text("fresh fixture", encoding="utf-8")
        assert remove_owned_profile(path, identity)
        assert profile_absent(path, identity)
        assert remove_owned_profile(path, identity)
    finally:
        if path.exists():
            assert remove_owned_profile(path, identity)


def test_unrelated_and_replaced_profile_are_refused():
    path, identity = create_owned_profile()
    sibling, sibling_identity = create_owned_profile()
    try:
        assert validated_owned_profile(sibling, identity) is None
        assert not remove_owned_profile(sibling, identity)
        assert sibling.exists()
        path.rmdir()
        path.mkdir()
        assert validated_owned_profile(path, identity) is None
        assert not remove_owned_profile(path, identity)
        assert path.exists()
    finally:
        path.rmdir()
        assert remove_owned_profile(sibling, sibling_identity)


def test_identity_capture_failure_leaves_unclaimed_directory(monkeypatch):
    created = []
    original_create = browser_profile._create_windows if os.name == "nt" else None
    original_identity = browser_profile.profile_identity

    if original_create is not None:
        def capture_windows(path):
            original_create(path)
            created.append(path)

        monkeypatch.setattr(browser_profile, "_create_windows", capture_windows)
    else:
        original_mkdir = Path.mkdir

        def capture_posix(path, *args, **kwargs):
            original_mkdir(path, *args, **kwargs)
            created.append(path)

        monkeypatch.setattr(Path, "mkdir", capture_posix)

    def fail_identity(_path):
        raise OSError("synthetic identity failure")

    monkeypatch.setattr(browser_profile, "profile_identity", fail_identity)
    try:
        with pytest.raises(OSError, match="synthetic identity failure"):
            create_owned_profile()
        assert len(created) == 1 and created[0].is_dir()
    finally:
        monkeypatch.setattr(browser_profile, "profile_identity", original_identity)
        if created:
            identity = profile_identity(created[0])
            assert remove_owned_profile(created[0], identity)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction semantics")
def test_junction_replacement_is_refused(tmp_path: Path):
    path, identity = create_owned_profile()
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    path.rmdir()
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(target)],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        pytest.skip("junction creation unavailable")
    try:
        assert validated_owned_profile(path, identity) is None
        assert not remove_owned_profile(path, identity)
        assert sentinel.read_text(encoding="utf-8") == "keep"
    finally:
        path.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle sharing semantics")
def test_guard_pins_profile_until_recovery_finishes():
    path, identity = create_owned_profile()
    moved = path.with_name(path.name + "-moved")
    try:
        with guard_owned_profile(path, identity) as held:
            assert held == path
            with pytest.raises(OSError):
                path.rename(moved)
        assert remove_owned_profile(path, identity)
    finally:
        if moved.exists():
            moved.rmdir()
        if path.exists():
            assert remove_owned_profile(path, identity)
