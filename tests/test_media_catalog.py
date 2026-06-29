"""0.46 — searchable catalog/timeline of generated media.

Covers agents/core/media_catalog.py: add (shape + kind validation), get/remove,
all (newest-first) + timeline (oldest-first, time-bounded), search (query/kind/
tag/time filters AND-ed), durable persistence across instances, corrupt-file
safety, bounded oldest-first pruning, and stats. Pure/offline — an injected
``now`` keeps ordering deterministic.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.media_catalog import MediaCatalog  # noqa: E402


def _cat(tmp_path, **kw):
    return MediaCatalog(tmp_path / "catalog.json", **kw)


def _add(cat, *, kind="image", prompt="a cat", path="/x.png", now=1000.0,
         backend="local-sd", cloud=False, tags=None, meta=None):
    return cat.add(kind=kind, prompt=prompt, path=path, now=now, backend=backend,
                   cloud=cloud, tags=tags, meta=meta)


# ── add ───────────────────────────────────────────────────────────────────────

def test_add_shape(tmp_path):
    cat = _cat(tmp_path)
    r = _add(cat, prompt="a red bicycle", tags=["bike"], meta={"seed": 7})
    assert r["id"].startswith("md-")
    assert r["kind"] == "image" and r["prompt"] == "a red bicycle"
    assert r["path"] == "/x.png" and r["backend"] == "local-sd"
    assert r["cloud"] is False and r["created_at"] == 1000.0
    assert r["tags"] == ["bike"] and r["meta"] == {"seed": 7}


def test_add_rejects_unknown_kind(tmp_path):
    cat = _cat(tmp_path)
    with pytest.raises(ValueError):
        _add(cat, kind="hologram")


def test_add_accepts_all_known_kinds(tmp_path):
    cat = _cat(tmp_path)
    for k in ("image", "thumbnail", "video"):
        assert _add(cat, kind=k)["kind"] == k


# ── get / remove ────────────────────────────────────────────────────────────

def test_get_and_remove(tmp_path):
    cat = _cat(tmp_path)
    r = _add(cat)
    assert cat.get(r["id"])["id"] == r["id"]
    assert cat.get("missing") is None
    assert cat.remove(r["id"]) is True
    assert cat.get(r["id"]) is None
    assert cat.remove(r["id"]) is False   # already gone


# ── ordering: all (newest-first) vs timeline (oldest-first) ────────────────────

def test_all_is_newest_first(tmp_path):
    cat = _cat(tmp_path)
    a = _add(cat, prompt="first", now=1)
    b = _add(cat, prompt="second", now=2)
    c = _add(cat, prompt="third", now=3)
    assert [x["id"] for x in cat.all()] == [c["id"], b["id"], a["id"]]


def test_timeline_is_oldest_first_and_time_bounded(tmp_path):
    cat = _cat(tmp_path)
    a = _add(cat, now=10)
    b = _add(cat, now=20)
    c = _add(cat, now=30)
    assert [x["id"] for x in cat.timeline()] == [a["id"], b["id"], c["id"]]
    # inclusive bounds
    assert [x["id"] for x in cat.timeline(since=20)] == [b["id"], c["id"]]
    assert [x["id"] for x in cat.timeline(until=20)] == [a["id"], b["id"]]
    assert [x["id"] for x in cat.timeline(since=20, until=20)] == [b["id"]]


# ── search ────────────────────────────────────────────────────────────────────

def test_search_filters_and_together(tmp_path):
    cat = _cat(tmp_path)
    _add(cat, kind="image", prompt="A Red Bicycle", tags=["vehicle"], now=1)
    _add(cat, kind="video", prompt="red sunset timelapse", tags=["nature"], now=2)
    _add(cat, kind="image", prompt="blue car", tags=["vehicle"], now=3)

    # case-insensitive substring on prompt
    assert {r["prompt"] for r in cat.search("red")} == {"A Red Bicycle", "red sunset timelapse"}
    # kind filter
    assert {r["prompt"] for r in cat.search(kind="image")} == {"A Red Bicycle", "blue car"}
    # tag filter
    assert {r["prompt"] for r in cat.search(tag="vehicle")} == {"A Red Bicycle", "blue car"}
    # ANDed: red AND image → only the bicycle
    assert [r["prompt"] for r in cat.search("red", kind="image")] == ["A Red Bicycle"]
    # newest-first ordering
    assert [r["prompt"] for r in cat.search(tag="vehicle")] == ["blue car", "A Red Bicycle"]


def test_search_time_bounds(tmp_path):
    cat = _cat(tmp_path)
    _add(cat, prompt="old", now=10)
    _add(cat, prompt="new", now=100)
    assert [r["prompt"] for r in cat.search(since=50)] == ["new"]
    assert [r["prompt"] for r in cat.search(until=50)] == ["old"]


# ── persistence + safety ───────────────────────────────────────────────────────

def test_persists_across_instances(tmp_path):
    cat = _cat(tmp_path)
    r = _add(cat, prompt="durable")
    cat2 = MediaCatalog(tmp_path / "catalog.json")
    assert cat2.get(r["id"])["prompt"] == "durable"


def test_corrupt_file_degrades_to_empty(tmp_path):
    p = tmp_path / "catalog.json"
    p.write_text("not json {{{")
    cat = MediaCatalog(p)
    assert cat.stats()["total"] == 0
    r = _add(cat)   # still writable (overwrites the garbage atomically)
    assert cat.get(r["id"]) is not None


def test_bounded_prunes_oldest_first(tmp_path):
    cat = _cat(tmp_path, max_keep=3)
    ids = [_add(cat, prompt=str(i), now=float(i))["id"] for i in range(5)]
    kept = {r["id"] for r in cat.all()}
    assert ids[0] not in kept and ids[1] not in kept
    assert {ids[2], ids[3], ids[4]} <= kept


def test_stats(tmp_path):
    cat = _cat(tmp_path)
    _add(cat, kind="image", cloud=False, now=1)
    _add(cat, kind="image", cloud=True, now=2)
    _add(cat, kind="video", cloud=True, now=3)
    s = cat.stats()
    assert s["total"] == 3
    assert s["cloud"] == 2
    assert s["by_kind"] == {"image": 2, "video": 1}
