"""Native NTFS ACL checks for the shared JSON writer and CoreMemory drift copy."""

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from agents.core.cognition.memory import CoreMemory
from agents.core.persistence import atomic_write_json
from tests.private_file_permissions import assert_private_file

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ACL regression")


def test_new_and_replaced_json_are_private_before_and_after_writing(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    original = Path.write_text
    def checked_write(path, text, *args, **kwargs):
        with pytest.raises(OSError):
            os.rename(path, path.with_name("stolen.json"))
        with pytest.raises(OSError):
            path.unlink()
        result = original(path, text, *args, **kwargs)
        return result
    monkeypatch.setattr(Path, "write_text", checked_write)

    atomic_write_json(target, {"x": 1})
    assert_private_file(target)
    atomic_write_json(target, {"x": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 2}
    assert_private_file(target)
    assert not list(tmp_path.glob(".state.*.json"))


def test_replacement_removes_legacy_inherited_acl_in_permissive_parent(tmp_path):
    parent = tmp_path / "permissive"
    parent.mkdir()
    subprocess.run(["icacls", str(parent), "/grant", "*S-1-5-32-545:(OI)(CI)(M)"],
                   check=True, capture_output=True)
    target = parent / "legacy.json"
    target.write_text("old", encoding="utf-8")
    with pytest.raises((AssertionError, OSError)):
        assert_private_file(target)
    atomic_write_json(target, {"private": True})
    assert_private_file(target)
    assert json.loads(target.read_text(encoding="utf-8")) == {"private": True}


def test_failed_write_preserves_previous_bytes_and_cleans_scratch(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"good": 1})
    before = target.read_bytes()
    original = Path.write_text
    def interrupted(path, text, *args, **kwargs):
        original(path, text[:4], *args, **kwargs)
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(Path, "write_text", interrupted)
    with pytest.raises(OSError, match="synthetic disk failure"):
        atomic_write_json(target, {"bad": 2})
    assert target.read_bytes() == before
    assert_private_file(target)
    assert not list(tmp_path.glob(".state.*.json"))


def test_concurrent_writers_use_distinct_private_scratch(tmp_path, monkeypatch):
    from agents.core.persistence import private_file

    target = tmp_path / "state.json"
    barrier = Barrier(2)
    original = Path.write_text
    replace = os.replace
    calls = 0

    def overlap(path, text, *args, **kwargs):
        barrier.wait(timeout=5)
        return original(path, text, *args, **kwargs)

    def transient_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            error = PermissionError("synthetic Windows sharing conflict")
            error.winerror = 5
            raise error
        return replace(source, destination)

    monkeypatch.setattr(Path, "write_text", overlap)
    monkeypatch.setattr(private_file.os, "replace", transient_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(atomic_write_json, target, {"writer": i}) for i in (1, 2)]
        for result in results:
            result.result(timeout=10)
    assert json.loads(target.read_text(encoding="utf-8")) in ({"writer": 1}, {"writer": 2})
    assert calls >= 3
    assert_private_file(target)
    assert not list(tmp_path.glob(".state.*.json"))


def test_drift_backup_is_private_and_never_overwritten(tmp_path):
    memory = CoreMemory(path=tmp_path / "user_core.json")
    data = b'{"facts":["synthetic manual edit"]}'
    digest = hashlib.sha256(data).hexdigest()
    bak = memory._keep_copy(data, digest)
    assert_private_file(bak)
    assert bak.read_bytes() == data
    assert memory._keep_copy(b"different", digest) == bak
    assert bak.read_bytes() == data


def test_acl_refusal_happens_before_payload_write(tmp_path, monkeypatch):
    from agents.core.persistence import private_file
    target = tmp_path / "state.json"
    atomic_write_json(target, {"good": 1})
    before = target.read_bytes()
    def refuse(_info):
        raise OSError("unsupported ACL")
    monkeypatch.setattr(private_file, "_verify_windows_acl", refuse)
    with pytest.raises(OSError, match="unsupported ACL"):
        atomic_write_json(target, {"secret": 2})
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".state.*.json"))
