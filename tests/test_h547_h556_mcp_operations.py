"""H547 / H556 — the per-server operational keys, TLS options, stdio recycling and process
groups of the MCP client.

Owner's side: a server can be given its own request and connect timeouts, keepalive,
idle and lifetime recycling, a private CA bundle or a client certificate (never "verify
off"), and a parallel-call opt-in; all of it is checked when it is added or reloaded and
saved back unchanged. A stdio server that sits unused is stopped and comes back on its next
call; one past its lifetime is restarted; a launcher and the server it started stop
together; a group a crashed hub left behind is stopped at the next start, and a recycled
pid is never touched.
"""
from __future__ import annotations

import asyncio
import datetime
import os
import ssl
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core.http_client import PluginHTTPClient
from agents.core.mcp import process_guard
from agents.core.mcp import resources as res_mod
from agents.core.mcp.client import MCPManager, MCPServer, operational_options
from agents.core.mcp.http_transport import MCPTransportError, tls_context
from agents.core.mcp.model_bridge import MCPModelBridge
from agents.core.mcp.resilience import STATE_RECYCLED
from agents.core.mcp.saved_reload import SavedReloadRefused, candidates

FAKE = Path(__file__).resolve().parent / "fixtures" / "mcp_fake_server.py"
LINUX = sys.platform.startswith("linux")


def _cmd(mode: str = "full") -> str:
    return f"{sys.executable} {FAKE} {mode}"


@pytest.fixture(autouse=True)
def _no_estop(monkeypatch, tmp_path):
    monkeypatch.setattr("agents.core.estop.is_engaged", lambda: False)
    monkeypatch.setattr(res_mod, "cache_dir", lambda server: tmp_path / "mcp_cache" / server)


@pytest.fixture
async def mgr():
    manager = MCPManager()
    yield manager
    await manager.close_all()


# ── parsing ─────────────────────────────────────────────────────────────────


def test_numeric_keys_are_bounded_and_keepalive_is_floored():
    opts, refused = operational_options({"timeout": 300, "connect_timeout": 60,
                                         "keepalive_interval": 1, "idle_timeout_seconds": 600,
                                         "max_lifetime_seconds": 3600}, strict=True)
    assert refused is None
    assert opts == {"timeout": 300.0, "connect_timeout": 60.0, "keepalive_interval": 5.0,
                    "idle_timeout_seconds": 600.0, "max_lifetime_seconds": 3600.0}
    for bad in ({"timeout": 0}, {"timeout": -1}, {"timeout": True}, {"timeout": "10"},
                {"timeout": 99999}, {"connect_timeout": float("nan")},
                {"supports_parallel_tool_calls": "yes"}):
        assert operational_options(bad, strict=True) == ({}, f"invalid_option:{next(iter(bad))}")


def test_lenient_load_drops_a_malformed_key_and_keeps_the_rest():
    opts, refused = operational_options({"name": "s", "timeout": "x", "connect_timeout": 45})
    assert refused is None and opts == {"connect_timeout": 45.0}


def test_tls_keys_never_turn_verification_off():
    assert operational_options({"ssl_verify": False}, strict=True) == ({}, "invalid_option:ssl_verify")
    assert operational_options({"ssl_verify": "relative/ca.pem"}, strict=True)[1] == "invalid_option:ssl_verify"
    assert operational_options({"ssl_verify": True}, strict=True) == ({}, None)
    assert operational_options({"ssl_verify": "/etc/ca.pem"}, strict=True)[0] == {"ssl_verify": "/etc/ca.pem"}
    assert operational_options({"client_cert": "/c.pem", "client_key": "/k.pem"},
                               strict=True)[0] == {"client_cert": ["/c.pem", "/k.pem"]}
    assert operational_options({"client_cert": ["/both.pem"]}, strict=True)[0] == {"client_cert": ["/both.pem"]}
    assert operational_options({"client_cert": ["/c", "/k", "pw"]}, strict=True)[1] == "invalid_option:client_cert"
    assert operational_options({"client_key": "/k.pem"}, strict=True)[1] == "invalid_option:client_key"
    with pytest.raises(TypeError):
        PluginHTTPClient("mcp:x", verify=False)


def test_options_round_trip_through_the_saved_list():
    srv = MCPServer("s", command="srv", options={"timeout": 120, "idle_timeout_seconds": 300,
                                                 "supports_parallel_tool_calls": True})
    assert srv.request_timeout == 120.0 and srv.idle_timeout == 300.0
    assert srv.supports_parallel_tool_calls is True
    mgr = MCPManager()
    mgr.servers["s"] = srv
    row = mgr.to_config()[0]
    assert row["timeout"] == 120.0 and row["supports_parallel_tool_calls"] is True
    back = MCPManager()
    back.load_from_config([row])
    assert back.servers["s"].options == srv.options
    parsed, _ = candidates([row])
    assert parsed["s"].options == srv.options


def test_saved_reload_refuses_malformed_or_misplaced_options():
    base = {"name": "s", "transport": "stdio", "command": "srv", "trust": "read-only"}
    for extra in ({"ssl_verify": False}, {"timeout": 0}, {"ssl_verify": "/etc/ca.pem"},
                  {"client_cert": "/c.pem"}):
        with pytest.raises(SavedReloadRefused):
            candidates([{**base, **extra}])
    http = {"name": "h", "transport": "streamable-http", "url": "https://mcp.example.test/mcp",
            "trust": "read-only", "ssl_verify": "/etc/ca.pem", "client_cert": ["/c.pem", "/k.pem"]}
    parsed, _ = candidates([http])
    assert parsed["h"].options == {"ssl_verify": "/etc/ca.pem", "client_cert": ["/c.pem", "/k.pem"]}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h547-admin")
    monkeypatch.setattr(web, "_save_mcp_config", lambda: None)
    orch = MagicMock()
    orch.mcp.servers = {}
    monkeypatch.setattr(web, "orch", orch)
    return TestClient(web.app), orch


def test_admin_add_takes_options_and_refuses_bad_ones(api):
    client, orch = api
    hdr = {"X-Admin-Token": "h547-admin"}
    ok = client.post("/api/admin/mcp", headers=hdr, json={
        "name": "slow", "command": "slow-mcp", "timeout": 300, "connect_timeout": 60,
        "keepalive_interval": 2, "max_lifetime_seconds": 86400})
    assert ok.status_code == 200
    srv = orch.mcp.servers["slow"]
    assert srv.request_timeout == 300.0 and srv.connect_timeout == 60.0 and srv.keepalive_interval == 5.0
    off = client.post("/api/admin/mcp", headers=hdr, json={
        "name": "h", "transport": "streamable-http", "url": "https://mcp.example.test/mcp",
        "ssl_verify": False})
    assert off.status_code == 400 and off.json() == {"error": "invalid_option", "option": "ssl_verify"}
    stdio_tls = client.post("/api/admin/mcp", headers=hdr, json={
        "name": "s2", "command": "x-mcp", "client_cert": "/c.pem"})
    assert stdio_tls.status_code == 400 and stdio_tls.json()["option"] == "client_cert"
    http = client.post("/api/admin/mcp", headers=hdr, json={
        "name": "h2", "transport": "streamable-http", "url": "https://mcp.example.test/mcp",
        "ssl_verify": "/etc/ssl/private-ca.pem"})
    assert http.status_code == 200 and orch.mcp.servers["h2"].options == {"ssl_verify": "/etc/ssl/private-ca.pem"}
    listed = client.get("/api/admin/mcp", headers=hdr).json()["servers"]
    assert {r["name"]: r["options"] for r in listed}["slow"]["timeout"] == 300.0


# ── TLS material ────────────────────────────────────────────────────────────


def _self_signed(tmp_path: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nerva-test-client")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "client.pem", tmp_path / "client.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


def test_tls_context_adds_a_ca_and_a_client_certificate_and_still_verifies(tmp_path):
    cert, key = _self_signed(tmp_path)
    ctx = tls_context(str(cert), [str(cert), str(key)])
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert any(c.get("subject") == ((("commonName", "nerva-test-client"),),) for c in ctx.get_ca_certs())
    with pytest.raises(MCPTransportError) as missing:
        tls_context(str(tmp_path / "nope.pem"))
    assert missing.value.reason == "tls_config" and missing.value.detail == "ca_bundle_missing"
    with pytest.raises(MCPTransportError) as bad:
        tls_context(None, [str(key)])          # a key is not a certificate
    assert bad.value.detail == "client_cert_unreadable"


async def test_http_connect_passes_timeout_and_tls_and_refuses_bad_material(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MCP_HTTP_CLIENT", "1")
    seen = {}

    class Fake:
        initialized = True

        def __init__(self, url, headers, *, name, **kw):
            seen.update(kw)

        async def initialize(self):
            return {"capabilities": {}}

        async def request(self, method, params, max_bytes=None):
            return {"result": {"tools": [{"name": "t", "inputSchema": {"type": "object"}}]}}

        async def close(self):
            pass

    cert, key = _self_signed(tmp_path)
    srv = MCPServer("h", transport="streamable-http", url="https://mcp.example.test/mcp",
                    http_transport_factory=Fake, trust="full",
                    options={"timeout": 120, "ssl_verify": str(cert), "client_cert": [str(cert), str(key)]})
    assert await srv.connect() is True
    assert seen["timeout"] == 120.0 and isinstance(seen["verify"], ssl.SSLContext)
    plain = MCPServer("p", transport="streamable-http", url="https://mcp.example.test/mcp",
                      http_transport_factory=Fake, trust="full")
    seen.clear()
    assert await plain.connect() is True and seen == {}
    broken = MCPServer("b", transport="streamable-http", url="https://mcp.example.test/mcp",
                       http_transport_factory=Fake, trust="full",
                       options={"ssl_verify": str(tmp_path / "missing.pem")})
    assert await broken.connect() is False
    assert broken.last_error == "tls_config:ca_bundle_missing" and broken.health.state == "refused"


# ── recycling and keepalive ─────────────────────────────────────────────────


async def test_idle_server_is_stopped_and_comes_back_on_its_next_call(mgr):
    srv = MCPServer("docs", command=_cmd(), trust="full", options={"idle_timeout_seconds": 30})
    mgr.register(srv)
    await mgr.connect_all()
    first_pid = srv._proc.pid
    mgr.keepalive_interval = 0.0
    now = time.time()
    assert await mgr.tick(now=now) == {"docs": "ping_ok"}
    # The keepalive did not count as use: thirty seconds later the server is idle.
    assert await mgr.tick(now=srv._last_io + 31) == {"docs": "recycled_idle"}
    assert not srv.is_connected() and srv.health.state == STATE_RECYCLED
    # The supervisor leaves it down …
    assert await mgr.tick(now=srv._last_io + 40) == {}
    # … and the next call brings it back.
    out = await mgr.call_tool("echo", {"a": 1}, server="docs")
    assert out["content"] and srv.is_connected() and srv._proc.pid != first_pid
    assert srv.health.counters.get("recycled_idle") == 1


async def test_server_past_its_lifetime_is_restarted_in_the_same_pass(mgr):
    srv = MCPServer("docs", command=_cmd(), trust="full", options={"max_lifetime_seconds": 60})
    mgr.register(srv)
    await mgr.connect_all()
    first_pid = srv._proc.pid
    done = await mgr.tick(now=srv._spawned_at + 61)
    assert done == {"docs": "reconnected"}
    assert srv.is_connected() and srv._proc.pid != first_pid
    assert srv.health.counters.get("recycled_lifetime") == 1


async def test_per_server_keepalive_interval(mgr):
    srv = MCPServer("docs", command=_cmd(), trust="full", options={"keepalive_interval": 300})
    mgr.register(srv)
    await mgr.connect_all()
    mgr.keepalive_interval = 0.0           # the manager default would ping every pass
    now = time.time()
    assert await mgr.tick(now=now) == {"docs": "ping_ok"}
    assert await mgr.tick(now=now + 10) == {}
    assert await mgr.tick(now=now + 301) == {"docs": "ping_ok"}


def test_parallel_opt_in_covers_only_read_only_tools():
    from agents.core.mcp.client import MCPTool

    srv = MCPServer("s", command="srv", trust="full", options={"supports_parallel_tool_calls": True})
    srv.tools = [MCPTool("read", "Read.", {"type": "object"}, "s", annotations={"readOnlyHint": True}),
                 MCPTool("write", "Write.", {"type": "object"}, "s")]
    mgr = MCPManager()
    mgr.servers["s"] = srv
    rows = {r["tool"]: r for r in mgr.model_tools()}
    assert rows["read"]["parallel_safe"] is True and rows["write"]["parallel_safe"] is False
    srv.supports_parallel_tool_calls = False
    assert all(r["parallel_safe"] is False for r in mgr.model_tools())

    registered = {}
    rpc = MagicMock()
    rpc.tools.return_value = []
    rpc.allows.return_value = False
    rpc.register_tool.side_effect = lambda name, handler, **kw: registered.__setitem__(name, kw)
    srv.supports_parallel_tool_calls = True
    asyncio.run(MCPModelBridge(rpc, lambda: mgr).sync())
    by_tool = {k.rsplit("__", 1)[-1]: v for k, v in registered.items()}
    assert by_tool["read"]["parallel_safe"] is True and by_tool["write"]["parallel_safe"] is False


# ── process groups, orphan reaper, discovery lock ───────────────────────────


def _children(pid: int) -> list[int]:
    try:
        text = Path(f"/proc/{pid}/task/{pid}/children").read_text()
    except OSError:
        return []
    return [int(p) for p in text.split()]


def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat[stat.rfind(")") + 2:].split()[0] != "Z"


@pytest.mark.skipif(not LINUX, reason="process groups are read from /proc")
async def test_a_launcher_and_the_server_it_started_stop_together(mgr):
    # A launcher that starts the real server as its child (as npx and uvx do). No ';' —
    # a shell metacharacter would refuse the command.
    launcher = (f"{sys.executable} -c \"__import__('sys').exit(__import__('subprocess').call("
                f"[__import__('sys').executable,'{FAKE}','full']))\"")
    srv = MCPServer("wrapped", command=launcher, trust="full")
    mgr.register(srv)
    assert srv.config_findings() == []
    await mgr.connect_all()
    assert srv.is_connected()
    leader = srv._proc.pid
    assert os.getpgid(leader) == leader          # its own group
    deadline = time.monotonic() + 5
    while not _children(leader) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    (child,) = _children(leader)
    proc = srv._proc
    await process_guard.terminate_group(proc, grace=2.0)
    deadline = time.monotonic() + 3
    while _alive(child) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert not _alive(child)
    srv._proc = None


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(["sleep", "30"], start_new_session=True)  # noqa: S603,S607 - test child


@pytest.mark.skipif(not LINUX, reason="start times are read from /proc")
def test_reaper_stops_only_the_recorded_process_of_a_dead_hub(tmp_path, monkeypatch):
    orphan, stranger = _sleeper(), _sleeper()
    try:
        process_guard.record(orphan.pid, "left-behind", root=tmp_path)
        process_guard.record(stranger.pid, "pid-reused", root=tmp_path)
        import json
        rows = json.loads((tmp_path / process_guard.REGISTRY_NAME).read_text())
        dead_hub = subprocess.Popen(["true"])  # noqa: S603,S607 - a pid that is gone
        dead_hub.wait()
        for key in rows:
            rows[key]["hub_pid"] = dead_hub.pid
        rows[str(stranger.pid)]["start"] = rows[str(stranger.pid)]["start"] + 1   # not the same process
        (tmp_path / process_guard.REGISTRY_NAME).write_text(json.dumps(rows))
        monkeypatch.setattr(process_guard, "GRACE_SECONDS", 2.0)
        stopped = process_guard.reap_orphans(root=tmp_path)
        assert stopped == [orphan.pid]
        assert orphan.wait(timeout=5) is not None
        assert stranger.poll() is None
        assert json.loads((tmp_path / process_guard.REGISTRY_NAME).read_text()) == {}
    finally:
        for p in (orphan, stranger):
            if p.poll() is None:
                p.kill()
                p.wait()


@pytest.mark.skipif(not LINUX, reason="start times are read from /proc")
def test_reaper_keeps_records_of_a_live_hub(tmp_path):
    child = _sleeper()
    try:
        process_guard.record(child.pid, "mine", root=tmp_path)
        assert process_guard.reap_orphans(root=tmp_path) == []
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


@pytest.mark.skipif(os.name != "posix", reason="flock")
async def test_discovery_lock_is_exclusive_and_bounded(tmp_path):
    async with process_guard.discovery_lock(root=tmp_path, wait=1.0) as first:
        assert first is True
        code = ("import fcntl,os,sys; fd=os.open(sys.argv[1], os.O_RDWR); "
                "fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)")
        other = subprocess.run([sys.executable, "-c", code, str(tmp_path / process_guard.LOCK_NAME)],  # noqa: S603
                               capture_output=True, timeout=10)
        assert other.returncode != 0                 # another process cannot take it
        async with process_guard.discovery_lock(root=tmp_path, wait=0.3) as second:
            assert second is False                   # same-process second holder times out
    async with process_guard.discovery_lock(root=tmp_path, wait=0.3) as again:
        assert again is True
