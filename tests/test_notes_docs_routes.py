"""DRA-53 — HTTP surface for the block-tree notes store (agents/core/notes_store.py).

The store shipped fully tested but ADOPTED BY NOTHING: no route, no caller, no
way for a person to reach it. The roadmap's own framing was "adopt it behind a
route or delete it" (docs/DEVELOPMENT_ROADMAP.md). These pin the adoption:

  GET/POST     /api/notes/docs
  GET/DELETE   /api/notes/docs/{doc_id}
  POST         /api/notes/docs/{doc_id}/blocks
  PATCH/DELETE /api/notes/blocks/{block_id}

The load-bearing assertion is (b): the fractional index — the whole reason this
store exists — has to reach the HTTP surface, i.e. inserting a block in the
middle must NOT renumber its siblings.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web  # noqa: E402
from agents.core.notes_store import NotesStore, reset_note_docs_store  # noqa: E402


@pytest.fixture
def client():
    """A client whose block store is a private in-memory DB."""
    store = NotesStore(":memory:").initialize()
    reset_note_docs_store(store)
    try:
        yield TestClient(web.app)
    finally:
        reset_note_docs_store(None)
        store.close()


def _doc(client, title="Doc"):
    r = client.post("/api/notes/docs", json={"title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _block(client, doc_id, text, **body):
    r = client.post(f"/api/notes/docs/{doc_id}/blocks", json={"text": text, **body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── (a) docs are creatable AND findable again ────────────────────────────────
def test_create_then_list_docs(client):
    doc_id = _doc(client, "Field notes")

    r = client.get("/api/notes/docs")
    assert r.status_code == 200
    docs = r.json()["docs"]
    assert [d["id"] for d in docs] == [doc_id]
    assert docs[0]["title"] == "Field notes"
    # the listing carries no block tree — it is a summary
    assert "children" not in docs[0]


def test_get_doc_returns_the_rendered_tree(client):
    doc_id = _doc(client, "Tree")
    head = _block(client, doc_id, "H", type="heading")
    _block(client, doc_id, "under H", parent_id=head)

    r = client.get(f"/api/notes/docs/{doc_id}")
    assert r.status_code == 200
    tree = r.json()
    assert tree["title"] == "Tree"
    assert [n["text"] for n in tree["children"]] == ["H"]
    assert [n["text"] for n in tree["children"][0]["children"]] == ["under H"]


def test_get_unknown_doc_is_a_400_with_a_reason_not_a_500(client):
    r = client.get("/api/notes/docs/nope")
    assert r.status_code == 400
    assert "error" in r.json()


# ── (b) the fractional index survives the HTTP surface ───────────────────────
def test_insert_in_the_middle_does_not_renumber_siblings(client):
    doc_id = _doc(client)
    first = _block(client, doc_id, "one")
    second = _block(client, doc_id, "two")
    before = {n["id"]: n["ordering"] for n in client.get(f"/api/notes/docs/{doc_id}").json()["children"]}

    third = _block(client, doc_id, "inserted", after=first)

    children = client.get(f"/api/notes/docs/{doc_id}").json()["children"]
    assert [n["id"] for n in children] == [first, third, second]
    after = {n["id"]: n["ordering"] for n in children}
    # ONE new key minted, ZERO existing rows touched — that is the point of the store.
    assert after[first] == before[first]
    assert after[second] == before[second]
    assert before[first] < after[third] < before[second]


# ── (c) block edit + subtree delete ──────────────────────────────────────────
def test_patch_block_updates_text_in_the_tree(client):
    doc_id = _doc(client)
    bid = _block(client, doc_id, "before")

    r = client.patch(f"/api/notes/blocks/{bid}", json={"text": "after", "type": "heading"})
    assert r.status_code == 200
    assert r.json()["block"]["text"] == "after"

    node = client.get(f"/api/notes/docs/{doc_id}").json()["children"][0]
    assert node["text"] == "after"
    assert node["type"] == "heading"


def test_delete_block_removes_the_whole_subtree(client):
    doc_id = _doc(client)
    parent = _block(client, doc_id, "parent")
    _block(client, doc_id, "child", parent_id=parent)
    keeper = _block(client, doc_id, "keeper")

    r = client.delete(f"/api/notes/blocks/{parent}")
    assert r.status_code == 200
    assert r.json()["deleted"] == 2

    children = client.get(f"/api/notes/docs/{doc_id}").json()["children"]
    assert [n["id"] for n in children] == [keeper]


def test_delete_doc_removes_it_from_the_listing(client):
    doc_id = _doc(client, "temp")
    _block(client, doc_id, "a")

    r = client.delete(f"/api/notes/docs/{doc_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
    assert client.get("/api/notes/docs").json()["docs"] == []


# ── (d) store errors map to 400, never a 500 ─────────────────────────────────
def test_cross_doc_parent_is_a_400(client):
    doc_a = _doc(client, "A")
    doc_b = _doc(client, "B")
    parent_in_a = _block(client, doc_a, "in A")

    r = client.post(f"/api/notes/docs/{doc_b}/blocks", json={"text": "x", "parent_id": parent_in_a})
    assert r.status_code == 400
    assert "different doc" in r.json()["error"]


def test_patch_unknown_block_is_a_400(client):
    r = client.patch("/api/notes/blocks/nope", json={"text": "x"})
    assert r.status_code == 400
    assert "error" in r.json()


def test_block_text_is_length_bounded(client):
    doc_id = _doc(client)
    r = client.post(f"/api/notes/docs/{doc_id}/blocks", json={"text": "x" * 20_001})
    assert r.status_code == 422


# ── (e) every new route is user-guarded ──────────────────────────────────────
def test_every_notes_docs_route_carries_the_user_guard():
    """Guard introspection, not a request: conftest disables the user guard for
    the whole suite, so a request-level probe would prove nothing."""
    from tests._route_introspect import iter_effective_routes

    expected = {
        ("GET", "/api/notes/docs"),
        ("POST", "/api/notes/docs"),
        ("GET", "/api/notes/docs/{doc_id}"),
        ("DELETE", "/api/notes/docs/{doc_id}"),
        ("POST", "/api/notes/docs/{doc_id}/blocks"),
        ("PATCH", "/api/notes/blocks/{block_id}"),
        ("DELETE", "/api/notes/blocks/{block_id}"),
    }
    seen = set()
    for r in iter_effective_routes(web.app):
        for method in (getattr(r, "methods", None) or set()) - {"HEAD", "OPTIONS"}:
            if (method, r.path) not in expected:
                continue
            seen.add((method, r.path))
            names = set()
            stack = list(getattr(getattr(r, "dependant", None), "dependencies", []))
            while stack:
                d = stack.pop()
                call = getattr(d, "call", None)
                if call is not None:
                    names.add(getattr(call, "__name__", ""))
                stack.extend(getattr(d, "dependencies", []))
            assert {"_user_guard", "user_guard"} & names, f"{method} {r.path} is not user-guarded"
    assert seen == expected, f"missing routes: {sorted(expected - seen)}"
