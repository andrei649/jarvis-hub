"""Pinned Hermes Krea contract adapted to a signed, one-submit Nerva job."""

import pytest


@pytest.mark.parametrize("model,path", [
    ("krea-2-medium", "medium"),
    ("krea-2-large", "large"),
    ("krea-2-medium-turbo", "medium-turbo"),
])
def test_three_donor_models_have_exact_fixed_submit_endpoint(model, path):
    from agents.core.media_backends.krea_image import endpoint_for, normalize_request, wire_body

    request = normalize_request("  A cinematic lamp  ", {"backend": "krea", "model": model})
    assert request["model"] == model
    assert endpoint_for(request) == f"https://api.krea.ai/generate/image/krea/krea-2/{path}"
    assert wire_body(request) == {
        "prompt": "A cinematic lamp", "aspect_ratio": "16:9", "resolution": "1K",
        "creativity": "medium",
    }


@pytest.mark.parametrize("size,ratio", [
    ("1536x1024", "16:9"), ("1024x1024", "1:1"), ("1024x1536", "9:16"),
])
def test_route_sizes_map_to_donor_krea_aspect_enum(size, ratio):
    from agents.core.media_backends.krea_image import normalize_request, wire_body

    request = normalize_request("lamp", {"backend": "krea", "size": size, "seed": 42,
                                         "creativity": "raw"})
    assert wire_body(request) == {"prompt": "lamp", "aspect_ratio": ratio,
                                 "resolution": "1K", "creativity": "raw", "seed": 42}


def test_style_guidance_is_normalized_as_url_strength_objects_without_edit_claim():
    from agents.core.media_backends.krea_image import (
        model_capabilities,
        normalize_request,
        wire_body,
    )

    refs = ["https://images.example.com/a.png",
            {"url": "https://images.example.com/b.png", "strength": 1.2}]
    request = normalize_request("lamp", {"backend": "krea", "image_style_references": refs})
    assert request["modality"] == "style_guided_generation"
    assert model_capabilities("krea-2-medium")["max_style_references"] == 10
    assert wire_body(request)["image_style_references"] == [
        {"url": "https://images.example.com/a.png", "strength": 0.6},
        {"url": "https://images.example.com/b.png", "strength": 1.2},
    ]


@pytest.mark.parametrize("bad", [
    {"backend": "krea", "model": "krea-3"},
    {"backend": "krea", "reference": "a" * 32},
    {"backend": "krea", "references": ["https://images.example.com/a.png"]},
    {"backend": "krea", "upscale": True},
    {"backend": "krea", "enhance": True},
    {"backend": "krea", "styles": [{"id": "lora-1"}]},
    {"backend": "krea", "moodboards": [{"url": "https://images.example.com/a.png"}]},
    {"backend": "krea", "quality": "high"},
    {"backend": "krea", "size": "auto"},
    {"backend": "krea", "seed": True},
    {"backend": "krea", "seed": -1},
    {"backend": "krea", "creativity": "surreal"},
    {"backend": "krea", "image_style_references": []},
    {"backend": "krea", "image_style_references": ["https://images.example.com/a.png"] * 11},
    {"backend": "krea", "image_style_references": ["http://images.example.com/a.png"]},
    {"backend": "krea", "image_style_references": ["https://localhost/a.png"]},
    {"backend": "krea", "image_style_references": ["https://127.0.0.1/a.png"]},
    {"backend": "krea", "image_style_references": ["https://user@images.example.com/a.png"]},
    {"backend": "krea", "image_style_references": ["https://images.example.com:444/a.png"]},
    {"backend": "krea", "image_style_references": [{"url": "https://images.example.com/a.png"}]},
    {"backend": "krea", "image_style_references": [
        {"url": "https://images.example.com/a.png", "strength": 2.1}]},
    {"backend": "krea", "image_style_references": [
        {"url": "https://images.example.com/a.png", "strength": True}]},
])
def test_unsupported_or_unsafe_generation_inputs_fail_before_paid_submit(bad):
    from agents.core.media_backends.krea_image import normalize_request

    with pytest.raises(ValueError):
        normalize_request("lamp", bad)


def test_exact_ten_style_references_are_kept_without_clamping():
    from agents.core.media_backends.krea_image import normalize_request, wire_body

    refs = [f"https://images.example.com/{index}.png" for index in range(10)]
    request = normalize_request("lamp", {"backend": "krea", "image_style_references": refs})
    assert len(wire_body(request)["image_style_references"]) == 10


@pytest.mark.parametrize("body", [
    {}, {"job_id": ""}, {"job_id": 1}, {"job_id": "../escape"},
    {"job_id": "abc?x=1"}, {"job_id": "a" * 129},
])
def test_submit_job_id_must_be_safe_fixed_origin_path_segment(body):
    from agents.core.media_backends.krea_image import parse_job_id

    with pytest.raises(ValueError):
        parse_job_id(body)


def test_submit_job_id_and_poll_url_are_bounded_to_krea_origin():
    from agents.core.media_backends.krea_image import parse_job_id, poll_endpoint

    job_id = parse_job_id({"job_id": "00000000-0000-0000-0000-000000000abc", "status": "queued"})
    assert poll_endpoint(job_id) == "https://api.krea.ai/jobs/00000000-0000-0000-0000-000000000abc"


@pytest.mark.parametrize("value,want", [
    ({"status": "queued", "result": None}, {"state": "pending", "url": None}),
    ({"status": "sampling", "result": None}, {"state": "pending", "url": None}),
    ({"status": "failed", "result": {"error": "secret provider detail"}},
     {"state": "failed", "url": None}),
    ({"status": "cancelled"}, {"state": "cancelled", "url": None}),
    ({"status": "completed", "result": {"urls": ["https://krea.cdn/a.png"]}},
     {"state": "completed", "url": "https://krea.cdn/a.png"}),
    ({"status": "intermediate-complete", "completed_at": "2026-05-27T00:01:00Z",
      "result": {"url": "https://krea.cdn/b.png"}},
     {"state": "completed", "url": "https://krea.cdn/b.png"}),
])
def test_poll_status_normalizes_donor_terminal_and_pending_shapes(value, want):
    from agents.core.media_backends.krea_image import parse_job_status

    assert parse_job_status(value) == want


@pytest.mark.parametrize("value", [
    [], {}, {"status": 1}, {"status": "completed", "result": None},
    {"status": "completed", "result": {"urls": []}},
    {"status": "completed", "result": {"urls": ["https://a.test/1", "https://a.test/2"]}},
    {"status": "completed", "result": {"url": "http://insecure.test/a.png"}},
    {"status": "failed", "result": {"urls": ["https://a.test/a.png"]}},
])
def test_malformed_or_conflicting_job_status_never_publishes_a_candidate(value):
    from agents.core.media_backends.krea_image import parse_job_status

    with pytest.raises(ValueError):
        parse_job_status(value)


def test_enhance_is_a_separate_explicit_post_contract():
    from agents.core.media_backends.krea_image import ENHANCE_ENDPOINT, normalize_enhance_request

    assert ENHANCE_ENDPOINT == "https://api.krea.ai/generate/enhance/krea/enhance"
    assert normalize_enhance_request("lamp", "https://krea.cdn/native.png") == {
        "image_url": "https://krea.cdn/native.png", "image_scaling_factor": 2, "prompt": "lamp",
    }
