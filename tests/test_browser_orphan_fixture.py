"""Failure-path ownership checks for the Linux-only test supervisor."""
from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import psutil
import pytest

from agents.core.browser_session import BrowserOwnershipJournal
from tests.browser_orphan_fixture import supervised_orphan

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(sys.platform != 'linux', reason='Linux test supervisor')]


def _fixture(tmp_path, *, exit_early=False):
    profile = Path(tempfile.mkdtemp(prefix='nerva-browser-orphan-'))
    journal = BrowserOwnershipJournal(tmp_path / 'journal')
    pid_file = tmp_path / 'native.pid'
    program = tmp_path / 'browser'
    program.write_text(f'#!{sys.executable}\n' + (
        "raise SystemExit('forced pre-ready exit')\n" if exit_early else
        'import os, subprocess, sys, time\n'
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
        f'open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
        'time.sleep(60)\n'))
    program.chmod(0o700)
    return str(program), journal, 'c' * 32, profile, tmp_path / 'launch', pid_file


async def _started(pid_file):
    deadline = asyncio.get_running_loop().time() + 10
    while not pid_file.exists():
        assert asyncio.get_running_loop().time() < deadline, 'owned child never started'
        await asyncio.sleep(.01)


def _closed(journal, sid, profile, work):
    receipt = json.loads((work / 'cleanup.json').read_text())
    assert receipt['survivors'] == []
    for pid, started in receipt['owned']:
        with contextlib.suppress(psutil.NoSuchProcess):
            assert psutil.Process(pid).create_time() != started
    assert not profile.exists()
    assert not journal._file(sid).exists()


async def test_pre_ready_exit_reports_failure_and_cleans_profile(tmp_path):
    chrome, journal, sid, profile, work, _ = _fixture(tmp_path, exit_early=True)
    with pytest.raises(AssertionError, match='controller failed'):
        async with supervised_orphan(chrome, journal, sid, profile, work):
            pytest.fail('pre-ready exit published a native record')
    _closed(journal, sid, profile, work)
    failure = json.loads((work / 'failure.json').read_text())
    assert 'forced pre-ready exit' in failure['chrome.stderr']
    assert not (work / 'record.json').exists()


async def test_outer_timeout_cleans_descendants_and_preserves_unrelated_process(tmp_path):
    chrome, journal, sid, profile, work, pid_file = _fixture(tmp_path)
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])

    async def launch():
        async with supervised_orphan(chrome, journal, sid, profile, work):
            pytest.fail('non-browser published a native record')

    task = asyncio.create_task(launch())
    try:
        await _started(pid_file)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, .01)
        _closed(journal, sid, profile, work)
        assert sentinel.poll() is None
        assert not (work / 'record.json').exists()
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        sentinel.kill()
        sentinel.wait(timeout=5)


async def test_parent_eof_during_startup_cleans_adopted_descendants(tmp_path):
    chrome, journal, sid, profile, work, pid_file = _fixture(tmp_path)
    work.mkdir()
    process = subprocess.Popen([sys.executable, '-m', 'tests.browser_orphan_fixture', '--supervisor',
        chrome, str(journal.root), sid, str(profile), str(work)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        await _started(pid_file)
    finally:
        process.stdin.close()
        await asyncio.to_thread(process.wait, 10)
        stderr = process.stderr.read()
        process.stdout.close()
        process.stderr.close()
    assert process.returncode == 0, stderr
    _closed(journal, sid, profile, work)


async def test_supervisor_launch_failure_cleans_empty_profile(tmp_path, monkeypatch):
    chrome, journal, sid, profile, work, _ = _fixture(tmp_path)

    def fail(*_args, **_kwargs):
        raise OSError('forced supervisor launch failure')

    monkeypatch.setattr(subprocess, 'Popen', fail)
    with pytest.raises(OSError, match='forced supervisor launch failure'):
        async with supervised_orphan(chrome, journal, sid, profile, work):
            pytest.fail('failed supervisor yielded')
    assert not profile.exists()
    assert not journal._file(sid).exists()
