"""Navigation DNS seam in GovernedBrowser.run_step must leave the event loop.

H15.1 follow-up: BrowserPolicy.domain_allowed -> check_ssrf resolves DNS
synchronously; called inline from async ``run_step`` it stalls the loop under a
slow resolver. These tests pin the seam by OS thread identity (spy on
socket.getaddrinfo, fully offline) and prove verdicts are unchanged across the
offload.
"""
import socket
import sys
import threading
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.browser_agent import (  # noqa: E402
    BrowserPolicy,
    GovernedBrowser,
    NullBrowserDriver,
)

# Documentation-range address; never dialed (NullBrowserDriver only records).
_PUBLIC_IP = "203.0.113.10"


def _fake_getaddrinfo(ips):
    def fake(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    return fake


async def test_navigate_dns_seam_runs_off_event_loop(monkeypatch):
    loop_tids = set()
    seam_tids = []

    def spy_getaddrinfo(*args, **kwargs):
        seam_tids.append(threading.get_ident())
        return _fake_getaddrinfo([_PUBLIC_IP])(*args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", spy_getaddrinfo)

    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["example.test"]))

    async def probe():
        loop_tids.add(threading.get_ident())
        return await gb.run_step(
            {"action": "navigate", "url": "https://example.test/page"}
        )

    res = await probe()

    assert seam_tids, "resolver seam was never exercised"
    assert all(t not in loop_tids for t in seam_tids), (
        f"DNS executed on the event-loop thread: seam={seam_tids} loop={sorted(loop_tids)}"
    )
    assert res["status"] == "done"
    assert [c[0] for c in drv.calls] == ["navigate"]


async def test_navigate_verdict_unchanged_private_ip_still_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["10.1.2.3"]))
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["internal.test"]))
    res = await gb.run_step({"action": "navigate", "url": "https://internal.test/x"})
    assert res["status"] == "blocked"
    assert "private" in res["reason"].lower()
    assert drv.calls == []


async def test_navigate_verdict_unchanged_resolver_failure_still_dispatches(monkeypatch):
    # check_ssrf treats resolver failure as a non-block (the fetch fails on its
    # own); moving the gate to a worker thread must keep that contract.
    def failing(*args, **kwargs):
        raise socket.gaierror(-2, "name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", failing)
    drv = NullBrowserDriver()
    gb = GovernedBrowser(driver=drv, policy=BrowserPolicy(["missing.test"]))
    res = await gb.run_step({"action": "navigate", "url": "https://missing.test/x"})
    assert res["status"] == "done"
    assert [c[0] for c in drv.calls] == ["navigate"]
