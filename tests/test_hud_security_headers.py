"""AUD-3 — the HUD ships security headers (CSP + anti-clickjacking + nosniff).

Defense-in-depth behind the output escaping in index.html: even if a sink were
missed, the CSP blocks external script loads, plugins/objects and cross-origin
framing. These assert the headers are attached to every response by the
_security_headers middleware.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from fastapi.testclient import TestClient

from agents import web


def test_security_headers_present_on_response():
    client = TestClient(web.app)
    resp = client.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"


def test_csp_present_and_locks_down_dangerous_sources():
    client = TestClient(web.app)
    csp = client.get("/").headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp          # no plugins/embeds
    assert "frame-ancestors 'self'" in csp     # no cross-origin clickjacking
    assert "base-uri 'self'" in csp


def test_csp_allows_hud_inline_script_and_style():
    # The HUD has an inline <script> and <style>; a strict policy without
    # 'unsafe-inline' would white-screen it, so the policy must keep them.
    client = TestClient(web.app)
    csp = client.get("/").headers.get("Content-Security-Policy", "")
    assert "script-src 'self' 'unsafe-inline'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
