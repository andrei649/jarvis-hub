"""Krea Enhance's separate, opt-in native POST contract."""

import pytest

from agents.core.media_backends import krea_enhance, krea_image

URL = "https://images.example.com/native.png"
MODELS = ("krea-2-medium", "krea-2-large", "krea-2-medium-turbo")
SIZES = ("1024x1024", "1536x1024", "1024x1536")


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("size", SIZES)
def test_explicit_enhance_is_a_separate_canonical_request(model, size):
    options = {"backend": "krea", "model": model, "size": size, "enhance_image_url": URL}
    original = dict(options)
    body = krea_enhance.normalize_request("  a lamp  ", options)
    assert options == original
    assert body == {"model": model, "prompt": "a lamp", "size": size,
                    "operation": "enhance", "image_url": URL, "image_scaling_factor": 2}
    assert krea_enhance.endpoint_for(body) == krea_image.ENHANCE_ENDPOINT
    assert krea_enhance.wire_body(body) == {
        "image_url": URL, "image_scaling_factor": 2, "prompt": "a lamp"}


def test_explicit_native_factor_two_is_accepted_without_changing_the_wire():
    body = krea_enhance.normalize_request("a lamp", {
        "backend": "krea", "model": "krea-2-medium", "size": "1024x1024",
        "enhance_image_url": URL, "image_scaling_factor": 2,
    })
    assert body["image_scaling_factor"] == 2
    assert krea_enhance.wire_body(body) == {
        "image_url": URL, "image_scaling_factor": 2, "prompt": "a lamp"}


@pytest.mark.parametrize("length,accepted", [(1024, True), (1025, False)])
def test_source_url_matches_current_provider_schema_limit(length, accepted):
    url = "https://images.example.com/" + "x" * (length - len("https://images.example.com/"))
    options = {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024",
               "enhance_image_url": url}
    if accepted:
        assert krea_enhance.normalize_request("a lamp", options)["image_url"] == url
    else:
        with pytest.raises(ValueError):
            krea_enhance.normalize_request("a lamp", options)


@pytest.mark.parametrize("options", [
    {"model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": URL},
    {"backend": "other", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": URL},
    {"backend": "krea", "size": "1024x1024", "enhance_image_url": URL},
    {"backend": "krea", "model": "unknown", "size": "1024x1024", "enhance_image_url": URL},
    {"backend": "krea", "model": "krea-2-medium", "size": "2048x2048", "enhance_image_url": URL},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024"},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": "http://images.example.com/native.png"},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": "https://127.0.0.1/native.png"},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": "https://images.example.com/native.png#fragment"},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": URL, "upscale": True},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": URL, "image_style_references": [URL]},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": URL, "image_scaling_factor": False},
    {"backend": "krea", "model": "krea-2-medium", "size": "1024x1024", "enhance_image_url": URL, "image_scaling_factor": 4},
])
def test_enhance_refuses_unsupported_or_implicit_options(options):
    with pytest.raises(ValueError):
        krea_enhance.normalize_request("a lamp", options)


@pytest.mark.parametrize("prompt", ["", " \n ", None, "x" * 4001])
def test_enhance_requires_bounded_prompt(prompt):
    with pytest.raises(ValueError):
        krea_enhance.normalize_request(prompt, {
            "backend": "krea", "model": "krea-2-medium", "size": "1024x1024",
            "enhance_image_url": URL,
        })


@pytest.mark.parametrize("change", [
    {"operation": "generation"}, {"image_scaling_factor": False},
    {"image_scaling_factor": 1}, {"model": "not-krea"},
    {"size": "2048x2048"}, {"image_url": "https://localhost/native.png"},
    {"prompt": ""}, {"references": [URL]},
])
def test_endpoint_and_wire_refuse_tampered_canonical_body(change):
    body = krea_enhance.normalize_request("a lamp", {
        "backend": "krea", "model": "krea-2-medium", "size": "1024x1024",
        "enhance_image_url": URL,
    })
    body.update(change)
    with pytest.raises(ValueError):
        krea_enhance.endpoint_for(body)
    with pytest.raises(ValueError):
        krea_enhance.wire_body(body)
