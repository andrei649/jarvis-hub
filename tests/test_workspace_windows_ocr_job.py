"""Controller proofs for the gated Windows OCR Job path; Mac fakes are not kernel proof."""
import asyncio
import json
import os
import shutil
import sys
import threading
import time
from io import BytesIO

import pytest


def test_job_spawn_sets_limits_and_atomic_ownership_before_resume():
    from agents.core.workspace.win_job_process import OwnedJobProcess

    class FakeKernel:
        def __init__(self):
            self.events = []

        def create_job(self):
            self.events.append('job')
            return 'job'

        def set_limits(self, job, memory_limit):
            self.events.append(('limits', job, memory_limit))

        def create_stdio(self):
            self.events.append('stdio')
            return ('parent-in', 'child-in', 'parent-out', 'child-out', 'child-err')

        def mark_inheritance(self, child_handles, parent_handles, job):
            self.events.append(('inherit', child_handles, parent_handles, job))

        def create_process(self, command, cwd, env, *, job, stdio, inherit_handles,
                           suspended, breakaway):
            self.events.append(('create', job, stdio, inherit_handles, suspended, breakaway))
            return 'process', 'thread'

        def is_process_in_job(self, process, job):
            self.events.append(('owned', process, job))
            return True

        def resume_thread(self, thread):
            self.events.append(('resume', thread))

        def close_handle(self, handle):
            self.events.append(('close', handle))

    api = FakeKernel()
    owner = OwnedJobProcess.spawn(['worker'], cwd='C:\\scratch', env={},
                                  memory_limit=512 * 1024 * 1024, api=api)
    assert owner.job == 'job' and owner.process_handle == 'process'
    assert api.events[:6] == [
        'job', ('limits', 'job', 512 * 1024 * 1024), 'stdio',
        ('inherit', ('child-in', 'child-out', 'child-err'),
         ('parent-in', 'parent-out'), 'job'),
        ('create', 'job', ('child-in', 'child-out', 'child-err'),
         ('child-in', 'child-out', 'child-err'), True, False),
        ('owned', 'process', 'job'),
    ]
    assert api.events[6] == ('resume', 'thread')


def test_unsupported_atomic_attribute_refuses_without_resuming_or_leaking_handles():
    from agents.core.workspace.win_job_process import OwnedJobProcess

    class NoAttribute:
        def __init__(self):
            self.events = []

        def create_job(self):
            return 'job'

        def set_limits(self, job, ceiling):
            self.events.append('limits')

        def create_stdio(self):
            return ('pi', 'ci', 'po', 'co', 'ce')

        def mark_inheritance(self, child, parent, job):
            self.events.append(('inherit', child, parent, job))

        def create_process(self, *_args, **_kwargs):
            self.events.append('atomic-attribute-unavailable')
            raise OSError('PROC_THREAD_ATTRIBUTE_JOB_LIST unavailable')

        def close_handle(self, handle):
            self.events.append(('close', handle))

    api = NoAttribute()
    with pytest.raises(OSError, match='JOB_LIST unavailable'):
        OwnedJobProcess.spawn(['worker'], cwd='C:\\scratch', env={},
                              memory_limit=512, api=api)
    assert api.events[:2] == ['limits', ('inherit', ('ci', 'co', 'ce'), ('pi', 'po'), 'job')]
    assert {event[1] for event in api.events if isinstance(event, tuple) and event[0] == 'close'} == {
        'pi', 'ci', 'po', 'co', 'ce', 'job'}


def test_partial_stdio_close_does_not_close_reused_foreign_handle():
    from agents.core.workspace.win_job_process import OwnedJobProcess

    class ReuseAfterClose:
        def __init__(self):
            self.closed = []
            self.co_failed = False

        def create_job(self):
            return 'job'

        def set_limits(self, *_args):
            pass

        def create_stdio(self):
            return ('pi', 'ci', 'po', 'co', 'ce')

        def mark_inheritance(self, *_args):
            pass

        def create_process(self, *_args, **_kwargs):
            return 'process', 'thread'

        def is_process_in_job(self, *_args):
            return True

        def resume_thread(self, *_args):
            pass

        def terminate_job(self, *_args):
            pass

        def wait_process(self, *_args):
            return True

        def active_processes(self, *_args):
            return 0

        def close_handle(self, handle):
            if handle == 'ci' and 'ci' in self.closed:
                raise AssertionError('unrelated handle reused ci value was closed')
            if handle == 'co' and not self.co_failed:
                self.co_failed = True
                raise OSError('synthetic partial child close failure')
            self.closed.append(handle)

    api = ReuseAfterClose()
    with pytest.raises(OSError, match='partial child close failure'):
        OwnedJobProcess.spawn(['worker'], cwd='C:\\scratch', env={},
                              memory_limit=512, api=api)
    assert api.closed.count('ci') == 1
    assert set(api.closed) == {'ci', 'co', 'ce', 'pi', 'po', 'process', 'thread', 'job'}


class _PersistentCloseFailure:
    def __init__(self, *, failed_handle):
        self.failed_handle = failed_handle
        self.closed = []
        self.co_attempts = 0

    def create_job(self):
        return 'job'

    def set_limits(self, *_args):
        pass

    def create_stdio(self):
        return ('pi', 'ci', 'po', 'co', 'ce')

    def mark_inheritance(self, *_args):
        pass

    def create_process(self, *_args, **_kwargs):
        return 'process', 'thread'

    def is_process_in_job(self, *_args):
        return True

    def resume_thread(self, *_args):
        pass

    def terminate_job(self, *_args):
        pass

    def wait_process(self, *_args):
        return True

    def active_processes(self, *_args):
        return 0

    def close_handle(self, handle):
        if handle == 'ci' and handle in self.closed:
            raise AssertionError('released ci value closed twice')
        if handle == 'co':
            self.co_attempts += 1
            if self.failed_handle == 'co' or self.co_attempts == 1:
                raise OSError('synthetic child close failure')
        if handle == self.failed_handle:
            raise OSError('persistent close failure')
        self.closed.append(handle)


@pytest.mark.parametrize(('failed_handle', 'retained'), [
    ('co', ('co',)), ('thread', ()),
])
def test_persistent_launch_close_failure_retains_only_uncertain_handles(
        failed_handle, retained):
    from agents.core.workspace.win_job_process import (
        _UNVERIFIED_OWNERS,
        JobCleanupUnverified,
        OwnedJobProcess,
    )

    api = _PersistentCloseFailure(failed_handle=failed_handle)
    before = len(_UNVERIFIED_OWNERS)
    try:
        with pytest.raises(JobCleanupUnverified):
            OwnedJobProcess.spawn(['worker'], cwd='C:\\scratch', env={},
                                  memory_limit=512, api=api)
        assert len(_UNVERIFIED_OWNERS) == before + 1
        saved_api, saved_job, saved_process, saved_thread, saved_stdio = _UNVERIFIED_OWNERS[-1]
        assert saved_api is api
        assert (saved_job, saved_process, saved_thread, saved_stdio) == (
            None, None, 'thread' if failed_handle == 'thread' else None, retained)
        assert api.closed.count('ci') == 1
        assert set(api.closed) == ({'ci', 'co', 'ce', 'pi', 'po', 'process', 'thread', 'job'}
                                   - {failed_handle})
    finally:
        del _UNVERIFIED_OWNERS[before:]


@pytest.mark.asyncio
async def test_termination_waits_for_grandchild_after_leader_exit():
    from agents.core.workspace.win_job_process import OwnedJobProcess

    class LateGrandchild:
        def __init__(self):
            self.events = []
            self.active = [2, 1, 0]

        def terminate_job(self, job):
            self.events.append('terminate')

        def active_processes(self, job):
            self.events.append('active')
            return self.active.pop(0)

        def wait_process(self, process, milliseconds):
            self.events.append('leader-reaped')
            return True

        def close_handle(self, handle):
            self.events.append(('close', handle))

    api = LateGrandchild()
    owner = OwnedJobProcess(api, 'job', 'process', 'thread', 'parent-in', 'parent-out')
    await owner.terminate_and_drain()
    assert owner.drained and api.events.count('active') == 3
    assert api.events[0] == 'terminate'
    assert api.events.index(('close', 'job')) > api.events.index('active')


class FakeOwner:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.read_block = asyncio.Event()
        self.cleanup_started = asyncio.Event()
        self.cleanup_release = asyncio.Event()
        self.cleanup_release.set()
        self.cleaned = False

    async def start_io(self):
        pass

    async def send(self, data):
        self.data = data

    async def read_line(self, buffer):
        if self.frames:
            return self.frames.pop(0)
        await self.read_block.wait()
        return None

    async def terminate_and_drain(self):
        self.cleanup_started.set()
        await self.cleanup_release.wait()
        self.cleaned = True


def _frame(**fields):
    return json.dumps(fields).encode()


@pytest.mark.asyncio
async def test_fake_controller_accepts_complete_pages_and_job_commit_only_after_drain(monkeypatch):
    from agents.core.workspace import extract_process

    owner = FakeOwner([
        _frame(event='page_start', page=1, page_count=1, deadline=time.monotonic() + 2),
        _frame(event='page_done', page=1, page_count=1),
        _frame(event='result', payload={'segments': [[1, 'generated OCR text']],
                                        'page_count': 1, 'limits': ['wall_time', 'job_commit', 'ocr']}),
    ])
    scratch = {}

    def spawn(kind, seconds, env, *, api):
        scratch['path'] = env['TMPDIR']
        assert kind == 'pdf' and seconds > 0 and os.path.isdir(env['TMPDIR'])
        return owner

    monkeypatch.setattr(extract_process, '_spawn_windows_owned', spawn)
    result = await extract_process._extract_windows_ocr(b'generated-pdf', 'pdf', timeout=3,
                                                        api=object())
    assert result.segments[0].text == 'generated OCR text'
    assert result.limits == ('wall_time', 'job_commit', 'ocr')
    assert owner.data == b'generated-pdf' and owner.cleaned
    assert not os.path.exists(scratch['path'])


@pytest.mark.asyncio
async def test_fake_page_clock_kills_native_hang_and_releases_after_drain(monkeypatch):
    from agents.core.workspace import extract, extract_process

    owner = FakeOwner([
        _frame(event='page_start', page=1, page_count=1, deadline=time.monotonic() + 0.03),
    ])
    monkeypatch.setattr(extract_process, '_spawn_windows_owned',
                        lambda *_args, **_kwargs: owner)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract_process._extract_windows_ocr(b'pdf', 'pdf', timeout=2, api=object())
    assert caught.value.code == 'timeout' and caught.value.page_count == 1
    assert owner.cleaned


@pytest.mark.asyncio
@pytest.mark.parametrize(('raw_deadline', 'expected_code'), [
    ('later', 'timeout'), (float('nan'), 'invalid_file'),
    (float('inf'), 'invalid_file'), ('bad', 'invalid_file'),
])
async def test_parent_page_bound_rejects_delayed_or_nonfinite_child_frame(
        monkeypatch, raw_deadline, expected_code):
    from agents.core.workspace import extract, extract_process

    monkeypatch.setattr(extract, 'OCR_PAGE_TIMEOUT_SECONDS', 0.03)
    deadline = time.monotonic() + 1 if raw_deadline == 'later' else raw_deadline
    owner = FakeOwner([_frame(event='page_start', page=1, page_count=1,
                              deadline=deadline)])
    monkeypatch.setattr(extract_process, '_spawn_windows_owned',
                        lambda *_args, **_kwargs: owner)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract_process._extract_windows_ocr(b'pdf', 'pdf', timeout=0.3,
                                                   api=object())
    assert caught.value.code == expected_code and owner.cleaned
    if expected_code == 'timeout':
        assert 'OCR page deadline' in str(caught.value)


@pytest.mark.asyncio
async def test_safe_unsupported_launch_releases_slot_and_scratch(monkeypatch):
    from agents.core.workspace import extract, extract_process

    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(extract_process, '_SLOTS', slots)
    scratch = {}

    def unsupported(kind, seconds, env, *, api):
        scratch['path'] = env['TMPDIR']
        raise OSError('atomic attribute unsupported before process creation')

    monkeypatch.setattr(extract_process, '_spawn_windows_owned', unsupported)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract_process._extract_windows_ocr(b'pdf', 'pdf', timeout=2, api=object())
    assert caught.value.code == 'invalid_file'
    assert not os.path.exists(scratch['path']) and slots.acquire(blocking=False)
    slots.release()


@pytest.mark.asyncio
async def test_scratch_failure_before_job_launch_recovers_slot(monkeypatch):
    from agents.core.workspace import extract, extract_process

    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(extract_process, '_SLOTS', slots)

    def no_scratch(**_kwargs):
        raise OSError('scratch unavailable')

    monkeypatch.setattr(extract_process.tempfile, 'mkdtemp', no_scratch)
    monkeypatch.setattr(extract_process, '_spawn_windows_owned',
                        lambda *_args, **_kwargs: pytest.fail('Job launch after scratch failure'))
    with pytest.raises(extract.ExtractionError) as caught:
        await extract_process._extract_windows_ocr(b'pdf', 'pdf', timeout=1, api=object())
    assert caught.value.code == 'invalid_file'
    assert slots.acquire(blocking=False)
    slots.release()


@pytest.mark.asyncio
async def test_controller_retains_slot_and_scratch_for_uncertain_launch_handle(monkeypatch):
    from agents.core.workspace import extract, extract_process
    from agents.core.workspace.win_job_process import _UNVERIFIED_OWNERS

    api = _PersistentCloseFailure(failed_handle='co')
    slots = threading.BoundedSemaphore(1)
    scratch = {}
    before = len(_UNVERIFIED_OWNERS)
    real_spawn = extract_process._spawn_windows_owned
    monkeypatch.setattr(extract_process, '_SLOTS', slots)

    def capture(kind, seconds, env, *, api):
        scratch['path'] = env['TMPDIR']
        return real_spawn(kind, seconds, env, api=api)

    monkeypatch.setattr(extract_process, '_spawn_windows_owned', capture)
    try:
        with pytest.raises(extract.ExtractionError) as caught:
            await extract_process._extract_windows_ocr(b'pdf', 'pdf', timeout=1, api=api)
        assert caught.value.code == 'invalid_file'
        assert os.path.isdir(scratch['path']) and not slots.acquire(blocking=False)
        assert len(_UNVERIFIED_OWNERS) == before + 1
        assert _UNVERIFIED_OWNERS[-1][-1] == ('co',)
    finally:
        if 'path' in scratch and os.path.isdir(scratch['path']):
            shutil.rmtree(scratch['path'])
        slots.acquire(blocking=False)
        slots.release()
        del _UNVERIFIED_OWNERS[before:]


@pytest.mark.asyncio
async def test_unverified_active_job_retains_slot_and_scratch(monkeypatch):
    from agents.core.workspace import extract, extract_process
    from agents.core.workspace.win_job_process import JobCleanupUnverified

    class Undrained(FakeOwner):
        async def terminate_and_drain(self):
            raise JobCleanupUnverified('ActiveProcesses still nonzero')

    owner = Undrained()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(extract_process, '_SLOTS', slots)
    scratch = {}

    def spawn(kind, seconds, env, *, api):
        scratch['path'] = env['TMPDIR']
        return owner

    monkeypatch.setattr(extract_process, '_spawn_windows_owned', spawn)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract_process._extract_windows_ocr(b'pdf', 'pdf', timeout=0.04, api=object())
    assert caught.value.code == 'invalid_file'
    assert os.path.isdir(scratch['path']) and not slots.acquire(blocking=False)
    # The fake has no process. Reclaim only this test's synthetic resources.
    shutil.rmtree(scratch['path'])
    slots.release()


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_release_slot_or_scratch_early(monkeypatch):
    from agents.core.workspace import extract_process

    owner = FakeOwner()
    owner.cleanup_release.clear()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(extract_process, '_SLOTS', slots)
    scratch = {}

    def spawn(kind, seconds, env, *, api):
        scratch['path'] = env['TMPDIR']
        return owner

    monkeypatch.setattr(extract_process, '_spawn_windows_owned', spawn)
    task = asyncio.create_task(extract_process._extract_windows_ocr(
        b'pdf', 'pdf', timeout=3, api=object()))
    for _ in range(100):
        if 'path' in scratch:
            break
        await asyncio.sleep(0.001)
    assert 'path' in scratch
    task.cancel()
    await asyncio.wait_for(owner.cleanup_started.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and os.path.isdir(scratch['path'])
    assert not slots.acquire(blocking=False)
    owner.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert owner.cleaned and not os.path.exists(scratch['path'])
    assert slots.acquire(blocking=False)
    slots.release()


@pytest.mark.asyncio
async def test_cancel_during_launch_waits_for_late_job_owner_before_release(monkeypatch):
    from agents.core.workspace import extract_process

    owner = FakeOwner()
    started = threading.Event()
    allow_launch = threading.Event()
    slots = threading.BoundedSemaphore(1)
    scratch = {}
    monkeypatch.setattr(extract_process, '_SLOTS', slots)

    def spawn(kind, seconds, env, *, api):
        scratch['path'] = env['TMPDIR']
        started.set()
        assert allow_launch.wait(2)
        return owner

    monkeypatch.setattr(extract_process, '_spawn_windows_owned', spawn)
    task = asyncio.create_task(extract_process._extract_windows_ocr(
        b'pdf', 'pdf', timeout=3, api=object()))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and os.path.isdir(scratch['path'])
    assert not slots.acquire(blocking=False)
    allow_launch.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert owner.cleaned and not os.path.exists(scratch['path'])
    assert slots.acquire(blocking=False)
    slots.release()


@pytest.mark.asyncio
async def test_malformed_and_oversize_frames_refuse_before_success(monkeypatch):
    from agents.core.workspace import extract, extract_process, win_job_process

    monkeypatch.setattr(win_job_process, '_MAX_FRAME', 8)

    class ByteReader:
        async def read(self, size):
            return b'oversized-frame'

    owner = win_job_process.OwnedJobProcess(object(), 'job', 'proc', 'thread', None, None)
    owner.reader = ByteReader()
    with pytest.raises(OSError, match='output budget'):
        await owner.read_line(bytearray())

    malformed = FakeOwner([b'{bad-json'])
    monkeypatch.setattr(extract_process, '_spawn_windows_owned',
                        lambda *_args, **_kwargs: malformed)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract_process._extract_windows_ocr(b'pdf', 'pdf', timeout=2, api=object())
    assert caught.value.code == 'invalid_file' and malformed.cleaned


def test_windows_child_scope_requires_real_job_claim_and_sync_stays_inert(monkeypatch):
    from agents.core.workspace import extract, win_job_process
    from tests.fixtures.workspace import samples

    monkeypatch.setattr(extract.sys, 'platform', 'win32')
    monkeypatch.setattr(win_job_process.sys, 'platform', 'win32')
    monkeypatch.setenv('NERVA_WORKSPACE_OCR', '1')
    monkeypatch.setenv('NERVA_WORKSPACE_KILLABLE_EXTRACTION', '1')
    monkeypatch.setattr(extract, '_ocr_engine', lambda: lambda *_: 'generated page text')
    assert extract._ocr_pdf(b'pdf', 1, extract._Guard(1, 100),
                            progress=lambda *_: None) is None
    assert win_job_process.claim_child('0' * 48) is None
    with win_job_process.child_scope(win_job_process._CHILD_PROOF):
        result = extract._ocr_pdf(b'pdf', 1, extract._Guard(1, 100),
                                  progress=lambda *_: None)
        assert result.segments[0].text == 'generated page text'
        with pytest.raises(extract.ExtractionError) as caught:
            extract.extract_bytes(samples.build_blank_pdf(1), 'pdf')
        assert caught.value.code == 'no_text'


@pytest.mark.asyncio
async def test_closed_native_gate_keeps_windows_ocr_on_time_only_refusal(monkeypatch):
    from agents.core.workspace import extract, extract_process

    class LegacyChild:
        returncode = 0

        async def communicate(self, data):
            return b'{"error":"no_text","page_count":1}', b''

    async def launch(*command, **kwargs):
        assert '--owned-win-job-ocr' not in command
        assert kwargs['start_new_session'] is False
        return LegacyChild()

    async def reap(child):
        assert isinstance(child, LegacyChild)

    async def forbidden(*args, **kwargs):
        pytest.fail('closed production gate entered native Job OCR')

    monkeypatch.setattr(extract_process.sys, 'platform', 'win32')
    monkeypatch.setattr(extract_process, '_WINDOWS_OCR_NATIVE_ACCEPTED', False)
    monkeypatch.setenv('NERVA_WORKSPACE_OCR', '1')
    monkeypatch.setenv('NERVA_WORKSPACE_KILLABLE_EXTRACTION', '1')
    monkeypatch.setattr(extract_process, '_extract_windows_ocr', forbidden)
    monkeypatch.setattr(extract_process.asyncio, 'create_subprocess_exec', launch)
    monkeypatch.setattr(extract_process, '_reap', reap)
    with pytest.raises(extract.ExtractionError) as caught:
        await extract_process.extract_in_child(b'generated-blank-pdf', 'pdf', timeout=2)
    assert caught.value.code == 'no_text'


@pytest.mark.skipif(sys.platform != 'win32', reason='requires native Windows Job and IOCP')
@pytest.mark.asyncio
async def test_native_windows_job_assignment_and_pipe_roundtrip():
    from agents.core.workspace.win_job_process import OwnedJobProcess

    script = ('import ctypes; import sys; from ctypes import wintypes; '
              'k=ctypes.WinDLL("kernel32",use_last_error=True); v=wintypes.BOOL(); '
              'assert k.IsProcessInJob(k.GetCurrentProcess(),None,ctypes.byref(v)); '
              'sys.stdout.write("owned\\n" if v.value else "unowned\\n")')
    owner = OwnedJobProcess.spawn([sys.executable, '-c', script], cwd=os.getcwd(),
                                  env=dict(os.environ), memory_limit=512 * 1024 * 1024)
    try:
        await owner.start_io()
        writer = asyncio.create_task(owner.send(b''))
        assert await asyncio.wait_for(owner.read_line(bytearray()), 3) == b'owned'
        await writer
    finally:
        await owner.terminate_and_drain()


@pytest.mark.skipif(sys.platform != 'win32', reason='requires native Windows Job commit limits')
@pytest.mark.asyncio
async def test_native_windows_process_commit_ceiling_refuses_large_allocation():
    from agents.core.workspace.win_job_process import OwnedJobProcess

    script = ('try:\n'
              ' x=bytearray(256*1024*1024)\n'
              ' print("ALLOCATED",flush=True)\n'
              'except MemoryError:\n'
              ' print("LIMITED",flush=True)\n')
    owner = OwnedJobProcess.spawn([sys.executable, '-c', script], cwd=os.getcwd(),
                                  env=dict(os.environ), memory_limit=64 * 1024 * 1024)
    try:
        await owner.start_io()
        writer = asyncio.create_task(owner.send(b''))
        line = await asyncio.wait_for(owner.read_line(bytearray()), 5)
        assert line == b'LIMITED'
        await writer
    finally:
        await owner.terminate_and_drain()
    assert owner.drained and owner.job is None


@pytest.mark.skipif(sys.platform != 'win32', reason='requires native Windows Job and IOCP')
@pytest.mark.asyncio
async def test_native_windows_grandchild_held_pipe_drains_after_leader_exit():
    from agents.core.workspace.win_job_process import OwnedJobProcess

    grandchild = 'import time; time.sleep(60)'
    script = ('import subprocess,sys; '
              f'subprocess.Popen([sys.executable,"-c",{grandchild!r}], '
              'stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=subprocess.DEVNULL); '
              'sys.stdout.write("grandchild-started\\n");sys.stdout.flush()')
    owner = OwnedJobProcess.spawn([sys.executable, '-c', script], cwd=os.getcwd(),
                                  env=dict(os.environ), memory_limit=512 * 1024 * 1024)
    try:
        await owner.start_io()
        writer = asyncio.create_task(owner.send(b''))
        assert await asyncio.wait_for(owner.read_line(bytearray()), 3) == b'grandchild-started'
        await writer
    finally:
        await owner.terminate_and_drain()
    assert owner.drained and owner.job is None


@pytest.mark.skipif(sys.platform != 'win32', reason='requires native Windows Job and OCR engine')
@pytest.mark.asyncio
async def test_native_windows_generated_pdf_ocr_all_pages(monkeypatch):
    from agents.core.workspace import extract_process

    pytest.importorskip('pypdfium2')
    pytest.importorskip('pytesseract')
    from PIL import Image, ImageDraw, ImageFont

    if shutil.which('tesseract') is None:
        pytest.skip('local Tesseract engine unavailable')
    font_path = 'C:\\Windows\\Fonts\\arial.ttf'
    if not os.path.isfile(font_path):
        pytest.skip('generated-input test font unavailable')
    image = Image.new('RGB', (1200, 300), 'white')
    ImageDraw.Draw(image).text((40, 70), 'SCANNEDWORD', fill='black',
                               font=ImageFont.truetype(font_path, 72))
    output = BytesIO()
    image.save(output, format='PDF', resolution=200)
    monkeypatch.setenv('NERVA_WORKSPACE_OCR', '1')
    monkeypatch.setenv('NERVA_WORKSPACE_KILLABLE_EXTRACTION', '1')
    result = await extract_process._extract_windows_ocr(output.getvalue(), 'pdf', timeout=60)
    assert result.page_count == 1 and 'SCANNEDWORD' in result.segments[0].text.upper()
    assert 'ocr' in result.limits and 'job_commit' in result.limits
