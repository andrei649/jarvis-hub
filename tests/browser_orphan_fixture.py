"""Linux-only orphan fixture supervisor; never used by production browser code.

The private subreaper owns even double-forked Chrome helpers. The test can kill its
controller without transferring cleanup responsibility to the machine's PID 1.
"""
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import http.client
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import psutil


def _snapshot(pid, started):
    result = {'pid': pid}
    try:
        process = psutil.Process(pid)
        if process.create_time() != started:
            return {**result, 'identity_changed': True}
        result.update(start=process.create_time(), status=process.status(),
                      exe=process.exe()[-512:], argv=[arg[:512] for arg in process.cmdline()[:32]])
    except psutil.Error as exc:
        result['error'] = type(exc).__name__
    return result


def _ready(pid, started, profile):
    """Fresh identity, exact argv and a responding owned DevTools endpoint."""
    process = psutil.Process(pid)
    if process.create_time() != started or process.status() in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
        raise RuntimeError('native exited or identity changed before readiness')
    if Path(process.exe()).name.lower() not in {'chrome', 'chromium', 'google chrome'}:
        return False
    if '--user-data-dir=' + str(profile) not in process.cmdline():
        return False
    try:
        port, endpoint = (profile / 'DevToolsActivePort').read_text().splitlines()
        if not (port.isdecimal() and 0 < int(port) < 65536 and endpoint.startswith('/devtools/browser/')):
            return False
        connection = http.client.HTTPConnection('127.0.0.1', int(port), timeout=.2)
        try:
            connection.request('GET', '/json/version')
            response = connection.getresponse()
            payload = json.loads(response.read(8192))
            if response.status != 200 or not payload['webSocketDebuggerUrl'].endswith(endpoint):
                return False
        finally:
            connection.close()
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return False
    fresh = psutil.Process(pid)
    return (fresh.create_time() == started
            and fresh.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
            and '--user-data-dir=' + str(profile) in fresh.cmdline())


def _controller(chrome, root, sid, profile, work):
    from agents.core.browser_session import BrowserOwnershipJournal

    controller = psutil.Process()
    with (work / 'chrome.stderr').open('wb') as stderr:
        proc = subprocess.Popen([chrome, '--headless=new', '--no-sandbox', '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking', '--no-proxy-server',
            '--host-resolver-rules=MAP * ~NOTFOUND', '--remote-debugging-port=0',
            '--user-data-dir=' + str(profile), 'about:blank'], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=stderr)
        native = psutil.Process(proc.pid)
        started = native.create_time()
        (work / 'launch.json').write_text(json.dumps([proc.pid, started]))
        deadline = time.monotonic() + 15
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f'native exited before readiness: {proc.returncode}')
            if _ready(proc.pid, started, profile):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('native readiness expired')
            time.sleep(.05)
        record = {'profile': str(profile), 'controller': [controller.pid, controller.create_time()],
                  'owner_process': [controller.pid, controller.create_time()], 'native': [proc.pid, started]}
        BrowserOwnershipJournal(root).write(sid, record)
        (work / 'record.json').write_text(json.dumps(record))
    os._exit(0)


def _cleanup():
    """Only enumerate this supervisor's descendants; guard every signal by start time."""
    owned = {}
    deadline = time.monotonic() + 5
    while True:
        for process in psutil.Process().children(recursive=True):
            with contextlib.suppress(psutil.Error):
                owned[(process.pid, process.create_time())] = process
        for (pid, started), _ in owned.items():
            with contextlib.suppress(psutil.Error):
                process = psutil.Process(pid)
                if process.create_time() == started:
                    process.kill()
        with contextlib.suppress(ChildProcessError):
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        if not psutil.Process().children(recursive=True):
            return {'owned': [list(identity) for identity in owned], 'survivors': []}
        if time.monotonic() >= deadline:
            return {'owned': [list(identity) for identity in owned],
                    'survivors': [_snapshot(p.pid, p.create_time()) for p in psutil.Process().children(recursive=True)]}
        time.sleep(.01)


def _supervise(chrome, root, sid, profile, work):
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    child = None
    try:
        if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise RuntimeError('private subreaper unavailable')
        with (work / 'controller.stderr').open('wb') as stderr:
            child = subprocess.Popen([sys.executable, '-m', 'tests.browser_orphan_fixture', '--controller', chrome,
                str(root), sid, str(profile), str(work)], stdout=subprocess.DEVNULL, stderr=stderr)
        # Include controller interpreter/import/launch overhead outside its
        # unchanged 15-second browser-readiness budget.
        deadline = time.monotonic() + 20
        while child.poll() is None:
            if stopping or select.select([sys.stdin], [], [], .02)[0] or time.monotonic() >= deadline:
                raise TimeoutError('controller launch interrupted or expired')
        if child.returncode:
            raise RuntimeError(f'controller failed: {child.returncode}')
        record = json.loads((work / 'record.json').read_text())
        (work / 'ready.json').write_text(json.dumps(_snapshot(*record['native'])))
        print(json.dumps({'record': record}), flush=True)
        # Parent EOF or termination always reaches our descendant cleanup. This
        # independent lease also bounds cleanup if the test process disappears.
        deadline = time.monotonic() + 60
        while not stopping and time.monotonic() < deadline:
            with contextlib.suppress(ChildProcessError):
                while os.waitpid(-1, os.WNOHANG)[0]:
                    pass
            if select.select([sys.stdin], [], [], .05)[0]:
                break
    except BaseException as exc:
        diagnostics = {'error': str(exc)[:1024]}
        launch = work / 'launch.json'
        if launch.exists():
            diagnostics['native'] = _snapshot(*json.loads(launch.read_text()))
        for name in ('controller.stderr', 'chrome.stderr'):
            path = work / name
            if path.exists():
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 4096))
                    diagnostics[name] = stream.read(4096).decode(errors='replace')
        (work / 'failure.json').write_text(json.dumps(diagnostics))
        with contextlib.suppress(BrokenPipeError):
            print(json.dumps(diagnostics), flush=True)
    finally:
        cleanup = _cleanup()
        if child is not None:
            child.wait(timeout=1)
        if not cleanup['survivors']:
            shutil.rmtree(profile, ignore_errors=True)
            if not profile.exists():
                (root / (sid + '.json')).unlink(missing_ok=True)
        for name in ('controller.stderr', 'chrome.stderr'):
            path = work / name
            if path.exists():
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 4096))
                    tail = stream.read(4096)
                path.write_bytes(tail)
        (work / 'cleanup.json').write_text(json.dumps(cleanup))


@asynccontextmanager
async def supervised_orphan(chrome, journal, sid, profile, work, *, launch_timeout=25):
    process = None
    result = None
    try:
        work.mkdir()
        process = subprocess.Popen([sys.executable, '-m', 'tests.browser_orphan_fixture', '--supervisor',
            chrome, str(journal.root), sid, str(profile), str(work)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Include supervisor startup outside its 20-second controller budget.
        line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), launch_timeout)
        result = json.loads(line)
        assert 'record' in result, result
        yield result['record']
    except BaseException as exc:
        if result and 'record' in result:
            diagnostics = {'error': str(exc)[:1024],
                           'native': _snapshot(*result['record']['native'])}
            (work / 'parent-failure.json').write_text(json.dumps(diagnostics))
            print(json.dumps(diagnostics), file=sys.stderr, flush=True)
        raise
    finally:
        if process is None:  # no controller or browser could have been launched
            profile.rmdir()
        else:
            process.stdin.close()  # EOF is handled during startup as well as after publication
            await asyncio.to_thread(process.wait, 10)
            assert process.returncode == 0, process.stderr.read()[-4096:]
            cleanup = json.loads((work / 'cleanup.json').read_text())
            assert cleanup['survivors'] == [], cleanup
            assert not profile.exists()
            assert not journal._file(sid).exists()
            process.stdout.close()
            process.stderr.close()


if __name__ == '__main__':
    mode, chrome, root, sid, profile, work = sys.argv[1:]
    action = _controller if mode == '--controller' else _supervise
    action(chrome, Path(root), sid, Path(profile), Path(work))
