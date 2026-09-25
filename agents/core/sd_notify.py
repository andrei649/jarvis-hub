"""H283 — systemd's readiness and watchdog protocol (``sd_notify``), spoken by the hub.

``/readyz`` and ``/healthz`` were shaped for systemd's ``WatchdogSec`` and a container
HEALTHCHECK, but nothing wrote to ``NOTIFY_SOCKET``: the shipped unit was
``Type=simple`` (started the moment the process ran, before any agent loaded) and the
README said to cron a curl instead. Now, when systemd starts the hub under
``Type=notify``:

- ``READY=1`` is sent once the lifespan has finished and ``/readyz`` would answer 200
  (the orchestrator and its agents are loaded), so ``systemctl start`` returns when
  the hub can serve, and units ordered ``After=`` it wait for that;
- ``WATCHDOG=1`` is sent every half ``WATCHDOG_USEC`` by a task on the event loop, so
  a loop that hangs stops the heartbeat and systemd restarts the hub
  (``Restart=on-failure``);
- ``STOPPING=1`` is sent when the lifespan begins to shut down.

With ``NOTIFY_SOCKET`` unset (a shell, Docker, launchd, Windows) every call is a
no-op. A message that cannot be sent is logged at debug and never raises: the
protocol is advisory to the process that runs it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket

from .env_config import env_str

logger = logging.getLogger("jarvis.sd_notify")

#: The shortest heartbeat accepted: a WATCHDOG_USEC below 2 s would busy the loop.
MIN_WATCHDOG_SECONDS = 1.0


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
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.sendto(message.encode("utf-8", "replace"), address)
        return True
    except OSError as exc:
        logger.debug("sd_notify %r not sent: %s", message.split("=", 1)[0], exc)
        return False


def watchdog_seconds() -> float | None:
    """Half of ``WATCHDOG_USEC``, when the watchdog is armed for this process.

    systemd sets ``WATCHDOG_PID`` to the main PID; a child that inherited the
    variables must not ping on its parent's behalf.
    """
    raw = env_str("WATCHDOG_USEC").strip()
    if not raw.isdigit() or int(raw) <= 0:
        return None
    pid = env_str("WATCHDOG_PID").strip()
    if pid and (not pid.isdigit() or int(pid) != os.getpid()):
        return None
    return max(MIN_WATCHDOG_SECONDS, int(raw) / 1_000_000 / 2)


async def _heartbeat(interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        notify("WATCHDOG=1")


class Notifier:
    """The hub's side of the protocol, driven by the lifespan."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self.ready_sent = False

    def ready(self, readiness: dict | None = None) -> bool:
        """``READY=1`` once the hub is ready (``readiness`` is ``/readyz``'s body), and
        the watchdog heartbeat from then on. A hub that is not ready says why instead."""
        if not enabled():
            return False
        if readiness is not None and not readiness.get("ready"):
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
