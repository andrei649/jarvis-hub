"""Only catalog rows with a trusted expected SHA can claim verified bytes."""

from __future__ import annotations

import hashlib
import json

import pytest

from agents.core.media_catalog import MediaCatalog
from agents.core.media_library import catalog_snapshot, export_generated, read_catalog_blob

_FIRST = b"%PDF-1.7\noriginal document\n%%EOF"
_OTHER = b"%PDF-1.7\nreplaced document\n%%EOF"
assert len(_FIRST) == len(_OTHER)


def _catalog(tmp_path, data=_FIRST):
    cache = tmp_path / "media" / "cache"
    cache.mkdir(parents=True)
    path = cache / "document.pdf"
    path.write_bytes(data)
    return MediaCatalog(tmp_path / "media" / "catalog.json"), path


def _add(catalog, path, **overrides):
    return catalog.add(
        kind="image", prompt="local document", path=str(path), now=1,
        record_id="md-123456789abc", **overrides,
    )


def test_bound_row_verifies_exact_returned_bytes_and_rejects_same_size_replacement(tmp_path):
    catalog, path = _catalog(tmp_path)
    expected = hashlib.sha256(_FIRST).hexdigest()
    row = _add(catalog, path, sha256=expected)
    assert row["sha256"] == expected
    meta, data = read_catalog_blob(row["id"], tmp_path)
    assert data == _FIRST
    assert meta["sha256"] == expected
    assert meta["digest_status"] == "verified"

    path.write_bytes(_OTHER)
    assert len(path.read_bytes()) == len(_FIRST)
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(row["id"], tmp_path)
    exported = export_generated(tmp_path)
    assert exported["items"] == []
    assert exported["missing"] == [row["id"]]
    assert exported["complete"] is False


def test_legacy_row_serves_but_reports_unbound_and_export_inherits_status(tmp_path):
    catalog, path = _catalog(tmp_path)
    row = _add(catalog, path)
    assert "sha256" not in row
    meta, data = read_catalog_blob(row["id"], tmp_path)
    assert data == _FIRST
    assert meta["sha256"] == hashlib.sha256(_FIRST).hexdigest()
    assert meta["digest_status"] == "unbound"
    exported = export_generated(tmp_path)
    assert len(exported["items"]) == 1
    assert exported["items"][0]["digest_status"] == "unbound"


@pytest.mark.parametrize("invalid", ["A" * 64, "f" * 63, "g" * 64, "", None, 123])
def test_add_and_persisted_record_reject_malformed_expected_digest(tmp_path, invalid):
    catalog, path = _catalog(tmp_path)
    if invalid is not None:
        with pytest.raises(ValueError):
            _add(catalog, path, sha256=invalid)
        assert not catalog._path.exists()

    row = _add(catalog, path)
    stored = json.loads(catalog._path.read_text())
    stored[0]["sha256"] = invalid
    catalog._path.write_text(json.dumps(stored))
    records, invalid_count = catalog_snapshot(tmp_path)
    assert records == {} and invalid_count == 1
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(row["id"], tmp_path)


@pytest.mark.parametrize("invalid", ["A" * 64, "f" * 63, "g" * 64, None, 123])
def test_supplied_snapshot_cannot_bypass_digest_shape_check(tmp_path, invalid):
    catalog, path = _catalog(tmp_path)
    row = _add(catalog, path)
    supplied = {row["id"]: {**row, "sha256": invalid}}
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(row["id"], tmp_path, records=supplied)


def test_stable_id_retry_never_backfills_or_strips_expected_digest(tmp_path):
    catalog, path = _catalog(tmp_path)
    expected = hashlib.sha256(_FIRST).hexdigest()
    legacy = _add(catalog, path)
    assert _add(catalog, path, sha256=expected) == legacy
    assert "sha256" not in catalog.get(legacy["id"])

    catalog.remove(legacy["id"])
    bound = _add(catalog, path, sha256=expected)
    assert _add(catalog, path) == bound
    assert _add(catalog, path, sha256=expected) == bound
    assert catalog.get(bound["id"])["sha256"] == expected
    with pytest.raises(ValueError, match="collision"):
        _add(catalog, path, sha256=hashlib.sha256(_OTHER).hexdigest())
    with pytest.raises(ValueError, match="collision"):
        catalog.add(
            kind="image", prompt="changed", path=str(path), now=1,
            record_id=bound["id"],
        )


def test_add_validates_digest_without_opening_artifact_path(tmp_path):
    catalog = MediaCatalog(tmp_path / "media" / "catalog.json")
    missing_path = tmp_path / "media" / "cache" / "never-created.pdf"
    row = _add(catalog, missing_path, sha256=hashlib.sha256(_FIRST).hexdigest())
    assert row["sha256"] == hashlib.sha256(_FIRST).hexdigest()
    assert not missing_path.exists()


def test_delivery_and_export_load_catalog_once_and_use_supplied_snapshot(tmp_path, monkeypatch):
    catalog, path = _catalog(tmp_path)
    row = _add(catalog, path, sha256=hashlib.sha256(_FIRST).hexdigest())
    original = MediaCatalog._load_rows
    reads = []

    def counted(self, **kwargs):
        reads.append(1)
        return original(self, **kwargs)

    monkeypatch.setattr(MediaCatalog, "_load_rows", counted)
    assert read_catalog_blob(row["id"], tmp_path)[0]["digest_status"] == "verified"
    assert len(reads) == 1
    reads.clear()
    assert export_generated(tmp_path)["items"][0]["digest_status"] == "verified"
    assert len(reads) == 1
    records, _ = catalog_snapshot(tmp_path)
    reads.clear()
    assert read_catalog_blob(row["id"], tmp_path, records=records)[1] == _FIRST
    assert reads == []


def test_supplied_mapping_is_selected_once_for_path_and_digest(tmp_path):
    catalog, path = _catalog(tmp_path)
    row = _add(catalog, path, sha256=hashlib.sha256(_FIRST).hexdigest())

    class ChangingRows(dict):
        calls = 0

        def get(self, key, default=None):
            self.calls += 1
            if self.calls == 1:
                return row
            return {**row, "sha256": hashlib.sha256(_OTHER).hexdigest()}

    supplied = ChangingRows()
    meta, data = read_catalog_blob(row["id"], tmp_path, records=supplied)
    assert supplied.calls == 1
    assert meta["digest_status"] == "verified" and data == _FIRST


@pytest.mark.parametrize("invalid_id", [[], None, "md-not-hex", "md-123456789abc/"])
def test_bad_id_refuses_before_catalog_read(tmp_path, monkeypatch, invalid_id):
    def no_catalog_read(_root):
        raise AssertionError("malformed id must not load the catalog")

    monkeypatch.setattr("agents.core.media_library.catalog_snapshot", no_catalog_read)
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(invalid_id, tmp_path)
