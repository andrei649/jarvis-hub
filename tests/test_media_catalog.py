"""0.46 — searchable catalog/timeline of generated media.

Covers agents/core/media_catalog.py: add (shape + kind validation), get/remove,
all (newest-first) + timeline (oldest-first, time-bounded), search (query/kind/
tag/time filters AND-ed), durable persistence across instances, corrupt-file
safety, bounded oldest-first pruning, and stats. Pure/offline — an injected
``now`` keeps ordering deterministic.
"""

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.media_catalog import MediaCatalog  # noqa: E402


def _cat(tmp_path, **kw):
    return MediaCatalog(tmp_path / "catalog.json", **kw)


def _add(
    cat,
    *,
    kind="image",
    prompt="a cat",
    path="/x.png",
    now=1000.0,
    backend="local-sd",
    cloud=False,
    tags=None,
    meta=None,
):
    return cat.add(
        kind=kind,
        prompt=prompt,
        path=path,
        now=now,
        backend=backend,
        cloud=cloud,
        tags=tags,
        meta=meta,
    )


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
    assert cat.remove(r["id"]) is False  # already gone


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


def test_search_limit_bounds_resolver_candidate_reads(tmp_path):
    cat = _cat(tmp_path)
    for index in range(10):
        _add(cat, prompt=f"aurora {index}", now=float(index))

    assert len(cat.search("aurora", limit=6)) == 6
    assert [row["prompt"] for row in cat.search("aurora", limit=2)] == [
        "aurora 9",
        "aurora 8",
    ]
    with pytest.raises(ValueError, match="limit"):
        cat.search("aurora", limit=0)


def test_search_normalizes_malformed_persisted_created_at(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(
        '[{"id":"md-bad-time","prompt":"aurora","created_at":"bad"}]',
        encoding="utf-8",
    )

    assert [row["id"] for row in MediaCatalog(path).search("aurora", limit=2)] == ["md-bad-time"]


def test_read_caps_persisted_entries_and_refuses_oversized_catalog_file(tmp_path, monkeypatch):
    import agents.core.media_catalog as mc

    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            [{"id": f"md-{index}", "prompt": "aurora", "created_at": index} for index in range(10)]
        ),
        encoding="utf-8",
    )
    assert len(MediaCatalog(path, max_keep=3).search("aurora", limit=10)) == 3

    monkeypatch.setattr(mc, "_MAX_FILE_BYTES", 16)
    assert MediaCatalog(path).search("aurora", limit=10) == []


def test_created_at_normalizer_handles_overflow_and_non_finite_values():
    import agents.core.media_catalog as mc

    assert mc._created_at({"created_at": 10**10_000}) == 0.0
    assert mc._created_at({"created_at": float("nan")}) == 0.0
    assert mc._created_at({"created_at": float("inf")}) == 0.0


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
    before = p.read_bytes()
    with pytest.raises(ValueError, match="unreadable"):
        _add(cat)
    assert p.read_bytes() == before


def test_mutation_refuses_file_and_record_over_limit_without_data_loss(tmp_path, monkeypatch):
    import agents.core.media_catalog as mc

    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            [{"id": f"md-{index}", "prompt": "aurora", "created_at": index} for index in range(4)]
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="record limit"):
        _add(MediaCatalog(path, max_keep=3))
    assert path.read_bytes() == before

    monkeypatch.setattr(mc, "_MAX_FILE_BYTES", len(before) - 1)
    with pytest.raises(ValueError, match="size limit"):
        MediaCatalog(path).remove("md-0")
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"prompt": "p" * 4_097}, "prompt"),
        ({"path": "/" + "p" * 2_048}, "path"),
        ({"tags": [str(index) for index in range(33)]}, "tags"),
        ({"tags": ["t" * 65]}, "tag"),
        ({"meta": {"payload": "m" * 16_385}}, "meta"),
        ({"meta": {"bad": object()}}, "meta"),
    ],
)
def test_add_rejects_unbounded_or_non_json_item_fields(tmp_path, overrides, reason):
    catalog = _cat(tmp_path)

    with pytest.raises(ValueError, match=reason):
        _add(catalog, **overrides)

    assert not (tmp_path / "catalog.json").exists()


def test_add_refuses_item_or_final_write_over_limit_without_replacing_store(tmp_path, monkeypatch):
    import agents.core.media_catalog as mc

    catalog = _cat(tmp_path)
    monkeypatch.setattr(mc, "_MAX_ITEM_BYTES", 64)
    with pytest.raises(ValueError, match="item size"):
        _add(catalog)
    assert not (tmp_path / "catalog.json").exists()

    monkeypatch.setattr(mc, "_MAX_ITEM_BYTES", 32_768)
    first = _add(catalog, prompt="first")
    store = tmp_path / "catalog.json"
    before = store.read_bytes()
    monkeypatch.setattr(mc, "_MAX_FILE_BYTES", len(before) + 8)
    with pytest.raises(ValueError, match="catalog size"):
        _add(catalog, prompt="second")
    assert store.read_bytes() == before
    assert catalog.get(first["id"])["prompt"] == "first"


def test_read_and_strict_mutation_reject_every_over_limit_persisted_record_field(
    tmp_path,
):
    base = {
        "id": "md-existing",
        "kind": "image",
        "prompt": "aurora",
        "path": "/media/aurora.png",
        "backend": "local",
        "cloud": False,
        "created_at": 1.0,
        "tags": ["night"],
        "meta": {"seed": 1},
    }
    invalid_records = []
    for field, value in (
        ("id", "i" * 65),
        ("kind", "k" * 33),
        ("prompt", "p" * 4_097),
        ("path", "/" + "p" * 2_048),
        ("backend", "b" * 129),
        ("cloud", "yes"),
        ("tags", [str(index) for index in range(33)]),
        ("tags", ["t" * 65]),
        ("meta", {str(index): index for index in range(33)}),
        ("meta", {"payload": "m" * 16_385}),
    ):
        invalid_records.append({**base, field: value})

    for index, record in enumerate(invalid_records):
        path = tmp_path / f"invalid-{index}.json"
        path.write_text(json.dumps([record]), encoding="utf-8")
        before = path.read_bytes()
        catalog = MediaCatalog(path)

        assert catalog.all() == []
        with pytest.raises(ValueError, match="invalid record"):
            _add(catalog)
        assert path.read_bytes() == before


def test_read_and_mutation_enforce_item_size_on_existing_records(tmp_path, monkeypatch):
    import agents.core.media_catalog as mc

    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "md-existing",
                    "kind": "image",
                    "prompt": "aurora",
                    "path": "/media/aurora.png",
                    "created_at": 1.0,
                    "tags": [],
                    "meta": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()
    monkeypatch.setattr(mc, "_MAX_ITEM_BYTES", 64)
    catalog = MediaCatalog(path)

    assert catalog.search("aurora") == []
    with pytest.raises(ValueError, match="invalid record"):
        catalog.remove("md-existing")
    assert path.read_bytes() == before


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


def test_default_catalog_if_enabled_is_opt_in(monkeypatch):
    import agents.core.media_catalog as mc

    # default-off: no flag → None (and no file I/O at all)
    assert mc.default_catalog_if_enabled(env={}) is None
    assert mc.default_catalog_if_enabled(env={"JARVIS_MEDIA_CATALOG": ""}) is None
    assert mc.default_catalog_if_enabled(env={"JARVIS_MEDIA_CATALOG": "0"}) is None
    assert mc.default_catalog_if_enabled(env={"JARVIS_MEDIA_CATALOG": "typo"}) is None
    # flag set → a MediaCatalog (monkeypatched to avoid touching the real data dir)
    sentinel = object()
    monkeypatch.setattr(mc, "MediaCatalog", lambda: sentinel)
    assert mc.default_catalog_if_enabled(env={"JARVIS_MEDIA_CATALOG": "1"}) is sentinel
