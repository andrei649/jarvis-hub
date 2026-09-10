"""Editing an image the hub already generated — the live half of H515 / H598.

Text-to-image existed and was governed. What did not exist was the other half of
Hermes' one `image_generate` tool: giving it an image to work *from*. This file
pins the shape that half was given, and one refusal is the reason for all of it.

**A reference is an opaque id, never a path.** The only handle an edit accepts is a
32-hex artifact id this hub minted, resolved by the same reader that serves the
download route. Nothing in the tuple — not a filename, not a URL, not a host path —
can name a file, so there is no argument a model can write that reads one. The
tests below therefore spend most of their attention on what is *refused*, and on
proving the refusal happens before any socket is opened.

Not covered here, and not claimed anywhere: that the resulting graph produces a good
edit on a real ComfyUI. The transport is exercised against a mock; the pixels are
the owner's host to prove.
"""

import base64
import json
import struct
import zlib
from pathlib import Path

import httpx
import pytest

from agents.core.media_backends.comfyui import (
    ComfyUIBackend,
    ComfyUIConfig,
    ImageGenerationError,
    artifact_bytes,
    validate_options,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
REFERENCE = "b" * 32


def _chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def configured(tmp_path, **overrides):
    return ComfyUIConfig.from_env({
        "JARVIS_LOCAL_IMAGE_GENERATION": "1",
        "JARVIS_COMFYUI_URL": "http://127.0.0.1:8188",
        "JARVIS_COMFYUI_CHECKPOINT": "sd-v1.safetensors",
        **overrides,
    }, output_root=tmp_path)


def seeded(tmp_path, artifact_id=REFERENCE, data=PNG):
    (tmp_path / (artifact_id + ".png")).write_bytes(data)
    return artifact_id


# ── the normalized tuple an approval will bind ───────────────────────────────

def test_an_edit_normalizes_to_reference_and_strength_without_a_canvas():
    assert validate_options("snow", {"reference": REFERENCE}) == {
        "seed": 0, "steps": 20, "strength": 60, "reference": REFERENCE,
    }


def test_text_to_image_normalizes_exactly_as_it_always_did():
    """The default tuple is unchanged, so an existing approval means what it meant."""
    assert validate_options("a boat", {}) == {"seed": 0, "width": 512, "height": 512, "steps": 20}


@pytest.mark.parametrize("options", [
    {"reference": REFERENCE, "width": 512},
    {"reference": REFERENCE, "height": 512},
], ids=["width", "height"])
def test_a_canvas_size_is_refused_for_an_edit_rather_than_silently_ignored(options):
    """An edit takes its size from the reference. Accepting and dropping the option
    would show the approver a number the generator never used."""
    with pytest.raises(ImageGenerationError, match="invalid_options"):
        validate_options("snow", options)


def test_strength_means_nothing_without_a_reference_and_is_refused_there():
    with pytest.raises(ImageGenerationError, match="invalid_options"):
        validate_options("a boat", {"strength": 40})


@pytest.mark.parametrize("value", [
    "../../etc/passwd", "/var/lib/nerva/media/generated/" + REFERENCE + ".png",
    "http://127.0.0.1:8188/view?filename=x.png", REFERENCE.upper(), "b" * 31, "b" * 33,
    "", None, 5, ["b" * 32],
], ids=["traversal", "host-path", "url", "uppercase", "short", "long", "empty", "null", "int", "list"])
def test_only_a_32_hex_id_is_a_reference(value):
    with pytest.raises(ImageGenerationError, match="invalid_options"):
        validate_options("snow", {"reference": value})


@pytest.mark.parametrize("strength", [0, 101, -1, 60.0, True, "60"])
def test_strength_is_a_bounded_integer_percent(strength):
    with pytest.raises(ImageGenerationError, match="invalid_options"):
        validate_options("snow", {"reference": REFERENCE, "strength": strength})


@pytest.mark.parametrize("strength", [1, 60, 100])
def test_the_whole_strength_range_is_usable(strength):
    assert validate_options("snow", {"reference": REFERENCE, "strength": strength})["strength"] == strength


# ── resolving the reference ──────────────────────────────────────────────────

def test_a_reference_resolves_to_the_owners_own_artifact_bytes(tmp_path):
    seeded(tmp_path)
    assert artifact_bytes(REFERENCE, tmp_path) == PNG


def test_a_symlink_out_of_the_artifact_root_is_refused(tmp_path):
    """The id regex already excludes traversal, so a link planted inside the root is
    the remaining way to make a valid id name a file the hub never generated."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(PNG)
    root = tmp_path / "generated"
    root.mkdir()
    (root / (REFERENCE + ".png")).symlink_to(outside / "secret.png")
    with pytest.raises(ImageGenerationError, match="reference_not_found"):
        artifact_bytes(REFERENCE, root)


def test_a_directory_wearing_the_artifact_name_is_refused(tmp_path):
    (tmp_path / (REFERENCE + ".png")).mkdir()
    with pytest.raises(ImageGenerationError, match="reference_not_found"):
        artifact_bytes(REFERENCE, tmp_path)


def test_bytes_that_are_not_the_accepted_png_subset_are_refused(tmp_path):
    seeded(tmp_path, data=b"GIF89a" + b"\x00" * 64)
    with pytest.raises(ImageGenerationError, match="reference_not_found"):
        artifact_bytes(REFERENCE, tmp_path)


def test_an_oversized_file_is_refused_without_being_read_into_a_response(tmp_path):
    seeded(tmp_path, data=b"\x89PNG\r\n\x1a\n" + b"\x00" * (16 * 1024 * 1024))
    with pytest.raises(ImageGenerationError, match="reference_not_found"):
        artifact_bytes(REFERENCE, tmp_path)


def test_a_missing_reference_is_the_same_refusal_as_an_invalid_one(tmp_path):
    """Same reason for both: whether that id exists is not something to leak."""
    with pytest.raises(ImageGenerationError, match="reference_not_found"):
        artifact_bytes(REFERENCE, tmp_path)
    with pytest.raises(ImageGenerationError, match="reference_not_found"):
        artifact_bytes("not a reference", tmp_path)


# ── the transport ────────────────────────────────────────────────────────────

def edit_service(record, *, upload_name="nerva-reference.png"):
    def service(request):
        record.append(request)
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": upload_name, "subfolder": "", "type": "input"})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p-1", "node_errors": {}})
        if request.url.path == "/history/p-1":
            return httpx.Response(200, json={"p-1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": "edited.png", "subfolder": "", "type": "output"}]}},
            }})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    return service


@pytest.mark.asyncio
async def test_an_edit_uploads_the_reference_then_samples_it_below_full_denoise(tmp_path):
    seeded(tmp_path)
    requests = []
    backend = ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(edit_service(requests)))
    result = await backend.generate("make it snow", {"reference": REFERENCE, "strength": 35, "seed": 7})

    upload, submit = requests[0], requests[1]
    assert upload.url.path == "/upload/image" and upload.method == "POST"
    assert PNG in upload.content, "the reference is uploaded as bytes, not as a name to fetch"
    workflow = json.loads(submit.content)["prompt"]
    assert {node["class_type"] for node in workflow.values()} == {
        "KSampler", "CheckpointLoaderSimple", "CLIPTextEncode", "VAEDecode",
        "SaveImage", "VAEEncode", "LoadImage",
    }, "an edit encodes the reference into the latent; no empty canvas is created"
    assert workflow["3"]["inputs"]["denoise"] == 0.35
    assert workflow["3"]["inputs"]["latent_image"] == ["10", 0]
    assert workflow["11"]["inputs"]["image"] == "nerva-reference.png"
    assert workflow["6"]["inputs"]["text"] == "make it snow"
    assert result["bytes"] == len(PNG) and Path(result["path"]).parent == tmp_path


@pytest.mark.asyncio
async def test_a_new_artifact_is_written_and_the_reference_is_left_alone(tmp_path):
    seeded(tmp_path)
    backend = ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(edit_service([])))
    result = await backend.generate("make it snow", {"reference": REFERENCE})
    assert result["artifact_id"] != REFERENCE, "an edit never overwrites what it edited"
    assert (tmp_path / (REFERENCE + ".png")).read_bytes() == PNG


@pytest.mark.asyncio
async def test_text_to_image_still_makes_exactly_one_post_and_no_upload(tmp_path):
    requests = []
    backend = ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(edit_service(requests)))
    await backend.generate("a boat", {})
    assert [r.url.path for r in requests if r.method == "POST"] == ["/prompt"]


@pytest.mark.asyncio
async def test_an_unusable_reference_costs_no_request_at_all(tmp_path):
    """The refusal is before the socket: a submission whose outcome we cannot observe
    must never be spent on a reference we could have rejected first."""
    requests = []
    backend = ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(edit_service(requests)))
    with pytest.raises(ImageGenerationError, match="reference_not_found"):
        await backend.generate("make it snow", {"reference": REFERENCE})
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"name": "../../../etc/passwd", "subfolder": "", "type": "input"},
    {"name": "reference.png", "subfolder": "elsewhere", "type": "input"},
    {"name": "reference.png", "subfolder": "", "type": "output"},
    {"name": "reference.exe", "subfolder": "", "type": "input"},
    {"subfolder": "", "type": "input"},
    {"name": 5, "subfolder": "", "type": "input"},
], ids=["traversal", "subfolder", "type", "extension", "missing", "not-a-string"])
async def test_the_uploaded_name_the_service_reports_back_is_revalidated(tmp_path, body):
    """ComfyUI renames on collision, so the name it returns is the one the workflow
    must use — which is exactly why it is validated before it reaches a node."""
    seeded(tmp_path)
    requests = []

    def service(request):
        requests.append(request)
        if request.url.path == "/upload/image":
            return httpx.Response(200, json=body)
        return edit_service([])(request)

    backend = ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(ImageGenerationError, match="invalid_response"):
        await backend.generate("make it snow", {"reference": REFERENCE})
    assert [r.url.path for r in requests] == ["/upload/image"], "no workflow was submitted"


@pytest.mark.asyncio
async def test_a_collision_rename_from_the_service_is_accepted_and_used(tmp_path):
    seeded(tmp_path)
    requests = []
    backend = ComfyUIBackend(configured(tmp_path),
                             transport=httpx.MockTransport(edit_service(requests, upload_name="nerva-reference (1).png")))
    await backend.generate("make it snow", {"reference": REFERENCE})
    workflow = json.loads(requests[1].content)["prompt"]
    assert workflow["11"]["inputs"]["image"] == "nerva-reference (1).png"


@pytest.mark.asyncio
async def test_an_upload_whose_outcome_is_unknown_is_never_retried(tmp_path):
    seeded(tmp_path)
    attempts = []

    def service(request):
        attempts.append(request)
        raise httpx.ConnectError("simulated loss", request=request)

    backend = ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(ImageGenerationError, match="reference_upload_unknown"):
        await backend.generate("make it snow", {"reference": REFERENCE})
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_an_edit_result_is_validated_as_a_png_like_any_other(tmp_path):
    seeded(tmp_path)
    corrupt = (b"\x89PNG\r\n\x1a\n"
               + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 4, 0, 0, 0))
               + _chunk(b"IDAT", zlib.compress(b"\x05\x00\x00"))
               + _chunk(b"IEND", b""))

    def service(request):
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "r.png", "subfolder": "", "type": "input"})
        if request.url.path == "/view":
            return httpx.Response(200, content=corrupt, headers={"content-type": "image/png"})
        return edit_service([])(request)

    backend = ComfyUIBackend(configured(tmp_path), transport=httpx.MockTransport(service))
    with pytest.raises(ImageGenerationError, match="invalid_image"):
        await backend.generate("make it snow", {"reference": REFERENCE})
    assert sorted(p.name for p in tmp_path.iterdir()) == [REFERENCE + ".png"]
