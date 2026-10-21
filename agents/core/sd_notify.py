"""H283 — systemd's readiness and watchdog protocol (``sd_notify``), spoken by the hub.

``/readyz`` and ``/healthz`` were shaped for systemd's ``WatchdogSec`` and a container
HEALTHCHECK, but nothing wrote to ``NOTIFY_SOCKET``: the shipped unit was
``Type=simple`` (started the moment the process ran, before any agent loaded) and the
README said to cron a curl instead. Now, when systemd starts the hub under
``Type=notify``:

- ``READY=1`` is sent once the server has bound its port and ``/readyz`` would answer
  200 (the orchestrator and its agents are loaded), so ``systemctl start`` returns
  when the hub can serve, and units ordered ``After=`` it wait for that;
- ``WATCHDOG=1`` is sent every half ``WATCHDOG_USEC`` by a task on the event loop, so
  a loop that hangs stops the heartbeat and systemd restarts the hub
  (``Restart=on-failure``);
- ``STOPPING=1`` is sent as the server begins to shut down, before it drains — unless the
  hub asked to restart itself (H010, ``agents.core.hub_restart``: an approved restore was
  staged). Then it is ``RELOADING=1``: STOPPING would move the unit to stop-sigterm and
  arm ``TimeoutStopSec``, and systemd would SIGKILL the same-pid re-exec partway through
  the restore. The watchdog stays armed in the reload state, so from RELOADING=1 through
  the drain, the execv and the new image's boot up to its ``READY=1`` a thread feeds it
  and extends the timeout (:func:`begin_restart_keepalive`, then
  :func:`continue_restart_keepalive` from serve.py's first lines, bounded by
  ``RESTART_KEEPALIVE_MAX_SECONDS``); :func:`keepalive` does the same around the restore.

Only the server knows those moments (uvicorn runs the app's lifespan before it binds),
so ``serve.py`` runs :class:`NotifyingServer`; a raw ``uvicorn agents.web:app`` says
nothing. With ``NOTIFY_SOCKET`` unset (a shell, Docker, launchd, Windows) every call
is a no-op. A message that cannot be sent is logged at debug and never raises: the
protocol is advisory to the process that runs it.
"""
from __future__ import annotations

import asyncio
import errno
import logging
import os
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager

import uvicorn

from .env_config import env_flag, env_str

logger = logging.getLogger("jarvis.sd_notify")

#: The shortest heartbeat taken from WATCHDOG_USEC (a shorter one would busy the loop),
#: unless the deadline itself is shorter: a ping must always land inside it.
MIN_WATCHDOG_SECONDS = 0.1

#: How long a message is retried while the service manager's queue is full. READY is
#: sent once and must not be lost to a busy manager; the event loop is never held longer.
SEND_TIMEOUT_SECONDS = 1.0


def _address() -> str | bytes | None:
    """``NOTIFY_SOCKET`` as a socket address: a path, or ``@name`` for the abstract
    namespace (Linux). Anything else (unset, relative) is no socket."""
    raw = env_str("NOTIFY_SOCKET").strip()
    if not raw:
        return None
    if raw.startswith("@"):
        return b"\0" + raw[1:].encode("utf-8", "surrogateescape")
    if raw.startswith("/"):
        return raw
    return None


def enabled() -> bool:
    """Whether a service manager asked to be told (``NOTIFY_SOCKET`` is set)."""
    return _address() is not None and hasattr(socket, "AF_UNIX")


def notify(message: str) -> bool:
    """Send one ``KEY=VALUE`` datagram to the service manager; ``False`` when unsent."""
    address = _address()
    if address is None or not hasattr(socket, "AF_UNIX"):
        return False
    data = message.encode("utf-8", "replace")
    deadline = time.monotonic() + SEND_TIMEOUT_SECONDS
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            while True:
                try:
                    sock.sendto(data, address)
                    return True
                except OSError as exc:
                    # Linux reports EAGAIN; Darwin reports ENOBUFS when the
                    # service manager's datagram buffer is full. Retry only these.
                    if exc.errno not in {errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS}:
                        raise
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
    except OSError as exc:
        logger.debug("sd_notify %r not sent: %s", message.split("=", 1)[0], exc)
        return False


def _decimal(raw: str) -> int | None:
    """An ASCII decimal, as systemd writes them; None for anything else (``int()``
    refuses digits such as ``²`` that ``isdigit()`` accepts)."""
    return int(raw) if raw.isascii() and raw.isdigit() else None


def watchdog_seconds() -> float | None:
    """Half of ``WATCHDOG_USEC``, when the watchdog is armed for this process.

    systemd sets ``WATCHDOG_PID`` to the main PID; a child that inherited the
    variables must not ping on its parent's behalf. Without ``WATCHDOG_PID`` any
    process is armed, as in libsystemd.
    """
    usec = _decimal(env_str("WATCHDOG_USEC").strip())
    if not usec:
        return None
    pid = env_str("WATCHDOG_PID").strip()
    if pid and _decimal(pid) != os.getpid():
        return None
    deadline = usec / 1_000_000
    return min(max(MIN_WATCHDOG_SECONDS, deadline / 2), deadline * 0.8)


async def _heartbeat(interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        notify("WATCHDOG=1")


class Notifier:
    """The hub's side of the protocol, driven by :class:`NotifyingServer`."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.ready_sent = False

    def ready(self, readiness: Mapping) -> bool:
        """``READY=1`` once the hub is ready (``readiness`` is ``/readyz``'s body), and
        the watchdog heartbeat from then on. A hub that is not ready says why instead."""
        if not enabled():
            return False
        if not readiness.get("ready"):
            notify(f"STATUS=not ready: {readiness.get('reason') or 'starting'}")
            return False
        self.ready_sent = notify("READY=1\nSTATUS=serving")
        if self.ready_sent:
            end_restart_keepalive()   # a self-restart's boot is over: the heartbeat takes over
        interval = watchdog_seconds()
        if self.ready_sent and interval is not None and self._task is None:
            self._task = asyncio.get_running_loop().create_task(_heartbeat(interval), name="sd_notify-watchdog")
        return self.ready_sent

    async def stopping(self, restarting: str | None = None) -> None:
        """``STOPPING=1``, and the heartbeat ends: a draining hub is not hung. A hub that
        is restarting itself (*restarting* is the reason) says ``RELOADING=1`` instead."""
        if enabled():
            if restarting:
                notify(f"RELOADING=1\nMONOTONIC_USEC={time.monotonic_ns() // 1000}\n"
                       f"STATUS=restarting: {restarting}")
                begin_restart_keepalive(restarting)
            else:
                notify("STOPPING=1\nSTATUS=draining")
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - the heartbeat is advisory
                logger.debug("sd_notify heartbeat ended")


NOTIFIER = Notifier()


class NotifyingServer(uvicorn.Server):
    """uvicorn's server, speaking the protocol at the moments only the server knows.

    uvicorn runs the app's lifespan *before* it binds the port: READY from the lifespan
    reached systemd while nothing listened, and a bind that then failed left
    ``systemctl start`` reporting success. Here READY follows the bind, decided by
    ``readiness()`` (``/readyz``'s body). And STOPPING opens the shutdown, before the
    drain: the lifespan's teardown runs after it, and not at all on a forced exit.
    """

    def __init__(self, config: uvicorn.Config, readiness: Callable[[], Mapping]) -> None:
        super().__init__(config)
        self._readiness = readiness

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)      # a failed bind exits here, unannounced
        if self.started:
            NOTIFIER.ready(self._readiness())

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        from . import hub_restart

        await NOTIFIER.stopping(restarting=hub_restart.requested())
        await super().shutdown(sockets=sockets)


#: The keepalive beat when no watchdog is armed (only the timeout is extended then).
KEEPALIVE_SECONDS = 10.0

#: Set in the environment by serve.run_server just before a self-restart's execv; the new
#: image reads (and removes) it on its first lines and keeps the unit fed until READY=1.
RESTART_ENV = "JARVIS_SELF_RESTART"

#: The longest a self-restart is kept fed without READY=1 (the shipped unit's
#: TimeoutStartSec): a re-exec'd boot that hangs past it is left to the watchdog.
RESTART_KEEPALIVE_MAX_SECONDS = 300.0


class _Pinger:
    """A thread that sends ``WATCHDOG=1`` + ``EXTEND_TIMEOUT_USEC`` every beat. A thread,
    not a loop task: it runs while the event loop drains, while nothing has started one
    yet (a re-exec'd boot imports the app), and while a restore blocks the main thread."""

    def __init__(self, status: str, *, interval: float | None = None,
                 max_seconds: float | None = None) -> None:
        self.beat = interval or watchdog_seconds() or KEEPALIVE_SECONDS
        self.message = (f"WATCHDOG=1\nEXTEND_TIMEOUT_USEC={int(self.beat * 3 * 1_000_000)}\n"
                        f"STATUS={status}")
        self._deadline = None if max_seconds is None else time.monotonic() + max_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="sd_notify-keepalive", daemon=True)

    def _loop(self) -> None:
        while not self._stop.wait(self.beat):
            if self._deadline is not None and time.monotonic() >= self._deadline:
                logger.warning("sd_notify keepalive ended: no READY=1 within its bound")
                return
            notify(self.message)

    def start(self) -> _Pinger:
        notify(self.message)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=SEND_TIMEOUT_SECONDS + self.beat)


@contextmanager
def keepalive(status: str, *, interval: float | None = None) -> Iterator[None]:
    """While the block runs, ping ``WATCHDOG=1`` and extend the current state's timeout
    (``EXTEND_TIMEOUT_USEC``) every beat: a long boot-time restore is busy, not hung.
    A no-op with no service manager listening."""
    if not enabled():
        yield
        return
    pinger = _Pinger(status, interval=interval).start()
    try:
        yield
    finally:
        pinger.stop()


_restart_pinger: _Pinger | None = None


def _start_restart_pinger(status: str, *, interval: float | None,
                          max_seconds: float | None) -> bool:
    global _restart_pinger
    if not enabled() or _restart_pinger is not None:
        return False
    _restart_pinger = _Pinger(status, interval=interval, max_seconds=max_seconds).start()
    return True


def begin_restart_keepalive(reason: str, *, interval: float | None = None) -> bool:
    """H010 review r2: a self-restart sends RELOADING=1, and the watchdog stays armed in
    the reload state — so the drain, the execv and the new image's boot must keep feeding
    it. Called as the restarting server shuts down; the thread lives until the execv."""
    return _start_restart_pinger(f"restarting: {reason}", interval=interval, max_seconds=None)


def continue_restart_keepalive(*, interval: float | None = None,
                               max_seconds: float | None = None) -> bool:
    """In the image a self-restart exec'd (``RESTART_ENV`` set, then removed here): feed
    the watchdog and extend the timeout from serve.py's first lines until READY=1
    (:meth:`Notifier.ready` ends it), bounded by ``RESTART_KEEPALIVE_MAX_SECONDS``."""
    restarted = env_flag(RESTART_ENV)
    os.environ.pop(RESTART_ENV, None)    # one boot only: the next exec starts clean
    if not restarted:
        return False
    return _start_restart_pinger(
        "restarting: booting the new image", interval=interval,
        max_seconds=RESTART_KEEPALIVE_MAX_SECONDS if max_seconds is None else max_seconds)


def end_restart_keepalive() -> None:
    global _restart_pinger
    pinger, _restart_pinger = _restart_pinger, None
    if pinger is not None:
        pinger.stop()
