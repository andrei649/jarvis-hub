import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import agents.core.extensions.store_lock as store_lock
from agents.core.extensions.store_lock import StoreLockError, locked_store


def _thread_critical(path, active, peak, start):
    start.wait(3)
    with locked_store(path):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        time.sleep(0.04)
        active[0] -= 1


def test_threads_share_one_critical_section_per_path(tmp_path):
    path = tmp_path / "catalog.json"
    active, peak = [0], [0]
    start = __import__("threading").Event()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_thread_critical, path, active, peak, start) for _ in range(4)]
        start.set()
        for future in futures:
            future.result(timeout=5)
    assert peak == [1]


def _process_critical(path, active, peak, start):
    start.wait(5)
    with locked_store(path):
        with active.get_lock():
            active.value += 1
            peak.value = max(peak.value, active.value)
        time.sleep(0.1)
        with active.get_lock():
            active.value -= 1


def test_processes_share_one_critical_section_per_path(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    path = tmp_path / "catalog.json"
    active, peak, start = ctx.Value("i", 0), ctx.Value("i", 0), ctx.Event()
    children = [ctx.Process(target=_process_critical, args=(path, active, peak, start)) for _ in range(3)]
    try:
        for child in children:
            child.start()
        start.set()
        for child in children:
            child.join(15)
        assert [child.exitcode for child in children] == [0, 0, 0]
        assert peak.value == 1
    finally:
        start.set()
        for child in children:
            if child.pid is not None and child.is_alive():
                child.terminate()
        for child in children:
            if child.pid is not None:
                child.join(5)


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock acquisition failure")
def test_os_lock_acquisition_failure_closes_open_descriptor(tmp_path, monkeypatch):
    import fcntl

    opened, closed = [], []
    real_open, real_close = os.open, os.close

    def track_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def track_close(fd):
        closed.append(fd)
        return real_close(fd)

    def fail_lock(*args, **kwargs):
        raise OSError("injected lock failure")

    monkeypatch.setattr(store_lock.os, "open", track_open)
    monkeypatch.setattr(store_lock.os, "close", track_close)
    monkeypatch.setattr(fcntl, "flock", fail_lock)
    with pytest.raises(StoreLockError) as raised, locked_store(tmp_path / "catalog.json"):
        pytest.fail("lock should not have been acquired")
    assert raised.value.reason == "extension_store_lock_unavailable"
    assert opened and opened[-1] in closed
    with pytest.raises(OSError):
        os.fstat(opened[-1])


def test_lock_symlink_swap_is_detected_without_nofollow(tmp_path, monkeypatch):
    target = tmp_path / "catalog.json"
    victim = tmp_path / "victim-lock"
    victim.write_text("keep")
    lock_path = tmp_path / "catalog.json.lock"
    real_open = os.open
    swapped = False

    def race_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == lock_path and not swapped:
            swapped = True
            lock_path.symlink_to(victim)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(store_lock.os, "O_NOFOLLOW", 0, raising=False)
    monkeypatch.setattr(store_lock.os, "open", race_open)
    with pytest.raises(StoreLockError), locked_store(target):
        pytest.fail("symlink lock must be rejected")
    assert lock_path.is_symlink()
    assert victim.read_text() == "keep"


def test_existing_lock_symlink_is_rejected(tmp_path):
    target = tmp_path / "catalog.json"
    victim = tmp_path / "victim-lock"
    victim.write_text("keep")
    lock_path = tmp_path / "catalog.json.lock"
    try:
        lock_path.symlink_to(victim)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(StoreLockError), locked_store(target):
        pytest.fail("symlink lock must be rejected")
    assert victim.read_text() == "keep"


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock path-swap injection")
def test_lock_path_swap_while_waiting_is_detected_after_acquire(tmp_path, monkeypatch):
    import fcntl

    target = tmp_path / "catalog.json"
    victim = tmp_path / "victim-lock"
    victim.write_text("keep")
    lock_path = tmp_path / "catalog.json.lock"
    opened, closed = [], []
    real_open, real_close, real_flock = os.open, os.close, fcntl.flock

    def track_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def track_close(fd):
        closed.append(fd)
        return real_close(fd)

    def swap_after_lock(fd, operation):
        result = real_flock(fd, operation)
        if operation == fcntl.LOCK_EX:
            lock_path.unlink()
            lock_path.symlink_to(victim)
        return result

    monkeypatch.setattr(store_lock.os, "open", track_open)
    monkeypatch.setattr(store_lock.os, "close", track_close)
    monkeypatch.setattr(fcntl, "flock", swap_after_lock)
    with pytest.raises(StoreLockError), locked_store(target):
        pytest.fail("path changed while waiting; lock must not be admitted")
    assert lock_path.is_symlink()
    assert victim.read_text() == "keep"
    assert opened[-1] in closed
    with pytest.raises(OSError):
        os.fstat(opened[-1])
