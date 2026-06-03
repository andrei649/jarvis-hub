"""Tests for H10.1 — Embeddable Chat Widget."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.widget import WidgetStore, render_snippet


# ── store ────────────────────────────────────────────────────────────────────

def test_issue_applies_defaults_and_overrides(tmp_path):
    s = WidgetStore(path=tmp_path / "w.json")
    w = s.issue({"title": "Support", "color": "#ff0000", "bogus": "x"})
    assert w["title"] == "Support" and w["color"] == "#ff0000"
    assert w["position"] == "bottom-right"          # default
    assert "bogus" not in w                          # unknown keys dropped
    assert w["token"]


def test_get_update_revoke_persistence(tmp_path):
    p = tmp_path / "w.json"
    s = WidgetStore(path=p)
    w = s.issue({"title": "A"})
    tok = w["token"]
    assert s.update(tok, {"title": "B"})["title"] == "B"
    assert WidgetStore(path=p).get(tok)["title"] == "B"   # persisted
    assert s.revoke(tok) is True
    assert WidgetStore(path=p).get(tok) is None
    assert s.revoke("nope") is False


# ── snippet rendering ────────────────────────────────────────────────────────

def test_render_snippet_embeds_token_and_theme():
    cfg = {"token": "abc123", "title": "Help", "color": "#123456",
           "position": "bottom-left", "greeting": "hey"}
    js = render_snippet(cfg, base_url="https://x.test")
    assert 'T="abc123"' in js
    assert 'BASE="https://x.test"' in js
    assert "#123456" in js and "Help" in js
    assert "/api/widget/" in js                      # posts to token endpoint


# ── endpoints ────────────────────────────────────────────────────────────────

def test_widget_endpoints():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    hdr = {"X-Admin-Token": "test-secret"}
    try:
        with TestClient(web.app) as c:
            if getattr(web.orch, "widgets", None) is None:
                return
            # issue requires admin
            assert c.post("/api/admin/widgets", json={"title": "T"}).status_code == 401
            issued = c.post("/api/admin/widgets", json={"title": "T", "color": "#0a0"}, headers=hdr)
            assert issued.status_code == 200
            tok = issued.json()["widget"]["token"]

            # public JS snippet
            js = c.get(f"/api/widget/{tok}")
            assert js.status_code == 200
            assert "application/javascript" in js.headers["content-type"]
            assert tok in js.text

            # public config + unknown token 404
            assert c.get(f"/api/widget/{tok}/config").json()["title"] == "T"
            assert c.get("/api/widget/nope").status_code == 404

            # message endpoint: bad token 404, empty message 400
            assert c.post("/api/widget/nope/message", json={"message": "hi"}).status_code == 404
            assert c.post(f"/api/widget/{tok}/message", json={}).status_code == 400
            # valid message returns a reply envelope (reply or error, never crash)
            r = c.post(f"/api/widget/{tok}/message", json={"message": "hello"})
            assert r.status_code == 200 and ("reply" in r.json())

            # revoke
            assert c.delete(f"/api/admin/widgets/{tok}", headers=hdr).status_code == 200
            assert c.get(f"/api/widget/{tok}").status_code == 404
    finally:
        web.ADMIN_TOKEN = old
