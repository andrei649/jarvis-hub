"""Pinned OpenRouter image catalog, native payloads and bounded results."""

import base64
import io

import pytest
from PIL import Image


def png(size=(16, 16)):
    output = io.BytesIO()
    Image.new("RGB", size, "blue").save(output, format="PNG")
    return output.getvalue()


def request(model=None, **options):
    from agents.core.media_backends.openrouter_image import normalize_request

    return normalize_request("blue square", {"backend": "openrouter", **({"model": model} if model else {}), **options})


def test_curated_catalog_keeps_chat_defaults_and_ten_dedicated_models():
    from agents.core.media_backends.openrouter_image import (
        CHAT_MODELS,
        DEFAULT_MODEL,
        IMAGE_API_MODELS,
        model_capabilities,
    )

    assert CHAT_MODELS == ("openai/gpt-5.4-image-2", "google/gemini-3-pro-image")
    assert CHAT_MODELS[0] == DEFAULT_MODEL
    assert len(IMAGE_API_MODELS) == 10
    assert "openai/gpt-image-2" in IMAGE_API_MODELS
    assert "krea/krea-2-medium-turbo" in IMAGE_API_MODELS
    caps = model_capabilities()
    assert set(caps) == set(CHAT_MODELS) | set(IMAGE_API_MODELS)
    assert caps["openai/gpt-image-2"] == {
        "edit": True, "max_reference_images": 16, "reference_kind": "artifact_id"}
    assert caps["microsoft/mai-image-2.5"]["max_reference_images"] == 1
    assert caps[DEFAULT_MODEL]["max_reference_images"] == 3


def test_fixed_model_to_surface_mapping_has_no_probe_or_fallback():
    from agents.core.media_backends.openrouter_image import endpoint_for

    assert endpoint_for(request()) == "https://openrouter.ai/api/v1/chat/completions"
    assert endpoint_for(request("openai/gpt-image-2")) == "https://openrouter.ai/api/v1/images"
    with pytest.raises(ValueError):
        request("some-lab/live-model")
    with pytest.raises(ValueError):
        endpoint_for({**request(), "surface": "images"})
    with pytest.raises(ValueError):
        endpoint_for({**request(), "callback_url": "https://evil.test"})


@pytest.mark.parametrize("model,expected", [
    ("openai/gpt-image-2", "16:9"),
    ("openai/gpt-image-1-mini", "3:2"),
    ("krea/krea-2-medium", "16:9"),
])
def test_model_specific_aspect_mapping(model, expected):
    assert request(model, size="1536x1024")["aspect_ratio"] == expected


def test_dedicated_knobs_are_exact_and_unsupported_knobs_refuse():
    body = request("openai/gpt-image-2", quality="high", background="opaque",
                   output_compression=75, aspect_ratio_exact="21:9")
    assert body["quality"] == "high" and body["background"] == "opaque"
    assert body["output_compression"] == 75 and body["aspect_ratio"] == "21:9"
    with pytest.raises(ValueError):
        request("openai/gpt-image-2", background="transparent")
    with pytest.raises(ValueError):
        request("microsoft/mai-image-2.5", quality="high")
    with pytest.raises(ValueError):
        request("openai/gpt-image-2", output_format="png")
    with pytest.raises(ValueError):
        request("openai/gpt-image-2", n=2)
    with pytest.raises(ValueError):
        request("openai/gpt-image-2", output_compression=101)
    with pytest.raises(ValueError):
        request("krea/krea-2-medium", aspect_ratio_exact="21:9")


def test_references_are_opaque_ids_and_model_capped_without_dropping():
    refs = [f"{i:032x}" for i in range(16)]
    assert request("openai/gpt-image-2", references=refs)["references"] == refs
    with pytest.raises(ValueError):
        request("openai/gpt-image-2", references=refs + ["f" * 32])
    with pytest.raises(ValueError):
        request("microsoft/mai-image-2.5", references=refs[:2])
    with pytest.raises(ValueError):
        request(references=refs[:4])
    with pytest.raises(ValueError):
        request(references=["https://openrouter.ai/image.png"])


def test_chat_wire_body_preserves_one_model_and_inlined_generated_artifact():
    from agents.core.media_backends.openrouter_image import wire_body

    body = request(references=["a" * 32], size="1024x1536")
    wire = wire_body(body, [png()])
    assert wire["model"] == "openai/gpt-5.4-image-2"
    assert wire["modalities"] == ["image", "text"]
    assert wire["image_config"] == {"aspect_ratio": "9:16"}
    parts = wire["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "blue square"}
    assert parts[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(png()).decode()
    assert "input_references" not in wire


def test_dedicated_wire_body_uses_input_references_and_one_result():
    from agents.core.media_backends.openrouter_image import wire_body

    body = request("openai/gpt-image-2", references=["a" * 32], quality="medium")
    wire = wire_body(body, [png()])
    assert wire == {"model": "openai/gpt-image-2", "prompt": "blue square",
                    "aspect_ratio": "1:1", "quality": "medium", "n": 1,
                    "input_references": [{"type": "image_url", "image_url": {
                        "url": "data:image/png;base64," + base64.b64encode(png()).decode()}}]}
    with pytest.raises(ValueError):
        wire_body(body, [])
    with pytest.raises(ValueError):
        wire_body(body, [b"not a PNG"])


def test_binary_response_variants_are_sanitized_to_png():
    from agents.core.media_backends.openrouter_image import parse_response

    encoded = base64.b64encode(png()).decode()
    kind, output = parse_response({"data": [{"b64_json": encoded, "media_type": "image/png"}]})
    assert kind == "bytes" and output.startswith(b"\x89PNG")
    kind, output = parse_response({"choices": [{"message": {"images": [
        {"image_url": {"url": "data:image/png;base64," + encoded}}]}}]})
    assert kind == "bytes" and output.startswith(b"\x89PNG")


def test_single_permitted_url_output_and_untrusted_urls_refused():
    from agents.core.media_backends.openrouter_image import parse_response

    url = "https://openrouter.ai/images/output.png"
    assert parse_response({"data": [{"url": url}]}) == ("url", url)
    # A provider result URL is only a candidate. The worker must admit its host,
    # resolve public DNS and download without forwarding Authorization.
    cdn = "https://assets.example.test/output.png"
    assert parse_response({"data": [{"url": cdn}]}) == ("url", cdn)
    assert parse_response({"choices": [{"message": {"images": [
        {"image_url": {"url": url}}]}}]}) == ("url", url)
    for bad in ("http://openrouter.ai/out.png",
                "https://user:pw@openrouter.ai/out.png", "https://openrouter.ai:8443/out.png",
                "https://127.0.0.1/out.png"):
        with pytest.raises(ValueError):
            parse_response({"data": [{"url": bad}]})


@pytest.mark.parametrize("value", [
    {"data": []}, {"data": [{"b64_json": "not-base64"}]},
    {"data": [{"url": "https://openrouter.ai/a"}, {"url": "https://openrouter.ai/b"}]},
    {"choices": [{"message": {"images": [{"image_url": {"url": "https://openrouter.ai/a"}},
                                       {"image_url": {"url": "https://openrouter.ai/b"}}]}}]},
    {"data": [{"url": "https://openrouter.ai/a", "b64_json": "abc"}]},
    {"data": [{"url": "https://openrouter.ai/a", "b64_json": 123}]},
])
def test_missing_multiple_or_ambiguous_results_refuse(value):
    from agents.core.media_backends.openrouter_image import parse_response

    with pytest.raises(ValueError):
        parse_response(value)


def test_auth_headers_only_bind_openrouter_key_to_fixed_origin():
    from agents.core.media_backends.openrouter_image import BASE_URL, auth_headers

    assert BASE_URL == "https://openrouter.ai/api/v1"
    headers = auth_headers("sk-or-test")
    assert headers["Authorization"] == "Bearer sk-or-test"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Title"] == "Nerva"
    with pytest.raises(ValueError):
        auth_headers("bad\r\nHost: evil.test")
