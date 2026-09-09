"""Local image backend protocol tests: the HTTP transport is the external seam."""

import base64
import importlib
import json
import struct
import zlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def png_chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png_with_pixels(compressed, *, width=1, height=1):
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 4, 0, 0, 0))
        + png_chunk(b"IDAT", compressed)
        + png_chunk(b"IEND", b"")
    )


def successful_service(request):
    if request.method == "POST":
        return httpx.Response(200, json={"prompt_id": "p-1"})
    if request.url.path.startswith("/history/"):
        return httpx.Response(200, json=output_history())
    return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})


@pytest.mark.parametrize("compressed", [
    b"not compressed pixels",
    zlib.compress(b"\x00\x00"),  # Truncated scanline (one filter byte + two channel bytes required).
    zlib.compress(b"\x05\x00\x00"),  # Unknown PNG filter.
    zlib.compress(b"\x00\x00\x00extra"),
    zlib.compress(b"\x00\x00\x00") + b"trailing zlib bytes",
    zlib.compress(b"\x00" * 2_000_000),  # Dimensions cannot authorize a decompression bomb.
], ids=["invalid-zlib", "short-row", "invalid-filter", "long-row", "trailing-zlib", "inflation-limit"])
def test_crc_correct_but_invalid_pixels_are_not_accepted(compressed):
    module = backend_module()
    with pytest.raises(module.ImageGenerationError, match="invalid_image"):
        module.validate_png(png_with_pixels(compressed))


@pytest.mark.asyncio
async def test_collision_never_deletes_or_replaces_an_existing_artifact(tmp_path, monkeypatch):
    module = backend_module()
    artifact_id = "a" * 32
    existing = tmp_path / (artifact_id + ".png")
    existing.write_bytes(b"preexisting owner artifact")
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex=artifact_id))
    backend = module.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(successful_service))
    with pytest.raises(module.ImageGenerationError, match="artifact_write_failed"):
        await backend.generate("boat", {})
    assert existing.read_bytes() == b"preexisting owner artifact"
    assert list(tmp_path.iterdir()) == [existing]


@pytest.mark.asyncio
async def test_image_is_not_published_if_flush_fails(tmp_path, monkeypatch):
    module = backend_module()
    visible_at_flush = []

    def failed_flush(_fd):
        visible_at_flush.extend(tmp_path.glob("*.png"))
        raise OSError("simulated disk failure")

    monkeypatch.setattr(module.os, "fsync", failed_flush)
    backend = module.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(successful_service))
    with pytest.raises(module.ImageGenerationError, match="artifact_write_failed"):
        await backend.generate("boat", {})
    assert visible_at_flush == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_compressed_response_is_refused_without_reading_body(tmp_path):
    module = backend_module()
    reads = []

    class MustNotRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            reads.append(True)
            yield b"compressed data must not be expanded"

    def service(request):
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=MustNotRead())

    backend = module.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(module.ImageGenerationError, match="content_encoding_refused"):
        await backend.generate("boat", {})
    assert reads == []


def test_changed_backend_source_invalidates_configuration_fingerprint(tmp_path, monkeypatch):
    module = backend_module()
    config = configured(tmp_path)
    config.fingerprint()
    different_source = tmp_path / "updated_backend.py"
    different_source.write_text("# Different implementation\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(different_source))
    with pytest.raises(module.ImageGenerationError, match="backend_source_changed"):
        config.fingerprint()


@pytest.mark.parametrize("color,channels", [(0, 1), (2, 3), (4, 2), (6, 4)])
def test_standard_static_eight_bit_outputs_validate(color, channels):
    data = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 3, 8, color, 0, 0, 0))
        + png_chunk(b"tEXt", b"prompt\0synthetic test")
        + png_chunk(b"IDAT", zlib.compress((b"\0" + b"\x7f" * (2 * channels)) * 3))
        + png_chunk(b"IEND", b"")
    )
    assert backend_module().validate_png(data) == (2, 3)


def test_uncompressed_unicode_prompt_metadata_is_supported():
    # Pillow SaveImage uses uncompressed iTXt when a prompt is outside Latin-1.
    image = png_with_pixels(zlib.compress(b"\0\0\0"))
    text = png_chunk(b"iTXt", b"prompt\0\0\0\0\0" + "O barcă și o țestoasă".encode())
    image = image[:33] + text + image[33:]
    assert backend_module().validate_png(image) == (1, 1)


@pytest.mark.parametrize("stage", ["json", "image"])
@pytest.mark.asyncio
async def test_oversized_response_creates_no_artifact(tmp_path, stage):
    module = backend_module()
    config = replace(configured(tmp_path), max_json_bytes=512, max_image_bytes=512)

    def service(request):
        assert request.headers["accept-encoding"] == "identity"
        if stage == "json" or request.url.path == "/view":
            return httpx.Response(200, content=b"x" * 513, headers={"content-type": "image/png"})
        return successful_service(request)

    backend = module.ComfyUIBackend(config, transport=httpx.MockTransport(service))
    with pytest.raises(module.ImageGenerationError, match="response_too_large"):
        await backend.generate("boat", {})
    assert list(tmp_path.iterdir()) == []


def backend_module():
    return importlib.import_module("agents.core.media_backends.comfyui")


def configured(tmp_path, **overrides):
    values = {
        "JARVIS_LOCAL_IMAGE_GENERATION": "1",
        "JARVIS_COMFYUI_URL": "http://127.0.0.1:8188",
        "JARVIS_COMFYUI_CHECKPOINT": "sd-v1.safetensors",
        **overrides,
    }
    return backend_module().ComfyUIConfig.from_env(values, output_root=tmp_path)


def output_history(prompt_id="p-1", *, filename="image.png", subfolder="", kind="output"):
    return {
        prompt_id: {
            "status": {"status_str": "success", "completed": True, "messages": []},
            "outputs": {"9": {"images": [{"filename": filename, "subfolder": subfolder, "type": kind}]}},
        }
    }


@pytest.mark.asyncio
async def test_fixed_local_workflow_produces_validated_artifact(tmp_path):
    requests = []

    def service(request):
        requests.append(request)
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/prompt":
            workflow = json.loads(request.content)["prompt"]
            assert workflow["4"]["inputs"]["ckpt_name"] == "sd-v1.safetensors"
            assert workflow["6"]["inputs"]["text"] == "a blue boat"
            assert workflow["3"]["inputs"]["seed"] == 7
            assert {node["class_type"] for node in workflow.values()} == {
                "KSampler", "CheckpointLoaderSimple", "EmptyLatentImage",
                "CLIPTextEncode", "VAEDecode", "SaveImage",
            }
            return httpx.Response(200, json={"prompt_id": "p-1", "number": 0, "node_errors": {}})
        if request.url.path == "/history/p-1":
            return httpx.Response(200, json=output_history())
        if request.url.path == "/view":
            assert request.url.params["filename"] == "image.png"
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        raise AssertionError(request.url)

    backend = backend_module().ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    result = await backend.generate("a blue boat", {"seed": 7})
    artifact = Path(result["path"])
    assert artifact.parent == tmp_path
    assert artifact.read_bytes() == PNG
    assert result["prompt_id"] == "p-1"
    assert result["bytes"] == len(PNG)
    assert sum(req.method == "POST" for req in requests) == 1


@pytest.mark.parametrize("url", [
    "https://example.com", "http://192.168.1.2:8188", "http://localhost:8188",
    "http://127.0.0.1:8188@evil.example", "http://user:pass@127.0.0.1:8188",
    "http://127.0.0.1:8188/path", "http://127.0.0.1:8188?target=elsewhere",
    "http://127.0.0.1:8188/#secret", "file:///tmp/generator",
])
def test_endpoint_cannot_select_cloud_lan_dns_credentials_or_extra_path(tmp_path, url):
    module = backend_module()
    with pytest.raises(module.ImageGenerationError, match="invalid_endpoint"):
        configured(tmp_path, JARVIS_COMFYUI_URL=url)


def test_unconfigured_backend_is_default_off_and_creates_no_directory(tmp_path):
    target = tmp_path / "must-not-exist"
    module = backend_module()
    assert module.ComfyUIConfig.from_env({}, output_root=target) is None
    with pytest.raises(module.ImageGenerationError, match="checkpoint_required"):
        module.ComfyUIConfig.from_env({"JARVIS_LOCAL_IMAGE_GENERATION": "1"}, output_root=target)
    assert not target.exists()


@pytest.mark.parametrize("filename,subfolder,kind", [
    ("../secret.png", "", "output"), ("image.png", "../secret", "output"),
    ("C:\\secret.png", "", "output"), ("image.png", "", "input"),
    ("//server/share.png", "", "output"), ("image.svg", "", "output"),
])
@pytest.mark.asyncio
async def test_hostile_output_locations_are_refused_before_download(tmp_path, filename, subfolder, kind):
    requests = []

    def service(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        if request.url.path.startswith("/history/"):
            return httpx.Response(200, json=output_history(filename=filename, subfolder=subfolder, kind=kind))
        raise AssertionError("hostile location must never reach /view")

    module = backend_module()
    backend = module.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(module.ImageGenerationError, match="invalid_output"):
        await backend.generate("boat", {"seed": 7})
    assert len(requests) == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_submit_timeout_is_reported_without_retry_or_artifact(tmp_path):
    submissions = []

    def service(request):
        submissions.append(request)
        raise httpx.ReadTimeout("backend may have accepted", request=request)

    module = backend_module()
    backend = module.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(module.ImageGenerationError, match="submission_unknown"):
        await backend.generate("boat", {"seed": 7})
    assert len(submissions) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_redirect_is_not_followed(tmp_path):
    targets = []

    def service(request):
        targets.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://cloud.example/prompt"})

    module = backend_module()
    backend = module.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(module.ImageGenerationError, match="redirect_refused"):
        await backend.generate("boat", {"seed": 7})
    assert targets == ["http://127.0.0.1:8188/prompt"]


@pytest.mark.asyncio
async def test_non_png_payload_is_never_saved(tmp_path):
    def service(request):
        if request.method == "POST":
            return httpx.Response(200, json={"prompt_id": "p-1"})
        if request.url.path.startswith("/history/"):
            return httpx.Response(200, json=output_history())
        return httpx.Response(200, content=b"<svg onload='bad'/>", headers={"content-type": "image/png"})

    module = backend_module()
    backend = module.ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(module.ImageGenerationError, match="invalid_image"):
        await backend.generate("boat", {"seed": 7})
    assert list(tmp_path.iterdir()) == []
