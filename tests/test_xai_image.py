"""Pinned xAI Imagine model selection, owner artifact references and native results."""

import base64
import io

import pytest
from PIL import Image


def png(size=(16, 16)):
    output = io.BytesIO()
    Image.new("RGB", size, "blue").save(output, format="PNG")
    return output.getvalue()


def request(model=None, **options):
    from agents.core.media_backends.xai_image import normalize_request

    return normalize_request("blue square", {"backend": "xai", **({"model": model} if model else {}), **options})


def test_curated_donor_catalog_preserves_default_and_exact_edit_caps():
    from agents.core.media_backends.xai_image import (
        DEFAULT_MODEL,
        MODEL_CATALOG,
        model_capabilities,
    )

    assert DEFAULT_MODEL == "grok-imagine-image"
    assert set(MODEL_CATALOG) == {
        "grok-imagine-image", "grok-imagine-image-2.0", "grok-imagine-image-quality",
    }
    assert model_capabilities()["grok-imagine-image-2.0"] == {
        "edit": True, "max_reference_images": 5, "reference_kind": "artifact_id",
    }
    assert model_capabilities()["grok-imagine-image-quality"]["max_reference_images"] == 3


def test_exact_model_and_fixed_native_generation_or_edit_endpoint():
    from agents.core.media_backends.xai_image import endpoint_for

    assert endpoint_for(request()) == "https://api.x.ai/v1/images/generations"
    assert endpoint_for(request("grok-imagine-image-2.0", references=["a" * 32])) == "https://api.x.ai/v1/images/edits"
    with pytest.raises(ValueError):
        request("grok-imagine-image-3.0")
    with pytest.raises(ValueError):
        endpoint_for({**request(), "surface": "edit"})


def test_generation_preserves_three_size_aspects_literal_resolution_and_2_0_quality():
    assert request(size="1536x1024")["aspect_ratio"] == "16:9"
    assert request(size="1024x1536")["aspect_ratio"] == "9:16"
    body = request("grok-imagine-image-2.0", resolution="2k", quality="medium")
    assert body["aspect_ratio"] == "1:1"
    assert body["resolution"] == "2k"
    assert body["quality"] == "medium"
    with pytest.raises(ValueError):
        request("grok-imagine-image", quality="low")
    with pytest.raises(ValueError):
        request("grok-imagine-image-2.0", resolution="2048")
    with pytest.raises(ValueError):
        request("grok-imagine-image-2.0", quality="high")


def test_edit_references_are_existing_artifact_ids_and_never_dropped_or_fallback():
    refs = [f"{i:032x}" for i in range(5)]
    body = request("grok-imagine-image-2.0", references=refs, size="1536x1024")
    assert body["references"] == refs
    assert body["aspect_ratio"] == "16:9"
    with pytest.raises(ValueError):
        request("grok-imagine-image-2.0", references=refs + ["f" * 32])
    with pytest.raises(ValueError):
        request("grok-imagine-image-quality", references=refs[:4])
    with pytest.raises(ValueError):
        request(references=["https://imgen.x.ai/input.png"])
    with pytest.raises(ValueError):
        request(references=["/tmp/input.png"])
    with pytest.raises(ValueError):
        request(references=["a" * 32, "a" * 32])


def test_generation_wire_uses_exact_selected_model_and_native_json():
    from agents.core.media_backends.xai_image import wire_body

    body = request("grok-imagine-image-2.0", size="1024x1536", resolution="2k", quality="low")
    assert wire_body(body, []) == {
        "model": "grok-imagine-image-2.0", "prompt": "blue square", "aspect_ratio": "9:16",
        "resolution": "2k", "quality": "low", "response_format": "b64_json", "n": 1,
    }


def test_single_edit_wire_encodes_owned_png_in_native_image_field():
    from agents.core.media_backends.xai_image import wire_body

    body = request("grok-imagine-image-2.0", references=["a" * 32], quality="medium")
    assert wire_body(body, [png()]) == {
        "model": "grok-imagine-image-2.0", "prompt": "blue square", "aspect_ratio": "1:1",
        "quality": "medium", "response_format": "b64_json",
        "image": {"type": "image_url", "url": "data:image/png;base64," + base64.b64encode(png()).decode()},
    }


def test_multi_edit_wire_preserves_order_and_rejects_missing_or_invalid_bytes():
    from agents.core.media_backends.xai_image import wire_body

    first, second = png(), png((20, 16))
    body = request("grok-imagine-image-2.0", references=["a" * 32, "b" * 32])
    wire = wire_body(body, [first, second])
    assert "image" not in wire
    assert wire["images"] == [
        {"type": "image_url", "url": "data:image/png;base64," + base64.b64encode(first).decode()},
        {"type": "image_url", "url": "data:image/png;base64," + base64.b64encode(second).decode()},
    ]
    with pytest.raises(ValueError):
        wire_body(body, [first])
    with pytest.raises(ValueError):
        wire_body(body, [first, b"not a PNG"])


def test_request_rejects_unsupported_knobs_and_multiple_paid_images():
    for options in ({"n": 2}, {"response_format": "url"}, {"storage_options": {"public_url": True}},
                    {"backend": "other"}, {"resolution": "4k"}):
        with pytest.raises(ValueError):
            request(**options)
    with pytest.raises(ValueError):
        request("grok-imagine-image-2.0", references=["a" * 32], resolution="2k")


def test_binary_result_is_decoded_and_sanitized_to_png():
    from agents.core.media_backends.xai_image import parse_response

    kind, output = parse_response({"data": [{"b64_json": base64.b64encode(png()).decode(), "mime_type": "image/png"}]})
    assert kind == "bytes" and output.startswith(b"\x89PNG")


def test_hosted_result_is_only_an_untrusted_https_candidate():
    from agents.core.media_backends.xai_image import parse_response

    url = "https://imgen.x.ai/xai-imgen/output.jpeg"
    assert parse_response({"data": [{"url": url, "mime_type": "image/jpeg"}]}) == ("url", url)
    # No fixture CDN host becomes a universal allowlist; root admits DNS/download.
    other = "https://assets.example.test/output.png"
    assert parse_response({"data": [{"url": other}]}) == ("url", other)
    for bad in ("http://imgen.x.ai/out", "https://127.0.0.1/out", "https://u:p@imgen.x.ai/out",
                "https://imgen.x.ai:8443/out", "https://imgen.x.ai/out#fragment"):
        with pytest.raises(ValueError):
            parse_response({"data": [{"url": bad}]})


@pytest.mark.parametrize("value", [
    {"data": []}, {"data": [{"url": "https://imgen.x.ai/a"}, {"url": "https://imgen.x.ai/b"}]},
    {"data": [{"url": "https://imgen.x.ai/a", "b64_json": "abc"}]},
    {"data": [{"url": "https://imgen.x.ai/a", "b64_json": 0}]},
    {"data": [{"b64_json": "not-base64"}]}, {"data": [{"b64_json": "abc", "mime_type": "image/svg+xml"}]},
])
def test_missing_extra_ambiguous_or_nonraster_results_refuse(value):
    from agents.core.media_backends.xai_image import parse_response

    with pytest.raises(ValueError):
        parse_response(value)


def test_auth_headers_are_fixed_origin_api_only_and_header_safe():
    from agents.core.media_backends.xai_image import BASE_URL, auth_headers

    assert BASE_URL == "https://api.x.ai/v1"
    assert auth_headers("synthetic-key")["Authorization"] == "Bearer synthetic-key"
    assert auth_headers("synthetic-key")["Content-Type"] == "application/json"
    with pytest.raises(ValueError):
        auth_headers("bad\r\nHost: evil.test")
