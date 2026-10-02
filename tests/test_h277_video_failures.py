"""A native video failure permits a new route only for reviewed failure kinds."""
from __future__ import annotations

import json

import httpx
import pytest

from agents.core.llm.video_failures import (
    provider_failure_category,
    transport_failure_category,
)


def error_body(**fields: object) -> bytes:
    return json.dumps({"error": fields}).encode()


@pytest.mark.parametrize(("status", "body", "category"), [
    (401, b"", "auth"),
    (402, b"not JSON", "payment"),
    (403, error_body(message="unauthenticated:bad-credentials"), "auth"),
    (403, error_body(code="bad-credentials"), "auth"),
    (403, error_body(message="quota exceeded"), "payment"),
    (404, error_body(type="resource_exhausted"), "payment"),
    (404, error_body(message="RESOURCE_EXHAUSTED"), "payment"),
    (403, error_body(message="not available on the free tier"), "payment"),
    (429, error_body(message="too many tokens per day"), "payment"),
    (429, error_body(code="budget_limit_exceeded"), "payment"),
    (429, error_body(message="too many requests"), "rate_limit"),
    (429, b"", "rate_limit"),
    (400, error_body(message="model is not supported"), "model_incompatible"),
    (400, error_body(code="model_not_supported"), "model_incompatible"),
])
def test_reviewed_provider_failures(status: int, body: bytes, category: str):
    assert provider_failure_category(status, body) == category


@pytest.mark.parametrize(("status", "body"), [
    (200, error_body(message="quota exceeded")),
    (200, b""),
    (400, error_body(message="invalid request")),
    (400, error_body(message="model not found")),
    (400, error_body(message="model is not supported; billing required")),
    (400, error_body(message="unsupported model; model not found")),
    (403, error_body(message="permission denied")),
    (403, error_body(message="not-bad-credentials")),
    (404, error_body(message="model not found")),
    (404, error_body(message="the quota page is missing")),
    (500, error_body(message="quota exceeded")),
])
def test_unreviewed_provider_failures_do_not_permit_fallback(status: int, body: bytes):
    assert provider_failure_category(status, body) is None


@pytest.mark.parametrize("message", [
    "unknown model",
    "is not a valid model",
    "absent from the OpenRouter catalog",
    "The model `ghost` is unsupported",
])
def test_model_not_found_markers_override_incompatible_code(message: str):
    assert provider_failure_category(400, error_body(
        code="model_not_supported", message=message)) is None


@pytest.mark.parametrize("body", [
    b"not JSON",
    b"[1, 2, 3]",
    b'{"message": "quota exceeded"}',
    b'{"error": "quota exceeded"}',
    b'{"error": {"details": {"message": "quota exceeded"}}}',
    b'{"error": {"message": ["quota exceeded"]}}',
    b'{"error": {"code": {"value": "quota_exceeded"}}}',
    b'{"error": {"type": 42}}',
])
def test_bad_error_structure_cannot_authorize_body_based_fallback(body: bytes):
    assert provider_failure_category(403, body) is None


def test_deeply_nested_bounded_json_is_refused_without_parser_exception():
    assert provider_failure_category(403, b"[" * 100000 + b"]" * 100000) is None


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500])
def test_oversized_failure_body_is_rejected_even_for_status_only_rules(status: int):
    assert provider_failure_category(status, b"x" * 512001) is None


@pytest.mark.parametrize(("exc", "category"), [
    (httpx.ConnectTimeout("connect"), "timeout"),
    (httpx.ReadTimeout("read"), "timeout"),
    (httpx.WriteTimeout("write"), "timeout"),
    (httpx.PoolTimeout("pool"), "timeout"),
    (httpx.ConnectError("connect"), "connection"),
    (httpx.ReadError("read"), "connection"),
    (httpx.WriteError("write"), "connection"),
    (httpx.NetworkError("network"), "connection"),
    (httpx.RemoteProtocolError("remote closed"), "connection"),
])
def test_known_httpx_transport_failures(exc: BaseException, category: str):
    assert transport_failure_category(exc) == category


@pytest.mark.parametrize("exc", [
    TimeoutError("timed out"),
    OSError("connection refused"),
    httpx.LocalProtocolError("connection refused"),
    httpx.UnsupportedProtocol("timed out"),
    httpx.ProxyError("remote closed"),
    RuntimeError("ReadTimeout: timed out"),
    type("ConnectError", (Exception,), {})("connection refused"),
])
def test_non_transport_and_lookalike_failures_are_refused(exc: BaseException):
    assert transport_failure_category(exc) is None
