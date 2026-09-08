"""Hermes absorption 5b — the Host-header guard against DNS rebinding.

A page on evil.example whose name is re-pointed at this box reaches the API from
the victim's browser with a loopback origin; its Host header carries the
attacker's name and nothing legitimate ever does. The guard refuses such a
request before the rate limiter and every route, accepts loopback names, IP
literals, the bound / arrival address and JARVIS_ALLOWED_HOSTS, exempts the
probes, and never echoes the header.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.core import host_policy  # noqa: E402

EVIL = "evil.example"
ROUTE = "/status"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("JARVIS_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("JARVIS_HOST", raising=False)
    monkeypatch.setattr(host_policy, "_memo_key", None)
    monkeypatch.setattr(web, "_host_refusals", 0, raising=False)
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 0)


def _client():
    return TestClient(web.app, raise_server_exceptions=True)  # lifespan NOT started


def _raw_asgi_get(path: str, headers: list[tuple[bytes, bytes]], *, client=("127.0.0.1", 50000)):
    """Drive the app with a hand-built scope so a header can be truly absent and the
    socket peer can be chosen (TestClient's peer is the name "testclient")."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": headers, "client": client, "server": ("127.0.0.1", 8000),
    }
    result = {"body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            result["code"] = message["status"]
        elif message["type"] == "http.response.body":
            result["body"] += message.get("body", b"")

    asyncio.run(web.app(scope, receive, send))
    return result["code"], result["body"].decode()


def test_evil_host_from_loopback_peer_is_400(caplog):
    # The rebinding case proper: the victim's browser on the same box, so the socket
    # peer is loopback and the log line says so — and never the Host value.
    with caplog.at_level(logging.WARNING, logger="jarvis.web"):
        code, body = _raw_asgi_get(ROUTE, [(b"host", EVIL.encode())], client=("127.0.0.1", 50000))
    assert code == 400
    assert json.loads(body) == {"error": "host not allowed", "code": 400}
    assert EVIL not in body
    refusals = [rec.getMessage() for rec in caplog.records if "Host header refused" in rec.getMessage()]
    assert refusals and "peer class loopback" in refusals[0]
    assert EVIL not in caplog.text
    # The same from a network peer (TestClient's peer is the name "testclient").
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="jarvis.web"):
        r = _client().get(ROUTE, headers={"host": EVIL})
    assert r.status_code == 400
    assert r.json() == {"error": "host not allowed", "code": 400}
    assert EVIL not in r.text
    assert any("peer class network" in rec.getMessage() for rec in caplog.records)
    assert EVIL not in caplog.text
    # The 400 still carries the security headers (the guard sits inside that layer).
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.parametrize("host, refused", [
    ("localhost:8000", False), ("127.0.0.1:8000", False), ("[::1]:8000", False),
    ("192.168.1.20:8000", False), ("LOCALHOST", False), ("localhost.", False),
    ("[fd00::5]", False), ("0.0.0.0:8000", False),
    # … paired with the shapes that must be refused, so the guard's absence shows.
    (EVIL, True), ("localhost:abc", True), ("localhost:8000:9000", True),
    ("127.0.0.1.evil.example", True), ("[::1]x", True),
])
def test_localhost_with_port_and_ip_literals_are_accepted(host, refused):
    assert (_client().get(ROUTE, headers={"host": host}).status_code == 400) is refused


def test_asgi_server_host_is_accepted():
    # TestClient's default Host is "testserver", which is also scope["server"][0].
    assert _client().get(ROUTE).status_code != 400
    assert _client().get(ROUTE, headers={"host": "testserver:80"}).status_code != 400
    # A name that merely contains the server host is not the server host.
    assert _client().get(ROUTE, headers={"host": "testserver.evil.example"}).status_code == 400


def test_bind_host_is_accepted(monkeypatch):
    monkeypatch.setenv("JARVIS_HOST", "nerva-box.lan")
    assert _client().get(ROUTE, headers={"host": "nerva-box.lan:8000"}).status_code != 400
    assert _client().get(ROUTE, headers={"host": EVIL}).status_code == 400


def test_allowed_hosts_entry_is_accepted(monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOWED_HOSTS", "nerva.tail.ts.net")
    assert _client().get(ROUTE, headers={"host": "nerva.tail.ts.net:443"}).status_code != 400
    assert _client().get(ROUTE, headers={"host": "Nerva.Tail.TS.NET."}).status_code != 400
    assert _client().get(ROUTE, headers={"host": EVIL}).status_code == 400
    # A subdomain is not the listed name.
    assert _client().get(ROUTE, headers={"host": "x.nerva.tail.ts.net"}).status_code == 400


def test_wildcard_in_allowed_hosts_refuses_boot():
    for raw in ("*", "*.example.com", ".example.com", "https://a.example", "a.example/path",
                "localhost:8000:9000", "::ffff:127.0.0.1:8000"):
        with pytest.raises(SystemExit) as ei:
            host_policy.assert_parseable_allowed_hosts({"JARVIS_ALLOWED_HOSTS": raw})
        assert "JARVIS_ALLOWED_HOSTS" in str(ei.value)
        assert raw not in str(ei.value)
    too_many = ",".join(f"h{i}.example" for i in range(host_policy.MAX_HOSTS + 1))
    with pytest.raises(SystemExit, match="JARVIS_ALLOWED_HOSTS: too many entries"):
        host_policy.assert_parseable_allowed_hosts({"JARVIS_ALLOWED_HOSTS": too_many})
    host_policy.assert_parseable_allowed_hosts({})
    host_policy.assert_parseable_allowed_hosts({"JARVIS_ALLOWED_HOSTS": " "})
    host_policy.assert_parseable_allowed_hosts({"JARVIS_ALLOWED_HOSTS": "a.example, B.example:8443"})
    assert host_policy.parse_allowed_hosts("a.example, B.example:8443, a.example") == ("a.example", "b.example")


def test_malformed_allowed_hosts_at_request_time_accepts_no_extra_names(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_ALLOWED_HOSTS", "*")
    with caplog.at_level(logging.WARNING, logger="jarvis.host_policy"):
        assert host_policy.allowed_hosts() == ()
        assert host_policy.allowed_hosts() == ()
    assert sum("JARVIS_ALLOWED_HOSTS" in r.getMessage() for r in caplog.records) == 1
    assert _client().get(ROUTE, headers={"host": EVIL}).status_code == 400


def test_healthz_from_any_host_is_exempt():
    assert _client().get("/healthz", headers={"host": EVIL}).status_code != 400
    assert _client().get(ROUTE, headers={"host": EVIL}).status_code == 400


def test_host_guard_runs_before_the_rate_limiter(monkeypatch):
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(web, "USER_TOKEN", "")
    calls = []

    def _recording(ip, now):
        calls.append(ip)
        return False

    monkeypatch.setattr(web, "_rate_limited", _recording)
    assert _client().get(ROUTE, headers={"host": EVIL}).status_code == 400
    assert calls == []  # a refused Host never reaches a rate bucket
    assert _client().get(ROUTE).status_code != 400
    assert calls  # the accepted request from the non-localhost test peer did


def test_missing_host_header_is_refused_except_probes():
    assert _raw_asgi_get(ROUTE, [])[0] == 400
    assert _raw_asgi_get(ROUTE, [(b"host", b"")])[0] == 400
    assert _raw_asgi_get(ROUTE, [(b"host", b"localhost")])[0] != 400
    assert _raw_asgi_get("/healthz", [])[0] != 400


def test_normalize_host_shapes():
    n = host_policy.normalize_host
    assert n(" Example.COM. ") == "example.com"
    assert n("[::1]:8000") == "::1"
    assert n("::1") == "::1"
    assert n("localhost:8000") == "localhost"
    # Several colons are an IPv6 literal or nothing: a typo must not become an
    # allowlist entry that never matches a real request.
    assert n("fd00::5") == "fd00::5"
    for garbage in ("", "localhost:abc", "[::1", "[::1]x", "a/b", "user@host", "a b", "x" * 300,
                    "localhost:8000:9000", "::ffff:127.0.0.1:8000", "a:b:c"):
        assert n(garbage) == ""
    assert host_policy.is_ip_literal("::1") and host_policy.is_ip_literal("10.0.0.1")
    assert not host_policy.is_ip_literal("localhost")
    assert host_policy.host_accepted(EVIL, bind_host="127.0.0.1", server_host="", allowed=()) is False
    assert host_policy.host_accepted(EVIL, bind_host="127.0.0.1", server_host="", allowed=(EVIL,)) is True
