"""Regression tests for two 2026-07-15 fresh-eyes audit findings not covered by
the security-correctness wave (the LLM/guardrails/autonomy findings were fixed
separately on main):

  - email channel: constructor must accept the config shape the wiring passes.
  - XFF rate-limit: X-Forwarded-For is only trusted behind a configured proxy.

Each test fails on the pre-fix code and passes after.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


# ── XFF rate-limit trust (web.py) ─────────────────────────────────────────────

def _fake_request(headers: dict, peer: str):
    class _Client:
        host = peer

    class _Req:
        def __init__(self):
            self.headers = {k.lower(): v for k, v in headers.items()}
            self.client = _Client()

    return _Req()


def test_client_ip_ignores_spoofed_xff_without_trusted_proxy(monkeypatch):
    import agents.web as web
    monkeypatch.delenv("JARVIS_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("JARVIS_TRUSTED_PROXY", raising=False)
    req = _fake_request({"X-Forwarded-For": "127.0.0.1"}, peer="203.0.113.9")
    # Must fall back to the unspoofable socket peer, not the forged header.
    assert web._client_ip(req) == "203.0.113.9"
    # Hermes absorption 5b: a configured list trusts ONLY the peers inside it — the
    # same forged header from a peer outside the list still resolves to the peer.
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1/32")
    assert web._client_ip(req) == "203.0.113.9"


def test_client_ip_honors_xff_when_proxy_trusted(monkeypatch):
    import agents.web as web
    monkeypatch.setenv("JARVIS_TRUSTED_PROXIES", "10.0.0.1/32")
    req = _fake_request({"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}, peer="10.0.0.1")
    assert web._client_ip(req) == "198.51.100.7"
