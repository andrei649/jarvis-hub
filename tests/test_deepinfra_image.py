"""Pinned Hermes DeepInfra image generation contract, without provider calls."""

import base64
import io

import pytest
from PIL import Image

from agents.core.media_backends import deepinfra_image as image

CATALOG = {"data": [
    {"id": "vendor/chat", "metadata": {"tags": ["chat"]}},
    {"id": "black-forest-labs/FLUX-1-schnell", "metadata": {
        "tags": ["image-gen"], "default_width": 1024, "default_height": 1024,
        "pricing": {"per_image_unit": 0.0005}}},
    {"id": "vendor/image-2", "metadata": {"tags": ["image-gen"]}},
    {"id": "vendor/stub", "metadata": None},
]}
_png = io.BytesIO()
Image.new("RGB", (1, 1), (0, 0, 0)).save(_png, format="PNG")
PNG = _png.getvalue()


def test_catalog_filters_only_served_image_gen_tags_and_exposes_text_only_caps():
    catalog = image.catalog_from_response(CATALOG)
    assert list(catalog) == ["black-forest-labs/FLUX-1-schnell", "vendor/image-2"]
    assert image.model_capabilities(catalog)["black-forest-labs/FLUX-1-schnell"] == {
        "modalities": ["text"], "max_reference_images": 0, "edit": False,
        "default_width": 1024, "default_height": 1024,
    }


def test_catalog_bounds_utf8_bytes_and_refuses_pathlike_model_ids():
    catalog = image.catalog_from_response({"data": [
        {"id": "vendor/../other", "metadata": {"tags": ["image-gen"]}},
        {"id": "vendor/%2e%2e", "metadata": {"tags": ["image-gen"]}},
        {"id": "vendor/good", "metadata": {"tags": ["image-gen"]}},
    ]})
    assert list(catalog) == ["vendor/good"]
    with pytest.raises(ValueError):
        image.catalog_from_response({"data": [{"id": "vendor/good", "metadata": {
            "tags": ["image-gen"], "description": "😀" * 150_000}}]})


def test_donor_generation_maps_aspect_to_exact_openai_wire_and_fixed_endpoint():
    catalog = image.catalog_from_response(CATALOG)
    body = image.normalize_request("  a cat  ", {
        "backend": "deepinfra", "model": "black-forest-labs/FLUX-1-schnell",
        "aspect_ratio": "landscape",
    }, catalog=catalog)
    assert body == {"model": "black-forest-labs/FLUX-1-schnell", "prompt": "a cat",
                    "size": "1536x1024", "n": 1}
    assert image.endpoint_for(body) == "https://api.deepinfra.com/v1/openai/images/generations"
    assert image.wire_body(body) == body
    assert image.auth_headers("test-key") == {"Authorization": "Bearer test-key"}


def test_first_live_model_only_when_catalog_provided_and_no_model_pinned():
    catalog = image.catalog_from_response(CATALOG)
    body = image.normalize_request("a cat", {"backend": "deepinfra"}, catalog=catalog)
    assert body["model"] == "black-forest-labs/FLUX-1-schnell"
    with pytest.raises(ValueError):
        image.normalize_request("a cat", {"backend": "deepinfra"}, catalog={})


@pytest.mark.parametrize("options", [
    {"backend": "openai"},
    {"backend": "deepinfra", "model": "vendor/chat"},
    {"backend": "deepinfra", "model": "vendor/unlisted"},
    {"backend": "deepinfra", "references": ["a" * 32]},
    {"backend": "deepinfra", "image_url": "https://example.com/image.png"},
    {"backend": "deepinfra", "quality": "high"},
    {"backend": "deepinfra", "n": 2},
    {"backend": "deepinfra", "size": "2048x2048"},
    {"backend": "deepinfra", "size": "1024x1024", "aspect_ratio": "portrait"},
])
def test_unsupported_backend_models_edits_knobs_and_sizes_refuse(options):
    with pytest.raises(ValueError):
        image.normalize_request("a cat", options, catalog=image.catalog_from_response(CATALOG))


def test_response_returns_one_bounded_raster_or_untrusted_url_candidate():
    assert image.parse_response({"data": [{"b64_json": base64.b64encode(PNG).decode()}]}) == ("bytes", PNG)
    assert image.parse_response({"data": [{"url": "https://cdn.example.test/image.png"}]}) == (
        "url", "https://cdn.example.test/image.png")


@pytest.mark.parametrize("value", [
    {}, {"data": []}, {"data": [{"b64_json": "%%%"}]},
    {"data": [{"b64_json": "aGVsbG8="}]},
    {"data": [{"url": "http://cdn.example.test/image.png"}]},
    {"data": [{"url": "https://localhost/image.png"}]},
    {"data": [{"url": "https://cdn.example.test/image.png#frag"}]},
    {"data": [{"url": "https://cdn.example.test/image.png"}, {"url": "https://cdn.example.test/other.png"}]},
])
def test_malformed_or_ambiguous_response_refuses(value):
    with pytest.raises(ValueError):
        image.parse_response(value)
