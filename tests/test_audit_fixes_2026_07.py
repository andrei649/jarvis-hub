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


# ── email channel constructor (channels/email.py + web.py wiring) ─────────────

def test_email_channel_accepts_config_dicts():
    from agents.core.channels.email import EmailChannel
    # The shape agents/web.py wires. Pre-fix web.py passed smtp_host=... kwargs,
    # which this constructor rejects — proving that branch never ran.
    ch = EmailChannel(
        handler=lambda *a, **k: None,
        smtp_config={"host": "smtp.example.com", "port": 587, "user": "u", "password": "p"},
        imap_config={"host": "imap.example.com", "port": 993, "user": "u", "password": "p"},
    )
    assert ch.smtp["host"] == "smtp.example.com"
    assert ch.imap["port"] == 993


def test_web_wiring_uses_config_dicts_not_flat_kwargs():
    # Guard the call site: the wiring must not regress to smtp_host= kwargs
    # (which raise TypeError against EmailChannel.__init__ at startup).
    src = (repo_root / "agents" / "web.py").read_text()
    assert "smtp_config={" in src, "web.py must build an smtp_config dict"
    assert "smtp_host=smtp_host" not in src, "flat smtp_host= kwargs crash EmailChannel at startup"


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
    monkeypatch.setattr(web, "TRUSTED_PROXY", False, raising=False)
    req = _fake_request({"X-Forwarded-For": "127.0.0.1"}, peer="203.0.113.9")
    # Must fall back to the unspoofable socket peer, not the forged header.
    assert web._client_ip(req) == "203.0.113.9"


def test_client_ip_honors_xff_when_proxy_trusted(monkeypatch):
    import agents.web as web
    monkeypatch.setattr(web, "TRUSTED_PROXY", True, raising=False)
    req = _fake_request({"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}, peer="10.0.0.1")
    assert web._client_ip(req) == "198.51.100.7"
