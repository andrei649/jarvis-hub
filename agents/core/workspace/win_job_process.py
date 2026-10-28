"""Windows-only, parent-owned Job process for the gated PDF OCR child.

The Job is assigned by CreateProcessW before the initial thread can run. This
module imports no Windows DLL until a native instance is requested. It is a
resource boundary, not a filesystem or network sandbox.
"""
from __future__ import annotations

import asyncio
import ctypes
import os
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from contextvars import ContextVar

_CHILD_NONCE = 'NERVA_WORKSPACE_JOB_NONCE'
_CHILD_PROOF = object()
_CHILD_SCOPE: ContextVar[bool] = ContextVar('workspace_win_job_ocr_child', default=False)
_UNVERIFIED_OWNERS = []  # Retain kill-on-close Jobs when cleanup cannot be proved.
_CHUNK = 65536
_MAX_FRAME = 128 * 1024 * 1024
_DRAIN_SECONDS = 5.0


class JobCleanupUnverified(OSError):
    """The owner still retains Job handles; caller must retain scratch and slot."""


def new_child_nonce() -> str:
    return secrets.token_hex(24)


def claim_child(nonce: str):
    """Only an OS-Job member with the parent's ephemeral marker may enter OCR."""
    if (sys.platform != 'win32' or not nonce or len(nonce) != 48
            or os.environ.get(_CHILD_NONCE) != nonce):
        return None
    try:
        if _Win32Kernel().current_process_in_job():
            return _CHILD_PROOF
    except (OSError, AttributeError):
        pass
    return None


@contextmanager
def child_scope(proof):
    if proof is not _CHILD_PROOF:
        raise OSError('Windows OCR Job ownership unavailable')
    token = _CHILD_SCOPE.set(True)
    try:
        yield
    finally:
        _CHILD_SCOPE.reset(token)


def in_owned_child() -> bool:
    return _CHILD_SCOPE.get() is True


class _Win32Kernel:
    """Thin stdlib Win32 adapter; injected fakes test controller ordering on Mac."""

    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('Windows Job API unavailable')
        import ctypes.wintypes as wt

        self.wt = wt
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)

        class BasicLimits(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64),
                        ('PerJobUserTimeLimit', ctypes.c_int64), ('LimitFlags', wt.DWORD),
                        ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t),
                        ('ActiveProcessLimit', wt.DWORD), ('Affinity', ctypes.c_size_t),
                        ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                        ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in (
                'TotalUserTime', 'TotalKernelTime', 'ThisPeriodTotalUserTime',
                'ThisPeriodTotalKernelTime')] + [
                (name, wt.DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses',
                                              'ActiveProcesses', 'TotalTerminatedProcesses')]

        class StartupInfo(ctypes.Structure):
            _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR),
                        ('lpDesktop', wt.LPWSTR), ('lpTitle', wt.LPWSTR),
                        ('dwX', wt.DWORD), ('dwY', wt.DWORD), ('dwXSize', wt.DWORD),
                        ('dwYSize', wt.DWORD), ('dwXCountChars', wt.DWORD),
                        ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
                        ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD),
                        ('cbReserved2', wt.WORD), ('lpReserved2', ctypes.c_void_p),
                        ('hStdInput', wt.HANDLE), ('hStdOutput', wt.HANDLE),
                        ('hStdError', wt.HANDLE)]

        class StartupInfoEx(ctypes.Structure):
            _fields_ = [('StartupInfo', StartupInfo), ('lpAttributeList', ctypes.c_void_p)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE),
                        ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]

        self.ExtendedLimits = ExtendedLimits
        self.Accounting = Accounting
        self.StartupInfoEx = StartupInfoEx
        self.ProcessInfo = ProcessInfo
        self.k.CreateJobObjectW.restype = wt.HANDLE
        self.k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wt.LPCWSTR)
        self.k.SetInformationJobObject.restype = wt.BOOL
        self.k.SetInformationJobObject.argtypes = (
            wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD)
        self.k.QueryInformationJobObject.restype = wt.BOOL
        self.k.QueryInformationJobObject.argtypes = (
            wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p)
        self.k.IsProcessInJob.restype = wt.BOOL
        self.k.IsProcessInJob.argtypes = (wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL))
        self.k.TerminateJobObject.restype = wt.BOOL
        self.k.TerminateJobObject.argtypes = (wt.HANDLE, wt.UINT)
        self.k.TerminateProcess.restype = wt.BOOL
        self.k.TerminateProcess.argtypes = (wt.HANDLE, wt.UINT)
        self.k.ResumeThread.restype = wt.DWORD
        self.k.ResumeThread.argtypes = (wt.HANDLE,)
        self.k.WaitForSingleObject.restype = wt.DWORD
        self.k.WaitForSingleObject.argtypes = (wt.HANDLE, wt.DWORD)
        self.k.CloseHandle.restype = wt.BOOL
        self.k.CloseHandle.argtypes = (wt.HANDLE,)
        self.k.SetHandleInformation.restype = wt.BOOL
        self.k.SetHandleInformation.argtypes = (wt.HANDLE, wt.DWORD, wt.DWORD)
        self.k.GetCurrentProcess.restype = wt.HANDLE

    @staticmethod
    def _error(label):
        raise OSError(ctypes.get_last_error(), label)

    def create_job(self):
        job = self.k.CreateJobObjectW(None, None)
        if not job:
            self._error('CreateJobObjectW failed')
        return job

    def set_limits(self, job, memory_limit):
        if type(memory_limit) is not int or memory_limit <= 0:
            raise OSError('invalid Job commit ceiling')
        limits = self.ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x200
        limits.ProcessMemoryLimit = memory_limit
        limits.JobMemoryLimit = memory_limit
        if not self.k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self._error('SetInformationJobObject failed')

    def create_stdio(self):
        import _winapi
        from asyncio.windows_utils import pipe

        stdin_child = stdin_parent = stdout_parent = stdout_child = stderr_child = None
        try:
            stdin_child, stdin_parent = pipe(duplex=True, overlapped=(False, True))
            stdout_parent, stdout_child = pipe(overlapped=(True, False))
            stderr_child = _winapi.CreateFile('NUL', _winapi.GENERIC_WRITE,
                _winapi.FILE_SHARE_READ | _winapi.FILE_SHARE_WRITE, 0,
                _winapi.OPEN_EXISTING, 0, 0)
            return stdin_parent, stdin_child, stdout_parent, stdout_child, stderr_child
        except BaseException:
            for handle in (stdin_child, stdin_parent, stdout_parent, stdout_child, stderr_child):
                if handle is not None:
                    self.close_handle(handle)
            raise

    def mark_inheritance(self, child_handles, parent_handles, job):
        for handle in (*parent_handles, job):
            if not self.k.SetHandleInformation(handle, 1, 0):
                self._error('noninheritable Job/parent handle required')
        for handle in child_handles:
            if not self.k.SetHandleInformation(handle, 1, 1):
                self._error('inheritable stdio handle required')

    def create_process(self, command, cwd, env, *, job, stdio, inherit_handles,
                       suspended, breakaway):
        if not suspended or breakaway or tuple(stdio) != tuple(inherit_handles):
            raise OSError('atomic owned process attributes required')
        if (not command or any(type(part) is not str for part in command)
                or type(cwd) is not str or type(env) is not dict
                or any(type(key) is not str or type(value) is not str or not key
                       or '=' in key for key, value in env.items())):
            raise OSError('invalid Windows OCR process arguments')
        wt = self.wt
        k = self.k
        k.InitializeProcThreadAttributeList.restype = wt.BOOL
        k.InitializeProcThreadAttributeList.argtypes = (
            ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t))
        k.UpdateProcThreadAttribute.restype = wt.BOOL
        k.UpdateProcThreadAttribute.argtypes = (
            ctypes.c_void_p, wt.DWORD, ctypes.c_size_t, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p)
        k.DeleteProcThreadAttributeList.argtypes = (ctypes.c_void_p,)
        k.CreateProcessW.restype = wt.BOOL
        k.CreateProcessW.argtypes = (
            wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
            ctypes.POINTER(self.StartupInfoEx), ctypes.POINTER(self.ProcessInfo))
        size = ctypes.c_size_t()
        k.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        if not size.value:
            self._error('process attribute list unavailable')
        attributes = ctypes.create_string_buffer(size.value)
        if not k.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
            self._error('process attribute list unavailable')
        handles = (wt.HANDLE * len(inherit_handles))(*inherit_handles)
        jobs = (wt.HANDLE * 1)(job)
        try:
            for key, value in ((0x20002, handles), (0x2000D, jobs)):
                if not k.UpdateProcThreadAttribute(
                        attributes, 0, key, value, ctypes.sizeof(value), None, None):
                    self._error('atomic Job/handle-list attribute unavailable')
            startup = self.StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = stdio[0]
            startup.StartupInfo.hStdOutput = stdio[1]
            startup.StartupInfo.hStdError = stdio[2]
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            info = self.ProcessInfo()
            line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            if any('\0' in str(part) for part in (*command, cwd, *env.keys(), *env.values())):
                raise OSError('invalid process environment')
            block = ctypes.create_unicode_buffer(
                ''.join(f'{key}={value}\0' for key, value in sorted(env.items())) + '\0')
            flags = 0x00080000 | 0x00000004 | 0x00000400 | 0x08000000
            if not k.CreateProcessW(command[0], line, None, None, True, flags,
                                    block, cwd, ctypes.byref(startup), ctypes.byref(info)):
                self._error('CreateProcessW with Job list failed')
            return info.hProcess, info.hThread
        finally:
            k.DeleteProcThreadAttributeList(attributes)

    def is_process_in_job(self, process, job):
        answer = self.wt.BOOL()
        if not self.k.IsProcessInJob(process, job, ctypes.byref(answer)):
            self._error('IsProcessInJob failed')
        return bool(answer.value)

    def current_process_in_job(self):
        return self.is_process_in_job(self.k.GetCurrentProcess(), None)

    def resume_thread(self, thread):
        if self.k.ResumeThread(thread) == 0xFFFFFFFF:
            self._error('ResumeThread failed')

    def terminate_job(self, job):
        if not self.k.TerminateJobObject(job, 1):
            self._error('TerminateJobObject failed')

    def terminate_process(self, process):
        if not self.k.TerminateProcess(process, 1):
            self._error('TerminateProcess failed')

    def active_processes(self, job):
        state = self.Accounting()
        if not self.k.QueryInformationJobObject(job, 1, ctypes.byref(state),
                                                ctypes.sizeof(state), None):
            self._error('QueryInformationJobObject failed')
        return int(state.ActiveProcesses)

    def wait_process(self, process, milliseconds):
        value = self.k.WaitForSingleObject(process, milliseconds)
        if value == 0:
            return True
        if value != 0x102:
            self._error('WaitForSingleObject failed')
        return False

    def close_handle(self, handle):
        if handle is not None and not self.k.CloseHandle(handle):
            self._error('CloseHandle failed')

    async def connect_io(self, parent_input, parent_output):
        from asyncio import windows_utils

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=_CHUNK)
        read_done = loop.create_future()
        write_done = loop.create_future()

        class ReadProtocol(asyncio.StreamReaderProtocol):
            def connection_lost(self, exc):
                super().connection_lost(exc)
                if not read_done.done():
                    read_done.set_result(None)

        class WriteProtocol(asyncio.streams.FlowControlMixin):
            def connection_lost(self, exc):
                super().connection_lost(exc)
                if not write_done.done():
                    write_done.set_result(None)

        reader_protocol = ReadProtocol(reader)
        read_handle = windows_utils.PipeHandle(parent_output)
        write_handle = windows_utils.PipeHandle(parent_input)
        read_transport = None
        try:
            read_transport, _ = await loop.connect_read_pipe(
                lambda: reader_protocol, read_handle)
            write_protocol = WriteProtocol(loop=loop)
            write_transport, _ = await loop.connect_write_pipe(
                lambda: write_protocol, write_handle)
        except BaseException:
            if read_transport is not None:
                read_transport.close()
            else:
                read_handle.close()
            write_handle.close()
            if read_transport is not None:
                # connect_write_pipe can fail after read IOCP registration.
                # Retire that transport before the owner considers launch
                # cleanup complete; caller cancellation must not orphan it.
                closing = asyncio.create_task(asyncio.wait_for(read_done, 1))
                while not closing.done():
                    with suppress(asyncio.CancelledError):
                        await asyncio.shield(closing)
                closing.result()
            raise
        writer = asyncio.StreamWriter(write_transport, write_protocol, None, loop)
        return reader, writer, read_transport, write_transport, read_done, write_done


class OwnedJobProcess:
    """Handle owner retained through termination, pipe drain and ActiveProcesses=0."""

    def __init__(self, api, job, process, thread, parent_input, parent_output):
        self.api, self.job, self.process, self.thread = api, job, process, thread
        self.parent_input, self.parent_output = parent_input, parent_output
        self.reader = self.writer = None
        self.read_transport = self.write_transport = None
        self.read_done = self.write_done = None
        self._cleanup_lock = asyncio.Lock()
        self.drained = False

    @classmethod
    def spawn(cls, command, *, cwd, env, memory_limit, api=None):
        api = _Win32Kernel() if api is None else api
        job = process = thread = None
        stdio = None
        live_stdio = []
        owned = False
        try:
            job = api.create_job()
            api.set_limits(job, memory_limit)
            stdio = api.create_stdio()
            live_stdio = list(stdio)
            parent_input, child_input, parent_output, child_output, child_error = stdio
            child = (child_input, child_output, child_error)
            parent = (parent_input, parent_output)
            api.mark_inheritance(child, parent, job)
            process, thread = api.create_process(
                command, cwd, env, job=job, stdio=child, inherit_handles=child,
                suspended=True, breakaway=False)
            if not api.is_process_in_job(process, job):
                raise OSError('atomic Windows OCR Job assignment failed')
            owned = True
            api.resume_thread(thread)
            for handle in child:
                api.close_handle(handle)
                live_stdio.remove(handle)
            return cls(api, job, process, thread, parent_input, parent_output)
        except BaseException:
            if process is not None:
                try:
                    if owned:
                        api.terminate_job(job)
                    else:
                        api.terminate_process(process)
                    if not api.wait_process(process, 5000):
                        raise OSError('Windows OCR launch child did not terminate')
                    if owned and api.active_processes(job) != 0:
                        raise OSError('Windows OCR launch Job still has active descendants')
                except BaseException as exc:
                    _UNVERIFIED_OWNERS.append((api, job, process, thread, tuple(live_stdio)))
                    raise JobCleanupUnverified('Windows OCR launch cleanup unverified') from exc
            close_error = None
            uncertain_stdio = []
            for handle in tuple(live_stdio):
                try:
                    api.close_handle(handle)
                    live_stdio.remove(handle)
                except OSError as exc:
                    uncertain_stdio.append(handle)
                    close_error = close_error or exc
            uncertain = {}
            for name, handle in (('thread', thread), ('process', process), ('job', job)):
                if handle is not None:
                    try:
                        api.close_handle(handle)
                    except OSError as exc:
                        uncertain[name] = handle
                        close_error = close_error or exc
            if close_error is not None:
                # The Job has no active members, but a failed parent CloseHandle
                # is still an uncertain owner. Do not advertise a clean launch
                # or automatically retry numeric values that Windows may reuse.
                _UNVERIFIED_OWNERS.append((
                    api, uncertain.get('job'), uncertain.get('process'),
                    uncertain.get('thread'), tuple(uncertain_stdio)))
                raise JobCleanupUnverified('Windows OCR launch handle cleanup unverified') from close_error
            raise

    async def start_io(self):
        try:
            (self.reader, self.writer, self.read_transport, self.write_transport,
             self.read_done, self.write_done) = await self.api.connect_io(
                 self.parent_input, self.parent_output)
        finally:
            # connect_io consumes both handles even when IOCP registration fails.
            self.parent_input = self.parent_output = None

    async def send(self, data: bytes):
        if self.writer is None:
            raise OSError('Windows OCR pipe is unavailable')
        try:
            for offset in range(0, len(data), _CHUNK):
                self.writer.write(data[offset:offset + _CHUNK])
                await self.writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.writer.close()

    async def read_line(self, buffer: bytearray):
        if self.reader is None:
            raise OSError('Windows OCR pipe is unavailable')
        search_from = 0
        while True:
            end = buffer.find(b'\n', search_from)
            if end >= 0:
                line = bytes(buffer[:end])
                del buffer[:end + 1]
                return line
            chunk = await self.reader.read(_CHUNK)
            if not chunk:
                if buffer:
                    line = bytes(buffer)
                    buffer.clear()
                    return line
                return None
            search_from = len(buffer)
            buffer.extend(chunk)
            if len(buffer) > _MAX_FRAME:
                raise OSError('Windows OCR frame exceeds output budget')

    async def terminate_and_drain(self):
        async with self._cleanup_lock:
            if self.drained:
                return
            try:
                await asyncio.to_thread(self.api.terminate_job, self.job)
                pipe_error = None
                if self.write_transport is not None:
                    self.write_transport.close()
                elif self.parent_input is not None:
                    try:
                        self.api.close_handle(self.parent_input)
                    except OSError as exc:
                        pipe_error = exc
                    self.parent_input = None
                if self.read_transport is not None:
                    self.read_transport.close()
                elif self.parent_output is not None:
                    try:
                        self.api.close_handle(self.parent_output)
                    except OSError as exc:
                        pipe_error = exc
                    self.parent_output = None
                deadline = time.monotonic() + _DRAIN_SECONDS
                while True:
                    active = await asyncio.to_thread(self.api.active_processes, self.job)
                    reaped = await asyncio.to_thread(self.api.wait_process, self.process, 50)
                    if active == 0 and reaped:
                        break
                    if time.monotonic() >= deadline:
                        raise OSError('Windows OCR Job still has active processes')
                    await asyncio.sleep(0.01)
                for closed in (self.read_done, self.write_done):
                    if closed is not None:
                        await asyncio.wait_for(asyncio.shield(closed), 1)
                if pipe_error is not None:
                    raise pipe_error
                self.drained = True
                self.close()
            except BaseException as exc:
                _UNVERIFIED_OWNERS.append(self)
                raise JobCleanupUnverified('Windows OCR Job cleanup unverified') from exc

    def close(self):
        if not self.drained:
            raise OSError('Windows OCR Job cannot close before verified drain')
        for name in ('thread', 'process', 'job'):
            handle = getattr(self, name)
            if handle is not None:
                self.api.close_handle(handle)
                setattr(self, name, None)
