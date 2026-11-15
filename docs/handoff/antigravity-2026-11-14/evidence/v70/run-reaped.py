"""Run one test command under a private Linux subreaper; never signal processes."""
import ctypes
import os
import sys
import time

if sys.platform != 'linux' or len(sys.argv) < 2:
    raise SystemExit('Usage on Linux: python run-reaped.py COMMAND [ARGS...]')
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
libc.prctl.restype = ctypes.c_int
if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
    raise OSError(ctypes.get_errno(), 'Cannot establish private test subreaper')
child = os.fork()
if child == 0:
    os.execvp(sys.argv[1], sys.argv[1:])
status = None
reaped = 0
while status is None:
    try:
        pid, value = os.wait()
    except InterruptedError:
        continue
    if pid == child:
        status = value
    else:
        reaped += 1
# Drain only descendants adopted by this launcher, with a bounded post-test wait.
deadline = time.monotonic() + 2
while time.monotonic() < deadline:
    try:
        pid, _ = os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        break
    if pid:
        reaped += 1
    else:
        time.sleep(0.02)
print(f'Private test launcher reaped {reaped} adopted descendants; no signals sent.', file=sys.stderr)
raise SystemExit(os.waitstatus_to_exitcode(status))
