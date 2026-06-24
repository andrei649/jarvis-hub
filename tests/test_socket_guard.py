"""AUD-10 (F37): the pytest-socket loopback guard makes a stray *real* network
call in a test fail fast, while in-process TestClient requests keep working.

The guard is wired globally in pytest.ini (``--allow-hosts=127.0.0.1,::1,localhost``).
Before it, an accidental outbound call would hang until the ``--timeout`` backstop
(30s local / 90s CI) fired; now it raises immediately at ``connect()``.
"""

import socket
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_socket import SocketConnectBlockedError


def test_external_connect_is_blocked_fast():
    """A real outbound connect to a non-loopback host raises immediately —
    no TCP handshake, no hang to the timeout backstop. The address is never
    actually dialed (the guard fires before the syscall)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    start = time.monotonic()
    try:
        with pytest.raises(SocketConnectBlockedError):
            s.connect(("93.184.216.34", 80))  # example.com — never reached
        # Fails fast: well under both the local (30s) and CI (90s) --timeout.
        assert time.monotonic() - start < 1.0
    finally:
        s.close()


def test_loopback_connect_is_allowed():
    """Loopback is NOT blocked — the guard lets it reach a real connect (here
    refused, since nothing is listening on 127.0.0.1:1). This is what keeps
    localhost test doubles and real loopback servers working."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        with pytest.raises(OSError) as exc:
            s.connect(("127.0.0.1", 1))
        assert not isinstance(exc.value, SocketConnectBlockedError)
    finally:
        s.close()


def test_in_process_testclient_unaffected():
    """TestClient drives the app over an in-process ASGI transport (no real
    socket), so the loopback guard leaves every existing HTTP-route suite
    fully functional."""
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    resp = TestClient(app).get("/ping")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
