"""Tests for H10.28 — Agent Config Preview."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.config_preview import preview_change, validate_prompt


# ── validation ───────────────────────────────────────────────────────────────

def test_validate_empty_is_invalid():
    valid, warnings = validate_prompt("   ")
    assert valid is False and warnings


def test_validate_warnings():
    _, w = validate_prompt("short")          # < min len, no headings
    assert any("short" in x for x in w)
    valid, w2 = validate_prompt("# Mission\nDo good things for the user always.")
    assert valid is True and w2 == []


def test_validate_unbalanced_frontmatter():
    _, w = validate_prompt("---\ntitle: x\n# Mission\nlong enough content here yes")
    assert any("frontmatter" in x for x in w)


# ── diff / preview ───────────────────────────────────────────────────────────

def test_preview_counts_changes():
    p = preview_change("line1\nline2\n# H", "line1\nCHANGED\n# H")
    assert p["changed"] is True
    assert p["added_lines"] == 1 and p["removed_lines"] == 1
    assert "-line2" in p["diff"] and "+CHANGED" in p["diff"]
    assert p["is_new"] is False


def test_preview_new_when_no_current():
    p = preview_change("", "# Mission\nbrand new agent prompt content")
    assert p["is_new"] is True and p["changed"] is True
    assert p["removed_lines"] == 0


def test_preview_no_change():
    p = preview_change("same", "same")
    assert p["changed"] is False
    assert p["added_lines"] == 0 and p["removed_lines"] == 0


# ── endpoint (admin-guarded) ─────────────────────────────────────────────────

def test_preview_endpoint():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    hdr = {"X-Admin-Token": "test-secret"}
    try:
        with TestClient(web.app) as c:
            # auth required
            assert c.post("/api/admin/prompts/jarvis/preview",
                          json={"proposed": "x"}).status_code == 401
            # missing proposed → 400
            assert c.post("/api/admin/prompts/jarvis/preview",
                          json={}, headers=hdr).status_code == 400
            # explicit current + proposed → diff
            r = c.post("/api/admin/prompts/jarvis/preview",
                       json={"current": "# Mission\nold", "proposed": "# Mission\nnew better content"},
                       headers=hdr)
            assert r.status_code == 200
            body = r.json()
            assert body["changed"] is True and "diff" in body and "valid" in body
    finally:
        web.ADMIN_TOKEN = old
