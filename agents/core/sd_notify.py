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
- ``STOPPING=1`` is sent as the server begins to shut down, before it drains.

Only the server knows those moments (uvicorn runs the app's lifespan before it binds),
so ``serve.py`` runs :class:`NotifyingServer`; a raw ``uvicorn agents.web:app`` says
nothing. With ``NOTIFY_SOCKET`` unset (a shell, Docker, launchd, Windows) every call
is a no-op. A message that cannot be sent is logged at debug and never raises: the
protocol is advisory to the process that runs it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from collections.abc import Callable, Mapping

import uvicorn

from .env_config import env_str

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
                except BlockingIOError:            # the manager's queue is full: wait for room
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
        interval = watchdog_seconds()
        if self.ready_sent and interval is not None and self._task is None:
            self._task = asyncio.get_running_loop().create_task(_heartbeat(interval), name="sd_notify-watchdog")
        return self.ready_sent

    async def stopping(self) -> None:
        """``STOPPING=1``, and the heartbeat ends: a draining hub is not hung."""
        if enabled():
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
        await NOTIFIER.stopping()
        await super().shutdown(sockets=sockets)
