"""New local image bytes bind their catalog row without manager-side file reads."""

import base64
import hashlib
from pathlib import Path

import httpx
import pytest

from agents.core.media_backends.comfyui import ComfyUIBackend, save_artifact, validate_png
from agents.core.media_backends.local_openai_image import LocalOpenAIImageBackend
from agents.core.media_backends.registry import resolve_config
from agents.core.media_catalog import MediaCatalog
from agents.core.media_gen import MediaGenManager
from agents.core.media_library import read_catalog_blob
from tests.test_h517_local_provider import environment, png
from tests.test_local_image_backend import PNG, configured, png_chunk, successful_service


def _manager(backend, catalog):
    return MediaGenManager(
        backends={"image": backend}, catalog=catalog,
        local_guard=lambda _kind, _prompt, _opts: (True, ""),
    )


def _with_text(image, text):
    # Preserve a valid PNG, dimensions, and byte length while changing content.
    return image[:-12] + png_chunk(b"tEXt", b"note\0" + text) + image[-12:]


def test_shared_save_returns_digest_of_exact_published_bytes(tmp_path, monkeypatch):
    expected = hashlib.sha256(PNG).hexdigest()
    destination_opened = []
    original_open = Path.open

    def observed_open(path, *args, **kwargs):
        if path.suffix == ".png":
            destination_opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    result = save_artifact(tmp_path, PNG, 1, 1)
    assert result["sha256"] == expected
    assert result["bytes"] == len(PNG)
    assert destination_opened == []
    assert Path(result["path"]).read_bytes() == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["comfy", "openai"])
async def test_actual_local_backends_bind_catalog_and_refuse_tampered_png(tmp_path, provider):
    output = tmp_path / "media" / "generated"
    catalog = MediaCatalog(tmp_path / "media" / "catalog.json")
    if provider == "comfy":
        original = PNG
        source = _with_text(original, b"a")

        def service(request):
            if request.url.path == "/view":
                return httpx.Response(200, content=source, headers={"content-type": "image/png"})
            return successful_service(request)

        backend = ComfyUIBackend(
            configured(output), transport=httpx.MockTransport(service),
        )
        options = {}
    else:
        original = png()
        source = _with_text(original, b"a")

        def service(_request):
            return httpx.Response(
                200, json={"data": [{"b64_json": base64.b64encode(source).decode()}]},
            )

        backend = LocalOpenAIImageBackend(
            resolve_config(env=environment(), output_root=output),
            transport=httpx.MockTransport(service),
        )
        options = {"width": 64, "height": 64}
    result = await _manager(backend.generate, catalog).generate("image", "boat", opts=options)
    assert result["ok"] is True
    producer = result["result"]
    assert producer["sha256"] == hashlib.sha256(source).hexdigest()
    row = catalog.get(result["catalog_id"])
    assert row["sha256"] == producer["sha256"]
    meta, data = read_catalog_blob(row["id"], tmp_path)
    assert meta["digest_status"] == "verified" and data == source
    # A second valid PNG with the same dimensions/length is still the wrong bytes.
    changed = _with_text(original, b"b")
    assert changed != source and len(changed) == len(source)
    assert validate_png(changed) == validate_png(source)
    Path(producer["path"]).write_bytes(changed)
    with pytest.raises(ValueError, match="artifact_not_found"):
        read_catalog_blob(row["id"], tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [{"path": "/absent/image.png"}, "/absent/image.png", {"url": "https://example.test/image.png"}])
async def test_missing_producer_digest_omits_keyword_for_legacy_catalog(legacy):
    calls = []

    class LegacyCatalog:
        def add(self, *, kind, prompt, path, now, backend, cloud, tags):
            calls.append(path)
            return {"id": "md-0123456789ab"}

    async def producer(_prompt, _opts):
        return legacy

    result = await _manager(producer, LegacyCatalog()).generate("image", "boat")
    assert result["ok"] is True and result["catalog_id"] == "md-0123456789ab"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "A" * 64, "a" * 63, 123, True])
async def test_present_invalid_digest_refuses_catalog_row_but_keeps_generation_ok(tmp_path, bad, monkeypatch):
    catalog = MediaCatalog(tmp_path / "media" / "catalog.json")
    warnings = []
    monkeypatch.setattr("agents.core.media_gen.logger.warning", lambda *args, **kwargs: warnings.append(args))

    async def producer(_prompt, _opts):
        return {"path": "/absent/image.png", "sha256": bad}

    result = await _manager(producer, catalog).generate("image", "boat")
    assert result["ok"] is True and "catalog_id" not in result
    assert catalog.all() == [] and len(warnings) == 1


@pytest.mark.asyncio
async def test_no_catalog_does_not_read_producer_path(tmp_path, monkeypatch):
    def forbidden(_self, *args, **kwargs):
        raise AssertionError("manager must not open a producer path")

    monkeypatch.setattr(Path, "open", forbidden)

    async def producer(_prompt, _opts):
        return {"path": str(tmp_path / "missing.png"), "sha256": "a" * 64}

    result = await _manager(producer, None).generate("image", "boat")
    assert result["ok"] is True and "catalog_id" not in result


@pytest.mark.asyncio
async def test_catalog_failure_does_not_change_successful_artifact(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr("agents.core.media_gen.logger.warning", lambda *args, **kwargs: warnings.append(args))

    class BrokenCatalog:
        def add(self, **_kwargs):
            raise OSError("catalog full")

    async def producer(_prompt, _opts):
        return save_artifact(tmp_path, PNG, 1, 1)

    result = await _manager(producer, BrokenCatalog()).generate("image", "boat")
    assert result["ok"] is True and "catalog_id" not in result
    assert Path(result["result"]["path"]).read_bytes() == PNG
    assert len(warnings) == 1
