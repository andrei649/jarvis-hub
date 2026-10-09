"""A proof-bound 4K Enhance result remains downloadable in the media catalog."""

import base64
import hashlib
import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.core.media_catalog import MediaCatalog
from agents.core.media_library import catalog_snapshot, export_generated, read_catalog_blob
from tests.test_cloud_image import cloud, png  # noqa: F401
from tests.test_cloud_image_krea_enhance import completed_source, enhance_responses
from tests.test_cloud_image_openrouter_krea import providers  # noqa: F401


async def _completed_pair(providers):
    source_id = await completed_source(providers)
    enhance_id = providers.runtime.enhance(source_id, "user")
    enhance_responses(providers)
    await providers.worker.apply_decision(enhance_id, "accept", decided_by="test owner")
    await providers.worker.tick()
    source = providers.queue.get(source_id)
    enhanced = providers.queue.get(enhance_id)
    assert enhanced.result["status"] == "ok", enhanced.result
    source_artifact = source.result["result"]["result"]["artifact_id"]
    enhanced_artifact = enhanced.result["result"]["result"]["artifact_id"]
    records, invalid = catalog_snapshot(providers.root)
    assert invalid == 0 and len(records) == 2
    rows = {row["meta"]["task_id"]: row for row in records.values()}
    return (source_id, rows[source_id], source_artifact), (enhance_id, rows[enhance_id], enhanced_artifact)


def _raw(providers, artifact_id):
    return (providers.root / "media" / "generated" / (artifact_id + ".png")).read_bytes()


@pytest.mark.asyncio
async def test_completed_4k_enhance_gallery_read_export_binary_and_zip(providers, monkeypatch):
    from agents.core.routers._deps import user_guard
    from agents.core.routers.artifact_store import router

    source, enhanced = await _completed_pair(providers)
    original_bytes = _raw(providers, source[2])
    enhanced_bytes = _raw(providers, enhanced[2])
    assert original_bytes != enhanced_bytes
    assert hashlib.sha256(enhanced_bytes).hexdigest() == enhanced[1]["meta"]["sha256"]
    for _, row, artifact_id in (source, enhanced):
        meta, data = read_catalog_blob(row["id"], providers.root)
        assert meta["mime"] == "image/png"
        assert data == _raw(providers, artifact_id)
    exported = export_generated(providers.root)
    assert exported["complete"] is True and exported["missing"] == []
    assert {item["id"]: base64.b64decode(item["base64"]) for item in exported["items"]} == {
        source[1]["id"]: original_bytes, enhanced[1]["id"]: enhanced_bytes}

    monkeypatch.setenv("JARVIS_HOME", str(providers.root))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_guard] = lambda: None
    client = TestClient(app)
    for _, row, artifact_id in (source, enhanced):
        response = client.get("/api/artifacts/" + row["id"] + "/blob")
        assert response.status_code == 200 and response.content == _raw(providers, artifact_id)
    bundle = client.post("/api/media/export", json={"ids": [source[1]["id"], enhanced[1]["id"]]})
    assert bundle.status_code == 200, bundle.text[:120] if bundle.status_code != 200 else ""
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["missing"] == []
        assert {item["id"] for item in manifest["items"]} == {source[1]["id"], enhanced[1]["id"]}
        assert archive.read("media/" + source[1]["id"]) == original_bytes
        assert archive.read("media/" + enhanced[1]["id"]) == enhanced_bytes
    assert [request.method for request in providers.requests] == ["POST", "GET", "GET", "POST", "GET", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "malformed", "symlink", "sha256", "task_id"])
async def test_gallery_4k_requires_unchanged_private_proof(providers, change):
    source, enhanced = await _completed_pair(providers)
    path = providers.runtime.records / (enhanced[2] + ".artifact")
    if change == "missing":
        path.unlink()
    elif change == "malformed":
        path.write_text("{")
    elif change == "symlink":
        path.unlink()
        target = providers.root / "forged-proof.json"
        target.write_text("{}")
        path.symlink_to(target)
    else:
        proof = json.loads(path.read_text())
        proof[change] = "0" * 64 if change == "sha256" else source[0]
        path.write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(enhanced[1]["id"], providers.root)
    exported = export_generated(providers.root)
    assert enhanced[1]["id"] in exported["missing"]
    assert {item["id"] for item in exported["items"]} == {source[1]["id"]}


@pytest.mark.asyncio
async def test_gallery_4k_rechecks_current_catalog_metadata_even_with_old_snapshot(providers):
    source, enhanced = await _completed_pair(providers)
    catalog_file = providers.root / "media" / "catalog.json"
    original = catalog_file.read_text()
    records, _ = catalog_snapshot(providers.root)
    for field, replacement in (("task_id", source[0]), ("sha256", "0" * 64),
                               ("backend", "openai:gpt-image-1.5")):
        rows = json.loads(original)
        row = next(row for row in rows if row["id"] == enhanced[1]["id"])
        if field == "backend":
            row[field] = replacement
        else:
            row["meta"][field] = replacement
        catalog_file.write_text(json.dumps(rows))
        with pytest.raises(ValueError, match="artifact_not_found"):
            read_catalog_blob(enhanced[1]["id"], providers.root)
        assert read_catalog_blob(enhanced[1]["id"], providers.root, records=records)[1] == _raw(
            providers, enhanced[2])
    catalog_file.write_text(original)
    assert read_catalog_blob(enhanced[1]["id"], providers.root)[1] == _raw(providers, enhanced[2])


@pytest.mark.asyncio
async def test_naked_4k_catalog_row_cannot_claim_enhance_admission(providers):
    source_id = await completed_source(providers)
    naked_id = "f" * 32
    data = png((4096, 128))
    path = providers.root / "media" / "generated" / (naked_id + ".png")
    path.write_bytes(data)
    row = MediaCatalog(providers.root / "media" / "catalog.json").add(
        kind="image", prompt="a lamp", path=str(path), backend="krea:krea-2-medium", cloud=True,
        meta={"task_id": source_id, "sha256": hashlib.sha256(data).hexdigest()}, now=1)
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(row["id"], providers.root)
    exported = export_generated(providers.root)
    assert row["id"] in exported["missing"]
