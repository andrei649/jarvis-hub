"""0.46 — media export bundles.

Covers agents/core/media_export.py: manifest building (existence + size +
missing tracking), and zip bundle writing (files namespaced by id, manifest.json
embedded, missing-on-disk items reported not faked). Uses real temp files.
"""

import json
import sys
import zipfile
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.media_export import build_manifest, write_bundle  # noqa: E402


def _item(id_, path, *, kind="image", prompt="p", tags=None, created_at=1.0):
    return {"id": id_, "kind": kind, "prompt": prompt, "path": str(path),
            "tags": tags or [], "created_at": created_at}


def _file(tmp_path, name, content=b"x"):
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ── manifest ──────────────────────────────────────────────────────────────────

def test_build_manifest_counts_and_sizes(tmp_path):
    a = _file(tmp_path, "a.png", b"12345")     # 5 bytes
    b = _file(tmp_path, "b.png", b"123")       # 3 bytes
    items = [_item("md-1", a), _item("md-2", b)]

    m = build_manifest(items, now=999.0)
    assert m["generated_at"] == 999.0
    assert m["count"] == 2 and m["present"] == 2 and m["missing"] == []
    assert m["total_bytes"] == 8
    assert m["items"][0]["exists"] is True and m["items"][0]["bytes"] == 5


def test_build_manifest_reports_missing(tmp_path):
    a = _file(tmp_path, "a.png", b"xy")
    items = [_item("md-1", a), _item("md-2", tmp_path / "gone.png")]

    m = build_manifest(items, now=1.0)
    assert m["count"] == 2 and m["present"] == 1
    assert m["missing"] == ["md-2"]
    assert m["total_bytes"] == 2   # only the present file counts
    gone = next(e for e in m["items"] if e["id"] == "md-2")
    assert gone["exists"] is False and gone["bytes"] == 0


def test_build_manifest_empty_selection():
    m = build_manifest([], now=1.0)
    assert m["count"] == 0 and m["present"] == 0 and m["total_bytes"] == 0
    assert m["items"] == [] and m["missing"] == []


# ── bundle ────────────────────────────────────────────────────────────────────

def test_write_bundle_contains_files_and_manifest(tmp_path):
    a = _file(tmp_path, "a.png", b"AAAA")
    b = _file(tmp_path, "b.png", b"BB")
    dest = tmp_path / "out" / "bundle.zip"

    res = write_bundle([_item("md-1", a), _item("md-2", b)], dest, now=42.0)
    assert res["bundle"] == str(dest) and res["bundled"] == 2
    assert dest.is_file()

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "media/md-1__a.png" in names and "media/md-2__b.png" in names
        assert zf.read("media/md-1__a.png") == b"AAAA"
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["count"] == 2 and manifest["present"] == 2


def test_write_bundle_skips_missing_but_records_it(tmp_path):
    a = _file(tmp_path, "a.png", b"AAAA")
    dest = tmp_path / "bundle.zip"

    res = write_bundle([_item("md-1", a), _item("md-2", tmp_path / "nope.png")], dest, now=1.0)
    assert res["bundled"] == 1 and res["missing"] == ["md-2"]
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert "media/md-1__a.png" in names
        assert not any("md-2" in n for n in names)   # missing file is not faked


def test_write_bundle_namespaces_same_basename_by_id(tmp_path):
    # two items with the same filename in different dirs must not collide
    d1 = tmp_path / "d1"
    d1.mkdir()
    d2 = tmp_path / "d2"
    d2.mkdir()
    a = _file(d1, "img.png", b"one")
    b = _file(d2, "img.png", b"two")
    dest = tmp_path / "bundle.zip"

    res = write_bundle([_item("md-1", a), _item("md-2", b)], dest, now=1.0)
    assert res["bundled"] == 2
    with zipfile.ZipFile(dest) as zf:
        assert zf.read("media/md-1__img.png") == b"one"
        assert zf.read("media/md-2__img.png") == b"two"
