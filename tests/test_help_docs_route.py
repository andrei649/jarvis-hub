"""H165 — in-app documentation, served read-only from an allowlist.

Hermes ships its user documentation inside the app. Nerva's user guide, flag table and
privacy notes lived only in the repository, so a HUD user had no way to read what a
flag costs or what the camera keeps without leaving the product. The docs route
serves a hard-coded slug → file table: the slug is only ever a dictionary key, never
joined into a path, so '../', encoded traversal and unknown slugs are all 404. The
body is Markdown text for the HUD's React-only renderer, never HTML.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
from agents import web  # noqa: E402
from agents.core.routers import help_docs  # noqa: E402

TOKEN = "help-docs-test-only"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    monkeypatch.setattr(web, "USER_TOKEN", TOKEN)
    monkeypatch.setenv("JARVIS_USER_TOKEN", TOKEN)
    return TestClient(web.app, headers={"X-User-Token": TOKEN})


def test_the_list_names_every_allowlisted_doc(client):
    reply = client.get("/api/help/docs")
    assert reply.status_code == 200 and "no-store" in reply.headers["cache-control"]
    docs = reply.json()["docs"]
    assert [d["slug"] for d in docs] == ["user-guide", "flags", "privacy", "camera-privacy"]
    assert all(d["available"] is True and d["title"] for d in docs)


@pytest.mark.parametrize("slug,path", [
    ("user-guide", "docs/USER_GUIDE.md"),
    ("flags", "docs/FLAGS.md"),
    ("privacy", "docs/PRIVACY.md"),
    ("camera-privacy", "docs/CAMERA_PRIVACY.md"),
])
def test_each_allowlisted_doc_is_served_as_markdown_text(client, slug, path):
    reply = client.get(f"/api/help/docs/{slug}")
    assert reply.status_code == 200 and "no-store" in reply.headers["cache-control"]
    body = reply.json()
    assert body["slug"] == slug and body["title"]
    assert body["markdown"] == (ROOT / path).read_text(encoding="utf-8")
    assert body["truncated"] is False


@pytest.mark.parametrize("url", [
    "/api/help/docs/unknown",
    "/api/help/docs/USER_GUIDE.md",
    "/api/help/docs/..%2F..%2FREADME.md",
    "/api/help/docs/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/api/help/docs/..",
    "/api/help/docs/flags%00",
    "/api/help/docs/FLAGS",
])
def test_anything_off_the_allowlist_is_404(client, url):
    assert client.get(url).status_code == 404


def test_the_route_is_user_guarded(monkeypatch):
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    monkeypatch.setattr(web, "USER_TOKEN", TOKEN)
    monkeypatch.setenv("JARVIS_USER_TOKEN", TOKEN)
    anonymous = TestClient(web.app)
    assert anonymous.get("/api/help/docs").status_code == 401
    assert anonymous.get("/api/help/docs/flags").status_code == 401


def test_a_missing_file_is_reported_not_raised(client, monkeypatch):
    monkeypatch.setitem(help_docs.DOCS, "privacy", ("Privacy", "docs/NOT_SHIPPED.md"))
    listed = {d["slug"]: d for d in client.get("/api/help/docs").json()["docs"]}
    assert listed["privacy"]["available"] is False
    reply = client.get("/api/help/docs/privacy")
    assert reply.status_code == 404 and "not available" in reply.json()["error"]


def test_an_oversized_doc_is_capped_and_says_so(client, monkeypatch):
    monkeypatch.setattr(help_docs, "MAX_DOC_CHARS", 100)
    body = client.get("/api/help/docs/flags").json()
    assert body["truncated"] is True and len(body["markdown"]) == 100


def test_a_symlinked_doc_is_refused(client, monkeypatch, tmp_path):
    target = tmp_path / "secret.md"
    target.write_text("# not a doc\n", encoding="utf-8")
    link = tmp_path / "docs"
    link.mkdir()
    (link / "LINKED.md").symlink_to(target)
    monkeypatch.setattr(help_docs, "_ROOT", tmp_path)
    monkeypatch.setitem(help_docs.DOCS, "flags", ("Flags", "docs/LINKED.md"))
    assert client.get("/api/help/docs/flags").status_code == 404


ANCHORS = json.loads((ROOT / "tests" / "fixtures" / "heading_anchors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("heading,anchor", sorted(ANCHORS.items()))
def test_heading_anchors_match_the_hud_renderer(heading, anchor):
    # frontend/src/test/markdown.test.tsx checks headingAnchor against the same fixture.
    assert help_docs.heading_anchor(heading) == anchor


def test_the_list_carries_each_docs_sections_and_the_names_they_document(client):
    flags = next(d for d in client.get("/api/help/docs").json()["docs"] if d["slug"] == "flags")
    by_name = {name: s["anchor"] for s in flags["sections"] for name in s["names"]}
    assert by_name["llm.execute_code"] == "llm.execute_code"
    assert by_name["JARVIS_ACTION_KERNEL"] == "jarvis_action_kernel"
    assert by_name["llm.execute_code_image"].startswith("llm.execute_code_sessions")


def test_sections_skip_fenced_headings_and_number_repeats():
    text = "# Title\n```\n# not a heading\n```\n## `A`\n## `A`\n"
    assert [(s["anchor"], s["names"]) for s in help_docs.sections(text)] == [
        ("title", []), ("a", ["A"]), ("a-2", ["A"])]
