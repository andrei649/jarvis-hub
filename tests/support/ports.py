"""A TCP port on 127.0.0.1 that stays closed for the whole test process (review T11).

The usual trick — bind port 0, read the number, close the socket — leaves a gap: until
the test connects, any other process may bind that port, a parallel xdist worker's
``--port 0`` fake server included, and the "closed port" then answers. Here the socket
stays bound but never listens: a connection is refused at once (``ECONNREFUSED``), and
no other socket can take the port while this process runs.
"""

from __future__ import annotations

import errno
import smtplib
import socket
import threading
from contextlib import contextmanager

_reserved: list[socket.socket] = []
_lock = threading.Lock()


def closed_port() -> int:
    """A port nobody listens on and nobody else can bind until this process exits."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    with _lock:
        _reserved.append(sock)
    return int(sock.getsockname()[1])


@contextmanager
def refused_smtp_connection(monkeypatch, port: int):
    """Refuse only one SMTP connect, independently of the host's closed-port behavior.

    A bound, non-listening port times out on some hosts. Patch smtplib's external
    connection seam only during the intended failure attempt; real sink sends remain
    real, and unrelated ports still use smtplib normally.
    """
    real_connect = smtplib.SMTP.connect
    refused_port = port

    def connect(self, host="localhost", port=0, source_address=None):
        if host == "127.0.0.1" and port == refused_port:
            raise ConnectionRefusedError(errno.ECONNREFUSED, "SMTP port refused the connection")
        return real_connect(self, host, port, source_address)

    with monkeypatch.context() as patch:
        patch.setattr(smtplib.SMTP, "connect", connect)
        yield
