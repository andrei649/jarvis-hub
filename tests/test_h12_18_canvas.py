"""H12.18: Agent Canvas / A2UI — governed, sanitized visual elements.

An agent posts only known-safe, length-bounded typed elements (no raw HTML/
script); each is attributed, inspectable, pinnable, and clearable by the owner.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.canvas import CanvasStore, _sanitize, ALLOWED_TYPES  # noqa: E402
import agents.web as web  # noqa: E402


@pytest.fixture
def canvas(tmp_path):
    return CanvasStore(path=str(tmp_path / "canvas.json"))


# ── sanitization (the "governed" core) ────────────────────────────

def test_unknown_type_rejected():
    with pytest.raises(ValueError):
        _sanitize("script", {"body": "alert(1)"})


def test_text_requires_body_and_bounds_length():
    with pytest.raises(ValueError):
        _sanitize("text", {"title": "x"})
    out = _sanitize("text", {"title": "T" * 500, "body": "B" * 5000})
    assert len(out["title"]) == 120 and len(out["body"]) == 2000


def test_link_requires_safe_scheme():
    with pytest.raises(ValueError):
        _sanitize("link", {"url": "javascript:alert(1)"})
    assert _sanitize("link", {"url": "https://x.io"})["url"] == "https://x.io"
    assert _sanitize("link", {"url": "/static/a.png"})["url"] == "/static/a.png"


def test_link_rejects_protocol_relative_url():
    # //host resolves against the page scheme → cross-origin, NOT same-origin.
    with pytest.raises(ValueError):
        _sanitize("link", {"url": "//attacker.example/pixel"})
    # browsers normalize \ to / in special URLs, so /\host is the same trick
    with pytest.raises(ValueError):
        _sanitize("link", {"url": "/\\attacker.example/pixel"})


def test_image_rejects_protocol_relative_src():
    with pytest.raises(ValueError):
        _sanitize("image_ref", {"src": "//attacker.example/pixel.png"})
    with pytest.raises(ValueError):
        _sanitize("image_ref", {"src": "/\\attacker.example/pixel.png"})


def test_url_control_chars_cannot_smuggle_protocol_relative():
    # Browsers strip TAB/LF/CR before parsing, so "/<ctl>/host" resolves to
    # "//host" (cross-origin). The single-slash same-origin branch must not be
    # fooled by an interior control char.
    for ctl in ("\t", "\n", "\r"):
        with pytest.raises(ValueError):
            _sanitize("link", {"url": f"/{ctl}/attacker.example/x"})
        with pytest.raises(ValueError):
            _sanitize("image_ref", {"src": f"/{ctl}/attacker.example/pixel.png"})


def test_lone_surrogate_is_dropped_so_the_store_can_save(tmp_path):
    # A lone UTF-16 surrogate (truncated astral char / crafted \udXXX escape)
    # parses fine but breaks a UTF-8 write; _s must drop it so post() persists
    # and the store is not poisoned for later saves.
    store = CanvasStore(path=str(tmp_path / "c.json"))
    el = store.post("jarvis", "markdown", {"body": "ok\ud83dend"})
    assert "\ud83d" not in el["payload"]["body"] and el["payload"]["body"] == "okend"
    # reloadable (the write did not raise) + a subsequent save still works
    assert CanvasStore(path=str(tmp_path / "c.json")).list()[0]["payload"]["body"] == "okend"
    assert store.post("jarvis", "text", {"body": "next"})


def test_clear_memory_does_not_persist(tmp_path):
    # The forget flow needs an in-memory-only clear so canvas.json survives until
    # the pre-forget backup captures it (purge_data resets the file afterwards).
    p = str(tmp_path / "c.json")
    store = CanvasStore(path=p)
    store.post("friday", "text", {"body": "on disk"})
    store.clear_memory()
    assert store.list() == []                                  # live store emptied
    assert CanvasStore(path=p).list()[0]["payload"]["body"] == "on disk"  # file intact


def test_safe_urls_still_accepted_after_protocol_relative_fix():
    assert _sanitize("link", {"url": "/static/report.png"})["url"] == "/static/report.png"
    assert _sanitize("link", {"url": "/api/media/thumb/1"})["url"] == "/api/media/thumb/1"
    assert _sanitize("link", {"url": "https://example.com/a"})["url"] == "https://example.com/a"
    assert _sanitize("link", {"url": "http://example.com/a"})["url"] == "http://example.com/a"
    assert _sanitize("image_ref", {"src": "/static/a.png"})["src"] == "/static/a.png"
    assert _sanitize("image_ref", {"src": "https://x.io/a.png"})["src"] == "https://x.io/a.png"


def test_list_and_table_bound_counts():
    lst = _sanitize("list", {"items": [str(i) for i in range(100)]})
    assert len(lst["items"]) == 50
    tbl = _sanitize("table", {"columns": ["a"], "rows": [["x"] * 20] * 80})
    assert len(tbl["rows"]) == 50 and len(tbl["rows"][0]) == 12


def test_all_allowed_types_have_a_validator():
    samples = {
        "text": {"body": "b"}, "markdown": {"body": "b"}, "list": {"items": ["a"]},
        "link": {"url": "https://x"}, "metric": {"label": "L"},
        "table": {"columns": ["c"]}, "image_ref": {"src": "https://x/a.png"},
    }
    for t in ALLOWED_TYPES:
        assert _sanitize(t, samples[t])          # no raise


# ── store ─────────────────────────────────────────────────────────

def test_post_attributes_and_lists_newest_first(canvas):
    canvas.post("friday", "text", {"body": "first"})
    canvas.post("pepper", "metric", {"label": "CPU", "value": "42%"})
    els = canvas.list()
    assert [e["agent"] for e in els] == ["pepper", "friday"]    # newest first
    assert all("id" in e and "created_at" in e for e in els)


def test_post_rejects_unsafe(canvas):
    with pytest.raises(ValueError):
        canvas.post("friday", "image_ref", {"src": "data:text/html,evil"})


def test_list_filter_by_agent(canvas):
    canvas.post("friday", "text", {"body": "a"})
    canvas.post("pepper", "text", {"body": "b"})
    assert len(canvas.list(agent="friday")) == 1


def test_pin_remove_and_clear_keep_pinned(canvas):
    a = canvas.post("friday", "text", {"body": "keep"})
    canvas.post("friday", "text", {"body": "drop"})
    canvas.pin(a["id"], True)
    assert canvas.clear() == 1                    # only the unpinned one
    assert len(canvas.list()) == 1 and canvas.list()[0]["pinned"] is True
    assert canvas.remove(a["id"]) is True and canvas.list() == []


def test_persistence_round_trip(tmp_path):
    p = str(tmp_path / "c.json")
    CanvasStore(path=p).post("friday", "text", {"body": "persisted"})
    assert CanvasStore(path=p).list()[0]["payload"]["body"] == "persisted"


# ── endpoints ─────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    import agents.core.routers.canvas as _canvas_mod
    monkeypatch.setattr(_canvas_mod, "_canvas_store", CanvasStore(path=str(tmp_path / "c.json")))
    monkeypatch.setattr(web, "orch", None)
    return TestClient(web.app)


def test_endpoint_post_list_and_reject(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    ok = client.post("/api/canvas/post",
                     json={"agent": "friday", "type": "metric",
                           "payload": {"label": "Latency", "value": "12ms"}})
    assert ok.status_code == 200 and ok.json()["type"] == "metric"
    # unknown type → 422 (governed)
    bad = client.post("/api/canvas/post", json={"type": "iframe", "payload": {"body": "x"}})
    assert bad.status_code == 422
    assert len(client.get("/api/canvas").json()["elements"]) == 1


def test_endpoint_pin_clear_remove(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    eid = client.post("/api/canvas/post",
                      json={"type": "text", "payload": {"body": "hi"}}).json()["id"]
    assert client.post(f"/api/canvas/{eid}/pin", params={"pinned": True}).json()["pinned"] is True
    assert client.post("/api/canvas/clear").json()["removed"] == 0   # pinned kept
    assert client.delete(f"/api/canvas/{eid}").json()["removed"] is True
    assert client.delete(f"/api/canvas/{eid}").status_code == 404
