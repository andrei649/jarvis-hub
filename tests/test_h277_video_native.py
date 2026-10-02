"""Pure native Gemini video codec contract for the H277 approved-video route."""

import json

import pytest

from agents.core.llm.video_native import (
    GEMINI_VIDEO_MAX_REQUEST_BYTES,
    VIDEO_MIME,
    VideoNativeRefused,
    gemini_request_url,
    gemini_video_answer,
    gemini_video_body,
    gemini_video_mime,
)


@pytest.mark.parametrize(
    ("base", "model", "expected"),
    [
        ("", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"),
        ("https://example.test/custom/", "models/gemini_2.pro", "https://example.test/custom/models/gemini_2.pro:generateContent"),
        ("http://localhost:8080/v1", "g1", "http://localhost:8080/v1/models/g1:generateContent"),
        ("http://[::1]:8080/v1", "g1", "http://[::1]:8080/v1/models/g1:generateContent"),
    ],
)
def test_request_url_normalizes_safe_explicit_routes(base, model, expected):
    assert gemini_request_url(base, model) == expected


@pytest.mark.parametrize(
    ("base", "model"),
    [
        ("http://remote.example/v1", "g1"),
        ("https://user:secret@example.test/v1", "g1"),
        ("https://example.test/v1?key=secret", "g1"),
        ("https://example.test/v1#secret", "g1"),
        ("https://example.test/v1\\escape", "g1"),
        ("https://example.test/v1\nunsafe", "g1"),
        ("https://example.test:0/v1", "g1"),
        ("https://example.test/v1", "models/g1/extra"),
        ("https://example.test/v1", "g1?key=secret"),
        ("https://example.test/v1", "g1\nunsafe"),
        ("https://example.test/v1", ""),
        ("https://example.test/v1", "a" * 257),
        ("https://api.openai.com/v1", "g1"),
        ("https://api.anthropic.com/v1", "g1"),
        ("https://eu.api.openai.com/v1", "g1"),
    ],
)
def test_request_url_refuses_unsafe_inputs_without_echoing_them(base, model):
    with pytest.raises(VideoNativeRefused) as exc:
        gemini_request_url(base, model)
    assert "secret" not in str(exc.value)
    assert "unsafe" not in str(exc.value)


@pytest.mark.parametrize(
    ("extension", "expected"),
    [
        (".mp4", "video/mp4"),
        (".webm", "video/webm"),
        (".mov", "video/quicktime"),
        (".avi", "video/avi"),
        (".mkv", "video/x-matroska"),
        (".mpeg", "video/mpeg"),
        (".mpg", "video/mpeg"),
    ],
)
def test_video_mime_table_declares_actual_container(extension, expected):
    assert VIDEO_MIME[extension] == expected


@pytest.mark.parametrize("mime", ["video/mp4", "video/webm", "video/quicktime", "video/avi", "video/mpeg"])
def test_gemini_mime_accepts_declared_supported_containers(mime):
    assert gemini_video_mime(mime) == mime


@pytest.mark.parametrize("mime", ["video/x-matroska", "video/mov", "image/png", "video/mp4;codecs=avc1", ""])
def test_gemini_mime_refuses_unsupported_or_disguised_containers(mime):
    with pytest.raises(VideoNativeRefused):
        gemini_video_mime(mime)


def test_body_contains_exact_video_bytes_and_text_in_native_shape():
    body = gemini_video_body("Describe ☀", "data:video/mp4;base64,AP8=")
    assert body == {
        "contents": [{"role": "user", "parts": [
            {"text": "Describe ☀"},
            {"inline_data": {"mime_type": "video/mp4", "data": "AP8="}},
        ]}],
    }


@pytest.mark.parametrize("mime", ["video/quicktime", "video/avi", "video/mpeg", "video/webm"])
def test_body_preserves_each_supported_declared_mime(mime):
    body = gemini_video_body("describe", f"data:{mime};base64,AAE=")
    assert body["contents"][0]["parts"][1]["inline_data"] == {
        "mime_type": mime, "data": "AAE=",
    }


@pytest.mark.parametrize(
    "data_url",
    [
        "https://example.test/video.mp4",
        "data:video/mp4,AP8=",
        "data:video/x-matroska;base64,AP8=",
        "data:video/mp4;base64,AP8",
        "data:video/mp4;base64,AP8=garbage",
        "data:video/mp4;base64,**==",
        "data:video/mp4;base64,",
        "data:video/mp4;base64,AP8=\n",
    ],
)
def test_body_refuses_malformed_data_and_unsupported_mime(data_url):
    with pytest.raises(VideoNativeRefused):
        gemini_video_body("describe", data_url)


def test_body_rejects_actual_compact_utf8_json_at_20mb_boundary():
    fixed = {"contents": [{"role": "user", "parts": [
        {"text": ""}, {"inline_data": {"mime_type": "video/mp4", "data": "AA=="}},
    ]}]}
    fixed_size = len(json.dumps(fixed, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    prompt = "x" * (GEMINI_VIDEO_MAX_REQUEST_BYTES - fixed_size - 1)
    accepted = gemini_video_body(prompt, "data:video/mp4;base64,AA==")
    assert len(json.dumps(accepted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) == 19_999_999
    with pytest.raises(VideoNativeRefused):
        gemini_video_body(prompt + "x", "data:video/mp4;base64,AA==")


def test_body_counts_multibyte_utf8_instead_of_characters():
    fixed = {"contents": [{"role": "user", "parts": [
        {"text": ""}, {"inline_data": {"mime_type": "video/mp4", "data": "AA=="}},
    ]}]}
    fixed_size = len(json.dumps(fixed, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    prompt = "x" * (GEMINI_VIDEO_MAX_REQUEST_BYTES - fixed_size - 2) + "é"
    with pytest.raises(VideoNativeRefused):
        gemini_video_body(prompt, "data:video/mp4;base64,AA==")


def test_answer_joins_only_visible_text_in_part_order():
    payload = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": "first "}, {"text": "hidden", "thought": True}, {"text": "second"},
    ]}}]}
    assert gemini_video_answer(payload) == "first second"


def test_answer_omits_non_text_thought_part_before_visible_text():
    payload = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"thought": True, "functionCall": {"name": "internal"}}, {"text": "visible"},
    ]}}]}
    assert gemini_video_answer(payload) == "visible"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "leak"}]}}]},
        {"candidates": []},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "one"}]}}, {"finishReason": "STOP", "content": {"parts": [{"text": "two"}]}}]},
        {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "partial"}]}}]},
        {"candidates": [{"finishReason": "STOP", "safetyRatings": [{"blocked": True}], "content": {"parts": [{"text": "leak"}]}}]},
        {"promptFeedback": {"safetyRatings": [{"blocked": True}]}, "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "leak"}]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "thought", "thought": True}]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "  "}]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"inline_data": {"data": "AA=="}}]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "ok"}, None]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "ok", "thought": 1}]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": "not-list"}}]},
    ],
)
def test_answer_refuses_blocked_malformed_or_empty_success(payload):
    with pytest.raises(VideoNativeRefused):
        gemini_video_answer(payload)
