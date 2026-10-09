"""FAL catalog adaptation keeps wire bodies model-specific and bounded."""

import pytest


@pytest.mark.parametrize("model,size,want_key,want_size", [
    ("fal-ai/flux-2/klein/9b", "1024x1024", "image_size", "square_hd"),
    ("fal-ai/nano-banana-pro", "1024x1536", "aspect_ratio", "9:16"),
    ("fal-ai/gpt-image-1.5", "1536x1024", "image_size", "1536x1024"),
    ("bytedance/seedream/v5/pro/text-to-image", "1536x1024", "image_size",
     {"width": 2048, "height": 1152}),
])
def test_generation_payload_families(model, size, want_key, want_size):
    from agents.core.media_backends.fal_image import normalize_request

    request = normalize_request("  blue bird  ", {"backend": "fal", "model": model, "size": size})
    assert request["endpoint"] == model
    assert request["body"]["prompt"] == "blue bird"
    assert request["body"][want_key] == want_size
    assert request["body"].keys() <= {"prompt"} | __import__(
        "agents.core.media_backends.fal_catalog", fromlist=["FAL_MODELS"]
    ).FAL_MODELS[model]["supports"]


def test_edit_payload_uses_catalog_endpoint_and_singular_reference():
    from agents.core.media_backends.fal_image import normalize_request

    ref = "https://v3.fal.media/files/source.png"
    request = normalize_request("edit", {
        "backend": "fal", "model": "fal-ai/kling-image/v3/text-to-image", "references": [ref],
    })
    assert request["endpoint"] == "fal-ai/kling-image/v3/image-to-image"
    assert request["body"]["image_url"] == ref
    assert "image_urls" not in request["body"]
    request = normalize_request("edit", {
        "backend": "fal", "model": "fal-ai/flux-2/klein/9b", "references": [ref],
    })
    assert request["endpoint"] == "fal-ai/flux-2/klein/9b/edit"
    assert request["body"]["image_urls"] == [ref]


@pytest.mark.parametrize("options", [
    {"backend": "fal", "reference": "a" * 32},
    {"backend": "fal", "references": ["https://evil.example/image.png"]},
    {"backend": "fal", "references": ["http://fal.media/image.png"]},
    {"backend": "fal", "references": ["https://fal.media.evil.example/image.png"]},
    {"backend": "fal", "references": ["https://user@fal.media/image.png"]},
    {"backend": "fal", "model": "fal-ai/z-image/turbo", "references": ["https://fal.media/a.png"]},
    {"backend": "fal", "model": "fal-ai/kling-image/v3/text-to-image",
     "references": ["https://fal.media/a.png", "https://fal.media/b.png"]},
    {"backend": "fal", "model": "fal-ai/gpt-image-1.5", "seed": 3},
    {"backend": "fal", "model": "fal-ai/nano-banana-pro", "steps": 4},
    {"backend": "fal", "quality": "high"},
    {"backend": "fal", "size": []},
    {"backend": "fal", "upscale": 2},
    {"backend": "fal", "endpoint": "https://evil.example"},
    {"backend": "fal", "model": "unknown"},
])
def test_unsupported_or_unbound_options_refused(options):
    from agents.core.media_backends.fal_image import normalize_request

    with pytest.raises(ValueError):
        normalize_request("prompt", options)


@pytest.mark.parametrize("response", [
    {}, {"images": []}, {"images": [{"url": "https://fal.media.evil.example/a"}]},
    {"images": [{"url": "http://fal.media/a"}]},
    {"images": [{"url": "https://user@fal.media/a"}]},
    {"images": [{"url": "https://fal.media:444/a"}]},
    {"images": [{"url": "https://fal.media/a"}, {"url": "https://fal.media/b"}]},
])
def test_provider_result_rejects_missing_multiple_or_unsafe_urls(response):
    from agents.core.media_backends.fal_image import result_url

    with pytest.raises(ValueError):
        result_url(response)
